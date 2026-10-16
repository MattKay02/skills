"""Offline tests for the store scripts: signing, the config and its guards,
the pictures, preflight and doctor, and that nothing reaches a store without
--yes. Every test builds a temporary project with its own .store-release.json,
and keeps any key files in a separate temporary folder outside it.

    python -m unittest store-release/scripts/test_store.py     (from the repo root)
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import urllib.error
import zlib
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature  # noqa: E402

import asc  # noqa: E402
import common  # noqa: E402
import pictures  # noqa: E402
import play  # noqa: E402
import preflight  # noqa: E402
import store  # noqa: E402
from common import StoreError, es256_jwt, rs256_jwt  # noqa: E402


def _unb64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + '=' * (-len(part) % 4))


def _png(path: Path, width: int, height: int, colour: int = 2, trns: bool = False) -> None:
    """Enough of a PNG for the checks: its header, a tRNS chunk if asked, and
    an empty image."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'
                     + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, colour, 0, 0, 0))
                     + (chunk(b'tRNS', b'\x00\x00\x00\x00\x00\x00') if trns else b'')
                     + chunk(b'IDAT', zlib.compress(b'')) + chunk(b'IEND', b''))


def _jpeg(path: Path, width: int, height: int) -> None:
    """A JPEG's start, an APP0 segment, and a baseline frame header."""
    path.parent.mkdir(parents=True, exist_ok=True)
    app0 = b'\xff\xe0' + struct.pack('>H', 16) + b'JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
    sof = b'\xff\xc0' + struct.pack('>HBHHB', 17, 8, height, width, 3) + b'\x01\x11\x00\x02\x11\x01\x03\x11\x01'
    path.write_bytes(b'\xff\xd8' + app0 + sof + b'\xff\xd9')


APPS = {
    'myapp': {
        'name': 'My App',
        'ios': {'bundle_id': 'com.example.myapp'},
        'android': {'package': 'com.example.myapp'},
        'listing': 'store/listing.json',
        'screenshots': {'ios': 'store/shots/ios', 'android': 'store/shots/android'},
        'play_feature_graphic': 'store/feature.png',
        'play_icon': 'store/icon.png',
        'creative': 'store/creative',
    },
    'iosonly': {'ios': {'bundle_id': 'com.example.iosonly'}},
    'droidonly': {'android': {'package': 'com.example.droidonly'}},
}


class Project:
    """A temporary project with a .store-release.json, and a separate
    temporary folder for key files, outside the project."""

    def __init__(self, test: unittest.TestCase, apps: dict | None = None, keys: dict | None = None,
                 no_keys: bool = False):
        project = tempfile.TemporaryDirectory()
        outside = tempfile.TemporaryDirectory()
        test.addCleanup(project.cleanup)
        test.addCleanup(outside.cleanup)
        self.root = Path(project.name).resolve() / 'project'
        self.root.mkdir()
        self.keys = Path(outside.name).resolve()
        self.config = self.root / '.store-release.json'
        if keys is None:
            keys = {'app_store_connect': str(self.keys / 'asc.json'),
                    'google_play': str(self.keys / 'play.json')}
        body = {'apps': apps or APPS}
        if not no_keys:
            body['keys'] = keys
        self.config.write_text(json.dumps(body, indent=2), encoding='utf-8')

    def path(self, relative: str) -> Path:
        return self.root / relative


def run(project: Project, *argv: str) -> tuple[int, str]:
    with contextlib.redirect_stdout(io.StringIO()) as printed, \
            contextlib.redirect_stderr(io.StringIO()):
        code = store.main([*argv, '--config', str(project.config)])
    return code, printed.getvalue()


class StoreTest(unittest.TestCase):
    def setUp(self):
        # A config named in the environment would win over the test's own.
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(common.CONFIG_ENV, None)
        self.project = Project(self)


class Signing(unittest.TestCase):
    def test_es256_is_what_apple_verifies(self):
        key = ec.generate_private_key(ec.SECP256R1())
        token = es256_jwt({'alg': 'ES256', 'kid': 'K'}, {'iss': 'I', 'aud': 'appstoreconnect-v1'}, key)
        head, body, sig = token.split('.')
        raw = _unb64(sig)
        self.assertEqual(len(raw), 64)  # r and s, not DER
        der = encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big'))
        key.public_key().verify(der, f'{head}.{body}'.encode(), ec.ECDSA(hashes.SHA256()))
        self.assertEqual(json.loads(_unb64(body))['aud'], 'appstoreconnect-v1')

    def test_rs256_is_what_google_verifies(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = rs256_jwt({'iss': 'a@b'}, key)
        head, body, sig = token.split('.')
        key.public_key().verify(_unb64(sig), f'{head}.{body}'.encode(), padding.PKCS1v15(), hashes.SHA256())
        self.assertEqual(json.loads(_unb64(head))['alg'], 'RS256')


class OnlyTheConfiguredApps(StoreTest):
    def test_another_app_is_refused_before_anything_is_called(self):
        with mock.patch.object(asc, '_token') as token, mock.patch.object(play, '_token') as play_token, \
                mock.patch.object(asc, 'call') as apple, mock.patch.object(play, 'call') as google:
            code, printed = run(self.project, 'status', 'otherapp')
        self.assertEqual(code, 1)
        self.assertIn('Stopped: No app "otherapp"', printed)
        self.assertIn('droidonly, iosonly, myapp', printed)
        token.assert_not_called()
        play_token.assert_not_called()
        apple.assert_not_called()
        google.assert_not_called()

    def test_a_store_the_app_is_not_on_is_refused(self):
        with mock.patch.object(play, '_token') as token, mock.patch.object(play, 'call') as google:
            code, printed = run(self.project, 'status', 'iosonly', '--android')
        self.assertEqual(code, 1)
        self.assertIn('iosonly has no "android" block', printed)
        token.assert_not_called()
        google.assert_not_called()

    def test_without_a_flag_only_the_apps_own_store_is_asked(self):
        fake = FakeStore({('POST', '/edits'): {'id': 'E1'}, ('GET', '/tracks'): {'tracks': []}})
        with mock.patch.object(asc, '_token') as apple_token, \
                mock.patch.object(play, '_token', return_value='t'), mock.patch.object(play, 'call', fake):
            code, printed = run(self.project, 'status', 'droidonly')
        self.assertEqual(code, 0, printed)
        apple_token.assert_not_called()
        self.assertIn('Google Play: droidonly (com.example.droidonly)', printed)


class ConfigDiscovery(StoreTest):
    def chdir(self, folder: Path) -> None:
        before = os.getcwd()
        os.chdir(folder)
        self.addCleanup(os.chdir, before)  # runs before the folder is removed

    def elsewhere(self) -> Path:
        """A folder with no config in it or above it."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return Path(folder.name)

    def test_found_by_walking_up_from_the_current_folder(self):
        deep = self.project.root / 'apps' / 'mobile'
        deep.mkdir(parents=True)
        self.chdir(deep)
        self.assertEqual(common.find_config(), self.project.config)
        # And end to end, with no --config: pictures needs no key and no network.
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            code = store.main(['pictures', 'iosonly'])
        self.assertEqual(code, 0, printed.getvalue())
        self.assertIn('pictures: iosonly (iosonly)', printed.getvalue())

    def test_config_flag_wins(self):
        self.chdir(self.elsewhere())
        os.environ[common.CONFIG_ENV] = str(self.elsewhere() / 'nothing.json')
        self.assertEqual(common.find_config(str(self.project.config)), self.project.config.resolve())

    def test_environment_variable(self):
        self.chdir(self.elsewhere())
        os.environ[common.CONFIG_ENV] = str(self.project.config)
        self.assertEqual(common.find_config(), self.project.config.resolve())

    def test_none_found_says_what_to_create(self):
        self.chdir(self.elsewhere())
        with self.assertRaises(StoreError) as caught:
            common.find_config()
        self.assertIn('example.store-release.json', str(caught.exception))
        self.assertIn('--config', str(caught.exception))

    def test_a_misspelt_field_is_refused(self):
        apps = {'myapp': {'ios': {'bundle_id': 'com.example.myapp'}, 'play_feature_graphics': 'x.png'}}
        project = Project(self, apps=apps)
        code, printed = run(project, 'pictures', 'myapp')
        self.assertEqual(code, 1)
        self.assertIn('play_feature_graphics, which this does not take', printed)


class KeysOutsideTheRepository(StoreTest):
    def test_a_key_inside_the_config_folder_is_refused(self):
        # A relative key path starts at the config's folder, so it is inside.
        project = Project(self, keys={'app_store_connect': 'secrets/asc.json'})
        (project.root / 'secrets').mkdir()
        (project.root / 'secrets' / 'asc.json').write_text('{}', encoding='utf-8')
        with mock.patch.object(asc, 'call') as apple:
            code, printed = run(project, 'status', 'myapp', '--ios')
        self.assertEqual(code, 1)
        self.assertIn("is inside the config's folder", printed)
        apple.assert_not_called()

    def test_a_key_inside_the_git_work_tree_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder).resolve()
            (repo / '.git').mkdir()
            (repo / 'app').mkdir()
            (repo / 'secrets').mkdir()
            key = repo / 'secrets' / 'asc.json'
            key.write_text('{}', encoding='utf-8')
            config = repo / 'app' / '.store-release.json'
            config.write_text(json.dumps({'keys': {'app_store_connect': str(key)}, 'apps': APPS}),
                              encoding='utf-8')
            with mock.patch.object(asc, 'call') as apple, \
                    contextlib.redirect_stdout(io.StringIO()) as printed:
                code = store.main(['status', 'myapp', '--ios', '--config', str(config)])
        self.assertEqual(code, 1)
        self.assertIn('inside the git work tree holding the config', printed.getvalue())
        apple.assert_not_called()

    def test_no_keys_says_what_to_create(self):
        project = Project(self, no_keys=True)
        code, printed = run(project, 'status', 'myapp', '--ios')
        self.assertEqual(code, 1)
        self.assertIn('has no "keys"', printed)
        self.assertIn('references/connect.md', printed)


class FakeStore:
    """Answers by URL, and remembers what was sent."""

    def __init__(self, answers):
        self.answers = answers
        self.sent: list[tuple[str, str]] = []
        self.bodies: list[tuple[str, str, dict | None]] = []

    def __call__(self, method, url, **kwargs):
        self.sent.append((method, url))
        self.bodies.append((method, url, kwargs.get('body')))
        for (m, fragment), answer in self.answers.items():
            if m == method and fragment in url:
                if isinstance(answer, Exception):
                    raise answer
                return answer.resolve() if hasattr(answer, 'resolve') else answer
        return None

    def writes(self):
        return [(m, u) for m, u in self.sent if m not in ('GET',)]


APPLE = {
    ('GET', '/v1/apps?'): {'data': [{'id': 'A1', 'attributes': {'primaryLocale': 'en-GB',
                                                                 'bundleId': 'com.example.myapp'}}]},
    ('GET', '/v1/builds?'): {
        'data': [{'id': 'B52', 'attributes': {'version': '52', 'processingState': 'VALID'},
                  'relationships': {'preReleaseVersion': {'data': {'id': 'P1'}}}}],
        'included': [{'id': 'P1', 'type': 'preReleaseVersions', 'attributes': {'version': '2.0.0'}}],
    },
    ('GET', '/appStoreVersions?'): {'data': []},
    ('POST', '/v1/appStoreVersions'): {'data': {'id': 'V1'}},
    ('POST', '/v1/reviewSubmissions'): {'data': {'id': 'R1'}},
    # Ahead of the general answer below, which a test swaps for a draft.
    ('GET', 'UNRESOLVED_ISSUES'): {'data': []},
    ('GET', '/v1/reviewSubmissions?'): {'data': []},
    ('GET', '/appStoreVersionLocalizations'): {
        'data': [{'id': 'L1', 'attributes': {'locale': 'en-GB'}}]},
}


class AppleSubmit(StoreTest):
    def run_submit(self, *flags, answers=None):
        fake = FakeStore(answers or APPLE)
        with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', fake):
            code, printed = run(self.project, 'submit', 'myapp', '--ios', '--build', '52', *flags)
        return code, fake, printed

    def test_without_yes_it_only_plans(self):
        code, fake, printed = self.run_submit()
        self.assertEqual(code, 0)
        self.assertEqual(fake.writes(), [])
        self.assertIn('release automatically on approval', printed)
        self.assertIn('(plan only: run again with --yes to do it)', printed)

    def test_with_yes_it_releases_itself_on_approval(self):
        code, fake, _ = self.run_submit('--yes')
        self.assertEqual(code, 0)
        posts = [u for m, u in fake.sent if m == 'POST']
        self.assertTrue(any(u.endswith('/v1/appStoreVersions') for u in posts))
        self.assertTrue(any(u.endswith('/v1/reviewSubmissionItems') for u in posts))
        self.assertTrue(any(m == 'PATCH' and u.endswith('/v1/reviewSubmissions/R1') for m, u in fake.sent))

    def with_draft(self, items):
        answers = dict(APPLE)
        answers[('GET', '/v1/reviewSubmissions?')] = {'data': [{'id': 'D1'}]}
        answers[('GET', '/reviewSubmissions/D1/items')] = {'data': items}
        return answers

    def test_a_draft_started_in_app_store_connect_is_the_one_submitted(self):
        code, fake, printed = self.run_submit(answers=self.with_draft([]))
        self.assertIn('in the draft submission started in App Store Connect', printed)
        code, fake, _ = self.run_submit('--yes', answers=self.with_draft([]))
        self.assertEqual(code, 0)
        self.assertFalse(any(m == 'POST' and u.endswith('/v1/reviewSubmissions') for m, u in fake.sent))
        self.assertTrue(any(m == 'POST' and u.endswith('/v1/reviewSubmissionItems') for m, u in fake.sent))
        self.assertTrue(any(m == 'PATCH' and u.endswith('/v1/reviewSubmissions/D1') for m, u in fake.sent))

    def test_a_version_already_in_the_draft_is_not_added_twice(self):
        already = [{'id': 'I1', 'relationships': {
            'appStoreVersion': {'data': {'type': 'appStoreVersions', 'id': 'V1'}}}}]
        code, fake, _ = self.run_submit('--yes', answers=self.with_draft(already))
        self.assertEqual(code, 0)
        self.assertFalse(any(u.endswith('/v1/reviewSubmissionItems') for _, u in fake.sent))
        self.assertTrue(any(m == 'PATCH' and u.endswith('/v1/reviewSubmissions/D1') for m, u in fake.sent))

    def test_whats_new_on_a_first_version_is_refused_before_anything_is_written(self):
        notes = self.project.path('whats-new.txt')
        notes.write_text('Faster.', encoding='utf-8')
        code, fake, printed = self.run_submit('--notes', str(notes), '--yes')
        self.assertEqual(code, 1)
        self.assertEqual(fake.writes(), [])
        self.assertIn("has never had a version out, so this one has no What's New", printed)
        # Once a version has been out, the next one takes What's New.
        answers = with_open_version('1.9.9', 'READY_FOR_DISTRIBUTION')
        code, fake, printed = self.run_submit('--notes', str(notes), answers=answers)
        self.assertEqual(code, 0, printed)
        self.assertIn("What's New (en-GB): set", printed)

    def test_a_submission_with_unresolved_issues_is_resubmitted_in_the_console(self):
        # After a rejection a second submission would be refused, and
        # cancelling the first drops its subscriptions back to the version page.
        answers = dict(APPLE)
        answers[('GET', 'UNRESOLVED_ISSUES')] = {'data': [{'id': 'U1'}]}
        code, fake, printed = self.run_submit('--yes', answers=answers)
        self.assertEqual(code, 1)
        self.assertEqual(fake.writes(), [])
        self.assertIn('U1 has unresolved issues', printed)
        self.assertIn('Resubmit', printed)


def with_open_version(number: str, state: str, release: str = 'AFTER_APPROVAL') -> dict:
    """APPLE, with no version under the build's number and one open under
    another. The versionString lookup is listed first so it answers before
    the general one."""
    answers = {('GET', 'versionString'): {'data': []}, **APPLE}
    answers[('GET', '/appStoreVersions?')] = {'data': [
        {'id': 'V0', 'attributes': {'versionString': number, 'appVersionState': state,
                                    'releaseType': release}}]}
    return answers


class ApplePrepare(StoreTest):
    def run_prepare(self, *flags, answers=None):
        fake = FakeStore(answers or APPLE)
        with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', fake):
            code, printed = run(self.project, 'prepare', 'myapp', '--build', '52', *flags)
        return code, fake, printed

    def test_without_yes_it_only_plans(self):
        code, fake, printed = self.run_prepare()
        self.assertEqual(code, 0)
        self.assertEqual(fake.writes(), [])
        self.assertIn('create version 2.0.0', printed)

    def test_with_yes_the_version_is_opened_and_not_sent_for_review(self):
        code, fake, _ = self.run_prepare('--yes')
        self.assertEqual(code, 0)
        writes = fake.writes()
        self.assertIn(('POST', 'https://api.appstoreconnect.apple.com/v1/appStoreVersions'), writes)
        self.assertTrue(any(u.endswith('/v1/appStoreVersions/V1/relationships/build') for _, u in writes))
        self.assertFalse(any('reviewSubmission' in u for _, u in writes))

    def test_a_rejected_version_takes_the_new_number(self):
        # Apple keeps one version open, so a rejected 1.9.9 goes back as 2.0.0.
        answers = with_open_version('1.9.9', 'REJECTED')
        code, fake, printed = self.run_prepare(answers=answers)
        self.assertEqual(code, 0)
        self.assertEqual(fake.writes(), [])
        self.assertIn('rename version 1.9.9 to 2.0.0', printed)

        code, fake, _ = self.run_prepare('--yes', answers=answers)
        self.assertEqual(code, 0)
        self.assertNotIn(('POST', 'https://api.appstoreconnect.apple.com/v1/appStoreVersions'),
                         fake.writes())
        renames = [b for m, u, b in fake.bodies
                   if m == 'PATCH' and u.endswith('/v1/appStoreVersions/V0')]
        # Renamed; its release type, already AFTER_APPROVAL, is left alone.
        self.assertEqual(renames[0]['data']['attributes'], {'versionString': '2.0.0'})
        self.assertTrue(any(u.endswith('/v1/appStoreVersions/V0/relationships/build')
                            for _, u in fake.writes()))

    def test_a_version_on_its_way_is_not_renamed(self):
        # Waiting for review is not open for changes: a new version is asked
        # for, and Apple's refusal says why.
        code, fake, printed = self.run_prepare(
            answers=with_open_version('1.9.9', 'WAITING_FOR_REVIEW'))
        self.assertEqual(code, 0)
        self.assertIn('create version 2.0.0', printed)


class AppleListing(StoreTest):
    """The listing goes on the app information being prepared, never the live one."""

    def run_listing(self, fields):
        sent = []
        fake = FakeStore({
            ('GET', '/v1/apps?'): {'data': [{'id': 'A1', 'attributes': {'primaryLocale': 'en-GB', 'bundleId': 'com.example.myapp'}}]},
            ('GET', '/appStoreVersions?'): {'data': [
                {'id': 'V2', 'attributes': {'versionString': '2.0.0', 'appVersionState': 'PREPARE_FOR_SUBMISSION'}},
                {'id': 'V1', 'attributes': {'versionString': '1.4.0', 'appVersionState': 'READY_FOR_DISTRIBUTION'}},
            ]},
            ('GET', '/appStoreVersionLocalizations'): {
                'data': [{'id': 'L2', 'attributes': {'locale': 'en-GB'}}]},
            ('GET', '/v1/apps/A1/appInfos'): {'data': [
                {'id': 'LIVE', 'attributes': {'state': 'READY_FOR_DISTRIBUTION'}},
                {'id': 'NEXT', 'attributes': {'state': 'PREPARE_FOR_SUBMISSION'}},
            ]},
            ('GET', '/appInfos/NEXT/appInfoLocalizations'): {
                'data': [{'id': 'IL2', 'attributes': {'locale': 'en-GB'}}]},
            ('GET', '/appStoreVersions/V2?'): {'data': {'id': 'V2', 'relationships': {
                'appStoreReviewDetail': {'data': None}}}},
        })

        def recording(method, url, **kwargs):
            if method != 'GET':
                sent.append((method, url.split('/v1/')[-1], kwargs.get('body')))
            return fake(method, url, **kwargs)

        source = self.project.path('listing-test.json')
        source.write_text(json.dumps({'ios': fields}), encoding='utf-8')
        with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', recording):
            code, _ = run(self.project, 'listing', 'myapp', '--ios', '--from', str(source), '--yes')
        return code, sent

    def test_the_name_goes_on_the_information_being_prepared(self):
        code, sent = self.run_listing({'name': 'My App'})
        self.assertEqual(code, 0)
        self.assertEqual(sent, [('PATCH', 'appInfoLocalizations/IL2', {
            'data': {'type': 'appInfoLocalizations', 'id': 'IL2',
                     'attributes': {'name': 'My App'}}})])

    def test_review_notes_and_copyright_go_on_the_version(self):
        code, sent = self.run_listing({'reviewNotes': 'Sign in with the demo account.',
                                       'copyright': '2026 Example Ltd'})
        self.assertEqual(code, 0)
        self.assertIn(('PATCH', 'appStoreVersions/V2', {
            'data': {'type': 'appStoreVersions', 'id': 'V2',
                     'attributes': {'copyright': '2026 Example Ltd'}}}), sent)
        posted = [body for method, path, body in sent if path == 'appStoreReviewDetails']
        self.assertEqual(posted[0]['data']['attributes'], {'notes': 'Sign in with the demo account.'})
        self.assertEqual(posted[0]['data']['relationships']['appStoreVersion']['data']['id'], 'V2')


class AppleReleaseType(StoreTest):
    def run_it(self, *flags):
        sent = []
        fake = FakeStore({
            ('GET', '/v1/apps?'): {'data': [{'id': 'A1', 'attributes': {'primaryLocale': 'en-GB', 'bundleId': 'com.example.myapp'}}]},
            ('GET', '/appStoreVersions?'): {'data': [
                {'id': 'V9', 'attributes': {'versionString': '1.0.0', 'appVersionState': 'WAITING_FOR_REVIEW',
                                            'releaseType': 'MANUAL'}},
            ]},
        })

        def recording(method, url, **kwargs):
            if method == 'PATCH':
                sent.append((url, kwargs['body']))
            return fake(method, url, **kwargs)

        with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', recording):
            code, printed = run(self.project, 'release-type', 'myapp', '--automatic', *flags)
        return code, sent, printed

    def test_without_yes_it_only_plans(self):
        code, sent, printed = self.run_it()
        self.assertEqual(code, 0)
        self.assertEqual(sent, [])
        self.assertIn('MANUAL -> AFTER_APPROVAL', printed)

    def test_with_yes_the_version_in_review_releases_itself(self):
        code, sent, _ = self.run_it('--yes')
        self.assertEqual(code, 0)
        url, body = sent[0]
        self.assertTrue(url.endswith('/v1/appStoreVersions/V9'))
        self.assertEqual(body['data']['attributes'], {'releaseType': 'AFTER_APPROVAL'})


def play_fake():
    return FakeStore({
        ('POST', '/edits'): {'id': 'E1'},
        ('GET', '/tracks'): {'tracks': [
            {'track': 'internal', 'releases': [
                {'name': '2.0.0 (1)', 'versionCodes': ['1'], 'status': 'completed'},
                {'name': '2.0.0 (3)', 'versionCodes': ['3'], 'status': 'completed'},
            ]},
        ]},
        ('GET', '/details'): {'defaultLanguage': 'en-GB'},
    })


class PlaySubmit(StoreTest):
    def run_submit(self, *flags, project=None):
        fake = play_fake()
        with mock.patch.object(play, '_token', return_value='t'), mock.patch.object(play, 'call', fake):
            code, printed = run(project or self.project, 'submit', 'myapp', '--android', *flags)
        return code, fake, printed

    def test_without_yes_it_only_plans_and_closes_the_edit(self):
        code, fake, printed = self.run_submit()
        self.assertEqual(code, 0)
        self.assertFalse(any(m == 'PUT' or u.endswith(':commit') for m, u in fake.sent))
        self.assertTrue(any(m == 'DELETE' for m, _ in fake.sent))  # the edit, discarded
        self.assertIn('2.0.0 (3)', printed)  # the newest internal build

    def test_with_yes_it_goes_to_everybody(self):
        code, fake, _ = self.run_submit('--yes')
        self.assertEqual(code, 0)
        put = [b for m, u, b in fake.bodies if m == 'PUT']
        release = put[0]['releases'][0]
        self.assertEqual(put[0]['track'], 'production')
        self.assertEqual(release['status'], 'completed')
        self.assertNotIn('userFraction', release)
        self.assertEqual(release['versionCodes'], ['3'])
        self.assertTrue(any(u.endswith(':commit') for _, u in fake.sent))

    def test_draft_until_published_sends_a_draft(self):
        apps = json.loads(json.dumps(APPS))
        apps['myapp']['android']['draft_until_published'] = True
        code, fake, printed = self.run_submit('--yes', project=Project(self, apps=apps))
        self.assertEqual(code, 0, printed)
        put = [b for m, u, b in fake.bodies if m == 'PUT']
        self.assertEqual(put[0]['releases'][0]['status'], 'draft')
        self.assertIn('Start rollout', printed)

    def test_release_notes_from_the_config_go_with_it(self):
        apps = json.loads(json.dumps(APPS))
        apps['myapp']['release_notes'] = 'store/notes.txt'
        project = Project(self, apps=apps)
        project.path('store').mkdir()
        project.path('store/notes.txt').write_text('<en-GB>\nFaster.\n</en-GB>\n<de-DE>\nSchneller.\n</de-DE>\n',
                                                   encoding='utf-8')
        code, fake, printed = self.run_submit('--yes', project=project)
        self.assertEqual(code, 0, printed)
        put = [b for m, u, b in fake.bodies if m == 'PUT']
        self.assertEqual(put[0]['releases'][0]['releaseNotes'],
                         [{'language': 'en-GB', 'text': 'Faster.'}, {'language': 'de-DE', 'text': 'Schneller.'}])

    def test_notes_over_500_characters_are_refused_before_anything_is_called(self):
        notes = self.project.path('long.txt')
        notes.write_text('x' * 501, encoding='utf-8')
        with mock.patch.object(play, '_token') as token, mock.patch.object(play, 'call') as google:
            code, printed = run(self.project, 'submit', 'myapp', '--android', '--notes', str(notes))
        self.assertEqual(code, 1)
        self.assertIn('500 characters at most', printed)
        token.assert_not_called()
        google.assert_not_called()


class Links(StoreTest):
    """The public pages: Apple's by the app's id and what is on sale, Play's
    by whether the page itself answers."""

    def test_each_store_says_whether_its_page_is_live(self):
        apple = FakeStore({
            ('GET', '/v1/apps?'): {'data': [{'id': '1234567890', 'attributes': {'primaryLocale': 'en-GB', 'bundleId': 'com.example.myapp'}}]},
            ('GET', '/appStoreVersions?'): {'data': [
                {'id': 'V2', 'attributes': {'versionString': '2.0.0', 'appVersionState': 'WAITING_FOR_REVIEW'}},
                {'id': 'V1', 'attributes': {'versionString': '1.4.0', 'appVersionState': 'READY_FOR_DISTRIBUTION'}},
            ]},
        })

        def play_page(method, url, **kwargs):
            raise play.StoreError(f'GET {url} refused (404): Not Found')

        with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', apple), \
                mock.patch.object(play, '_token', return_value='t'), mock.patch.object(play, 'call', play_page):
            code, printed = run(self.project, 'links', 'myapp')
        self.assertEqual(code, 0)
        self.assertIn('https://apps.apple.com/app/id1234567890 (on sale: 1.4.0)', printed)
        self.assertIn('https://play.google.com/store/apps/details?id=com.example.myapp (not live yet)', printed)


class PlayHeldForReview(StoreTest):
    """Play refuses to send some edits for review from the API; they are then
    committed unsent, as its message asks, and the output says where to send them."""

    def test_the_release_waits_in_publishing_overview(self):
        fake = play_fake()

        def refusing(method, url, **kwargs):
            if url.endswith(':commit'):
                fake.sent.append((method, url))
                raise play.StoreError(
                    'POST https://androidpublisher.googleapis.com/... refused (400): Changes cannot '
                    'be sent for review automatically. Please set the query parameter '
                    'changesNotSentForReview to true.')
            return fake(method, url, **kwargs)

        with mock.patch.object(play, '_token', return_value='t'), mock.patch.object(play, 'call', refusing):
            code, printed = run(self.project, 'submit', 'myapp', '--android', '--yes')
        self.assertEqual(code, 0)
        self.assertTrue(any(u.endswith(':commit?changesNotSentForReview=true') for _, u in fake.sent))
        self.assertFalse(any(m == 'DELETE' for m, _ in fake.sent))  # committed, not thrown away
        self.assertIn('Publishing overview', printed)


class PlayPictures(StoreTest):
    def test_the_icon_goes_up_with_the_screenshots(self):
        fake = FakeStore({
            ('POST', '/edits'): {'id': 'E1'},
            ('GET', '/details'): {'defaultLanguage': 'en-GB'},
        })
        _png(self.project.path('store/shots/android/1-log.png'), 1080, 1920)
        _png(self.project.path('store/shots/android/2-plan.png'), 1080, 1920)
        _png(self.project.path('store/icon.png'), 512, 512, colour=6)  # Play's icon may carry alpha
        with mock.patch.object(play, '_token', return_value='t'), mock.patch.object(play, 'call', fake):
            code, printed = run(self.project, 'screenshots', 'myapp', '--android', '--yes')
        self.assertEqual(code, 0, printed)
        self.assertIn('the icon', printed)
        posted = [u for m, u in fake.sent if m == 'POST']
        self.assertTrue(any('/listings/en-GB/icon?' in u for u in posted))
        self.assertFalse(any('/featureGraphic?' in u for u in posted))
        self.assertEqual(sum(1 for u in posted if '/phoneScreenshots?' in u), 2)

    def test_tablet_folders_go_up_as_their_own_kind(self):
        fake = FakeStore({('POST', '/edits'): {'id': 'E1'}, ('GET', '/details'): {'defaultLanguage': 'en-GB'}})
        _png(self.project.path('store/shots/android/1.png'), 1080, 1920)
        _png(self.project.path('store/shots/android/2.png'), 1080, 1920)
        _png(self.project.path('store/shots/android/tenInch/1.png'), 1600, 2560)
        with mock.patch.object(play, '_token', return_value='t'), mock.patch.object(play, 'call', fake):
            code, printed = run(self.project, 'screenshots', 'myapp', '--android')
        self.assertEqual(code, 0, printed)
        self.assertIn('2 phone screenshots, 1 10-inch tablet screenshots', printed)
        self.assertFalse(any(m == 'POST' and 'uploadType' in u for m, u in fake.sent))

    def test_an_alpha_screenshot_stops_the_upload_before_anything_is_called(self):
        _png(self.project.path('store/shots/android/1.png'), 1080, 1920, colour=6)
        _png(self.project.path('store/shots/android/2.png'), 1080, 1920)
        with mock.patch.object(play, '_token') as token, mock.patch.object(play, 'call') as google:
            code, printed = run(self.project, 'screenshots', 'myapp', '--android', '--yes')
        self.assertEqual(code, 1)
        self.assertIn('Google Play refuses alpha', printed)
        token.assert_not_called()
        google.assert_not_called()


def apple_shots(existing: dict[str, int] | None = None, locales=('en-GB',)) -> dict:
    """An open version whose localizations hold [existing] {display type:
    count} screenshot sets, and answers for an upload."""
    existing = existing or {}
    sets = [{'id': f'S-{d}', 'attributes': {'screenshotDisplayType': d}} for d in existing]
    answers = {
        ('GET', '/v1/apps?'): {'data': [{'id': 'A1', 'attributes': {'primaryLocale': 'en-GB',
                                                                     'bundleId': 'com.example.myapp'}}]},
        ('GET', '/appStoreVersions?'): {'data': [
            {'id': 'V2', 'attributes': {'versionString': '2.0.0', 'appVersionState': 'PREPARE_FOR_SUBMISSION'}}]},
    }
    for d, n in existing.items():
        answers[('GET', f'/appScreenshotSets/S-{d}/appScreenshots')] = {'data': [
            {'id': f'{d}-{i}', 'attributes': {}} for i in range(n)]}
    answers.update({
        ('GET', '/appScreenshotSets'): {'data': sets},
        ('GET', '/appStoreVersionLocalizations'): {'data': [
            {'id': f'L-{locale}', 'attributes': {'locale': locale}} for locale in locales]},
        ('POST', '/v1/appScreenshotSets'): {'data': {'id': 'S9'}},
        ('POST', '/v1/appScreenshots'): {'data': {'id': 'SH1', 'attributes': {'uploadOperations': [
            {'method': 'PUT', 'url': 'https://upload.example/SH1', 'offset': 0, 'length': 10,
             'requestHeaders': []}]}}},
    })
    return answers


class AppleScreenshots(StoreTest):
    def test_display_types_come_from_folders_and_pixel_sizes(self):
        _png(self.project.path('store/shots/ios/01-home.png'), 1290, 2796)
        _png(self.project.path('store/shots/ios/02-plan.png'), 2796, 1290)  # landscape
        _png(self.project.path('store/shots/ios/APP_IPAD_PRO_3GEN_129/01-home.png'), 2064, 2752)
        _png(self.project.path('store/shots/ios/APP_IPHONE_55/01-home.png'), 1242, 2208)
        sets = pictures.ios_sets(self.project.path('store/shots/ios'))
        self.assertEqual({k: [p.name for p in v] for k, v in sets.items()}, {
            'APP_IPHONE_67': ['01-home.png', '02-plan.png'],
            'APP_IPHONE_55': ['01-home.png'],
            'APP_IPAD_PRO_3GEN_129': ['01-home.png'],
        })
        self.assertEqual(pictures.infer_display_type(1320, 2868), 'APP_IPHONE_67')
        self.assertEqual(pictures.infer_display_type(1284, 2778), 'APP_IPHONE_65')
        self.assertEqual(pictures.infer_display_type(2048, 2732), 'APP_IPAD_PRO_3GEN_129')

    def test_an_unknown_size_is_refused_with_the_sizes_apple_takes(self):
        _png(self.project.path('store/shots/ios/1.png'), 1000, 1000)
        with self.assertRaises(StoreError) as caught:
            pictures.ios_sets(self.project.path('store/shots/ios'))
        self.assertIn('1.png is 1000x1000, which is no App Store screenshot size', str(caught.exception))
        self.assertIn('1290x2796', str(caught.exception))
        self.assertIn('2064x2752', str(caught.exception))

    def test_an_unknown_folder_name_is_refused(self):
        _png(self.project.path('store/shots/ios/iphone/1.png'), 1290, 2796)
        with self.assertRaises(StoreError) as caught:
            pictures.ios_sets(self.project.path('store/shots/ios'))
        self.assertIn('iphone/ is not a display type', str(caught.exception))

    def test_the_plan_names_each_display_type_and_sends_nothing(self):
        _png(self.project.path('store/shots/ios/1.png'), 1290, 2796)
        _png(self.project.path('store/shots/ios/APP_IPAD_PRO_3GEN_129/1.png'), 2064, 2752)
        fake = FakeStore(apple_shots(existing={'APP_IPHONE_67': 6, 'APP_IPHONE_55': 3}))
        with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', fake):
            code, printed = run(self.project, 'screenshots', 'myapp', '--ios')
        self.assertEqual(code, 0, printed)
        self.assertIn('APP_IPHONE_67: replace: delete the 6 there now, upload 1: 1.png', printed)
        self.assertIn('APP_IPAD_PRO_3GEN_129: none there now, upload 1: 1.png', printed)
        self.assertIn('left as they are: APP_IPHONE_55', printed)
        self.assertIn('(plan only: run again with --yes to do it)', printed)
        self.assertEqual(fake.writes(), [])

    def test_with_yes_each_set_is_made_for_its_display_type(self):
        _png(self.project.path('store/shots/ios/APP_IPAD_PRO_3GEN_129/1.png'), 2064, 2752)
        fake = FakeStore(apple_shots())
        with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', fake):
            code, printed = run(self.project, 'screenshots', 'myapp', '--ios', '--yes')
        self.assertEqual(code, 0, printed)
        made = [b for m, u, b in fake.bodies if m == 'POST' and u.endswith('/v1/appScreenshotSets')]
        self.assertEqual(made[0]['data']['attributes'], {'screenshotDisplayType': 'APP_IPAD_PRO_3GEN_129'})
        self.assertTrue(any(m == 'PUT' and u == 'https://upload.example/SH1' for m, u in fake.sent))


class Pictures(StoreTest):
    def check(self, *flags, code=0):
        got, printed = run(self.project, 'pictures', 'myapp', *flags)
        self.assertEqual(got, code, printed)
        return printed

    def test_alpha_is_found_by_colour_type_and_by_trns(self):
        _png(self.project.path('store/shots/ios/1-rgba.png'), 1290, 2796, colour=6)
        _png(self.project.path('store/shots/ios/2-trns.png'), 1290, 2796, colour=2, trns=True)
        _png(self.project.path('store/shots/ios/3-rgb.png'), 1290, 2796)
        printed = self.check('--ios', code=1)
        self.assertIn('BLOCK  APP_IPHONE_67 1-rgba.png has an alpha channel (RGBA)', printed)
        self.assertIn('BLOCK  APP_IPHONE_67 2-trns.png has a transparent colour (tRNS chunk)', printed)
        self.assertNotIn('3-rgb.png has', printed)
        facts = pictures.read_image(self.project.path('store/shots/ios/3-rgb.png'))
        self.assertFalse(facts.alpha)

    def test_play_counts_sizes_and_the_icon(self):
        _png(self.project.path('store/shots/android/1.png'), 1080, 1920)
        _png(self.project.path('store/feature.png'), 1024, 501)
        _png(self.project.path('store/icon.png'), 512, 512, colour=6)
        printed = self.check('--android', code=1)
        self.assertIn('BLOCK  Google Play phoneScreenshots: 1 in', printed)
        self.assertIn('featureGraphic feature.png is 1024x501: Play takes exactly 1024x500', printed)
        self.assertIn('OK     Google Play icon: icon.png, 512x512 PNG RGBA', printed)

    def test_names_that_sort_out_of_order_are_flagged(self):
        for name in ('1-a.png', '2-b.png', '10-c.png'):
            _png(self.project.path(f'store/shots/ios/{name}'), 1290, 2796)
        printed = self.check('--ios')
        self.assertIn('WARN   App Store APP_IPHONE_67: uploads go in file name order, which is '
                      '1-a.png, 10-c.png, 2-b.png', printed)

    def test_jpeg_sizes_are_read(self):
        _jpeg(self.project.path('store/shots/ios/1.jpg'), 1320, 2868)
        facts = pictures.read_image(self.project.path('store/shots/ios/1.jpg'))
        self.assertEqual((facts.format, facts.width, facts.height, facts.alpha), ('JPEG', 1320, 2868, False))
        printed = self.check('--ios')
        self.assertIn('APP_IPHONE_67 (iPhone 6.9-inch and 6.7-inch, by pixel size): 1 screenshot', printed)

    def test_the_last_line_asks_for_a_look_at_every_picture(self):
        _png(self.project.path('store/shots/ios/1.png'), 1290, 2796)
        printed = self.check('--ios')
        self.assertIn('MANUAL This cannot read the text in a picture', printed)
        self.assertIn('"Free"', printed)
        self.assertIn('% off', printed)


def preflight_apple(state='PREPARE_FOR_SUBMISSION', encryption=False, subscription='APPROVED',
                    released=False):
    versions = [{'id': 'V1', 'attributes': {'versionString': '1.0.1', 'appVersionState': state,
                                            'releaseType': 'AFTER_APPROVAL'}}]
    if released:
        versions.append({'id': 'V0', 'attributes': {'versionString': '1.0.0',
                                                    'appVersionState': 'READY_FOR_DISTRIBUTION'}})
    build = {'version': '31', 'processingState': 'VALID', 'expired': False,
             'usesNonExemptEncryption': encryption, 'uploadedDate': '2026-10-15T10:00:00-07:00'}
    return {
        ('GET', '/v1/apps?'): {'data': [{'id': 'A1', 'attributes': {'primaryLocale': 'en-GB',
                                                                     'bundleId': 'com.example.myapp'}}]},
        ('GET', '/v1/builds?'): {
            'data': [{'id': 'B31', 'attributes': build,
                      'relationships': {'preReleaseVersion': {'data': {'id': 'P1'}}}}],
            'included': [{'id': 'P1', 'type': 'preReleaseVersions', 'attributes': {'version': '1.0.1'}}]},
        ('GET', '/appStoreVersions?'): {'data': versions},
        ('GET', '/v1/appStoreVersions/V1?'): {
            'data': {'id': 'V1', 'attributes': {'copyright': '2026 Example', 'releaseType': 'AFTER_APPROVAL'},
                     'relationships': {
                         'build': {'data': {'type': 'builds', 'id': 'B31'}},
                         'appStoreReviewDetail': {'data': {'type': 'appStoreReviewDetails', 'id': 'R1'}}}},
            'included': [
                {'type': 'builds', 'id': 'B31', 'attributes': build},
                {'type': 'appStoreReviewDetails', 'id': 'R1', 'attributes': {
                    'contactFirstName': 'A', 'contactLastName': 'B', 'contactPhone': '+44 0',
                    'contactEmail': 'a@example.com', 'demoAccountRequired': True,
                    'demoAccountName': 'demo', 'demoAccountPassword': 'not-shown'}}]},
        ('GET', '/appScreenshotSets/S1/appScreenshots'): {'data': [
            {'id': 'X1', 'attributes': {'assetDeliveryState': {'state': 'COMPLETE'}}},
            {'id': 'X2', 'attributes': {'assetDeliveryState': {'state': 'COMPLETE'}}}]},
        ('GET', '/appScreenshotSets'): {'data': [
            {'id': 'S1', 'attributes': {'screenshotDisplayType': 'APP_IPHONE_67'}}]},
        ('GET', '/appStoreVersionLocalizations'): {'data': [{'id': 'L1', 'attributes': {
            'locale': 'en-GB', 'description': 'd', 'keywords': 'k',
            'supportUrl': 'https://example.com/support'}}]},
        ('GET', '/appInfoLocalizations'): {'data': [{'id': 'IL1', 'attributes': {
            'locale': 'en-GB', 'privacyPolicyUrl': 'https://example.com/privacy'}}]},
        ('GET', '/v1/appInfos/I1?'): {'data': {'id': 'I1', 'relationships': {
            'primaryCategory': {'data': {'type': 'appCategories', 'id': 'HEALTH_AND_FITNESS'}}}}},
        ('GET', '/appInfos'): {'data': [{'id': 'I1', 'attributes': {'state': 'PREPARE_FOR_SUBMISSION'}}]},
        ('GET', '/subscriptionGroups/G1/subscriptions'): {'data': [{'id': 'SUB1', 'attributes': {
            'name': 'Premium', 'productId': 'premium.monthly', 'state': subscription}}]},
        ('GET', '/subscriptionGroups'): {'data': [{'id': 'G1'}]},
        ('GET', '/v1/reviewSubmissions?'): {'data': []},
    }


def preflight_play(production=None):
    return {
        ('POST', '/edits'): {'id': 'E1'},
        ('GET', '/details'): {'defaultLanguage': 'en-GB', 'contactEmail': 'a@example.com',
                              'contactWebsite': 'https://example.com'},
        ('GET', '/tracks'): {'tracks': [
            {'track': 'internal', 'releases': [{'name': '1.0.1 (31)', 'versionCodes': ['31'],
                                                'status': 'completed'}]},
            {'track': 'production', 'releases': production if production is not None else [
                {'name': '1.0.1 (31)', 'versionCodes': ['31'], 'status': 'completed'}]},
        ]},
        ('GET', '/listings/en-GB/icon'): {'images': [{'id': '1'}]},
        ('GET', '/listings/en-GB/featureGraphic'): {'images': [{'id': '2'}]},
        ('GET', '/listings/en-GB/phoneScreenshots'): {'images': [{'id': '3'}, {'id': '4'}]},
        ('GET', '/listings/en-GB'): {'title': 'My App', 'shortDescription': 's', 'fullDescription': 'f'},
    }


class Preflight(StoreTest):
    def run_preflight(self, *flags, apple=None, google=None):
        apple = FakeStore(apple or preflight_apple())
        google = FakeStore(google or preflight_play())
        with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', apple), \
                mock.patch.object(play, '_token', return_value='t'), mock.patch.object(play, 'call', google), \
                mock.patch.object(preflight, 'fetch_status', return_value=(200, 'https://example.com')):
            code, printed = run(self.project, 'preflight', 'myapp', *flags)
        self.code = code
        return printed, apple, google

    def test_a_clean_version_reads_every_check_and_writes_nothing(self):
        printed, apple, google = self.run_preflight('--build', '31')
        self.assertEqual(self.code, 0, printed)
        self.assertIn('Summary: 0 BLOCK, 0 UNCHECKED', printed)
        self.assertIn('OK     [export compliance] build 31 (1.0.1) uses no non-exempt encryption', printed)
        self.assertIn('APP_IPHONE_67 (iPhone 6.9-inch and 6.7-inch): 2 screenshots, every one COMPLETE', printed)
        self.assertIn("1.0.1 is the app's first version: What's New is not needed", printed)
        self.assertNotIn('not-shown', printed)  # the demo password is never printed
        self.assertEqual(apple.writes(), [])
        # Play: exactly one edit, opened and discarded, nothing else written.
        self.assertEqual([m for m, u in google.writes()], ['POST', 'DELETE'])

    def test_an_unanswered_encryption_question_blocks(self):
        printed, _, _ = self.run_preflight('--ios', '--build', '31', apple=preflight_apple(encryption=None))
        self.assertEqual(self.code, 1)
        self.assertIn('BLOCK  [export compliance] build 31 (1.0.1) has not answered the export '
                      'compliance question', printed)

    def test_a_subscription_missing_metadata_blocks(self):
        printed, _, _ = self.run_preflight('--ios', apple=preflight_apple(subscription='MISSING_METADATA'))
        self.assertEqual(self.code, 1)
        self.assertIn('BLOCK  [subscriptions] Premium (premium.monthly) is MISSING_METADATA', printed)
        printed, _, _ = self.run_preflight('--ios', apple=preflight_apple(subscription='READY_TO_SUBMIT'))
        self.assertIn('WARN   [subscriptions] Premium (premium.monthly) is READY_TO_SUBMIT: attach it on '
                      'the version page in App Store Connect if this is its first submission', printed)

    def test_the_manual_lines_are_always_there(self):
        printed, _, _ = self.run_preflight()
        for line in ('MANUAL [App Privacy details] App Privacy',
                     'MANUAL [App Review 5.1.1(v)]',
                     'MANUAL [App Review 4 (Design)] nothing asks for a name or email after Sign in',
                     'MANUAL [App Review 2.3.7]',
                     'MANUAL [App Review 3.1.2]',
                     'MANUAL [Play policy] Data safety',
                     "MANUAL [Play policy] the target API level"):
            self.assertIn(line, printed)

    def test_the_manual_lines_survive_a_store_that_cannot_be_read(self):
        def down(method, url, **kwargs):
            raise StoreError(f'{method} {url} refused (500): down')
        with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', down):
            code, printed = run(self.project, 'preflight', 'myapp', '--ios')
        self.assertEqual(code, 1, printed)
        self.assertIn('UNCHECKED [App Store Connect] everything on the App Store: could not read it', printed)
        self.assertIn('MANUAL [App Privacy details]', printed)
        self.assertIn('1 UNCHECKED', printed)

    def test_a_version_waiting_for_review_is_reported_not_failed(self):
        printed, apple, _ = self.run_preflight('--ios', '--build', '31',
                                               apple=preflight_apple(state='WAITING_FOR_REVIEW'))
        self.assertIn('OK     [version] version 1.0.1 is WAITING_FOR_REVIEW: already submitted', printed)
        self.assertEqual(apple.writes(), [])

    def test_an_update_needs_whats_new(self):
        printed, _, _ = self.run_preflight('--ios', apple=preflight_apple(released=True))
        self.assertIn("BLOCK  [App Store Connect] 1.0.1 en-GB: What's New is empty, and 1.0.1 is an update",
                      printed)

    def test_a_play_app_never_published_needs_a_draft(self):
        printed, _, _ = self.run_preflight('--android', google=preflight_play(production=[]))
        self.assertIn('WARN   [Google Play] no release has ever gone out beyond internal testing', printed)
        self.assertIn('--draft', printed)


    def test_one_failing_read_is_unchecked_and_the_rest_still_run(self):
        apple = preflight_apple()
        apple[('GET', '/subscriptionGroups')] = StoreError('GET .../subscriptionGroups refused (500): down')
        printed, _, _ = self.run_preflight('--ios', '--build', '31', apple=apple)
        self.assertEqual(self.code, 1, printed)
        self.assertIn('UNCHECKED [subscriptions] the subscriptions: GET .../subscriptionGroups refused (500)',
                      printed)
        # Everything that does not need the subscriptions still ran.
        self.assertIn('OK     [App Review 5.1.1(i)] privacy policy URL', printed)
        self.assertIn('OK     [App Review] no review submission open', printed)
        self.assertIn('Summary: 0 BLOCK, 1 UNCHECKED', printed)

    def test_a_failed_versions_read_still_checks_what_does_not_need_it(self):
        apple = preflight_apple()
        apple[('GET', '/appStoreVersions?')] = StoreError('GET .../appStoreVersions refused (500): down')
        printed, _, _ = self.run_preflight('--ios', '--build', '31', apple=apple)
        self.assertEqual(self.code, 1, printed)
        self.assertIn('UNCHECKED [version] the version, its build, text, screenshots', printed)
        self.assertIn('OK     [export compliance] build 31 (1.0.1) uses no non-exempt encryption', printed)
        self.assertIn('OK     [App Review 5.1.1(i)] privacy policy URL', printed)
        self.assertIn('OK     [subscriptions] Premium (premium.monthly) is APPROVED', printed)

    def test_a_failed_play_details_read_still_checks_the_tracks(self):
        google = preflight_play()
        google[('GET', '/details')] = StoreError('GET .../details refused (503): down')
        printed, _, google = self.run_preflight('--android', google=google)
        self.assertEqual(self.code, 1, printed)
        self.assertIn('UNCHECKED [Play policy] the contact details, listing text and listing pictures', printed)
        self.assertIn('OK     [Google Play] internal: newest build', printed)
        self.assertEqual([m for m, u in google.writes()], ['POST', 'DELETE'])

    def test_every_localization_is_compared_with_the_primary(self):
        apple = {
            ('GET', '/appStoreVersionLocalizations/L2/appScreenshotSets'): {'data': [
                {'id': 'S2', 'attributes': {'screenshotDisplayType': 'APP_IPHONE_67'}}]},
            ('GET', '/appStoreVersionLocalizations/L3/appScreenshotSets'): {'data': []},
            ('GET', '/appScreenshotSets/S2/appScreenshots'): {'data': [
                {'id': 'Y1', 'attributes': {'assetDeliveryState': {'state': 'COMPLETE'}}}]},
            **preflight_apple(),
        }
        apple[('GET', '/appStoreVersionLocalizations')] = {'data': [
            {'id': loc, 'attributes': {'locale': code, 'description': 'd', 'keywords': 'k',
                                       'supportUrl': 'https://example.com/support'}}
            for loc, code in (('L1', 'en-GB'), ('L2', 'de-DE'), ('L3', 'fr-FR'))]}
        printed, _, _ = self.run_preflight('--ios', apple=apple)
        self.assertIn('WARN   [App Store Connect] 1.0.1 de-DE: APP_IPHONE_67 has 1, en-GB has 2', printed)
        self.assertIn('WARN   [App Store Connect] 1.0.1 fr-FR: no screenshots of its own '
                      '(screenshots --locale fr-FR adds them)', printed)

    def test_a_held_version_is_said_to_stay_held(self):
        apple = preflight_apple()
        apple[('GET', '/v1/appStoreVersions/V1?')]['data']['attributes']['releaseType'] = 'MANUAL'
        printed, _, _ = self.run_preflight('--ios', apple=apple)
        self.assertIn('1.0.1 is held after approval until `release` (prepare and submit keep it; '
                      '--automatic changes it)', printed)

    def test_a_release_on_testing_tracks_means_the_app_is_not_a_draft(self):
        google = preflight_play(production=[])
        google[('GET', '/tracks')]['tracks'].append(
            {'track': 'beta', 'releases': [{'name': '1.0.0 (2)', 'versionCodes': ['2'], 'status': 'completed'}]})
        printed, _, _ = self.run_preflight('--android', google=google)
        self.assertNotIn('treats the app as a draft', printed)


class Doctor(StoreTest):
    def test_a_missing_key_is_reported_with_the_fix(self):
        with mock.patch.object(asc, 'call') as apple:
            code, printed = run(self.project, 'doctor', 'myapp', '--ios')
        self.assertEqual(code, 1)
        self.assertIn('FAIL  App Store Connect key: No App Store Connect key at', printed)
        self.assertIn('fix: create an App Store Connect API key: see references/connect.md', printed)
        self.assertIn('Stopped: 1 of', printed)
        # Store folders not made yet are noted, not failed.
        self.assertIn('NOTE  screenshots.ios: store/shots/ios does not exist yet', printed)
        apple.assert_not_called()

    def test_working_keys_pass_every_check_and_open_one_play_edit(self):
        apps = {'myapp': {'ios': {'bundle_id': 'com.example.myapp'},
                          'android': {'package': 'com.example.myapp'}}}
        project = Project(self, apps=apps)
        ec_key = ec.generate_private_key(ec.SECP256R1())
        (project.keys / 'AuthKey_ABC123.p8').write_bytes(ec_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        (project.keys / 'asc.json').write_text(json.dumps({'issuer_id': 'i', 'key_id': 'ABC123'}),
                                               encoding='utf-8')
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        (project.keys / 'play.json').write_text(json.dumps({
            'type': 'service_account', 'client_email': 'robot@example.iam.gserviceaccount.com',
            'private_key': rsa_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                 serialization.NoEncryption()).decode('ascii'),
            'token_uri': 'https://oauth2.googleapis.com/token'}), encoding='utf-8')
        apple = FakeStore({('GET', '/v1/apps?'): {'data': [
            {'id': 'A1', 'attributes': {'bundleId': 'com.example.myapp'}}]}})
        google = FakeStore({('POST', 'oauth2.googleapis.com/token'): {'access_token': 'tok'},
                            ('POST', '/edits'): {'id': 'E1'}})
        with mock.patch.object(asc, 'call', apple), mock.patch.object(play, 'call', google):
            code, printed = run(project, 'doctor', 'myapp')
        self.assertEqual(code, 0, printed)
        self.assertNotIn('FAIL', printed)
        self.assertIn('doctor: all', printed)
        self.assertIn('token accepted; app A1 found for com.example.myapp', printed)
        self.assertNotIn('robot@example', printed)  # nothing from the key file is printed
        self.assertEqual([m for m, u in google.sent if '/edits' in u], ['POST', 'DELETE'])


class Retry(unittest.TestCase):
    """Apple's API answers an occasional 5xx: a read is tried again, a write never."""

    @staticmethod
    def refusal(code):
        return urllib.error.HTTPError('https://api.example/x', code, 'err', hdrs=None,
                                      fp=io.BytesIO(b'{"errors": [{"title": "Server error"}]}'))

    class Answer:
        def __init__(self, body: bytes):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def test_a_get_is_tried_again_after_a_5xx(self):
        answers = [self.refusal(500), self.refusal(503), self.Answer(b'{"data": []}')]
        with mock.patch.object(common.urllib.request, 'urlopen', side_effect=answers) as opened, \
                mock.patch.object(common.time, 'sleep') as slept, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(common.call('GET', 'https://api.example/x'), {'data': []})
        self.assertEqual(opened.call_count, 3)
        self.assertEqual([c.args[0] for c in slept.call_args_list], list(common.RETRY_DELAYS))

    def test_a_get_gives_up_after_two_retries(self):
        answers = [self.refusal(500), self.refusal(500), self.refusal(500)]
        with mock.patch.object(common.urllib.request, 'urlopen', side_effect=answers) as opened, \
                mock.patch.object(common.time, 'sleep'), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(StoreError) as caught:
                common.call('GET', 'https://api.example/x?secret=1')
        self.assertEqual(opened.call_count, 3)
        self.assertIn('refused (500): Server error', str(caught.exception))
        self.assertNotIn('secret', str(caught.exception))  # the query is never shown

    def test_a_write_is_never_sent_twice(self):
        with mock.patch.object(common.urllib.request, 'urlopen', side_effect=[self.refusal(500)]) as opened, \
                mock.patch.object(common.time, 'sleep') as slept:
            with self.assertRaises(StoreError):
                common.call('POST', 'https://api.example/x', body={})
        self.assertEqual(opened.call_count, 1)
        slept.assert_not_called()

    def test_a_4xx_is_not_retried(self):
        with mock.patch.object(common.urllib.request, 'urlopen', side_effect=[self.refusal(404)]) as opened:
            with self.assertRaises(StoreError):
                common.call('GET', 'https://api.example/x')
        self.assertEqual(opened.call_count, 1)


def run_flags(project: Project, *argv: str) -> tuple[int, str]:
    """Like run, but for a usage error: the exit code and what was said on stderr."""
    with contextlib.redirect_stdout(io.StringIO()) as printed, \
            contextlib.redirect_stderr(io.StringIO()) as said:
        try:
            code = store.main([*argv, '--config', str(project.config)])
        except SystemExit as e:
            code = e.code
    return code, printed.getvalue() + said.getvalue()


def write_keys(folder: Path, token_uri: str = 'https://oauth2.googleapis.com/token') -> None:
    """Working-looking key files: a P-256 .p8 with its asc.json, and a
    service account JSON with an RSA key."""
    ec_key = ec.generate_private_key(ec.SECP256R1())
    (folder / 'AuthKey_ABC123.p8').write_bytes(ec_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    (folder / 'asc.json').write_text(json.dumps({'issuer_id': 'i', 'key_id': 'ABC123'}), encoding='utf-8')
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (folder / 'play.json').write_text(json.dumps({
        'type': 'service_account', 'client_email': 'robot@example.iam.gserviceaccount.com',
        'private_key': rsa_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()).decode('ascii'),
        'token_uri': token_uri}), encoding='utf-8')


class ExactBundleId(StoreTest):
    def test_a_prefix_match_is_refused(self):
        fake = FakeStore({('GET', '/v1/apps?'): {'data': [
            {'id': 'A9', 'attributes': {'primaryLocale': 'en-GB', 'bundleId': 'com.example.myapp.pro'}}]}})
        with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', fake):
            code, printed = run(self.project, 'status', 'myapp', '--ios')
        self.assertEqual(code, 1)
        self.assertIn('No app with bundle id exactly com.example.myapp', printed)
        self.assertIn('returned only com.example.myapp.pro', printed)
        self.assertEqual(len(fake.sent), 1)  # the lookup, and nothing after it

    def test_the_exact_one_is_taken_among_prefix_matches(self):
        fake = FakeStore({('GET', '/v1/apps?'): {'data': [
            {'id': 'A9', 'attributes': {'primaryLocale': 'en-GB', 'bundleId': 'com.example.myapp.pro'}},
            {'id': 'A1', 'attributes': {'primaryLocale': 'en-GB', 'bundleId': 'com.example.myapp'}}]},
            ('GET', '/appStoreVersions?'): {'data': []}})
        with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', fake):
            code, printed = run(self.project, 'links', 'myapp', '--ios')
        self.assertEqual(code, 0, printed)
        self.assertIn('https://apps.apple.com/app/idA1', printed)

    def test_doctor_refuses_a_prefix_match_too(self):
        project = Project(self, apps={'myapp': {'ios': {'bundle_id': 'com.example.myapp'}}})
        write_keys(project.keys)
        fake = FakeStore({('GET', '/v1/apps?'): {'data': [
            {'id': 'A9', 'attributes': {'bundleId': 'com.example.myapp.pro'}}]}})
        with mock.patch.object(asc, 'call', fake):
            code, printed = run(project, 'doctor', 'myapp')
        self.assertEqual(code, 1)
        self.assertIn('FAIL  App Store Connect: the token is accepted, but: No app with bundle id exactly', printed)


class ReleaseTypeKept(StoreTest):
    """An existing version keeps its release type unless asked: a version held
    with release-type --manual is not quietly switched back."""

    def go(self, *argv, answers):
        fake = FakeStore(answers)
        with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', fake):
            code, printed = run(self.project, *argv)
        self.assertEqual(code, 0, printed)
        return fake, printed

    def patched(self, fake, version_id='V0'):
        return [b['data']['attributes'] for m, u, b in fake.bodies
                if m == 'PATCH' and u.endswith(f'/v1/appStoreVersions/{version_id}')]

    def test_a_held_version_stays_held(self):
        answers = with_open_version('1.9.9', 'REJECTED', release='MANUAL')
        fake, printed = self.go('prepare', 'myapp', '--build', '52', answers=answers)
        self.assertIn('rename version 1.9.9 to 2.0.0 (the one open for changes; Apple keeps one at a '
                      'time); held after approval until `release` (release type MANUAL, kept)', printed)
        fake, printed = self.go('prepare', 'myapp', '--build', '52', '--yes', answers=answers)
        self.assertEqual(self.patched(fake), [{'versionString': '2.0.0'}])
        fake, printed = self.go('submit', 'myapp', '--ios', '--build', '52', '--yes', answers=answers)
        self.assertEqual(self.patched(fake), [{'versionString': '2.0.0'}])
        self.assertIn('submitted: once Apple approves it, it waits for `release`', printed)

    def test_automatic_changes_it_and_the_plan_says_so(self):
        answers = with_open_version('1.9.9', 'REJECTED', release='MANUAL')
        fake, printed = self.go('prepare', 'myapp', '--build', '52', '--automatic', answers=answers)
        self.assertIn('release type MANUAL -> AFTER_APPROVAL: release automatically on approval', printed)
        self.assertEqual(fake.writes(), [])
        fake, printed = self.go('prepare', 'myapp', '--build', '52', '--automatic', '--yes', answers=answers)
        self.assertEqual(self.patched(fake), [{'versionString': '2.0.0', 'releaseType': 'AFTER_APPROVAL'}])

    def test_a_new_version_can_be_held_from_the_start(self):
        fake, printed = self.go('submit', 'myapp', '--ios', '--build', '52', '--manual', '--yes', answers=APPLE)
        created = [b for m, u, b in fake.bodies if m == 'POST' and u.endswith('/v1/appStoreVersions')]
        self.assertEqual(created[0]['data']['attributes']['releaseType'], 'MANUAL')
        self.assertIn('create version 2.0.0; held after approval until `release`', printed)

    def test_yes_echoes_the_whole_plan_it_carried_out(self):
        fake, printed = self.go('prepare', 'myapp', '--build', '52', '--yes',
                                answers=with_open_version('1.9.9', 'REJECTED'))
        for line in ('rename version 1.9.9 to 2.0.0', 'attach build 52', 'not sent for review',
                     'done: listing, screenshots and subscriptions can go on it now'):
            self.assertIn(line, printed)
        self.assertNotIn('plan only', printed)


class KeysInAnyRepository(StoreTest):
    def repo(self) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name).resolve()
        (root / '.git').mkdir()
        (root / 'keys').mkdir()
        return root

    def test_a_key_in_another_repository_is_refused(self):
        key = self.repo() / 'keys' / 'asc.json'
        key.write_text('{}', encoding='utf-8')
        project = Project(self, keys={'app_store_connect': str(key)})
        with mock.patch.object(asc, 'call') as apple:
            code, printed = run(project, 'status', 'myapp', '--ios')
        self.assertEqual(code, 1)
        self.assertIn('is inside a git work tree', printed)
        self.assertIn('a dotfiles repository in the home folder counts', printed)
        apple.assert_not_called()

    def test_a_p8_pointed_into_a_repository_is_refused(self):
        p8 = self.repo() / 'keys' / 'AuthKey_K.p8'
        p8.write_text('not read', encoding='utf-8')
        (self.project.keys / 'asc.json').write_text(json.dumps(
            {'issuer_id': 'i', 'key_id': 'K', 'key_file': str(p8)}), encoding='utf-8')
        with mock.patch.object(asc, 'call') as apple:
            code, printed = run(self.project, 'status', 'myapp', '--ios')
        self.assertEqual(code, 1)
        self.assertIn('The App Store Connect private key (key_file in asc.json)', printed)
        self.assertIn('is inside a git work tree', printed)
        apple.assert_not_called()


class MalformedFiles(StoreTest):
    def test_a_malformed_listing_names_the_file(self):
        bad = self.project.path('bad-listing.json')
        bad.write_text('{"ios": {"name": "x",}', encoding='utf-8')
        with mock.patch.object(asc, '_token') as token:
            code, printed = run(self.project, 'listing', 'myapp', '--from', str(bad))
        self.assertEqual(code, 1)
        self.assertIn('bad-listing.json (the listing file) is not valid JSON', printed)
        token.assert_not_called()

    def test_unreadable_notes_name_the_file(self):
        bad = self.project.path('notes.txt')
        bad.write_bytes(b'\xff\xfe\x00not utf-8')
        with mock.patch.object(play, '_token') as token:
            code, printed = run(self.project, 'submit', 'myapp', '--android', '--notes', str(bad))
        self.assertEqual(code, 1)
        self.assertIn('notes.txt (release notes) cannot be read as UTF-8 text', printed)
        code, printed = run(self.project, 'submit', 'myapp', '--android', '--notes', 'missing.txt')
        self.assertEqual(code, 1)
        self.assertIn('No release notes file at missing.txt', printed)
        token.assert_not_called()

    def test_a_malformed_key_file_is_never_echoed(self):
        (self.project.keys / 'asc.json').write_text('{"issuer_id": "SECRET-ISSUER-123", oops',
                                                    encoding='utf-8')
        code, printed = run(self.project, 'status', 'myapp', '--ios')
        self.assertEqual(code, 1)
        self.assertIn('asc.json is not valid JSON', printed)
        self.assertNotIn('SECRET-ISSUER-123', printed)

        (self.project.keys / 'asc.json').write_text(json.dumps({'issuer_id': 'i', 'key_id': 'K'}),
                                                    encoding='utf-8')
        (self.project.keys / 'AuthKey_K.p8').write_text(
            '-----BEGIN PRIVATE KEY-----\nSECRETKEYMATERIAL\n-----END PRIVATE KEY-----\n', encoding='utf-8')
        code, printed = run(self.project, 'status', 'myapp', '--ios')
        self.assertEqual(code, 1)
        self.assertIn('AuthKey_K.p8 is not an unencrypted PEM private key', printed)
        self.assertNotIn('SECRETKEYMATERIAL', printed)

        (self.project.keys / 'play.json').write_text(json.dumps({
            'type': 'service_account', 'client_email': 'robot@example.com',
            'private_key': '-----BEGIN PRIVATE KEY-----\nSECRETPLAYKEY\n-----END PRIVATE KEY-----\n'}),
            encoding='utf-8')
        code, printed = run(self.project, 'doctor', 'myapp', '--android')
        self.assertEqual(code, 1)
        self.assertIn("FAIL  Google Play key: The service account key's private_key does not load", printed)
        self.assertNotIn('SECRETPLAYKEY', printed)
        self.assertNotIn('robot@example.com', printed)


class PinnedTokenEndpoint(StoreTest):
    def test_the_assertion_goes_to_google_whatever_the_key_file_says(self):
        write_keys(self.project.keys, token_uri='https://attacker.example/token')
        fake = FakeStore({('POST', '/token'): {'access_token': 'tok'}})
        app = common.load_config(self.project.config).app('myapp')
        with mock.patch.object(play, 'call', fake):
            self.assertEqual(play._token(app), 'tok')
        self.assertEqual(fake.sent, [('POST', 'https://oauth2.googleapis.com/token')])


class TextLimits(StoreTest):
    def listing(self, body: dict) -> tuple[int, str]:
        source = self.project.path('listing.json')
        source.write_text(json.dumps(body), encoding='utf-8')
        with mock.patch.object(asc, '_token') as apple, mock.patch.object(play, '_token') as google:
            code, printed = run(self.project, 'listing', 'myapp', '--from', str(source), '--yes')
        apple.assert_not_called()
        google.assert_not_called()
        return code, printed

    def test_apple_limits_are_checked_before_anything_is_sent(self):
        code, printed = self.listing({'ios': {'description': 'x' * 4001, 'keywords': 'k' * 101,
                                              'subtitle': 's' * 31}})
        self.assertEqual(code, 1)
        self.assertIn('description has 4001 characters (at most 4000)', printed)
        self.assertIn('keywords has 101 characters (at most 100)', printed)
        self.assertIn('subtitle has 31 characters (at most 30)', printed)

    def test_play_limits_are_checked_before_anything_is_sent(self):
        code, printed = self.listing({'ios': {'name': 'Fine'},
                                      'android': {'title': 't' * 31, 'shortDescription': 's' * 81}})
        self.assertEqual(code, 1)
        self.assertIn('title has 31 characters (at most 30)', printed)
        self.assertIn('shortDescription has 81 characters (at most 80)', printed)

    def test_whats_new_over_4000_is_refused_before_anything_is_attached(self):
        notes = self.project.path('whats-new.txt')
        notes.write_text('x' * 4001, encoding='utf-8')
        with mock.patch.object(asc, '_token') as token, mock.patch.object(asc, 'call') as apple:
            code, printed = run(self.project, 'submit', 'myapp', '--ios', '--build', '52',
                                '--notes', str(notes), '--yes')
        self.assertEqual(code, 1)
        self.assertIn('whatsNew has 4001 characters (at most 4000)', printed)
        token.assert_not_called()
        apple.assert_not_called()


class TestFlightNotes(StoreTest):
    def test_what_to_test_goes_on_the_primary_locale_never_another(self):
        fake = FakeStore({**APPLE, ('GET', '/betaBuildLocalizations'): {'data': [
            {'id': 'BL-fr', 'attributes': {'locale': 'fr-FR'}}]}})
        notes = self.project.path('test.txt')
        notes.write_text('Try the new plan screen.', encoding='utf-8')
        with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', fake):
            code, printed = run(self.project, 'test-notes', 'myapp', '--ios', '--build', '52',
                                '--notes', str(notes), '--yes')
        self.assertEqual(code, 0, printed)
        self.assertFalse(any(m == 'PATCH' for m, u in fake.sent))
        made = [b for m, u, b in fake.bodies if m == 'POST' and u.endswith('/v1/betaBuildLocalizations')]
        self.assertEqual(made[0]['data']['attributes']['locale'], 'en-GB')


class UnusedFlags(StoreTest):
    def test_flags_a_command_does_not_use_are_refused(self):
        cases = [
            (('release', 'myapp', '--android'), 'release does not take --android: release is for the App '
                                                'Store only'),
            (('submit', 'myapp', '--ios', '--build', '52', '--draft'), '--draft is for submit --android, not --ios'),
            (('submit', 'myapp', '--ios', '--build', '52', '--rollout', '0.5'), '--rollout is for submit --android'),
            (('submit', 'myapp', '--android', '--build', '52'), '--build is for submit --ios, not --android'),
            (('status', 'myapp', '--yes'), 'status does not take --yes: status changes nothing'),
            (('pictures', 'myapp', '--locale', 'de-DE'), 'pictures does not take --locale'),
            (('prepare', 'myapp', '--build', '52', '--automatic', '--manual'), 'one or the other'),
        ]
        with mock.patch.object(asc, '_token') as apple, mock.patch.object(play, '_token') as google:
            for argv, said in cases:
                code, printed = run_flags(self.project, *argv)
                self.assertEqual(code, 2, argv)
                self.assertIn(said, printed, argv)
        apple.assert_not_called()
        google.assert_not_called()

    def test_doctor_refuses_an_app_not_in_the_config_before_any_call(self):
        with mock.patch.object(asc, 'call') as apple, mock.patch.object(play, 'call') as google:
            code, printed = run(self.project, 'doctor', 'otherapp')
        self.assertEqual(code, 1)
        self.assertIn('FAIL  app: No app "otherapp"', printed)
        apple.assert_not_called()
        google.assert_not_called()


def tracks_fake(production=None, beta=None) -> FakeStore:
    tracks = [{'track': 'internal', 'releases': [
        {'name': '2.0.0 (3)', 'versionCodes': ['3'], 'status': 'completed'}]}]
    if beta is not None:
        tracks.append({'track': 'beta', 'releases': beta})
    if production is not None:
        tracks.append({'track': 'production', 'releases': production})
    return FakeStore({('POST', '/edits'): {'id': 'E1'}, ('GET', '/tracks'): {'tracks': tracks},
                      ('GET', '/details'): {'defaultLanguage': 'en-GB'}})


class PlayTracksAndRollout(StoreTest):
    def submit(self, fake, *flags):
        with mock.patch.object(play, '_token', return_value='t'), mock.patch.object(play, 'call', fake):
            return run(self.project, 'submit', 'myapp', '--android', *flags)

    def test_a_staged_rollout_from_another_track(self):
        fake = tracks_fake(beta=[{'name': '2.1.0 (5)', 'versionCodes': ['5'], 'status': 'completed'}])
        code, printed = self.submit(fake, '--from-track', 'beta', '--rollout', '0.2')
        self.assertEqual(code, 0, printed)
        self.assertIn('2.1.0 (5) (5): completed from beta to production', printed)
        self.assertIn('staged rollout to 20% of users once Google approves it', printed)
        self.assertFalse(any(m == 'PUT' for m, u in fake.sent))
        code, printed = self.submit(tracks_fake(beta=[{'name': '2.1.0 (5)', 'versionCodes': ['5'],
                                                       'status': 'completed'}]),
                                    '--from-track', 'beta', '--rollout', '0.2', '--yes')
        self.assertEqual(code, 0, printed)

    def test_the_staged_release_body(self):
        fake = tracks_fake()
        code, printed = self.submit(fake, '--rollout', '0.2', '--yes')
        self.assertEqual(code, 0, printed)
        release = [b for m, u, b in fake.bodies if m == 'PUT'][0]['releases'][0]
        self.assertEqual((release['status'], release['userFraction'], release['versionCodes']),
                         ('inProgress', 0.2, ['3']))

    def test_everybody_by_default_and_the_plan_says_so(self):
        code, printed = self.submit(tracks_fake())
        self.assertIn('rollout 100%: for everybody, live once Google approves it', printed)
        self.assertIn('from internal to production', printed)

    def test_a_build_already_on_production_is_not_sent_again(self):
        fake = tracks_fake(production=[{'name': '2.0.0 (3)', 'versionCodes': ['3'], 'status': 'completed'}])
        code, printed = self.submit(fake, '--yes')
        self.assertEqual(code, 1)
        self.assertIn('is already on production', printed)
        self.assertFalse(any(m == 'PUT' for m, u in fake.sent))
        self.assertTrue(any(m == 'DELETE' for m, u in fake.sent))  # the edit, discarded

    def test_a_draft_takes_no_rollout_and_a_bad_share_is_refused(self):
        with mock.patch.object(play, '_token') as token:
            code, printed = run(self.project, 'submit', 'myapp', '--android', '--draft', '--rollout', '0.5')
            self.assertEqual(code, 1)
            self.assertIn('leave out --rollout', printed)
            for bad in ('0', '1.5', 'half'):
                code, said = run_flags(self.project, 'submit', 'myapp', '--android', '--rollout', bad)
                self.assertEqual(code, 2, bad)
                self.assertIn('--rollout takes a share of users above 0 and at most 1', said)
            code, said = run_flags(self.project, 'submit', 'myapp', '--android', '--from-track', 'production')
            self.assertEqual(code, 2)
        token.assert_not_called()


class ScreenshotPlansAndFailures(StoreTest):
    def test_the_play_plan_says_what_is_there_now_and_writes_nothing(self):
        _png(self.project.path('store/shots/android/01.png'), 1080, 1920)
        _png(self.project.path('store/shots/android/02.png'), 1080, 1920)
        _png(self.project.path('store/icon.png'), 512, 512)
        fake = FakeStore({('POST', '/edits'): {'id': 'E1'}, ('GET', '/details'): {'defaultLanguage': 'en-GB'},
                          ('GET', '/listings/en-GB/phoneScreenshots'): {'images': [{'id': str(i)} for i in range(6)]},
                          ('GET', '/listings/en-GB/icon'): {'images': [{'id': 'i'}]}})
        with mock.patch.object(play, '_token', return_value='t'), mock.patch.object(play, 'call', fake):
            code, printed = run(self.project, 'screenshots', 'myapp', '--android')
        self.assertEqual(code, 0, printed)
        self.assertIn('phoneScreenshots: replace the 6 there now with 2: 01.png, 02.png', printed)
        self.assertIn('icon: replace the 1 there now with 1: icon.png', printed)
        self.assertEqual([m for m, u in fake.writes()], ['POST', 'DELETE'])  # open and discard the edit
        self.assertFalse(any(':commit' in u for m, u in fake.sent))

    def test_an_ios_upload_failing_part_way_says_what_is_left(self):
        _png(self.project.path('store/shots/ios/01.png'), 1290, 2796)
        _png(self.project.path('store/shots/ios/APP_IPAD_PRO_3GEN_129/01.png'), 2064, 2752)
        fake = FakeStore(apple_shots(existing={'APP_IPHONE_67': 2}))
        puts = []

        def flaky(method, url, **kwargs):
            if method == 'PUT':
                puts.append(url)
                if len(puts) == 2:
                    raise StoreError('PUT https://upload.example/SH1 failed: connection reset')
            return fake(method, url, **kwargs)

        with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', flaky):
            code, printed = run(self.project, 'screenshots', 'myapp', '--ios', '--yes')
        self.assertEqual(code, 1)
        self.assertIn('Stopped part way', printed)
        self.assertIn('replaced already: APP_IPHONE_67 (1)', printed)
        self.assertIn('APP_IPAD_PRO_3GEN_129: 0 of the 0 that were there deleted; 0 of 1 uploaded', printed)
        self.assertIn('Run screenshots again to recover', printed)

    def test_a_play_upload_failing_part_way_changes_nothing(self):
        _png(self.project.path('store/shots/android/01.png'), 1080, 1920)
        _png(self.project.path('store/shots/android/02.png'), 1080, 1920)
        fake = FakeStore({('POST', 'uploadType=media'): StoreError('POST upload refused (500): busy'),
                          ('POST', '/edits'): {'id': 'E1'}, ('GET', '/details'): {'defaultLanguage': 'en-GB'}})
        with mock.patch.object(play, '_token', return_value='t'), mock.patch.object(play, 'call', fake):
            code, printed = run(self.project, 'screenshots', 'myapp', '--android', '--yes')
        self.assertEqual(code, 1)
        self.assertIn('Nothing changed on Google Play: the edit was not committed', printed)
        self.assertFalse(any(':commit' in u for m, u in fake.sent))
        self.assertTrue(any(m == 'DELETE' and u.endswith('/edits/E1') for m, u in fake.sent))


class Locales(StoreTest):
    def test_listing_goes_on_the_named_locale(self):
        sent = []
        fake = FakeStore({
            ('GET', '/v1/apps?'): {'data': [{'id': 'A1', 'attributes': {'primaryLocale': 'en-GB',
                                                                         'bundleId': 'com.example.myapp'}}]},
            ('GET', '/appStoreVersions?'): {'data': [
                {'id': 'V2', 'attributes': {'versionString': '2.0.0', 'appVersionState': 'PREPARE_FOR_SUBMISSION'}}]},
            ('GET', '/appStoreVersionLocalizations'): {'data': [
                {'id': 'L-en', 'attributes': {'locale': 'en-GB'}}, {'id': 'L-de', 'attributes': {'locale': 'de-DE'}}]},
        })

        def recording(method, url, **kwargs):
            if method != 'GET':
                sent.append((method, url.split('/v1/')[-1]))
            return fake(method, url, **kwargs)

        source = self.project.path('listing.json')
        source.write_text(json.dumps({'ios': {'description': 'Beschreibung'},
                                      'android': {'title': 'Titel'}}), encoding='utf-8')
        google = FakeStore({('POST', '/edits'): {'id': 'E1'}, ('GET', '/details'): {'defaultLanguage': 'en-GB'}})
        with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', recording), \
                mock.patch.object(play, '_token', return_value='t'), mock.patch.object(play, 'call', google):
            code, printed = run(self.project, 'listing', 'myapp', '--from', str(source), '--locale', 'de-DE',
                                '--yes')
        self.assertEqual(code, 0, printed)
        self.assertEqual(sent, [('PATCH', 'appStoreVersionLocalizations/L-de')])
        self.assertTrue(any(m == 'PATCH' and u.endswith('/listings/de-DE') for m, u in google.sent))

    def test_screenshots_go_on_the_named_locale(self):
        _png(self.project.path('store/shots/ios/01.png'), 1290, 2796)
        fake = FakeStore(apple_shots(locales=('en-GB', 'de-DE')))
        with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', fake):
            code, printed = run(self.project, 'screenshots', 'myapp', '--ios', '--locale', 'de-DE', '--yes')
        self.assertEqual(code, 0, printed)
        self.assertIn('2.0.0 (de-DE)', printed)
        made = [b for m, u, b in fake.bodies if m == 'POST' and u.endswith('/v1/appScreenshotSets')]
        self.assertEqual(made[0]['data']['relationships']['appStoreVersionLocalization']['data']['id'], 'L-de-DE')

    def test_a_locale_the_version_lacks_is_refused(self):
        _png(self.project.path('store/shots/ios/01.png'), 1290, 2796)
        fake = FakeStore(apple_shots())
        with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', fake):
            code, printed = run(self.project, 'screenshots', 'myapp', '--ios', '--locale', 'fr-FR')
        self.assertEqual(code, 1)
        self.assertIn('has no fr-FR localization (it has: en-GB)', printed)


class PictureTypes(StoreTest):
    def test_mac_tv_and_vision_folders_are_refused_on_an_ios_version(self):
        _png(self.project.path('store/shots/ios/APP_DESKTOP/01.png'), 2880, 1800)
        with self.assertRaises(StoreError) as caught:
            pictures.ios_sets(self.project.path('store/shots/ios'))
        self.assertIn('APP_DESKTOP/ is not a display type', str(caught.exception))

    def test_the_newer_69_inch_size_is_read_as_67(self):
        self.assertEqual(pictures.infer_display_type(1260, 2736), 'APP_IPHONE_67')


class PlanOnlySweep(StoreTest):
    """Every command that changes a store, run without --yes: nothing is
    written, except Play's edit, which is opened and discarded."""

    def apple(self) -> dict:
        return {
            ('GET', 'versionString'): {'data': []},
            ('GET', '/v1/apps?'): {'data': [{'id': 'A1', 'attributes': {'primaryLocale': 'en-GB',
                                                                         'bundleId': 'com.example.myapp'}}]},
            ('GET', '/v1/builds?'): APPLE[('GET', '/v1/builds?')],
            ('GET', '/appStoreVersions?'): {'data': [
                {'id': 'V2', 'attributes': {'versionString': '1.9.9', 'appVersionState': 'PREPARE_FOR_SUBMISSION',
                                            'releaseType': 'MANUAL'}},
                {'id': 'V3', 'attributes': {'versionString': '1.9.8', 'appVersionState': 'PENDING_DEVELOPER_RELEASE'}}]},
            ('GET', 'UNRESOLVED_ISSUES'): {'data': []},
            ('GET', '/v1/reviewSubmissions?'): {'data': []},
            ('GET', '/v1/betaGroups'): {'data': [{'id': 'G1', 'attributes': {'name': 'Internal'}}]},
            ('GET', '/placements'): {'data': [], 'included': []},
            ('GET', '/appScreenshotSets'): {'data': []},
            ('GET', '/appStoreVersionLocalizations'): {'data': [{'id': 'L1', 'attributes': {'locale': 'en-GB'}}]},
            ('GET', '/assetLibrary'): {'data': {'type': 'appAssetLibraries', 'id': 'LIB'}},
            ('GET', '/appAssetLibraries/LIB/images'): {'data': []},
        }

    def google(self) -> dict:
        return {
            ('POST', '/edits'): {'id': 'E1'},
            ('GET', '/tracks'): {'tracks': [{'track': 'internal', 'releases': [
                {'name': '2.0.0 (3)', 'versionCodes': ['3'], 'status': 'completed'}]}]},
            ('GET', '/details'): {'defaultLanguage': 'en-GB'},
        }

    def test_nothing_is_written_without_yes(self):
        root = self.project.root
        _png(root / 'store/shots/ios/01.png', 1290, 2796)
        _png(root / 'store/shots/android/01.png', 1080, 1920)
        _png(root / 'store/shots/android/02.png', 1080, 1920)
        _png(root / 'store/creative/universal.png', 5244, 2950)
        (root / 'store/listing.json').write_text(json.dumps(
            {'ios': {'description': 'd'}, 'android': {'title': 't'}}), encoding='utf-8')
        notes = root / 'notes.txt'
        notes.write_text('Better.', encoding='utf-8')
        commands = [
            ('listing', 'myapp'),
            ('test-notes', 'myapp', '--notes', str(notes), '--ios', '--build', '52'),
            ('test-notes', 'myapp', '--notes', str(notes), '--android'),
            ('add-tester', 'myapp', '--email', 'a@example.com', '--group', 'Internal'),
            ('release', 'myapp'),
            ('release-type', 'myapp', '--automatic'),
            ('prepare', 'myapp', '--build', '52'),
            ('submit', 'myapp', '--ios', '--build', '52'),
            ('submit', 'myapp', '--android'),
            ('screenshots', 'myapp', '--ios'),
            ('screenshots', 'myapp', '--android'),
            ('assets', 'myapp'),
        ]
        for argv in commands:
            apple, google = FakeStore(self.apple()), FakeStore(self.google())
            with mock.patch.object(asc, '_token', return_value='t'), mock.patch.object(asc, 'call', apple), \
                    mock.patch.object(play, '_token', return_value='t'), mock.patch.object(play, 'call', google):
                code, printed = run(self.project, *argv)
            self.assertEqual(code, 0, (argv, printed))
            self.assertIn('(plan only: run again with --yes to do it)', printed, argv)
            self.assertEqual(apple.writes(), [], argv)
            opened = [u for m, u in google.writes() if m == 'POST']
            discarded = [u for m, u in google.writes() if m == 'DELETE']
            self.assertTrue(all(u.endswith('/edits') for u in opened), argv)
            self.assertTrue(all(u.endswith('/edits/E1') for u in discarded), argv)
            self.assertEqual(len(opened), len(discarded), argv)
            self.assertEqual(len(google.writes()), len(opened) + len(discarded), argv)


OPEN = {'id': 'V2', 'attributes': {'versionString': '2.0.1', 'appVersionState': 'PREPARE_FOR_SUBMISSION'}}
LIVE = {'id': 'V1', 'attributes': {'versionString': '2.0.0', 'appVersionState': 'READY_FOR_DISTRIBUTION'}}


def asset_answers(versions, spec='UNI', placed=None, included=None, library=None, videos=None):
    return {
        ('GET', '/v1/apps?'): {'data': [{'id': 'A1', 'attributes': {'primaryLocale': 'en-GB', 'bundleId': 'com.example.myapp'}}]},
        ('GET', '/appStoreVersions?'): {'data': versions},
        ('GET', '/placements'): {'data': placed or [], 'included': included or []},
        ('GET', '/appStoreVersionLocalizations'): {
            'data': [{'id': 'L1', 'attributes': {'locale': 'en-GB'}}]},
        ('GET', '/assetLibrary'): {'data': {'type': 'appAssetLibraries', 'id': 'LIB'}},
        ('GET', '/appAssetLibraries/LIB/images'): {'data': library or []},
        ('GET', '/appAssetLibraries/LIB/videos'): {'data': videos or []},
        ('POST', '/v1/appAssetLibraryVideos'): {'data': {'id': 'VID1', 'attributes': {
            'state': 'AWAITING_UPLOAD', 'uploadOperations': [{
                'method': 'PUT', 'url': 'https://upload.example/VID1', 'offset': 0, 'length': 10,
                'requestHeaders': [{'name': 'Content-Type', 'value': 'video/mp4'}]}]}}},
        ('GET', '/v1/appAssetLibraryVideos/'): {'data': {'id': 'VID1', 'attributes': {
            'state': 'PREPARE_FOR_SUBMISSION', 'specId': 'HV'}}},
        ('POST', '/v1/appAssetLibraryImages'): {'data': {'id': 'IMG1', 'attributes': {
            'state': 'AWAITING_UPLOAD', 'uploadOperations': [{
                'method': 'PUT', 'url': 'https://upload.example/IMG1', 'offset': 0, 'length': 10,
                'requestHeaders': [{'name': 'Content-Type', 'value': 'image/png'}]}]}}},
        ('GET', '/v1/appAssetLibraryImages/'): {'data': {'id': 'IMG1', 'attributes': {
            'state': 'PREPARE_FOR_SUBMISSION', 'specId': spec}}},
        ('GET', '/v1/appAssetLibraryRefData'): {'data': [{'attributes': {
            'placementTypes': [
                {'placementTypeId': 'PRODUCT_PAGE_HEADER_ASSET', 'specMappings': [
                    {'placementGroupId': 'DEFAULT_PROFILE', 'specs': ['UNI', 'HDR', 'HV']}]},
                {'placementTypeId': 'APP_STORE_SEARCH_RESULTS_ASSET', 'specMappings': [
                    {'placementGroupId': 'DEFAULT_PROFILE', 'specs': ['UNI', 'SRCH']}]},
            ],
            'imageSpecs': [{'specId': 'UNI', 'shortName': 'i5244x2950a0'},
                           {'specId': 'HDR', 'shortName': 'i3840x1646a0'},
                           {'specId': 'SRCH', 'shortName': 'i3x2w1920~3840a0'}],
            'videoSpecs': [{'specId': 'HV', 'shortName': 'v3840x1646f30~60t15~30'}],
        }}]},
    }


class _Next:
    """An answer that changes on each request: the next one from [states]."""

    def __init__(self, states):
        self.states = states

    def resolve(self):
        return next(self.states)


class AppleAssets(StoreTest):
    """The product page header and search results asset: checked on disk
    first, uploaded once, placed on every localization of the open version."""

    def run_assets(self, files, *flags, answers=None):
        sent = []
        fake = FakeStore(answers or asset_answers([OPEN, LIVE]))

        def recording(method, url, **kwargs):
            sent.append((method, url, kwargs))
            return fake(method, url, **kwargs)

        with tempfile.TemporaryDirectory() as folder:
            for name, (width, height) in files.items():
                if name.endswith('.mp4'):
                    # Not a real film: ffprobe is stood in for below.
                    (Path(folder) / name).write_bytes(b'0' * 64)
                else:
                    _png(Path(folder) / name, width, height)
            film = mock.patch.object(
                asc, '_video_facts', return_value=(3840, 1646, asc.Fraction(30), 15.0))
            with film, mock.patch.object(asc, '_token', return_value='t') as token, \
                    mock.patch.object(asc, 'call', recording):
                code, printed = run(self.project, 'assets', 'myapp', '--from', folder, *flags)
        return code, sent, printed, token

    @staticmethod
    def writes(sent):
        return [(m, u, k) for m, u, k in sent if m != 'GET']

    def test_without_yes_it_only_plans(self):
        code, sent, printed, _ = self.run_assets({'universal.png': (5244, 2950)})
        self.assertEqual(code, 0)
        self.assertEqual(self.writes(sent), [])
        self.assertIn('universal.png (5244x2950): product page header and search results; upload it',
                      printed)
        self.assertIn('on version 2.0.1 (PREPARE_FOR_SUBMISSION), in en-GB', printed)
        self.assertIn('--yes', printed)

    def test_universal_fills_both_placements(self):
        code, sent, printed, _ = self.run_assets({'universal.png': (5244, 2950)}, '--yes')
        self.assertEqual(code, 0, printed)
        writes = self.writes(sent)
        reserved = [k['body'] for m, u, k in writes if u.endswith('/v1/appAssetLibraryImages')]
        self.assertEqual(len(reserved), 1)  # one upload for both
        self.assertEqual(reserved[0]['data']['attributes']['category'], 'CREATIVE_ASSETS')
        put = [k for m, u, k in writes if m == 'PUT']
        self.assertNotIn('token', put[0])  # the upload URL takes no key
        commit = [k['body'] for m, u, k in writes if m == 'PATCH']
        self.assertEqual(commit[0]['data']['attributes'], {'uploaded': True})
        placed = [k['body']['data'] for m, u, k in writes if u.endswith('/v1/appAssetLibraryPlacements')]
        self.assertEqual({p['attributes']['placementType'] for p in placed},
                         {'PRODUCT_PAGE_HEADER_ASSET', 'APP_STORE_SEARCH_RESULTS_ASSET'})
        for p in placed:
            self.assertEqual(p['attributes']['placementGroup'], 'DEFAULT_PROFILE')
            self.assertEqual(p['relationships']['image']['data']['id'], 'IMG1')
            self.assertEqual(p['relationships']['appStoreVersionLocalization']['data']['id'], 'L1')

    def test_header_with_universal_is_refused_before_anything_is_called(self):
        code, sent, printed, token = self.run_assets(
            {'universal.png': (5244, 2950), 'header.png': (3840, 1646)}, '--yes')
        self.assertEqual(code, 1)
        self.assertIn('universal.png fills both placements, so header.png cannot go with it', printed)
        self.assertEqual(sent, [])
        token.assert_not_called()

    def test_a_wrong_size_is_refused_with_the_size_expected(self):
        code, sent, printed, _ = self.run_assets({'universal.png': (5244, 2949)}, '--yes')
        self.assertEqual(code, 1)
        self.assertIn('universal.png is 5244x2949: it has to be 5244x2950 (16:9).', printed)
        self.assertEqual(sent, [])

    def test_no_version_open_means_upload_only(self):
        answers = asset_answers([LIVE])
        code, sent, printed, _ = self.run_assets({'universal.png': (5244, 2950)}, answers=answers)
        self.assertEqual(code, 0)
        self.assertEqual(self.writes(sent), [])
        self.assertIn('the placements wait for prepare', printed)
        code, sent, printed, _ = self.run_assets({'universal.png': (5244, 2950)}, '--yes', answers=answers)
        self.assertEqual(code, 0, printed)
        urls = [u for m, u, k in self.writes(sent)]
        self.assertTrue(any(u.endswith('/v1/appAssetLibraryImages') for u in urls))
        self.assertFalse(any('Placements' in u for u in urls))
        self.assertIn('uploaded only', printed)

    def test_what_is_placed_now_is_deleted_before_the_new_one_is_created(self):
        answers = asset_answers(
            [OPEN, LIVE], spec='HDR',
            placed=[{'id': 'OLD', 'attributes': {'placementType': 'PRODUCT_PAGE_HEADER_ASSET',
                                                 'mediaType': 'IMAGE'},
                     'relationships': {'image': {'data': {'type': 'appAssetLibraryImages', 'id': 'IMG0'}}}}],
            included=[{'type': 'appAssetLibraryImages', 'id': 'IMG0',
                       'attributes': {'fileName': 'old-header.png'}}])
        code, sent, printed, _ = self.run_assets({'header.png': (3840, 1646)}, answers=answers)
        self.assertIn('en-GB: product page header: delete the one there now (old-header.png), '
                      'then place header.png', printed)
        code, sent, printed, _ = self.run_assets({'header.png': (3840, 1646)}, '--yes', answers=answers)
        self.assertEqual(code, 0, printed)
        order = [(m, u.split('/v1/')[-1]) for m, u, k in self.writes(sent)]
        deleted = order.index(('DELETE', 'appAssetLibraryPlacements/OLD'))
        created = order.index(('POST', 'appAssetLibraryPlacements'))
        self.assertLess(deleted, created)
        self.assertEqual(sum(1 for o in order if o[1].startswith('appAssetLibraryPlacements')), 2)

    def test_an_asset_already_in_the_library_is_placed_not_uploaded_again(self):
        with tempfile.TemporaryDirectory() as folder:
            _png(Path(folder) / 'universal.png', 5244, 2950)
            size = (Path(folder) / 'universal.png').stat().st_size
        answers = asset_answers([OPEN, LIVE], library=[{'id': 'IMG1', 'attributes': {
            'fileName': 'universal.png', 'fileSize': size, 'state': 'APPROVED'}}])
        code, sent, printed, _ = self.run_assets({'universal.png': (5244, 2950)}, '--yes', answers=answers)
        self.assertEqual(code, 0, printed)
        urls = [u for m, u, k in self.writes(sent)]
        self.assertFalse(any(u.endswith('/v1/appAssetLibraryImages') for u in urls))
        self.assertEqual(sum(1 for u in urls if u.endswith('/v1/appAssetLibraryPlacements')), 2)

    def test_a_version_in_review_gets_nothing_placed_and_the_files_still_upload(self):
        # The Asset Library does not touch a version, so a version waiting on
        # Apple holds nothing back but its own placements.
        waiting = {'id': 'V2', 'attributes': {'versionString': '2.0.1', 'appVersionState': 'WAITING_FOR_REVIEW'}}
        code, sent, printed, _ = self.run_assets(
            {'universal.png': (5244, 2950)}, '--yes', answers=asset_answers([waiting, LIVE]))
        self.assertEqual(code, 0, printed)
        urls = [u for m, u, k in self.writes(sent)]
        self.assertTrue(any(u.endswith('/v1/appAssetLibraryImages') for u in urls))
        self.assertFalse(any('Placements' in u for u in urls))
        self.assertIn('2.0.1 is WAITING_FOR_REVIEW: nothing is placed on it', printed)

    def test_a_videos_opening_still_is_set_when_it_is_reserved(self):
        code, sent, printed, _ = self.run_assets(
            {'header.mp4': (3840, 1646)}, '--poster', '00:00:05:00', '--yes')
        self.assertEqual(code, 0, printed)
        reserve = [k for m, u, k in self.writes(sent) if u.endswith('/v1/appAssetLibraryVideos')]
        self.assertEqual(len(reserve), 1)
        attributes = reserve[0]['body']['data']['attributes']
        self.assertEqual(attributes['previewFrameTimeCode'], '00:00:05:00')
        self.assertIn('opening still 00:00:05:00', printed)

    def test_an_opening_still_past_the_end_is_refused_before_anything_is_sent(self):
        code, sent, printed, _ = self.run_assets(
            {'header.mp4': (3840, 1646)}, '--poster', '00:00:20:00', '--yes')
        self.assertEqual(code, 1)
        self.assertEqual(sent, [])
        self.assertIn('past the end of header.mp4', printed)

    def test_an_opening_still_frame_must_fit_the_frame_rate(self):
        code, sent, printed, _ = self.run_assets(
            {'header.mp4': (3840, 1646)}, '--poster', '00:00:05:30')
        self.assertEqual(code, 1)
        self.assertIn('runs 00 to 29', printed)

    def test_a_video_reporting_complete_is_still_processing(self):
        # Seen live: COMPLETE between the commit and PREPARE_FOR_SUBMISSION.
        answers = asset_answers([OPEN, LIVE])
        answers[('GET', '/v1/appAssetLibraryVideos/')] = {'data': {'id': 'VID1', 'attributes': {
            'state': 'COMPLETE', 'specId': None}}}
        ready = {'data': {'id': 'VID1', 'attributes': {'state': 'PREPARE_FOR_SUBMISSION', 'specId': 'HV'}}}
        states = iter([answers[('GET', '/v1/appAssetLibraryVideos/')], ready])
        answers[('GET', '/v1/appAssetLibraryVideos/')] = _Next(states)
        with mock.patch.object(asc.time, 'sleep'):
            code, sent, printed, _ = self.run_assets({'header.mp4': (3840, 1646)}, '--yes', answers=answers)
        self.assertEqual(code, 0, printed)
        self.assertIn('header.mp4: ready', printed)

    def test_a_reused_video_gets_its_opening_still_changed(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'header.mp4').write_bytes(b'0' * 64)
            size = (Path(folder) / 'header.mp4').stat().st_size
        answers = asset_answers([OPEN, LIVE], videos=[{'id': 'VID9', 'attributes': {
            'fileName': 'header.mp4', 'fileSize': size, 'state': 'PREPARE_FOR_SUBMISSION',
            'previewFrameTimeCode': '00:00:00:00'}}])
        code, sent, printed, _ = self.run_assets(
            {'header.mp4': (3840, 1646)}, '--poster', '00:00:05:00', '--yes', answers=answers)
        self.assertEqual(code, 0, printed)
        patches = [(u, k) for m, u, k in self.writes(sent) if m == 'PATCH']
        self.assertTrue(any(u.endswith('/v1/appAssetLibraryVideos/VID9')
                            and k['body']['data']['attributes'] == {'previewFrameTimeCode': '00:00:05:00'}
                            for u, k in patches), patches)
        self.assertFalse(any(u.endswith('/v1/appAssetLibraryVideos') for m, u, k in self.writes(sent)))


if __name__ == '__main__':
    unittest.main()
