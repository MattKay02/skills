"""Google Play: status, submission to production, release notes, testers,
listing text and pictures, for the apps in the project's config.

The key is a JSON key for a Google Cloud service account that has been
granted the app in Play Console, kept outside the repository:
`keys.google_play` in .store-release.json names it. See references/connect.md.

Every change goes through an *edit*, Play's transaction: opened, changed, then
committed, or deleted when nothing should change.

Every command here opens an edit, the read-only ones too (status, doctor,
preflight, testers). Never run one while a CI build is uploading to Play:
opening a new edit expires the upload's own ("This edit has expired, please
create a new Edit") and the upload fails.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from common import App, StoreError, call, connect_doc, rs256_jwt
from pictures import read_image

API = 'https://androidpublisher.googleapis.com/androidpublisher/v3/applications'
UPLOAD = 'https://androidpublisher.googleapis.com/upload/androidpublisher/v3/applications'
SCOPE = 'https://www.googleapis.com/auth/androidpublisher'
# Google's own token endpoint, pinned. The key file carries a token_uri too,
# but trusting it would let an edited key file send the signed assertion,
# good for an hour, to any address it names.
TOKEN_URL = 'https://oauth2.googleapis.com/token'
NOTES_LIMIT = 500
# Play's text limits, checked on disk before anything is sent.
TEXT_LIMITS = {'title': 30, 'shortDescription': 80, 'fullDescription': 4000}

# Said when Play kept a committed edit for sending by hand (Play.commit).
HELD = ('  saved, but Play would not send it for review from here: Play Console > '
        'Publishing overview > Send changes for review')

SCREENSHOT_KINDS = {'phoneScreenshots': 'phone screenshots',
                    'sevenInchScreenshots': '7-inch tablet screenshots',
                    'tenInchScreenshots': '10-inch tablet screenshots'}


# --- The key -----------------------------------------------------------------


def read_account(app: App) -> dict:
    """The service account's key file, checked. Nothing in it is printed."""
    path = app.config.key_file('google_play')
    try:
        account = json.loads(path.read_text(encoding='utf-8'))
    except ValueError:
        raise StoreError(f'{path} is not valid JSON: download the service account key again '
                         f'(see {connect_doc()}).') from None
    if not isinstance(account, dict) or account.get('type') != 'service_account' \
            or not account.get('client_email') or not account.get('private_key'):
        raise StoreError(f'{path} is not a Google service account key (it needs "type": '
                         '"service_account", "client_email" and "private_key"). '
                         f'See {connect_doc()}.')
    return account


def load_private_key(account: dict):
    try:
        key = serialization.load_pem_private_key(account['private_key'].encode('utf-8'), password=None)
    except (ValueError, TypeError):
        raise StoreError('The service account key\'s private_key does not load: download a new '
                         f'JSON key (see {connect_doc()}).') from None
    if not isinstance(key, rsa.RSAPrivateKey):
        raise StoreError('The service account key\'s private_key is not an RSA key.')
    return key


def exchange(account: dict, key=None) -> str:
    """Trade a signed assertion for an access token at Google's token
    endpoint (TOKEN_URL, whatever the key file's token_uri says)."""
    key = key or load_private_key(account)
    now = int(time.time())
    assertion = rs256_jwt(
        {'iss': account['client_email'], 'scope': SCOPE, 'aud': TOKEN_URL,
         'iat': now, 'exp': now + 3600},
        key,
    )
    form = urllib.parse.urlencode({
        'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
        'assertion': assertion,
    }).encode('ascii')
    res = call('POST', TOKEN_URL, data=form,
               headers={'Content-Type': 'application/x-www-form-urlencoded'})
    return res['access_token']


def _token(app: App) -> str:
    return exchange(read_account(app))


# --- Release notes -----------------------------------------------------------

_TAGGED = re.compile(r'<([A-Za-z]{2,3}(?:-[A-Za-z0-9]+)*)>\s*(.*?)\s*</\1>', re.DOTALL)


def parse_notes(text: str) -> list[tuple[str | None, str]]:
    """Release notes as [(language, text)]. Plain text is for the listing's
    default language (None); text in Play Console's own tags, <en-GB>...</en-GB>
    one block per language, is split by language."""
    text = text.strip()
    blocks = list(_TAGGED.finditer(text))
    if not blocks:
        return [(None, text)]
    leftover = _TAGGED.sub('', text).strip()
    if leftover:
        raise StoreError('Release notes mix language tags with untagged text '
                         f'("{leftover[:60]}"): put every language in its own <xx-YY> block, or use '
                         'plain text for the default language alone.')
    return [(m.group(1), m.group(2).strip()) for m in blocks]


def check_notes(text: str, source: str) -> list[tuple[str | None, str]]:
    """Refuse notes over Play's 500 characters, before anything is opened."""
    notes = parse_notes(text)
    long = [(lang or 'default language', len(body)) for lang, body in notes if len(body) > NOTES_LIMIT]
    if long:
        said = ', '.join(f'{lang} has {n}' for lang, n in long)
        raise StoreError(f"Play's release notes take {NOTES_LIMIT} characters at most per language; "
                         f'{source}: {said}. Shorten it (the App Store takes a longer What\'s New '
                         'from a file of its own).')
    return notes


def _release_notes(notes: list[tuple[str | None, str]], language: str) -> list[dict]:
    return [{'language': lang or language, 'text': body} for lang, body in notes]


def _notes_label(notes: list[tuple[str | None, str]] | None, language: str) -> str:
    if not notes:
        return f'release notes ({language}): none'
    if len(notes) == 1 and notes[0][0] is None:
        return f'release notes ({language}): set'
    return 'release notes: ' + ', '.join(lang or language for lang, _ in notes)


def _describe(release: dict) -> str:
    fraction = release.get('userFraction')
    rollout = f' at {round(fraction * 100)}%' if fraction else ''
    codes = ', '.join(release.get('versionCodes', [])) or 'no build'
    return f"{release.get('name') or '?'} ({codes}): {release.get('status')}{rollout}"


class Play:
    def __init__(self, app: App, token: str | None = None, locale: str | None = None):
        """[locale] is the listing language that listing and screenshots work
        on; the app's default language unless named (--locale)."""
        app.require('android')
        self.app = app
        self.package = app.package
        self.locale = locale
        self.token = token or _token(app)

    def _url(self, edit: str, path: str = '') -> str:
        return f'{API}/{self.package}/edits/{edit}{path}'

    def open(self) -> str:
        return call('POST', f'{API}/{self.package}/edits', token=self.token, body={})['id']

    def discard(self, edit: str) -> None:
        call('DELETE', self._url(edit), token=self.token, expect_json=False)

    def commit(self, edit: str) -> bool:
        """Commit the edit and send it for review. Play sometimes will not
        send from the API ("Changes cannot be sent for review automatically",
        while changes made in Play Console wait to be sent, for one): the edit
        is then committed unsent, as Play's message asks, and this returns
        False so the caller can say it waits in Publishing overview."""
        try:
            call('POST', self._url(edit, ':commit'), token=self.token)
            return True
        except StoreError as e:
            if 'changesNotSentForReview' not in str(e):
                raise
        call('POST', self._url(edit, ':commit?changesNotSentForReview=true'), token=self.token)
        return False

    def get(self, edit: str, path: str):
        return call('GET', self._url(edit, path), token=self.token) or {}

    def tracks(self, edit: str) -> list[dict]:
        return self.get(edit, '/tracks').get('tracks', [])

    def default_language(self, edit: str) -> str:
        return self.get(edit, '/details').get('defaultLanguage', 'en-US')

    def language(self, edit: str) -> str:
        """The listing language to work on: --locale, else the default."""
        return self.locale or self.default_language(edit)

    # --- Reading ------------------------------------------------------------

    def status(self) -> list[str]:
        edit = self.open()
        try:
            lines = [f"Google Play: {self.app.name} ({self.package})"]
            for track in self.tracks(edit):
                releases = track.get('releases') or []
                if not releases:
                    continue
                for release in releases:
                    lines.append(f"  {track['track']}: {_describe(release)}")
            return lines
        finally:
            self.discard(edit)

    def link(self) -> list[str]:
        """The public Google Play page. Play's API cannot say whether an app
        is live (a release reads `completed` while still in review), so the
        page itself is asked: it answers 404 until the app is."""
        url = f'https://play.google.com/store/apps/details?id={self.package}'
        try:
            call('GET', url, expect_json=False)
            state = 'live'
        except StoreError:
            state = 'not live yet'
        return [f"Google Play: {url} ({state})"]

    # --- Submitting ---------------------------------------------------------

    @staticmethod
    def newest(track: dict) -> dict | None:
        releases = [r for r in track.get('releases') or [] if r.get('versionCodes')]
        if not releases:
            return None
        return max(releases, key=lambda r: max(int(c) for c in r['versionCodes']))

    def submit(self, notes: list[tuple[str | None, str]] | None, draft: bool, apply: bool,
               draft_reason: str = '', source_track: str = 'internal',
               rollout: float | None = None) -> list[str]:
        """The newest build on [source_track] to production: for everybody,
        or to a share of users when [rollout] is below 1 (a staged rollout).
        Google reviews it and, unless managed publishing is on, it goes live
        the moment it is approved. [notes] come from check_notes."""
        edit = self.open()
        committed = False
        try:
            by_name = {t['track']: t for t in self.tracks(edit)}
            if source_track not in by_name:
                raise StoreError(f'No track "{source_track}" for {self.app.name}: it has '
                                 f'{", ".join(sorted(by_name)) or "none"}.')
            source = self.newest(by_name[source_track])
            if source is None:
                raise StoreError(f'No build on the {source_track} track for {self.app.name}.')
            # A build already out on production has nothing left to send; a
            # draft holding it may still be sent for review.
            live = [r for r in (by_name.get('production') or {}).get('releases') or []
                    if r.get('status') in ('completed', 'inProgress', 'halted')
                    and set(source['versionCodes']) <= set(r.get('versionCodes') or [])]
            if live:
                raise StoreError(
                    f'{_describe(source)}, the newest on {source_track}, is already on production '
                    f'({_describe(live[0])}): nothing to send. Upload a newer build to {source_track} '
                    'first. A staged rollout\'s share is changed in Play Console > Production.')
            language = self.default_language(edit)
            staged = rollout is not None and rollout < 1
            release = {
                'name': source.get('name'),
                'versionCodes': source['versionCodes'],
                # A draft is all Play takes for an app with nothing ever
                # rolled out; after that, completed is 100% on approval and
                # inProgress is a staged rollout to userFraction of users.
                'status': 'draft' if draft else ('inProgress' if staged else 'completed'),
            }
            if staged:
                release['userFraction'] = rollout
            if notes:
                release['releaseNotes'] = _release_notes(notes, language)
            if draft:
                reach = 'as a draft, to roll out by hand' + draft_reason
            elif staged:
                reach = (f'staged rollout to {rollout * 100:g}% of users once Google approves it '
                         '(raise it later in Play Console)')
            else:
                reach = 'rollout 100%: for everybody, live once Google approves it'
            plan = [
                f"Google Play: {self.app.name} {_describe(source)} from {source_track} to production",
                f'  {reach}',
                f"  {_notes_label(notes, language)}",
            ]
            if not apply:
                return plan + ['  (plan only: run again with --yes to do it)']
            call('PUT', self._url(edit, '/tracks/production'), token=self.token,
                 body={'track': 'production', 'releases': [release]})
            try:
                sent = self.commit(edit)
            except StoreError as e:
                if 'draft app' in str(e).lower() and not draft:
                    raise StoreError(
                        f"{e}\n  Play treats an app as a draft until it is first published "
                        '(an internal rollout does not count), and takes only draft '
                        'releases for it. Run again with --draft (or set '
                        'android.draft_until_published in the config), then start the rollout '
                        'in Play Console; every later release can go from here.'
                    ) from None
                raise
            committed = True
            if draft:
                return plan + ['  a draft on production: nothing goes to Google until it is '
                               'rolled out in Play Console > Production > Start rollout']
            return plan + (['  sent to Google for review'] if sent else [HELD])
        finally:
            if not committed:
                self.discard(edit)

    def test_notes(self, notes: list[tuple[str | None, str]], apply: bool) -> list[str]:
        """Release notes on the newest internal build, which testers see."""
        edit = self.open()
        committed = False
        try:
            tracks = {t['track']: t for t in self.tracks(edit)}
            internal = tracks.get('internal')
            newest = self.newest(internal or {})
            if newest is None:
                raise StoreError(f'No build on the internal track for {self.app.name}.')
            language = self.default_language(edit)
            plan = [f"Google Play: internal notes for {self.app.name} {_describe(newest)} "
                    f"({', '.join(lang or language for lang, _ in notes)})"]
            if not apply:
                return plan + ['  (plan only: run again with --yes to do it)']
            for release in internal['releases']:
                if release is newest:
                    release['releaseNotes'] = _release_notes(notes, language)
            call('PUT', self._url(edit, '/tracks/internal'), token=self.token, body=internal)
            sent = self.commit(edit)
            committed = True
            return plan + ['  set'] + ([] if sent else [HELD])
        finally:
            if not committed:
                self.discard(edit)

    def testers(self) -> list[str]:
        """Who the internal track reaches. Play keeps individual addresses
        in its email lists, which have no API: only Google Groups show here."""
        edit = self.open()
        try:
            found = self.get(edit, '/testers/internal')
            groups = ', '.join(found.get('googleGroups') or []) or 'none'
            return [f"Google Play: {self.app.name} internal testers, Google Groups: {groups}",
                    '  (email lists are managed in Play Console > Testing > Internal testing)']
        finally:
            self.discard(edit)

    # --- The listing --------------------------------------------------------

    def listing(self, fields: dict, apply: bool) -> list[str]:
        """Text from the listing file's "android" block."""
        allowed = {k: fields[k] for k in ('title', 'shortDescription', 'fullDescription', 'video') if k in fields}
        edit = self.open()
        committed = False
        try:
            language = self.language(edit)
            plan = [f"Google Play listing: {self.app.name} ({language}): {', '.join(allowed) or 'nothing'}"]
            if not apply:
                return plan + ['  (plan only: run again with --yes to do it)']
            call('PATCH', self._url(edit, f'/listings/{language}'), token=self.token,
                 body={'language': language, **allowed})
            sent = self.commit(edit)
            committed = True
            return plan + ['  updated'] + ([] if sent else [HELD])
        finally:
            if not committed:
                self.discard(edit)

    def screenshots(self, groups: dict[str, list[Path]], feature: Path | None, icon: Path | None,
                    apply: bool) -> list[str]:
        """Replace each kind of screenshot given (phone, and the tablets when
        their folders exist) with its files, in name order, and the feature
        graphic and the 512x512 icon when given. Kinds not given are left as
        they are. Everything is already checked on disk. The plan reads what
        the listing holds now. It all goes in one edit, so a failure part way
        changes nothing on Play."""
        if not groups.get('phoneScreenshots'):
            raise StoreError('No phone screenshots to upload.')
        edit = self.open()
        committed = False
        try:
            language = self.language(edit)
            replacing: dict[str, list[Path]] = dict(groups)
            if feature:
                replacing['featureGraphic'] = [feature]
            if icon:
                replacing['icon'] = [icon]
            now = {kind: len(self.get(edit, f'/listings/{language}/{kind}').get('images') or [])
                   for kind in replacing}
            plan = [f"Google Play pictures: {self.app.name} ({language}): "
                    + ', '.join(f'{len(files)} {SCREENSHOT_KINDS[kind]}' for kind, files in groups.items())
                    + (', the feature graphic' if feature else '')
                    + (', the icon' if icon else '')]
            for kind, files in replacing.items():
                names = ', '.join(f.name for f in files)
                there = f'replace the {now[kind]} there now with' if now[kind] else 'none there now, upload'
                plan.append(f'  {kind}: {there} {len(files)}: {names}')
            if not apply:
                return plan + ['  (plan only: run again with --yes to do it)']
            try:
                for kind in replacing:
                    call('DELETE', self._url(edit, f'/listings/{language}/{kind}'),
                         token=self.token, expect_json=False)
                for kind, files in replacing.items():
                    for file in files:
                        call('POST',
                             f'{UPLOAD}/{self.package}/edits/{edit}/listings/{language}/{kind}?uploadType=media',
                             token=self.token, data=file.read_bytes(),
                             headers={'Content-Type': read_image(file).content_type})
                sent = self.commit(edit)
            except StoreError as e:
                raise StoreError(f'{e}\n  Nothing changed on Google Play: the edit was not committed, so '
                                 'the listing keeps the pictures it had. Run screenshots again.') from None
            committed = True
            return plan + ['  uploaded'] + ([] if sent else [HELD])
        finally:
            if not committed:
                self.discard(edit)
