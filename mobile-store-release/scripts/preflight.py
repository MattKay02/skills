"""Read-only checks: `preflight`, a punch list of what would stop or sink a
submission, and `doctor`, whether the config and the keys work.

    python store.py preflight <app> [--ios] [--android] [--build N]
    python store.py doctor    <app> [--ios|--android]

Neither changes anything. Each preflight line has a severity and names what it
guards (an App Review guideline, a Play policy, or a field the store
requires):

    BLOCK      the store will refuse it, or App Review will reject it
    UNCHECKED  a read failed, so what it would have checked is unknown
    WARN       likely trouble, or something to decide
    OK         checked and fine (or a state worth knowing)
    MANUAL     the APIs cannot see it: check it by hand

preflight exits 1 when any line is BLOCK or UNCHECKED, so "0 BLOCK" can
never mean "checked nothing". A failed read stops only the checks that need
what it would have read; every other check still runs.

Google Play: both open one Play edit, read, and discard it. Never run them
while a CI build is uploading to Play: opening a new edit expires the
upload's own ("This edit has expired, please create a new Edit").
"""

from __future__ import annotations

import urllib.parse

import asc
import play
from asc import DONE, EDITABLE, AppStore
from common import (App, StoreError, connect_doc, fetch_status, find_config, load_config,
                    EXAMPLE, CONFIG_NAME)
from pictures import DISPLAY_SIZES, IPHONE_REQUIRED
from play import NOTES_LIMIT, Play, _describe, parse_notes

SEVERITIES = ('BLOCK', 'UNCHECKED', 'WARN', 'OK', 'MANUAL')

IOS_MANUAL = [
    ('App Privacy details', 'App Privacy is answered in App Store Connect and matches what the '
                            'app and every SDK in it collect'),
    ('age rating', 'the age rating questionnaire in App Information is answered and still true'),
    ('App Review 5.1.1(v)', 'if the app has accounts, they can be deleted from inside the app; with '
                            'Sign in with Apple, deleting the account also revokes its Apple token '
                            '(Sign in with Apple REST API, /auth/revoke)'),
    ('App Review 4 (Design)', 'nothing asks for a name or email after Sign in with Apple: Apple '
                              'already supplies them'),
    ('App Review 2.3.7', 'store pictures and text show no price words ("Free", a currency, '
                         '"trial", "% off"); pictures lists the files to look at'),
    ('App Review 2.1', 'the demo account signs in on a clean install and reaches every feature '
                       'behind sign-in'),
    ('App Review 3.1.2', 'with subscriptions: the purchase screen shows title, length and price, '
                         'and links to the Terms of Use (EULA) and the Privacy Policy; the App Store '
                         'description links both too'),
    ('App Store Connect', 'if the app runs on iPad, a 13-inch iPad screenshot set '
                          '(APP_IPAD_PRO_3GEN_129) is on the version'),
]
ANDROID_MANUAL = [
    ('Play policy', 'Data safety is answered in Play Console and matches what the app and every '
                    'SDK in it collect'),
    ('Play policy', 'the content rating questionnaire (IARC) is answered'),
    ('Play policy', "the target API level meets Play's current requirement for new apps and updates"),
    ('Play policy', 'App content declarations are complete: privacy policy, app access (sign-in '
                    'for reviewers), ads, target audience, and any health, news or financial ones'),
    ('Play policy', 'the ads declaration matches whether the app shows ads, SDKs included'),
    ('Play policy', 'if the app has accounts: deletion from inside the app, and a web link to '
                    'request it, given in Data safety'),
    ('Play policy', 'store pictures and text show no price or ranking words ("Free", "% off", '
                    '"#1", "best"); pictures lists the files to look at'),
    ('Google Play', 'managed publishing is off (Publishing overview) if releases should go live '
                    'once Google approves them'),
]


class Punch:
    """The punch list: headings and lines, each with a severity and a guard."""

    def __init__(self) -> None:
        self.items: list[tuple[str | None, str, str]] = []

    def heading(self, text: str) -> None:
        self.items.append((None, '', text))

    def add(self, severity: str, guard: str, text: str) -> None:
        assert severity in SEVERITIES, severity
        self.items.append((severity, guard, text))

    def attempt(self, guard: str, what: str, fn, *args):
        """Run one read; a refusal becomes an UNCHECKED line naming what was
        not checked, rather than the end of the list, since the checks that
        do not need it still say something."""
        try:
            return fn(*args)
        except StoreError as e:
            self.add('UNCHECKED', guard, f'{what}: {e}')
            return None

    def failed(self) -> bool:
        return bool(self.count('BLOCK') or self.count('UNCHECKED'))

    def count(self, severity: str) -> int:
        return sum(1 for s, _, _ in self.items if s == severity)

    def render(self, title: str) -> list[str]:
        lines = [title]
        for severity, guard, text in self.items:
            if severity is None:
                lines += ['', text]
            else:
                lines.append(f'  {severity:<6} [{guard}] {text}')
        lines += ['', 'Summary: ' + ', '.join(f'{self.count(s)} {s}' for s in SEVERITIES)]
        return lines


# --- App Store ---------------------------------------------------------------


def _build_checks(build: dict, punch: Punch, label: str) -> None:
    number = build['number']
    state = build['state']
    said = f"{label} {number}" + (f" ({build['version']})" if build.get('version') else '')
    if state == 'VALID':
        punch.add('OK', 'build', f"{said} is VALID" + (f", uploaded {build['uploaded']}"
                                                         if build.get('uploaded') else ''))
    elif state == 'PROCESSING':
        punch.add('WARN', 'build', f'{said} is still PROCESSING: wait until it is VALID before submitting')
    else:
        punch.add('BLOCK', 'build', f'{said} is {state}: upload a new build')
    if build.get('expired'):
        punch.add('BLOCK', 'build', f'{said} has expired (builds expire 90 days after upload): '
                                    'upload a new one')
    encryption = build.get('encryption')
    if encryption is None:
        punch.add('BLOCK', 'export compliance',
                  f'{said} has not answered the export compliance question (usesNonExemptEncryption '
                  'is empty). Answer it in App Store Connect > TestFlight > the build, and set '
                  'ITSAppUsesNonExemptEncryption in Info.plist so later builds answer it themselves')
    elif encryption:
        punch.add('WARN', 'export compliance',
                  f'{said} says it uses non-exempt encryption: App Store Connect needs export '
                  'compliance documentation for it before review')
    else:
        punch.add('OK', 'export compliance', f'{said} uses no non-exempt encryption')


def _version_state(version: dict, punch: Punch) -> None:
    v, state = version['version'], version['state']
    if state in EDITABLE:
        punch.add('OK', 'version', f'version {v} is {state}: open for changes')
        if state in ('REJECTED', 'METADATA_REJECTED'):
            punch.add('WARN', 'App Review', f"App Review rejected {v}: read its message in App Store "
                                            'Connect > App Review before sending it again')
    elif state in DONE:
        punch.add('BLOCK', 'version', f'version {v} is {state}: a version is submitted once, so '
                                      'this build needs the next version number')
    else:
        punch.add('OK', 'version', f'version {v} is {state}: already submitted, so nothing on it '
                                   'can change until App Review answers; the lines below describe '
                                   'what was sent')


def _target(store: AppStore, versions: list[dict], build: dict | None, number: str | None,
            punch: Punch) -> dict | None:
    """The version the checks are about: the build's own version when it has
    one, else the version open for changes (renamed by prepare and submit),
    else the one on its way to the store."""
    open_now = next((v for v in versions if v['state'] in EDITABLE), None)
    on_way = next((v for v in versions if v['state'] not in EDITABLE and v['state'] not in DONE), None)
    if build is not None and build.get('version'):
        wanted = build['version']
        named = next((v for v in versions if v['version'] == wanted), None)
        if named is None:
            raw = store._version_named(wanted)
            if raw:
                named = {'id': raw['id'], 'version': wanted, 'state': asc._state(raw['attributes']),
                         'release': raw['attributes'].get('releaseType')}
        if named:
            _version_state(named, punch)
            return named
        if open_now:
            punch.add('OK', 'version', f"version {open_now['version']} is open for changes "
                                       f"({open_now['state']}) and build {number} is {wanted}: "
                                       f"prepare and submit rename it to {wanted} (Apple keeps one "
                                       'version open at a time)')
            if open_now['state'] in ('REJECTED', 'METADATA_REJECTED'):
                punch.add('WARN', 'App Review', f"App Review rejected {open_now['version']}: read its "
                                                'message in App Store Connect > App Review before '
                                                'sending it again')
            return open_now
        if on_way:
            punch.add('WARN', 'version', f"version {on_way['version']} is {on_way['state']}: Apple opens "
                                         f'no new version while one is on its way, so {wanted} cannot '
                                         'be created until App Review answers (or it is taken out of review)')
            return None
        punch.add('OK', 'version', f'no version {wanted} yet: prepare or submit creates it')
        return None
    if open_now:
        _version_state(open_now, punch)
        return open_now
    if on_way:
        _version_state(on_way, punch)
        return on_way
    punch.add('OK', 'version', 'no version is open or on its way: prepare --build N creates the next one')
    return None


def _version_detail(store: AppStore, target: dict, build: dict | None, number: str | None,
                    punch: Punch) -> dict | None:
    """The build attached, the copyright, the release type and App Review's
    details, from one read of the version. Returns the attached build (in the
    shape builds() gives) when no build was named."""
    res = store.get(f"/v1/appStoreVersions/{target['id']}",
                    {'include': 'build,appStoreReviewDetail'})
    data = res.get('data') or {}
    attributes = data.get('attributes') or {}
    included = {(i.get('type'), i.get('id')): i for i in res.get('included') or []}
    links = data.get('relationships') or {}
    v = target['version']
    editable = target['state'] in EDITABLE

    attached = (links.get('build') or {}).get('data')
    attached_build = None
    if attached:
        found = included.get(('builds', attached['id'])) or {}
        a = found.get('attributes') or {}
        attached_build = {'id': attached['id'], 'number': a.get('version') or '?', 'version': v,
                          'state': a.get('processingState'), 'expired': a.get('expired'),
                          'uploaded': (a.get('uploadedDate') or '')[:16],
                          'encryption': a.get('usesNonExemptEncryption')}
        if build is not None and attached['id'] != build['id'] and editable:
            punch.add('OK', 'build', f"build {attached_build['number']} is attached to {v}; submit "
                                     f'--build {number} attaches {number} in its place')
        else:
            punch.add('OK', 'build', f"build {attached_build['number']} is attached to {v}")
    elif build is not None and editable:
        punch.add('OK', 'build', f'no build attached to {v} yet: prepare or submit attaches build {number}')
    else:
        punch.add('BLOCK', 'build', f'no build attached to {v}: prepare --build N attaches one')

    if attributes.get('copyright'):
        punch.add('OK', 'App Store Connect', f'copyright set on {v}')
    else:
        punch.add('BLOCK', 'App Store Connect', f'no copyright on {v}: set it ("copyright" in the '
                                                'listing file, then listing)')

    release = attributes.get('releaseType') or target.get('release')
    if release == 'AFTER_APPROVAL':
        punch.add('OK', 'release', f'{v} releases itself once Apple approves it')
    elif release == 'MANUAL':
        punch.add('OK', 'release', f'{v} is held after approval until `release`'
                                   + (' (prepare and submit keep it; --automatic changes it)'
                                      if editable else ''))
    elif release == 'SCHEDULED':
        punch.add('OK', 'release', f"{v} releases on {attributes.get('earliestReleaseDate') or 'its date'}, "
                                   'once approved')

    link = (links.get('appStoreReviewDetail') or {}).get('data')
    detail = included.get(('appStoreReviewDetails', link['id'])) if link else None
    _review_detail(detail, v, punch)
    return attached_build if build is None else None


def _review_detail(detail: dict | None, v: str, punch: Punch) -> None:
    """App Review's contact and demo account. The password is only ever
    tested for being there, never printed."""
    if detail is None:
        punch.add('BLOCK', 'App Review contact',
                  f'no App Review information on {v}: add the contact (name, phone, email) on the '
                  'version page, and a demo account if the app needs sign-in')
        return
    a = detail.get('attributes') or {}
    missing = [label for key, label in (('contactFirstName', 'first name'), ('contactLastName', 'last name'),
                                        ('contactPhone', 'phone'), ('contactEmail', 'email'))
               if not a.get(key)]
    if missing:
        punch.add('BLOCK', 'App Review contact',
                  f'the App Review contact on {v} has no {", ".join(missing)}: fill it in on the version page')
    else:
        punch.add('OK', 'App Review contact', f'name, phone and email set on {v}')
    if a.get('demoAccountRequired'):
        if a.get('demoAccountName') and a.get('demoAccountPassword'):
            punch.add('OK', 'App Review 2.1', 'demo account set (not shown)')
        else:
            punch.add('BLOCK', 'App Review 2.1', 'sign-in is marked required but the demo account name '
                                                 'or password is empty: fill both in on the version page')
    else:
        punch.add('WARN', 'App Review 2.1', 'no demo account (sign-in is not marked required): if any '
                                            'feature needs an account, App Review needs one that works')


def _texts(store: AppStore, target: dict, update: bool, punch: Punch) -> list[dict] | None:
    """The version's text in every localization. Returns the localizations.
    What's New is required on an update and not shown on a first version."""
    v = target['version']
    locs = store.get(f"/v1/appStoreVersions/{target['id']}/appStoreVersionLocalizations")['data']
    if not locs:
        punch.add('BLOCK', 'App Store Connect', f'{v} has no localizations')
        return None
    for loc in locs:
        a = loc.get('attributes') or {}
        locale = a.get('locale') or '?'
        missing = [label for key, label in (('description', 'description'), ('keywords', 'keywords'),
                                            ('supportUrl', 'support URL')) if not a.get(key)]
        if missing:
            punch.add('BLOCK', 'App Store Connect', f'{v} {locale}: no {", ".join(missing)} '
                                                    '(listing sets them)')
        else:
            punch.add('OK', 'App Store Connect', f'{v} {locale}: description, keywords and support URL set')
        if not update and a.get('whatsNew'):
            punch.add('WARN', 'App Store Connect', f"{v} {locale}: What's New is set, but {v} is the "
                                                   "app's first version, which has none: clear it")
        if update:
            if a.get('whatsNew'):
                punch.add('OK', 'App Store Connect', f"{v} {locale}: What's New set")
            else:
                punch.add('BLOCK', 'App Store Connect',
                          f"{v} {locale}: What's New is empty, and {v} is an update: "
                          'submit --ios --notes FILE sets it (or "whatsNew" in the listing file)')
    if not update:
        punch.add('OK', 'App Store Connect', f"{v} is the app's first version: What's New is not needed")
    return locs


def _locale_shots(store: AppStore, loc: dict, v: str, punch: Punch) -> dict[str, int]:
    """One localization's screenshot sets: whether Apple finished processing
    each picture (assetDeliveryState). Returns {display type: count}."""
    locale = (loc.get('attributes') or {}).get('locale') or '?'
    counts: dict[str, int] = {}
    for s in store.get(f"/v1/appStoreVersionLocalizations/{loc['id']}/appScreenshotSets")['data']:
        display = (s.get('attributes') or {}).get('screenshotDisplayType') or '?'
        shots = store.get(f"/v1/appScreenshotSets/{s['id']}/appScreenshots", {'limit': 50})['data']
        counts[display] = len(shots)
        delivery = [((x.get('attributes') or {}).get('assetDeliveryState') or {}) for x in shots]
        states = [d.get('state') for d in delivery]
        failed = [d for d in delivery if d.get('state') == 'FAILED']
        if not shots:
            punch.add('WARN', 'App Store Connect', f'{v} {locale} {display}: the set is empty')
        elif failed:
            why = '; '.join(e.get('description') or e.get('code') or '?'
                            for d in failed for e in d.get('errors') or []) or 'no reason given'
            punch.add('BLOCK', 'App Store Connect', f'{v} {locale} {display}: {len(failed)} of '
                                                    f'{len(shots)} failed processing ({why}): fix '
                                                    'them and run screenshots again')
        elif 'AWAITING_UPLOAD' in states:
            punch.add('BLOCK', 'App Store Connect', f'{v} {locale} {display}: an upload never finished '
                                                    '(AWAITING_UPLOAD): run screenshots again')
        elif any(state != 'COMPLETE' for state in states):
            punch.add('WARN', 'App Store Connect', f'{v} {locale} {display}: {len(shots)} screenshots, '
                                                   f'still processing ({", ".join(sorted(set(map(str, states))))})'
                                                   ': check again in a few minutes')
        else:
            label = DISPLAY_SIZES.get(display, (display,))[0]
            punch.add('OK', 'App Store Connect', f'{v} {locale} {display} ({label}): {len(shots)} '
                                                 'screenshots, every one COMPLETE')
    return counts


def _screenshots(store: AppStore, locs: list[dict], v: str, punch: Punch) -> None:
    """Every localization's screenshot sets. The primary needs a set (and an
    iPhone one); any other localization with none, or with a different count
    from the primary's, is a WARN: screenshots and listing take --locale."""
    def locale_of(loc: dict) -> str:
        return (loc.get('attributes') or {}).get('locale') or '?'

    primary = next((l for l in locs if locale_of(l) == store.primary), locs[0])
    counts = punch.attempt('App Store Connect', f'the {locale_of(primary)} screenshots',
                           _locale_shots, store, primary, v, punch)
    if counts is not None:
        if not counts:
            punch.add('BLOCK', 'App Store Connect', f'no screenshots on {v} {locale_of(primary)}: '
                                                    'run screenshots')
        elif not any(k in IPHONE_REQUIRED for k in counts):
            punch.add('WARN', 'App Store Connect', f'{v} {locale_of(primary)}: no 6.9-inch (APP_IPHONE_67) '
                                                   'or 6.5-inch (APP_IPHONE_65) set; an iPhone app needs one')
    for loc in locs:
        if loc is primary:
            continue
        theirs = punch.attempt('App Store Connect', f'the {locale_of(loc)} screenshots',
                               _locale_shots, store, loc, v, punch)
        if theirs is None or counts is None:
            continue
        if not theirs:
            punch.add('WARN', 'App Store Connect', f'{v} {locale_of(loc)}: no screenshots of its own '
                                                   f'(screenshots --locale {locale_of(loc)} adds them)')
            continue
        differ = [f'{d} has {theirs.get(d, 0)}, {locale_of(primary)} has {n}'
                  for d, n in counts.items() if theirs.get(d, 0) != n]
        differ += [f'{d} has {n}, {locale_of(primary)} has none' for d, n in theirs.items() if d not in counts]
        if differ:
            punch.add('WARN', 'App Store Connect', f'{v} {locale_of(loc)}: {"; ".join(differ)}')
        else:
            punch.add('OK', 'App Store Connect', f'{v} {locale_of(loc)}: the same screenshot sets and '
                                                 f'counts as {locale_of(primary)}')


def _url(url: str, what: str, guard: str, punch: Punch) -> None:
    """A public page, opened the way a reviewer would: no credentials."""
    code, detail = fetch_status(url)
    if code is not None and 200 <= code < 300:
        punch.add('OK', guard, f'{what} answers {code}: {url}')
    elif code in (401, 403, 429):
        punch.add('WARN', guard, f'{what} answered {code} to this script ({detail}): open {url} in a '
                                 'browser to confirm a reviewer can read it')
    elif code is None:
        punch.add('BLOCK', guard, f'{what} does not load ({detail}): {url}')
    else:
        punch.add('BLOCK', guard, f'{what} answers {code} ({detail}): {url}')


def _app_info(store: AppStore, punch: Punch) -> None:
    """The privacy policy and the primary category, from the app information
    going out with the next version (or the live one when none is)."""
    infos = store.get(f'/v1/apps/{store.app_id}/appInfos')['data']
    if not infos:
        punch.add('WARN', 'App Store Connect', 'no app information found')
        return

    def state(info: dict) -> str | None:
        a = info.get('attributes') or {}
        return a.get('state') or a.get('appStoreState')

    live = DONE | {'REPLACED_WITH_NEW_INFO'}
    info = next((i for i in infos if state(i) not in live), infos[0])
    locs = store.get(f"/v1/appInfos/{info['id']}/appInfoLocalizations")['data']
    primary = next((l for l in locs if (l.get('attributes') or {}).get('locale') == store.primary),
                   locs[0] if locs else None)
    locale = ((primary or {}).get('attributes') or {}).get('locale') or store.primary
    privacy = ((primary or {}).get('attributes') or {}).get('privacyPolicyUrl')
    if privacy:
        _url(privacy, f'privacy policy URL ({locale})', 'App Review 5.1.1(i)', punch)
    else:
        punch.add('BLOCK', 'App Review 5.1.1(i)', f'no privacy policy URL in App Information ({locale}): '
                                                  '"privacyPolicyUrl" in the listing file, then listing')
    res = store.get(f"/v1/appInfos/{info['id']}", {'include': 'primaryCategory'})
    category = ((res.get('data') or {}).get('relationships') or {}).get('primaryCategory')
    if isinstance(category, dict) and 'data' in category:
        if category['data']:
            punch.add('OK', 'App Store Connect', f"primary category {category['data'].get('id')}")
        else:
            punch.add('BLOCK', 'App Store Connect', 'no primary category in App Information')


def _subscriptions(store: AppStore, punch: Punch) -> None:
    groups = store.get(f'/v1/apps/{store.app_id}/subscriptionGroups', {'limit': 50})['data']
    if not groups:
        punch.add('OK', 'subscriptions', 'no subscription groups')
        return
    for group in groups:
        subs = store.get(f"/v1/subscriptionGroups/{group['id']}/subscriptions", {'limit': 50})['data']
        for sub in subs:
            a = sub.get('attributes') or {}
            name = f"{a.get('name') or '?'} ({a.get('productId') or sub['id']})"
            state = a.get('state')
            if state == 'MISSING_METADATA':
                punch.add('BLOCK', 'subscriptions', f'{name} is MISSING_METADATA: complete its '
                                                    'localization, price, availability and review '
                                                    'screenshot in App Store Connect')
            elif state == 'READY_TO_SUBMIT':
                punch.add('WARN', 'subscriptions', f'{name} is READY_TO_SUBMIT: attach it on the version '
                                                   'page in App Store Connect if this is its first '
                                                   'submission (Apple takes a first subscription only '
                                                   'with a version)')
            elif state in ('REJECTED', 'DEVELOPER_ACTION_NEEDED'):
                punch.add('BLOCK', 'subscriptions', f"{name} is {state}: read App Review's note on it in "
                                                    'App Store Connect and fix it')
            else:
                punch.add('OK', 'subscriptions', f'{name} is {state}')


def _submissions(store: AppStore, punch: Punch) -> None:
    open_ones = store.get('/v1/reviewSubmissions', {
        'filter[app]': store.app_id, 'filter[platform]': 'IOS',
        'filter[state]': 'UNRESOLVED_ISSUES,READY_FOR_REVIEW,WAITING_FOR_REVIEW,IN_REVIEW',
        'limit': 10,
    })['data']
    if not open_ones:
        punch.add('OK', 'App Review', 'no review submission open')
    for s in open_ones:
        a = s.get('attributes') or {}
        state = a.get('state')
        if state == 'UNRESOLVED_ISSUES':
            punch.add('WARN', 'App Review', f"submission {s['id']} has unresolved issues: attach the new "
                                            'build with prepare, then resubmit that submission in App '
                                            'Store Connect. Do not cancel it: cancelling drops what is '
                                            'in it (subscriptions too) back to the version page')
        elif state == 'READY_FOR_REVIEW':
            punch.add('OK', 'App Review', f"draft submission {s['id']} was started in App Store Connect: "
                                          'submit --ios sends the version inside it, with everything '
                                          'already in it')
        else:
            when = (a.get('submittedDate') or '')[:16]
            punch.add('OK', 'App Review', f"submission {s['id']} is {state}" + (f', sent {when}' if when else ''))


def ios(app: App, number: str | None, punch: Punch) -> None:
    punch.heading(f'App Store: {app.name} ({app.bundle_id})')
    try:
        store = AppStore(app)
    except StoreError as e:
        punch.add('UNCHECKED', 'App Store Connect', f'everything on the App Store: could not read it: '
                                                    f'{e} (doctor checks the key)')
        return
    punch.add('OK', 'App Store Connect', f'app {store.app_id}, primary locale {store.primary}')

    build = None
    if number:
        found = punch.attempt('build', f'build {number}', store.builds, 1, number)
        if found == []:
            punch.add('BLOCK', 'build', f'no build {number} in App Store Connect: upload it and wait '
                                        'for processing')
        elif found:
            build = found[0]

    # Each read below stops only what depends on it; the rest still run.
    versions = punch.attempt('version', 'the version, its build, text, screenshots, release type '
                             'and App Review details (the versions could not be read)',
                             store.versions, 10)
    target = _target(store, versions, build, number, punch) if versions is not None else None
    if build is not None:
        _build_checks(build, punch, 'build')
    if target is not None:
        attached = punch.attempt('build', 'the attached build, copyright, release type and App Review '
                                 'details', _version_detail, store, target, build, number, punch)
        if attached:
            _build_checks(attached, punch, 'attached build')
        # An update when another version has been out before this one.
        update = any(v['state'] in DONE and v['id'] != target['id'] for v in versions)
        locs = punch.attempt('App Store Connect', "the version's text, its screenshots and the "
                             'support URL (the localizations could not be read)', _texts, store,
                             target, update, punch)
        if locs:
            _screenshots(store, locs, target['version'], punch)
            primary = next((l for l in locs if (l.get('attributes') or {}).get('locale') == store.primary),
                           locs[0])
            support = (primary.get('attributes') or {}).get('supportUrl')
            if support:
                _url(support, 'support URL', 'App Review 1.5', punch)
    punch.attempt('App Review 5.1.1(i)', 'the privacy policy URL and primary category', _app_info,
                  store, punch)
    punch.attempt('subscriptions', 'the subscriptions', _subscriptions, store, punch)
    punch.attempt('App Review', 'the review submissions', _submissions, store, punch)


# --- Google Play -------------------------------------------------------------


def _release_notes(app: App, punch: Punch) -> None:
    path = app.release_notes
    if path is None:
        punch.add('OK', 'Google Play', 'no release_notes in the config: submit --android sends '
                                       '--notes FILE, or none')
        return
    if not path.is_file():
        punch.add('WARN', 'Google Play', f'release_notes names {path}, which does not exist: submit '
                                         '--android refuses until it does (or pass --notes FILE)')
        return
    try:
        notes = parse_notes(path.read_text(encoding='utf-8'))
    except StoreError as e:
        punch.add('BLOCK', 'Google Play', str(e))
        return
    for lang, body in notes:
        label = lang or 'default language'
        if len(body) > NOTES_LIMIT:
            punch.add('BLOCK', 'Google Play', f'release notes ({label}) are {len(body)} characters: '
                                              f'Play takes {NOTES_LIMIT} at most')
        elif not body:
            punch.add('WARN', 'Google Play', f'release notes ({label}) are empty')
        else:
            punch.add('OK', 'Google Play', f'release notes ({label}): {len(body)} of {NOTES_LIMIT} '
                                           f'characters, from {app.shown(path)}')


def _tracks(app: App, tracks: list[dict], punch: Punch) -> None:
    by_name = {t.get('track'): t for t in tracks}
    internal = Play.newest(by_name.get('internal') or {})
    if internal:
        punch.add('OK', 'Google Play', f'internal: newest build {_describe(internal)}')
    else:
        punch.add('BLOCK', 'Google Play', 'no build on the internal track: submit --android promotes '
                                          'the newest internal build (or --from-track NAME), so upload '
                                          'one there first')
    production = (by_name.get('production') or {}).get('releases') or []
    for release in production:
        note = (' (Play says completed while a release is still in review; links shows whether '
                'the app is live)') if release.get('status') == 'completed' else ''
        punch.add('OK', 'Google Play', f'production: {_describe(release)}{note}')
    if not production:
        punch.add('OK', 'Google Play', 'production: no release yet')
    # Play treats an app as a draft until a release goes out on any track but
    # internal testing: closed or open testing ends it as well as production.
    out = [(name, r) for name, t in by_name.items() if name != 'internal'
           for r in (t or {}).get('releases') or []
           if r.get('status') in ('completed', 'inProgress', 'halted')]
    if not out:
        if app.draft_until_published:
            punch.add('OK', 'Google Play', 'no release has gone out beyond internal testing, and '
                                           'draft_until_published is set: submit --android sends a '
                                           'draft, to roll out by hand in Play Console')
        else:
            punch.add('WARN', 'Google Play', 'no release has ever gone out beyond internal testing, so '
                                             'Play likely treats the app as a draft and takes only draft '
                                             'releases: use submit --android --draft (or set '
                                             'android.draft_until_published), then start the rollout '
                                             'in Play Console')
    elif app.draft_until_published:
        name = out[0][0]
        punch.add('WARN', 'Google Play', f'a release has gone out on {name} but draft_until_published '
                                         'is still true: set it to false so submit --android sends '
                                         'releases for review')
    codes = [int(c) for r in production if r.get('status') in ('completed', 'inProgress', 'halted')
             for c in r.get('versionCodes') or []]
    if internal and codes:
        newest = max(int(c) for c in internal['versionCodes'])
        if newest > max(codes):
            punch.add('OK', 'Google Play', f'internal build {newest} is newer than production '
                                           f'({max(codes)}): submit --android sends it')
        else:
            punch.add('OK', 'Google Play', f"internal's newest build ({newest}) is already on production: "
                                           'submit --android has nothing to send')


def android(app: App, punch: Punch) -> None:
    punch.heading(f'Google Play: {app.name} ({app.package})')
    _release_notes(app, punch)
    try:
        store = Play(app)
        edit = store.open()
    except StoreError as e:
        punch.add('UNCHECKED', 'Google Play', f'everything on Google Play: could not read it: {e} '
                                              '(doctor checks the key)')
        return
    try:
        details = punch.attempt('Play policy', 'the contact details, listing text and listing pictures '
                                '(the app details could not be read)', store.get, edit, '/details')
        tracks = punch.attempt('Google Play', 'the tracks and releases', store.tracks, edit)
        if tracks is not None:
            _tracks(app, tracks, punch)
        if details is not None:
            language = details.get('defaultLanguage') or 'en-US'
            if details.get('contactEmail'):
                punch.add('OK', 'Play policy', 'contact email set in the app details')
            else:
                punch.add('BLOCK', 'Play policy', 'no contact email in the app details (Play Console > '
                                                  'Store settings): Play requires one')
            if details.get('contactWebsite'):
                punch.add('OK', 'Play policy', f"contact website set: {details['contactWebsite']}")
            else:
                punch.add('WARN', 'Play policy', 'no contact website in the app details')
            listing = punch.attempt('Google Play', f'the {language} listing text', store.get, edit,
                                    f'/listings/{language}')
            if listing is not None:
                missing = [label for key, label in (('title', 'title'), ('shortDescription', 'short description'),
                                                    ('fullDescription', 'full description')) if not listing.get(key)]
                if missing:
                    punch.add('BLOCK', 'Google Play', f'listing ({language}) has no {", ".join(missing)}: '
                                                      'listing sets them')
                else:
                    punch.add('OK', 'Google Play', f'listing ({language}): title, short and full description set')
            for kind, need, label in (('icon', 1, 'icon'), ('featureGraphic', 1, 'feature graphic'),
                                      ('phoneScreenshots', 2, 'phone screenshots')):
                found = punch.attempt('Google Play', f'the {label} on the {language} listing', store.get,
                                      edit, f'/listings/{language}/{kind}')
                if found is None:
                    continue
                count = len(found.get('images') or [])
                if count >= need:
                    punch.add('OK', 'Google Play', f'{label} on the listing ({language}): {count}')
                else:
                    punch.add('BLOCK', 'Google Play', f'{label} on the listing ({language}): {count}; Play needs '
                                                      f'{need} or more (screenshots uploads them)')
    finally:
        try:
            store.discard(edit)
        except StoreError as e:
            punch.add('WARN', 'Google Play', f'could not discard the edit ({e}); it expires by itself')


def run(app: App, want_ios: bool, want_android: bool, number: str | None) -> tuple[list[str], bool]:
    """The punch list, and whether it failed: any BLOCK or UNCHECKED line."""
    punch = Punch()
    # The MANUAL lines go in whatever the stores answered: they are what the
    # APIs cannot see, so they matter most when the rest could not be read.
    if want_ios:
        ios(app, number, punch)
        for guard, text in IOS_MANUAL:
            punch.add('MANUAL', guard, text)
    if want_android:
        android(app, punch)
        for guard, text in ANDROID_MANUAL:
            punch.add('MANUAL', guard, text)
    title = f'preflight: {app.name} ({app.key})' + (f', build {number}' if number else '')
    return punch.render(title), punch.failed()


# --- Doctor ------------------------------------------------------------------


class Checks:
    def __init__(self, title: str) -> None:
        self.lines = [title]
        self.total = 0
        self.failed = 0

    def ok(self, what: str, detail: str) -> None:
        self.total += 1
        self.lines.append(f'  OK    {what}: {detail}')

    def fail(self, what: str, detail: str, fix: str) -> None:
        self.total += 1
        self.failed += 1
        self.lines += [f'  FAIL  {what}: {detail}', f'        fix: {fix}']

    def note(self, what: str, detail: str) -> None:
        """Worth knowing, but not a failure: not counted."""
        self.lines.append(f'  NOTE  {what}: {detail}')


def _apple_fix(error: str) -> str:
    if '(401)' in error:
        return ('Apple refused the token: check that issuer_id and key_id in asc.json belong to this '
                '.p8, that the key is not revoked (Users and Access > Integrations), and that this '
                "computer's clock is right")
    if '(403)' in error:
        return "the key's role cannot read apps: give it App Manager or Admin"
    return "Apple's API failed: run doctor again in a minute"


def _play_fix(error: str, package: str) -> str:
    lowered = error.lower()
    if 'has not been used' in lowered or 'is disabled' in lowered or 'service_disabled' in lowered:
        return ("enable the Google Play Android Developer API in the service account's Google Cloud "
                'project (APIs & Services > Library)')
    if '(404)' in error or 'not found' in lowered:
        return (f'Play has no app {package} this account can see: create it in Play Console and upload '
                "the first build by hand (Play's API cannot create an app), then grant the service "
                'account access to it')
    if '(401)' in error or '(403)' in error:
        return ('invite the service account in Play Console > Users and permissions and grant it this '
                f'app (release and store listing permissions); see {connect_doc()}')
    return "Google's API failed: run doctor again in a minute"


def doctor(explicit: str | None, key: str, ios_flag: bool, android_flag: bool) -> Checks:
    """One line per check, OK or FAIL, each FAIL with its fix. A check that
    depends on a failed one is not run."""
    checks = Checks(f'doctor: {key}')
    try:
        path = find_config(explicit)
    except StoreError as e:
        checks.fail('config', str(e), f'create {CONFIG_NAME} at the project root, starting from '
                                      f'{EXAMPLE}; or pass --config PATH')
        return checks
    try:
        config = load_config(path)
    except StoreError as e:
        checks.fail('config', str(e), f'correct it; {EXAMPLE} shows every field')
        return checks
    checks.ok('config', f'{path} is valid')
    try:
        app = config.app(key)
    except StoreError as e:
        checks.fail('app', str(e), f'use one of the apps listed, or add "{key}" under "apps"')
        return checks
    checks.ok('app', f'"{app.name}": iOS {app.bundle_id or "(none)"}, Android {app.package or "(none)"}')

    want_ios, want_android = bool(app.bundle_id), bool(app.package)
    if ios_flag or android_flag:
        want_ios, want_android = ios_flag, android_flag
    for flag, platform, have in ((want_ios, 'ios', app.bundle_id), (want_android, 'android', app.package)):
        if flag and not have:
            checks.fail('app', f'{key} has no "{platform}" block',
                        f'add "{platform}" to apps.{key} in the config, or drop --{platform}')
            return checks

    if config.keys is None:
        checks.fail('keys', f'{path} has no "keys"',
                    'add "keys" with "app_store_connect" and "google_play" paths outside the '
                    f'repository; how to make each key: {connect_doc()}')
    else:
        if want_ios:
            _doctor_apple(app, checks)
        if want_android:
            _doctor_play(app, checks)

    paths = [('listing', app.listing)]
    if want_ios:
        paths += [('screenshots.ios', app.screenshots_ios), ('creative', app.creative)]
    if want_android:
        paths += [('screenshots.android', app.screenshots_android),
                  ('play_feature_graphic', app.play_feature_graphic),
                  ('play_icon', app.play_icon), ('release_notes', app.release_notes)]
    # The store files a config names need not exist yet (a new project sets up
    # its keys before it has pictures), so a missing one is a note, not a FAIL.
    for name, value in paths:
        if value is None:
            continue
        if value.exists():
            checks.ok(name, app.shown(value))
        else:
            checks.note(name, f'{app.shown(value)} does not exist yet; the commands that read it '
                              'stop until it does')
    return checks


def _doctor_apple(app: App, checks: Checks) -> None:
    what = 'App Store Connect key'
    try:
        path = app.config.key_file('app_store_connect')
    except StoreError as e:
        checks.fail(what, str(e), f'create an App Store Connect API key: see {connect_doc()}')
        return
    checks.ok(what, f'{path} (outside the repository)')
    try:
        issuer_id, key_id, key_file = asc.credentials(app)
        key = asc.load_private_key(key_file)
    except StoreError as e:
        checks.fail(what, str(e), f'fix asc.json or download the .p8 again: see {connect_doc()}')
        return
    checks.ok(what, f'asc.json names an issuer and a key; {key_file.name} loads (outside the repository)')
    try:
        token = asc.sign(issuer_id, key_id, key)
        query = urllib.parse.urlencode({'filter[bundleId]': app.bundle_id})
        found = asc.call('GET', f'{asc.API}/v1/apps?{query}', token=token)['data']
    except StoreError as e:
        checks.fail('App Store Connect', str(e), _apple_fix(str(e)))
        return
    try:
        match = asc.find_app(found, app.bundle_id)
    except StoreError as e:
        checks.fail('App Store Connect', f'the token is accepted, but: {e}',
                    "check bundle_id; create the app record in App Store Connect; or use a key from the "
                    'team that owns the app')
        return
    checks.ok('App Store Connect', f"token accepted; app {match['id']} found for {app.bundle_id}")


def _doctor_play(app: App, checks: Checks) -> None:
    what = 'Google Play key'
    try:
        path = app.config.key_file('google_play')
    except StoreError as e:
        checks.fail(what, str(e), f'create a Google Play service account key: see {connect_doc()}')
        return
    checks.ok(what, f'{path} (outside the repository)')
    try:
        account = play.read_account(app)
        key = play.load_private_key(account)
    except StoreError as e:
        checks.fail(what, str(e), f'download a new JSON key for the service account: see {connect_doc()}')
        return
    checks.ok(what, 'a service account key; its private key loads')
    try:
        token = play.exchange(account, key)
    except StoreError as e:
        checks.fail('Google Play', f'Google refused the key: {e}',
                    'the key may be deleted, or the service account disabled, in Google Cloud > IAM > '
                    f'Service accounts: make a new JSON key ({connect_doc()})')
        return
    checks.ok('Google Play', 'token accepted')
    store = Play(app, token=token)
    try:
        edit = store.open()
    except StoreError as e:
        checks.fail('Google Play', f'cannot open an edit for {app.package}: {e}',
                    _play_fix(str(e), app.package))
        return
    try:
        store.discard(edit)
    except StoreError:
        pass  # an edit left open expires by itself
    checks.ok('Google Play', f'the service account can open an edit for {app.package} (opened and discarded)')
