"""What the store scripts share: the project config and its guards, token
signing, and one small HTTP helper.

Standard library and `cryptography` only, so nothing else has to be
installed (`pip install cryptography` if it is missing).

The config is the permission boundary. One App Store Connect team key reaches
every app on the team, and one Play service account reaches every app it was
granted, so these scripts only ever name the apps listed in the project's
.store-release.json and refuse any other before a store is called. The keys
stay outside the repository: a key path that resolves inside the project is
refused, so a key cannot be committed by accident.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

CONFIG_NAME = '.store-release.json'
CONFIG_ENV = 'STORE_RELEASE_CONFIG'
SCRIPTS = Path(__file__).resolve().parent
CONNECT_DOC = SCRIPTS.parent / 'references' / 'connect.md'
EXAMPLE = SCRIPTS / 'example.store-release.json'

KEY_KINDS = {'app_store_connect': 'App Store Connect', 'google_play': 'Google Play'}
APP_FIELDS = ('name', 'ios', 'android', 'listing', 'screenshots', 'play_feature_graphic',
              'play_icon', 'creative', 'release_notes')
IOS_FIELDS = ('bundle_id',)
ANDROID_FIELDS = ('package', 'draft_until_published')
SCREENSHOT_FIELDS = ('ios', 'android')

# Apple's API answers an occasional 500 or 503 that clears on the next try.
# Only reads are retried: a write that failed may still have landed, and
# sending it again could do it twice.
RETRY_DELAYS = (2.0, 5.0)


class StoreError(Exception):
    """Something a store refused, or a config or key that is wrong, said plainly."""


def connect_doc() -> str:
    """Where the key set-up is explained, for error messages."""
    return f'references/connect.md in the mobile-store-release skill ({CONNECT_DOC})'


def check_lengths(fields: dict, limits: dict[str, int], where: str) -> None:
    """Refuse text over a store's limits, before anything is sent: a store
    refuses it anyway, and a refusal half way through leaves half a listing."""
    over = [f'{name} has {len(value)} characters (at most {limits[name]})'
            for name, value in fields.items()
            if name in limits and isinstance(value, str) and len(value) > limits[name]]
    if over:
        raise StoreError(f'{where}: {"; ".join(over)}. Shorten it; nothing was sent.')


# --- The config --------------------------------------------------------------


def _ignored(name: str) -> bool:
    """Keys starting with _ or $ are notes ("_comment", "$schema") and skipped."""
    return name.startswith(('_', '$'))


def _unknown(block: dict, allowed: tuple[str, ...]) -> list[str]:
    return [k for k in block if k not in allowed and not _ignored(k)]


def _within(path: Path, folder: Path) -> bool:
    """Whether [path] is [folder] or inside it, compared the way the file
    system compares names (case-insensitively on Windows)."""
    a = os.path.normcase(str(path.resolve()))
    b = os.path.normcase(str(folder.resolve()))
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:  # different drives
        return False


def git_work_tree(folder: Path) -> Path | None:
    """The git work tree holding [folder], found by its .git, if there is one."""
    folder = folder.resolve()
    for candidate in (folder, *folder.parents):
        if (candidate / '.git').exists():
            return candidate
    return None


def expand_key_path(value: str, root: Path) -> Path:
    """A key path as written in the config: ~ and environment variables
    expanded; a relative path starts at the config's folder (and is then
    refused for being inside it)."""
    path = Path(os.path.expandvars(os.path.expanduser(str(value))))
    return path if path.is_absolute() else root / path


@dataclass
class App:
    """One app from the config: what it is called on each store, and where
    its store files are. Paths are absolute; None when not configured."""

    key: str
    name: str
    bundle_id: str | None
    package: str | None
    draft_until_published: bool
    listing: Path | None
    screenshots_ios: Path | None
    screenshots_android: Path | None
    play_feature_graphic: Path | None
    play_icon: Path | None
    creative: Path | None
    release_notes: Path | None
    config: Config = field(repr=False, compare=False)

    def require(self, platform: str) -> None:
        """Refuse a platform the app has no block for in the config."""
        if platform == 'ios' and not self.bundle_id:
            raise StoreError(f'{self.key} has no "ios" block in {self.config.path}: '
                             'it is not on the App Store as far as this config knows.')
        if platform == 'android' and not self.package:
            raise StoreError(f'{self.key} has no "android" block in {self.config.path}: '
                             'it is not on Google Play as far as this config knows.')

    def shown(self, path: Path) -> str:
        """A path as a plan names it: from the config's folder when inside it."""
        try:
            return path.resolve().relative_to(self.config.root.resolve()).as_posix()
        except ValueError:
            return str(path)


@dataclass
class Config:
    path: Path
    root: Path
    keys: dict[str, Path] | None
    apps: dict[str, App] = field(default_factory=dict)

    def app(self, key: str) -> App:
        """The app by its key. Any other is refused here, before a store is
        called: the config is the list of what these scripts may touch."""
        if key not in self.apps:
            raise StoreError(f'No app "{key}" in {self.path}. It lists: '
                             f'{", ".join(sorted(self.apps))}. Only these can be touched.')
        return self.apps[key]

    def outside_repository(self, path: Path, what: str) -> None:
        """Refuse a key that resolves inside the config's folder, the git
        work tree holding it, or any other git work tree: a key in a
        repository is one `git add` from being published, and that includes
        a dotfiles repository kept in the home folder."""
        places = [(self.root, "the config's folder")]
        tree = git_work_tree(self.root)
        if tree is not None:
            places.append((tree, 'the git work tree holding the config'))
        for folder, label in places:
            if _within(path, folder):
                raise StoreError(
                    f'{what} ({path}) is inside {label} ({folder}). Keys must live outside '
                    'the repository so they are never committed: move it, for example to '
                    f'~/.store-keys/<project>/, and point the config there. See {connect_doc()}.')
        other = git_work_tree(path.parent)
        if other is not None:
            raise StoreError(
                f'{what} ({path}) is inside a git work tree ({other}). Keys must live where no '
                'repository contains them, and a dotfiles repository in the home folder counts: '
                'move it to a folder no .git sits above, and point the config there. '
                f'See {connect_doc()}.')

    def key_file(self, kind: str) -> Path:
        """The key file for one store, checked: listed, outside the
        repository, and present. Its contents are never printed."""
        label = KEY_KINDS[kind]
        if self.keys is None:
            raise StoreError(
                f'{self.path} has no "keys". Add one naming key files outside the repository:\n'
                '  "keys": {\n'
                '    "app_store_connect": "~/.store-keys/<project>/asc.json",\n'
                '    "google_play": "~/.store-keys/<project>/play-service-account.json"\n'
                '  }\n'
                f'How to make each key: {connect_doc()}.')
        path = self.keys.get(kind)
        if path is None:
            raise StoreError(
                f'{self.path} "keys" has no "{kind}": add the path to the {label} key file '
                f'(outside the repository). How to make one: {connect_doc()}.')
        self.outside_repository(path, f'The {label} key (keys.{kind})')
        if not path.is_file():
            raise StoreError(f'No {label} key at {path} (keys.{kind} in {self.path}). '
                             f'How to make one: {connect_doc()}.')
        return path


def find_config(explicit: str | None = None, start: Path | None = None) -> Path:
    """The config: --config, else $STORE_RELEASE_CONFIG, else the nearest
    .store-release.json from the current folder up."""
    for value, source in ((explicit, '--config'), (os.environ.get(CONFIG_ENV), CONFIG_ENV)):
        if value:
            path = Path(os.path.expanduser(value))
            if not path.is_file():
                raise StoreError(f'No config at {path} (from {source}).')
            return path.resolve()
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        candidate = folder / CONFIG_NAME
        if candidate.is_file():
            return candidate
    raise StoreError(
        f'No {CONFIG_NAME} in {here} or any folder above it. Create one at the project root '
        f'(start from {EXAMPLE}), or pass --config PATH, or set {CONFIG_ENV}.')


def load_config(path: Path) -> Config:
    """Read and check the config. Anything misspelt is refused by name, so a
    typo cannot quietly drop a file from an upload."""
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except ValueError as e:
        raise StoreError(f'{path} is not valid JSON: {e}') from None
    if not isinstance(raw, dict):
        raise StoreError(f'{path} should hold a JSON object with "keys" and "apps".')
    unknown = _unknown(raw, ('keys', 'apps'))
    if unknown:
        raise StoreError(f'{path} has {", ".join(unknown)}, which this does not take: '
                         'the top level holds "keys" and "apps".')
    root = path.parent

    keys = raw.get('keys')
    resolved: dict[str, Path] | None = None
    if keys is not None:
        if not isinstance(keys, dict):
            raise StoreError(f'"keys" in {path} should be an object.')
        unknown = _unknown(keys, tuple(KEY_KINDS))
        if unknown:
            raise StoreError(f'"keys" in {path} has {", ".join(unknown)}: it takes '
                             'app_store_connect and google_play.')
        resolved = {k: expand_key_path(v, root) for k, v in keys.items()
                    if k in KEY_KINDS and v}

    apps = raw.get('apps')
    if not isinstance(apps, dict) or not apps:
        raise StoreError(f'{path} lists no apps: add an "apps" object (see {EXAMPLE.name}).')
    config = Config(path=path, root=root, keys=resolved)
    for key, block in apps.items():
        if _ignored(key):
            continue
        config.apps[key] = _app(key, block, config)
    return config


def _app(key: str, block, config: Config) -> App:
    where = f'apps.{key} in {config.path}'
    if not isinstance(block, dict):
        raise StoreError(f'{where} should be an object.')
    unknown = _unknown(block, APP_FIELDS)
    if unknown:
        raise StoreError(f'{where} has {", ".join(unknown)}, which this does not take. '
                         f'It takes: {", ".join(APP_FIELDS)}.')

    def sub(name: str, allowed: tuple[str, ...]) -> dict | None:
        value = block.get(name)
        if value is None:
            return None
        if not isinstance(value, dict):
            raise StoreError(f'{where}: "{name}" should be an object.')
        extra = _unknown(value, allowed)
        if extra:
            raise StoreError(f'{where}: "{name}" has {", ".join(extra)}; it takes {", ".join(allowed)}.')
        return value

    ios = sub('ios', IOS_FIELDS)
    android = sub('android', ANDROID_FIELDS)
    shots = sub('screenshots', SCREENSHOT_FIELDS) or {}
    if ios is not None and not ios.get('bundle_id'):
        raise StoreError(f'{where}: "ios" needs "bundle_id".')
    if android is not None and not android.get('package'):
        raise StoreError(f'{where}: "android" needs "package".')
    if ios is None and android is None:
        raise StoreError(f'{where} needs an "ios" block, an "android" block, or both.')

    def rel(value) -> Path | None:
        return (config.root / str(value)).resolve() if value else None

    return App(
        key=key,
        name=str(block.get('name') or key),
        bundle_id=(ios or {}).get('bundle_id'),
        package=(android or {}).get('package'),
        draft_until_published=bool((android or {}).get('draft_until_published', False)),
        listing=rel(block.get('listing')),
        screenshots_ios=rel(shots.get('ios')),
        screenshots_android=rel(shots.get('android')),
        play_feature_graphic=rel(block.get('play_feature_graphic')),
        play_icon=rel(block.get('play_icon')),
        creative=rel(block.get('creative')),
        release_notes=rel(block.get('release_notes')),
        config=config,
    )


# --- Signing -----------------------------------------------------------------


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _segment(obj: dict) -> str:
    return b64url(json.dumps(obj, separators=(',', ':')).encode('utf-8'))


def es256_jwt(header: dict, claims: dict, key: ec.EllipticCurvePrivateKey) -> str:
    """A JWT signed ES256, as App Store Connect asks: the signature is r and s
    as two 32-byte integers, not the DER `cryptography` returns."""
    signing_input = f'{_segment(header)}.{_segment(claims)}'
    der = key.sign(signing_input.encode('ascii'), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return f'{signing_input}.{b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))}'


def rs256_jwt(claims: dict, key) -> str:
    """A JWT signed RS256, as Google's token endpoint asks."""
    signing_input = f'{_segment({"alg": "RS256", "typ": "JWT"})}.{_segment(claims)}'
    signature = key.sign(signing_input.encode('ascii'), padding.PKCS1v15(), hashes.SHA256())
    return f'{signing_input}.{b64url(signature)}'


# --- HTTP --------------------------------------------------------------------


def _redact(url: str) -> str:
    """The address without its query: upload URLs carry signatures."""
    parts = urllib.parse.urlsplit(url)
    return f'{parts.scheme}://{parts.netloc}{parts.path}'


def _summarise(detail: str) -> str:
    """The store's own words for what went wrong, without the noise."""
    try:
        body = json.loads(detail)
    except ValueError:
        return detail.strip()[:500]
    if not isinstance(body, dict):
        return detail.strip()[:500]
    if isinstance(body.get('errors'), list):  # Apple
        return '; '.join(
            ' '.join(str(e.get(k)) for k in ('title', 'detail') if e.get(k))
            for e in body['errors']
        )
    if isinstance(body.get('error'), dict):  # Google
        return str(body['error'].get('message') or body['error'])
    if 'error_description' in body:  # Google's token endpoint
        return f"{body.get('error')}: {body['error_description']}"
    return detail.strip()[:500]


def _retrying(method: str, url: str, code: int, delay: float) -> None:
    print(f'  ({method} {_redact(url)} answered {code}; trying again in {delay:g} s)',
          file=sys.stderr, flush=True)


def call(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    expect_json: bool = True,
):
    """One request. A refusal raises StoreError with the store's own reason;
    no token or key ever appears in what is raised or printed. A GET that
    meets a 5xx is tried again, twice at most, after a short wait."""
    sent = dict(headers or {})
    if token:
        sent['Authorization'] = f'Bearer {token}'
    payload = data
    if body is not None:
        payload = json.dumps(body).encode('utf-8')
        sent.setdefault('Content-Type', 'application/json')
    retries = len(RETRY_DELAYS) if method == 'GET' else 0
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, data=payload, method=method, headers=sent)
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                raw = response.read()
            break
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode('utf-8', 'replace')
            except OSError:
                detail = ''
            if e.code >= 500 and attempt < retries:
                _retrying(method, url, e.code, RETRY_DELAYS[attempt])
                time.sleep(RETRY_DELAYS[attempt])
                continue
            raise StoreError(f'{method} {_redact(url)} refused ({e.code}): {_summarise(detail)}') from None
        except urllib.error.URLError as e:
            raise StoreError(f'{method} {_redact(url)} failed: {e.reason}') from None
        except (TimeoutError, ConnectionError) as e:
            raise StoreError(f'{method} {_redact(url)} failed: {e}') from None
    if not raw or not expect_json:
        return None
    return json.loads(raw)


USER_AGENT = 'mobile-store-release-preflight/1.0 (+https://github.com/MattKay02/skills)'


def fetch_status(url: str, timeout: float = 20) -> tuple[int | None, str]:
    """Open a public page the way a reviewer would: a plain GET with no
    credentials, following redirects. Returns the final status (None when it
    could not be reached) and a short detail."""
    request = urllib.request.Request(url, method='GET', headers={
        'User-Agent': USER_AGENT, 'Accept': 'text/html,application/xhtml+xml,*/*'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.geturl()
    except urllib.error.HTTPError as e:
        return e.code, str(e.reason)
    except urllib.error.URLError as e:
        return None, str(e.reason)
    except (ValueError, OSError) as e:
        return None, str(e)
