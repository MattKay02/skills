#!/usr/bin/env python3
"""App Store Connect and Google Play releases from the terminal, for the apps
named in the project's .store-release.json.

    python store.py <command> <app> [options]

    doctor       <app> [--ios|--android]
    status       <app> [--ios|--android]
    links        <app> [--ios|--android]
    preflight    <app> [--ios] [--android] [--build N]
    pictures     <app> [--ios|--android]
    prepare      <app> --build N [--automatic|--manual] [--yes]
    submit       <app> --ios --build N [--notes FILE] [--automatic|--manual] [--yes]
    submit       <app> --android [--notes FILE] [--draft] [--from-track NAME] [--rollout F] [--yes]
    release      <app> [--yes]
    release-type <app> --automatic|--manual [--yes]
    test-notes   <app> --notes FILE [--ios --build N | --android] [--yes]
    testers      <app> [--ios|--android]
    add-tester   <app> --email ADDRESS --group NAME [--yes]
    listing      <app> [--ios|--android] [--from FILE] [--locale CODE] [--yes]
    screenshots  <app> [--ios|--android] [--locale CODE] [--yes]
    assets       <app> [--from DIR] [--poster HH:MM:SS:FF] [--yes]

**Nothing changes without --yes.** Without it every command prints what it
would do and stops, so a plan can be read before a store is touched.

Release types: a new iOS version releases itself once Apple approves it; a
version that already exists keeps the release type it has (so one held with
`release-type --manual` stays held) unless prepare or submit is given
--automatic or --manual. An Android release goes to production for everybody,
or to a share of users with --rollout, live once Google approves it (unless
managed publishing is on in Play Console).

The config is the permission boundary: only the apps it lists can be named,
any other is refused before a store is called, and the keys it points to
must live where no repository contains them.

Google Play: every Play command opens an edit, the read-only ones too (status,
doctor, preflight, testers). Never run one while a CI build is uploading to
Play: opening a new edit expires the upload's own ("This edit has expired,
please create a new Edit") and the upload fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The scripts run from wherever the skill is installed: keep that folder free
# of __pycache__, and let the modules beside this one import each other.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import App, StoreError, check_lengths, find_config, load_config  # noqa: E402

COMMANDS = {
    'doctor': 'check the config, the keys, and that both stores accept them (read-only)',
    'status': 'where each version, build, track and review submission stands (read-only)',
    'links': 'the public store pages, and whether each is live (read-only)',
    'preflight': 'a punch list before submitting: BLOCK, UNCHECKED, WARN, OK, MANUAL (read-only)',
    'pictures': 'check the store pictures on disk: format, size, alpha, counts, order (local only)',
    'prepare': 'open the build\'s App Store version with the build attached; not submitted',
    'submit': 'send for review: --ios --build N, or --android (newest build on a track to production)',
    'release': 'release an approved App Store version that was held for a manual release',
    'release-type': 'switch the App Store version on its way to --automatic or --manual release',
    'test-notes': "set TestFlight's What to Test, or Play's internal release notes, from --notes FILE",
    'testers': "list TestFlight groups and testers, and Play's internal Google Groups (read-only)",
    'add-tester': 'add a TestFlight tester (--email) to a group (--group)',
    'listing': 'send the listing text from the listing file (or --from FILE)',
    'screenshots': "replace the screenshots, and Play's feature graphic and icon",
    'assets': 'App Store product page header and search results asset, from the creative folder',
}

# The options each command takes; any other given is refused, so a flag that
# would be ignored (release --android, submit --ios --draft) cannot mislead.
FLAGS = {
    'ios': '--ios', 'android': '--android', 'build': '--build', 'notes': '--notes',
    'draft': '--draft', 'automatic': '--automatic', 'manual': '--manual', 'email': '--email',
    'group': '--group', 'source': '--from', 'poster': '--poster', 'locale': '--locale',
    'from_track': '--from-track', 'rollout': '--rollout', 'yes': '--yes',
}
TAKES = {
    'doctor': {'ios', 'android'},
    'status': {'ios', 'android'},
    'links': {'ios', 'android'},
    'preflight': {'ios', 'android', 'build'},
    'pictures': {'ios', 'android'},
    'prepare': {'ios', 'build', 'automatic', 'manual', 'yes'},
    'submit': {'ios', 'android', 'build', 'notes', 'draft', 'automatic', 'manual',
               'from_track', 'rollout', 'yes'},
    'release': {'ios', 'yes'},
    'release-type': {'ios', 'automatic', 'manual', 'yes'},
    'test-notes': {'ios', 'android', 'build', 'notes', 'yes'},
    'testers': {'ios', 'android'},
    'add-tester': {'ios', 'email', 'group', 'yes'},
    'listing': {'ios', 'android', 'source', 'locale', 'yes'},
    'screenshots': {'ios', 'android', 'locale', 'yes'},
    'assets': {'ios', 'source', 'poster', 'yes'},
}
READ_ONLY = {'doctor', 'status', 'links', 'preflight', 'pictures', 'testers'}
APP_STORE_ONLY = {'prepare', 'release', 'release-type', 'add-tester', 'assets'}
SUBMIT_IOS_ONLY = ('build', 'automatic', 'manual')
SUBMIT_ANDROID_ONLY = ('draft', 'from_track', 'rollout')

EPILOG = '\n'.join(
    ['commands:']
    + [f'  {name:<13}{purpose}' for name, purpose in COMMANDS.items()]
    + ['',
       'Nothing that changes a store happens without --yes: without it, each command',
       'prints its plan and "(plan only: run again with --yes to do it)". A flag a',
       'command does not use is refused rather than ignored.',
       '',
       'preflight and pictures exit 1 when any line is BLOCK (or UNCHECKED: a read',
       'that failed), 0 otherwise. Every other command exits 1 with "Stopped: <reason>"',
       'when it stops, and a usage error (a missing or refused flag) exits 2.',
       '',
       'The config is .store-release.json, found by walking up from the current folder,',
       'or --config PATH, or $STORE_RELEASE_CONFIG.',
       '',
       'Google Play: every Play command opens an edit, the read-only ones too (status,',
       'doctor, preflight, testers). Never run one while a CI build is uploading to',
       'Play: a new edit expires the upload\'s own ("This edit has expired, please',
       'create a new Edit") and the upload fails.'])


def _refuse_unused(parser, args) -> None:
    given = [dest for dest in FLAGS if getattr(args, dest) not in (None, False)]
    extra = [dest for dest in given if dest not in TAKES[args.command]]
    if extra:
        names = ', '.join(FLAGS[d] for d in extra)
        if args.command in APP_STORE_ONLY and 'android' in extra:
            why = f'{args.command} is for the App Store only'
        elif args.command in READ_ONLY and 'yes' in extra:
            why = f'{args.command} changes nothing, so it has no plan to confirm'
        else:
            why = f'{args.command} has no use for it'
        parser.error(f'{args.command} does not take {names}: {why}.')
    if args.command == 'submit':
        if args.ios and (bad := [FLAGS[d] for d in SUBMIT_ANDROID_ONLY if d in given]):
            parser.error(f'{", ".join(bad)} {"is" if len(bad) == 1 else "are"} for submit --android, '
                         'not --ios.')
        if args.android and (bad := [FLAGS[d] for d in SUBMIT_IOS_ONLY if d in given]):
            parser.error(f'{", ".join(bad)} {"is" if len(bad) == 1 else "are"} for submit --ios, '
                         'not --android.')
    if args.automatic and args.manual:
        parser.error('--automatic and --manual: one or the other.')


def _platforms(args, app: App) -> tuple[bool, bool]:
    """The stores the app is on, unless one is named; a store the app is not
    on is refused."""
    if args.ios:
        app.require('ios')
    if args.android:
        app.require('android')
    if not args.ios and not args.android:
        return bool(app.bundle_id), bool(app.package)
    return args.ios, args.android


def _text(path: str | Path | None, what: str = 'notes') -> str | None:
    """A text file's contents, or a StoreError naming the file."""
    if not path:
        return None
    try:
        return Path(path).read_text(encoding='utf-8').strip()
    except FileNotFoundError:
        raise StoreError(f'No {what} file at {path}.') from None
    except (UnicodeDecodeError, OSError) as e:
        raise StoreError(f'{path} ({what}) cannot be read as UTF-8 text: {e}') from None


def _listing_file(path: Path) -> dict:
    """The listing file, or a StoreError naming it."""
    try:
        listing = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise StoreError(f'No listing file at {path}.') from None
    except (ValueError, OSError) as e:
        raise StoreError(f'{path} (the listing file) is not valid JSON: {e}') from None
    if not isinstance(listing, dict) or any(
            not isinstance(listing.get(k), dict) for k in ('ios', 'android') if k in listing):
        raise StoreError(f'{path} (the listing file) should hold an object with an "ios" and/or an '
                         '"android" object of fields.')
    return listing


def _android_notes(args, app: App):
    """Play's release notes: --notes FILE, else the config's release_notes.
    Checked against Play's 500 characters before anything is opened."""
    from play import check_notes
    if args.notes:
        return check_notes(_text(args.notes, 'release notes'), args.notes)
    if app.release_notes is None:
        return None
    if not app.release_notes.is_file():
        raise StoreError(f'release_notes in the config names {app.release_notes}, which does not '
                         'exist: create it, or pass --notes FILE.')
    return check_notes(_text(app.release_notes, 'release notes'), app.shown(app.release_notes))


def _rollout(parser, args) -> float | None:
    if args.rollout is None:
        return None
    try:
        fraction = float(args.rollout)
    except ValueError:
        fraction = -1.0
    if not 0 < fraction <= 1:
        parser.error('--rollout takes a share of users above 0 and at most 1: 0.1 is 10%, 1 is everybody.')
    return fraction


def _gate(app: App, ios: bool, android: bool) -> None:
    """The pictures are checked on disk before any upload; a BLOCK stops it."""
    from pictures import check
    blocks = check(app, ios, android).blocks()
    if blocks:
        raise StoreError('\n  '.join(['The pictures cannot go up as they are:', *blocks,
                                      f'(pictures {app.key} shows the full table)']))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='store.py', description=__doc__.split('\n\n')[0], epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=list(COMMANDS), metavar='command',
                        help='one of the commands below')
    parser.add_argument('app', help='an app key from "apps" in the config')
    parser.add_argument('--config', metavar='PATH', help='the config file (default: the nearest '
                        '.store-release.json from here up, or $STORE_RELEASE_CONFIG)')
    parser.add_argument('--ios', action='store_true', help='the App Store only')
    parser.add_argument('--android', action='store_true', help='Google Play only')
    parser.add_argument('--build', metavar='N', help='the iOS build number, as TestFlight shows it')
    parser.add_argument('--notes', metavar='FILE', help="a text file: What's New (4000 characters), "
                        "Play's release notes (500 per language), or what to test")
    parser.add_argument('--draft', action='store_true',
                        help='submit --android: a draft on production, for an app never published')
    parser.add_argument('--from-track', dest='from_track', metavar='NAME',
                        help='submit --android: the track whose newest build goes to production '
                             '(default internal)')
    parser.add_argument('--rollout', metavar='F', help='submit --android: the share of users, above 0 '
                        'and at most 1 (default 1, everybody; 0.1 is a staged rollout to 10%%)')
    parser.add_argument('--automatic', action='store_true',
                        help='release itself once Apple approves it (release-type, prepare, submit --ios)')
    parser.add_argument('--manual', action='store_true',
                        help='wait for `release` after approval (release-type, prepare, submit --ios)')
    parser.add_argument('--email', metavar='ADDRESS', help='add-tester: the tester')
    parser.add_argument('--group', metavar='NAME', help='add-tester: the TestFlight group')
    parser.add_argument('--from', dest='source', metavar='PATH',
                        help='listing: the listing file; assets: the folder of creative assets')
    parser.add_argument('--locale', metavar='CODE', help='listing, screenshots: the localization or '
                        'listing language to change (default the primary one), e.g. de-DE')
    parser.add_argument('--poster', metavar='HH:MM:SS:FF', help='assets: the frame shown before a '
                        'video plays (e.g. 00:00:05:00)')
    parser.add_argument('--yes', action='store_true', help='do it, rather than show the plan')
    args = parser.parse_args(argv)
    # Store names and messages can hold any character; a console that cannot
    # show one should print a stand-in, not stop the run halfway.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')
    _refuse_unused(parser, args)
    wanted = 'AFTER_APPROVAL' if args.automatic else ('MANUAL' if args.manual else None)

    if args.command == 'doctor':
        from preflight import doctor
        checks = doctor(args.config, args.app, args.ios, args.android)
        print('\n'.join(checks.lines))
        if checks.failed:
            print(f'Stopped: {checks.failed} of {checks.total} checks failed; each FAIL says how to fix it.')
            return 1
        print(f'doctor: all {checks.total} checks passed')
        return 0

    out: list[str] = []
    code = 0
    try:
        config = load_config(find_config(args.config))
        app = config.app(args.app)  # any other app is refused here, before a store is called
        ios, android = _platforms(args, app)

        if args.command == 'status':
            if ios:
                from asc import AppStore
                out += AppStore(app).status()
            if android:
                from play import Play
                out += Play(app).status()

        elif args.command == 'links':
            out.append(app.name)
            if ios:
                from asc import AppStore
                out += ['  ' + line for line in AppStore(app).link()]
            if android:
                from play import Play
                out += ['  ' + line for line in Play(app).link()]

        elif args.command == 'preflight':
            from preflight import run
            lines, failed = run(app, ios, android, args.build)
            out += lines
            code = 1 if failed else 0

        elif args.command == 'pictures':
            from pictures import check
            report = check(app, ios, android)
            out += report.render(f'pictures: {app.name} ({app.key}), on disk only')
            code = 1 if report.blocks() else 0

        elif args.command == 'prepare':
            if not args.build:
                parser.error('prepare needs --build, the TestFlight build number')
            app.require('ios')
            from asc import AppStore
            out += AppStore(app).prepare(args.build, args.yes, wanted)

        elif args.command == 'submit':
            if args.ios == args.android:
                parser.error('submit one store at a time: --ios or --android')
            if args.ios:
                if not args.build:
                    parser.error('--ios needs --build, the TestFlight build number')
                from asc import TEXT_LIMITS, AppStore
                notes = _text(args.notes, "What's New")
                if notes:
                    check_lengths({'whatsNew': notes}, TEXT_LIMITS, args.notes)
                out += AppStore(app).submit(args.build, notes, args.yes, wanted)
            else:
                rollout = _rollout(parser, args)
                if args.from_track == 'production':
                    parser.error('--from-track names the track the build comes from, not production.')
                notes = _android_notes(args, app)
                draft = args.draft or app.draft_until_published
                if draft and rollout is not None and rollout < 1:
                    raise StoreError('A draft is rolled out by hand in Play Console, where its share is '
                                     'chosen: leave out --rollout.')
                reason = (' (draft_until_published in the config)'
                          if app.draft_until_published and not args.draft else '')
                from play import Play
                out += Play(app).submit(notes, draft, args.yes, reason,
                                        args.from_track or 'internal', rollout)

        elif args.command == 'release':
            app.require('ios')
            from asc import AppStore
            out += AppStore(app).release(args.yes)

        elif args.command == 'release-type':
            if wanted is None:
                parser.error('release-type needs one of --automatic or --manual')
            app.require('ios')
            from asc import AppStore
            out += AppStore(app).release_type(args.automatic, args.yes)

        elif args.command == 'test-notes':
            if not args.notes:
                parser.error('test-notes needs --notes FILE')
            if ios and not args.build:
                parser.error('--ios needs --build, the TestFlight build number')
            notes = _text(args.notes, 'test notes')
            if not notes:
                raise StoreError(f'{args.notes} is empty.')
            play_notes = None
            if ios:
                from asc import TEXT_LIMITS
                check_lengths({'whatsNew': notes}, TEXT_LIMITS, f'{args.notes} (What to Test)')
            if android:
                from play import check_notes
                play_notes = check_notes(notes, args.notes)
            if ios:
                from asc import AppStore
                out += AppStore(app).test_notes(args.build, notes, args.yes)
            if android:
                from play import Play
                out += Play(app).test_notes(play_notes, args.yes)

        elif args.command == 'testers':
            if ios:
                from asc import AppStore
                out += AppStore(app).testers()
            if android:
                from play import Play
                out += Play(app).testers()

        elif args.command == 'add-tester':
            if not args.email or not args.group:
                parser.error('add-tester needs --email and --group (a TestFlight group)')
            app.require('ios')
            from asc import AppStore
            out += AppStore(app).add_tester(args.email, args.group, args.yes)

        elif args.command == 'listing':
            source = Path(args.source) if args.source else app.listing
            if source is None:
                raise StoreError(f'No listing file: set "listing" for {app.key} in the config, '
                                 'or pass --from FILE.')
            listing = _listing_file(source)
            # Every limit is checked for both stores before either is called.
            if ios and 'ios' in listing:
                from asc import TEXT_LIMITS
                check_lengths(listing['ios'], TEXT_LIMITS, f'{source} "ios"')
            if android and 'android' in listing:
                from play import TEXT_LIMITS as PLAY_LIMITS
                check_lengths(listing['android'], PLAY_LIMITS, f'{source} "android"')
            if ios:
                if 'ios' in listing:
                    from asc import AppStore
                    out += AppStore(app, locale=args.locale).listing(listing['ios'], args.yes)
                else:
                    out.append(f'App Store listing: no "ios" block in {source}, nothing to send')
            if android:
                if 'android' in listing:
                    from play import Play
                    out += Play(app, locale=args.locale).listing(listing['android'], args.yes)
                else:
                    out.append(f'Google Play listing: no "android" block in {source}, nothing to send')

        elif args.command == 'screenshots':
            from pictures import android_groups, ios_sets
            ios_folder, android_folder = app.screenshots_ios, app.screenshots_android
            if ios and ios_folder is None:
                raise StoreError(f'No screenshots.ios for {app.key} in the config.')
            if android and android_folder is None:
                raise StoreError(f'No screenshots.android for {app.key} in the config.')
            # Everything is read and checked on disk before any store is called.
            sets = ios_sets(ios_folder) if ios else {}
            groups = android_groups(android_folder) if android else {}
            _gate(app, ios, android)
            if ios:
                from asc import AppStore
                out += AppStore(app, locale=args.locale).screenshots(sets, app.shown(ios_folder), args.yes)
            if android:
                from play import Play
                feature, icon = app.play_feature_graphic, app.play_icon
                out += Play(app, locale=args.locale).screenshots(
                    groups, feature if feature and feature.is_file() else None,
                    icon if icon and icon.is_file() else None, args.yes)

        elif args.command == 'assets':
            app.require('ios')
            from asc import AppStore, check_poster, creative_files
            folder = Path(args.source) if args.source else app.creative
            if folder is None:
                raise StoreError(f'No creative folder: set "creative" for {app.key} in the config, '
                                 'or pass --from DIR.')
            files = creative_files(folder)  # checked on disk before any call
            poster = check_poster(args.poster, files)
            out += AppStore(app).assets(files, app.shown(folder), args.yes, poster)
    except StoreError as e:
        print('\n'.join(out + [f'Stopped: {e}']))
        return 1
    print('\n'.join(out))
    return code


if __name__ == '__main__':
    sys.exit(main())
