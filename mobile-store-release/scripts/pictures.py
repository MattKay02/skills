"""Store pictures, checked on disk: format, pixel size, alpha, counts and
upload order. Local only: nothing here touches the network or a key.

    python store.py pictures <app> [--ios|--android]

The App Store's screenshots are laid out as
`<screenshots.ios>/<DISPLAY_TYPE>/*.png` (APP_IPHONE_67/, APP_IPAD_PRO_3GEN_129/,
...), or as PNGs directly in `<screenshots.ios>/`, whose display type is read
from their pixel size. Google Play's are `<screenshots.android>/*.png` for the
phone, with optional `sevenInch/` and `tenInch/` folders for tablets.

Pictures upload in file name order, so name them 01-home.png, 02-plan.png,
...: two digits keep 10 after 09 rather than after 1.

What this cannot do is read the text in a picture. It ends by saying so: the
agent has to look at every picture for price words and for claims the app
does not back up, which is what App Review 2.3.7 and Play's metadata policy
reject most often.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from common import App, StoreError

IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg')
CONTENT_TYPES = {'PNG': 'image/png', 'JPEG': 'image/jpeg'}

# --- The App Store's display types -------------------------------------------
# Apple's screenshot sizes per display type (portrait; landscape is the same
# swapped), from its screenshot specifications. Apple's API names predate its
# marketing sizes: APP_IPHONE_67 is the 6.9-inch and 6.7-inch slot, and
# APP_IPAD_PRO_3GEN_129 the 13-inch iPad. Today an iPhone app needs the
# 6.9-inch set (or 6.5-inch), an iPad app the 13-inch set; Apple scales them
# down for smaller devices.
DISPLAY_SIZES: dict[str, tuple[str, tuple[tuple[int, int], ...]]] = {
    # 1260x2736 is the newest 6.9-inch size and the least certain here: if
    # App Store Connect refuses one, preflight shows the set as FAILED.
    'APP_IPHONE_67': ('iPhone 6.9-inch and 6.7-inch', ((1320, 2868), (1290, 2796), (1260, 2736))),
    'APP_IPHONE_65': ('iPhone 6.5-inch', ((1284, 2778), (1242, 2688))),
    'APP_IPHONE_61': ('iPhone 6.3-inch and 6.1-inch', ((1206, 2622), (1179, 2556), (1170, 2532))),
    'APP_IPHONE_58': ('iPhone 5.8-inch', ((1125, 2436),)),
    'APP_IPHONE_55': ('iPhone 5.5-inch', ((1242, 2208),)),
    'APP_IPHONE_47': ('iPhone 4.7-inch', ((750, 1334),)),
    'APP_IPHONE_40': ('iPhone 4-inch', ((640, 1136), (640, 1096))),
    'APP_IPHONE_35': ('iPhone 3.5-inch', ((640, 960), (640, 920))),
    'APP_IPAD_PRO_3GEN_129': ('iPad 13-inch', ((2064, 2752), (2048, 2732))),
    'APP_IPAD_PRO_3GEN_11': ('iPad 11-inch', ((1668, 2420), (1668, 2388), (1640, 2360), (1488, 2266))),
    'APP_IPAD_PRO_129': ('iPad Pro 12.9-inch (2nd generation)', ((2048, 2732),)),
    'APP_IPAD_105': ('iPad 10.5-inch', ((1668, 2224),)),
    'APP_IPAD_97': ('iPad 9.7-inch', ((1536, 2048), (1536, 2008), (768, 1024), (768, 1004))),
}
# Display types this tool uploads to but does not size-check: the Apple Watch
# ones, which go on an iOS version for an app with a watch app. Mac, Apple TV
# and Vision Pro screenshots belong to versions of those platforms, which this
# tool does not open, so their folders are refused.
OTHER_DISPLAY_TYPES = (
    'APP_WATCH_ULTRA', 'APP_WATCH_SERIES_10', 'APP_WATCH_SERIES_7', 'APP_WATCH_SERIES_4',
    'APP_WATCH_SERIES_3',
)
DISPLAY_TYPES = (*DISPLAY_SIZES, *OTHER_DISPLAY_TYPES)
IPHONE_REQUIRED = ('APP_IPHONE_67', 'APP_IPHONE_65')
APPLE_MAX_PER_SET = 10


def _both_ways(sizes) -> set[tuple[int, int]]:
    return {s for w, h in sizes for s in ((w, h), (h, w))}


# A size read from a loose picture names one display type: the first that
# takes it, in the order above (so 2048x2732 is the 13-inch iPad, not the
# older 12.9-inch slot).
_INFER: dict[tuple[int, int], str] = {}
for _type, (_label, _sizes) in DISPLAY_SIZES.items():
    for _size in _both_ways(_sizes):
        _INFER.setdefault(_size, _type)


def accepted_sizes() -> str:
    """Apple's sizes as one line per display type, for a refusal."""
    return '; '.join(f"{t} ({label}): " + ', '.join(f'{w}x{h}' for w, h in sizes)
                     for t, (label, sizes) in DISPLAY_SIZES.items()) + ' (or landscape)'


def infer_display_type(width: int, height: int) -> str | None:
    return _INFER.get((width, height))


# --- Google Play -------------------------------------------------------------
PLAY_GROUPS = {'': 'phoneScreenshots', 'sevenInch': 'sevenInchScreenshots',
               'tenInch': 'tenInchScreenshots'}
PLAY_MAX_PER_TYPE = 8
PLAY_MIN_PHONE = 2
PLAY_SHOT_MAX_BYTES = 8 * 1024 * 1024
PLAY_FEATURE = (1024, 500)
PLAY_FEATURE_MAX_BYTES = 15 * 1024 * 1024
PLAY_ICON = (512, 512)
PLAY_ICON_MAX_BYTES = 1024 * 1024

# --- Reading pictures --------------------------------------------------------

PNG_COLOURS = {0: 'greyscale', 2: 'RGB', 3: 'a palette', 4: 'greyscale with alpha', 6: 'RGBA'}
_JPEG_FRAMES = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


@dataclass(frozen=True)
class Facts:
    format: str               # 'PNG' or 'JPEG'
    width: int
    height: int
    colour: str               # 'RGB', 'RGBA', 'greyscale', 'a palette', 'CMYK', ...
    alpha: bool               # an alpha channel, or a transparent colour (tRNS)
    depth: int                # bits per channel
    png_colour_type: int | None = None
    transparent_colour: bool = False
    bytes: int = 0

    @property
    def content_type(self) -> str:
        return CONTENT_TYPES[self.format]


def read_png(path: Path) -> Facts:
    """Width, height and colour from the PNG's IHDR, and whether a tRNS chunk
    (a transparent colour) comes before the image data, where PNG puts it."""
    with path.open('rb') as source:
        if source.read(8) != b'\x89PNG\r\n\x1a\n':
            raise StoreError(f'{path.name} is not a PNG.')
        head = source.read(8)
        if len(head) < 8:
            raise StoreError(f'{path.name} has no PNG header (IHDR).')
        length, kind = struct.unpack('>I4s', head)
        if kind != b'IHDR' or length < 13:
            raise StoreError(f'{path.name} has no PNG header (IHDR).')
        width, height, depth, colour = struct.unpack('>IIBB', source.read(10))
        source.seek(length - 10 + 4, 1)  # the rest of IHDR, and its CRC
        transparent = False
        while True:
            head = source.read(8)
            if len(head) < 8:
                break
            length, kind = struct.unpack('>I4s', head)
            if kind == b'IDAT':
                break
            if kind == b'tRNS':
                transparent = True
            source.seek(length + 4, 1)
    return Facts('PNG', width, height, PNG_COLOURS.get(colour, f'PNG colour type {colour}'),
                 colour in (4, 6) or transparent, depth, colour, transparent,
                 path.stat().st_size)


def read_jpeg(path: Path) -> Facts:
    """Width, height and components from the first frame header (SOFn)."""
    with path.open('rb') as source:
        if source.read(2) != b'\xff\xd8':
            raise StoreError(f'{path.name} is not a JPEG.')
        while True:
            byte = source.read(1)
            if not byte:
                break
            if byte != b'\xff':
                continue
            marker = source.read(1)
            while marker == b'\xff':
                marker = source.read(1)
            if not marker:
                break
            m = marker[0]
            if m == 0x01 or m == 0xD8 or 0xD0 <= m <= 0xD7:
                continue  # markers with no length
            if m in (0xD9, 0xDA):
                break  # the end, or the scan, before any frame header
            size = source.read(2)
            if len(size) < 2:
                break
            length = struct.unpack('>H', size)[0]
            if m in _JPEG_FRAMES:
                depth, height, width, components = struct.unpack('>BHHB', source.read(6))
                colour = {1: 'greyscale', 3: 'RGB', 4: 'CMYK'}.get(components, f'{components} components')
                return Facts('JPEG', width, height, colour, False, depth, None, False,
                             path.stat().st_size)
            source.seek(length - 2, 1)
    raise StoreError(f'{path.name} has no JPEG frame header.')


def read_image(path: Path) -> Facts:
    """PNG or JPEG, told apart by their first bytes rather than the name."""
    with path.open('rb') as source:
        start = source.read(8)
    if start.startswith(b'\x89PNG'):
        return read_png(path)
    if start.startswith(b'\xff\xd8'):
        return read_jpeg(path)
    raise StoreError(f'{path.name} is neither a PNG nor a JPEG.')


def _images(folder: Path) -> list[Path]:
    """The pictures directly in [folder], in upload order: by file name, as
    Python sorts strings, the same on every system."""
    return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES),
                  key=lambda p: p.name)


def _natural(name: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', name)]


# --- Layouts, for the uploads ------------------------------------------------


def ios_layout(folder: Path) -> tuple[dict[str, list[Path]], list[str], dict[str, str]]:
    """The App Store screenshot sets in [folder]: {display type: files in
    upload order}, the problems that stop an upload, and how each set's type
    was found ('folder' or 'pixel size')."""
    sets: dict[str, list[Path]] = {}
    how: dict[str, str] = {}
    problems: list[str] = []
    if not folder.is_dir():
        return sets, [f'No folder at {folder}.'], how
    for sub in sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.name):
        if sub.name.startswith('.'):
            continue
        if sub.name not in DISPLAY_TYPES:
            problems.append(f'{sub.name}/ is not a display type this tool knows. Name each folder '
                            f'after one of: {", ".join(DISPLAY_TYPES)}. (If Apple added a new one, '
                            'add it to DISPLAY_SIZES in pictures.py.)')
            continue
        files = _images(sub)
        if files:
            sets[sub.name] = files
            how[sub.name] = 'folder'
    loose: dict[str, list[Path]] = {}
    for path in _images(folder):
        try:
            facts = read_image(path)
        except StoreError as e:
            problems.append(str(e))
            continue
        display = infer_display_type(facts.width, facts.height)
        if display is None:
            problems.append(f'{path.name} is {facts.width}x{facts.height}, which is no App Store '
                            f'screenshot size. Apple takes: {accepted_sizes()}.')
            continue
        loose.setdefault(display, []).append(path)
    for display, files in loose.items():
        if display in sets:
            problems.append(f'{", ".join(p.name for p in files)} (read as {display} from their size) '
                            f'and the {display}/ folder both fill {display}: keep one.')
            continue
        sets[display] = files
        how[display] = 'pixel size'
    for display, files in sets.items():
        if len(files) > APPLE_MAX_PER_SET:
            problems.append(f'{display} has {len(files)} screenshots: the App Store takes '
                            f'{APPLE_MAX_PER_SET} at most per display type.')
    if not sets and not problems:
        problems.append(f'No screenshots in {folder}: put PNGs in it, or in folders named '
                        'after display types (APP_IPHONE_67/, APP_IPAD_PRO_3GEN_129/, ...), '
                        'named 01-home.png, 02-plan.png, ... in the order they should show.')
    ordered = {t: sets[t] for t in DISPLAY_TYPES if t in sets}
    return ordered, problems, how


def ios_sets(folder: Path) -> dict[str, list[Path]]:
    """The sets to upload, or a StoreError naming every problem in the layout."""
    sets, problems, _ = ios_layout(folder)
    if problems:
        raise StoreError('\n  '.join(['The App Store screenshots cannot go up as they are:', *problems]))
    return sets


def android_groups(folder: Path) -> dict[str, list[Path]]:
    """{Play image type: files in upload order}: the phone screenshots in
    [folder], and tablets in its sevenInch/ and tenInch/ folders."""
    if not folder.is_dir():
        raise StoreError(f'No folder at {folder}.')
    groups: dict[str, list[Path]] = {}
    for sub, kind in PLAY_GROUPS.items():
        where = folder / sub if sub else folder
        if where.is_dir():
            files = _images(where)
            if files:
                groups[kind] = files
    if 'phoneScreenshots' not in groups:
        raise StoreError(f'No phone screenshots (PNG or JPEG) in {folder}.')
    return groups


# --- The check ---------------------------------------------------------------

SEVERITY_ORDER = {'BLOCK': 0, 'WARN': 1, 'OK': 2, 'MANUAL': 3}


@dataclass
class Row:
    target: str
    path: Path
    facts: Facts | None
    verdict: str = 'OK'


@dataclass
class Report:
    rows: list[Row] = field(default_factory=list)
    findings: list[tuple[str, str]] = field(default_factory=list)

    def add(self, severity: str, text: str, row: Row | None = None) -> None:
        self.findings.append((severity, text))
        if row is not None and SEVERITY_ORDER[severity] < SEVERITY_ORDER[row.verdict]:
            row.verdict = severity

    def blocks(self) -> list[str]:
        return [text for severity, text in self.findings if severity == 'BLOCK']

    def render(self, title: str) -> list[str]:
        lines = [title]
        if self.rows:
            header = ('target', 'file', 'format', 'pixels', 'colour', 'verdict')
            table = [header] + [
                (r.target, r.path.name,
                 r.facts.format if r.facts else '?',
                 f'{r.facts.width}x{r.facts.height}' if r.facts else '?',
                 r.facts.colour if r.facts else '?',
                 r.verdict)
                for r in self.rows]
            widths = [max(len(row[i]) for row in table) for i in range(len(header))]
            lines.append('')
            lines += ['  ' + '  '.join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip()
                      for row in table]
        lines.append('')
        for severity in ('BLOCK', 'WARN', 'OK'):
            lines += [f'  {severity:<6} {text}' for s, text in self.findings if s == severity]
        lines.append(f'  {"MANUAL":<6} {MANUAL_LOOK}')
        counts = {s: sum(1 for f, _ in self.findings if f == s) for s in ('BLOCK', 'WARN', 'OK')}
        lines += ['', f"Summary: {counts['BLOCK']} BLOCK, {counts['WARN']} WARN, {counts['OK']} OK, "
                      '1 MANUAL']
        return lines


MANUAL_LOOK = (
    'This cannot read the text in a picture. View every picture yourself before it goes up: '
    'no price words ("Free", a currency sign or amount, "trial", "% off", "sale") '
    '[App Review 2.3.7, Play metadata policy], and no claim or feature that is not in the '
    'app as built.')


def _picture(report: Report, target: str, path: Path) -> Row:
    """Read one picture into a row; an unreadable one is a BLOCK."""
    try:
        facts = read_image(path)
    except StoreError as e:
        row = Row(target, path, None)
        report.rows.append(row)
        report.add('BLOCK', f'{target} {path.name}: {e}', row)
        return row
    row = Row(target, path, facts)
    report.rows.append(row)
    named = path.suffix.lower()
    if (facts.format == 'PNG') != (named == '.png'):
        report.add('WARN', f'{target} {path.name} is a {facts.format} named {named}: '
                           'rename it to match.', row)
    return row


def _colour(report: Report, row: Row, store: str, alpha_ok: bool = False) -> None:
    """No alpha for the stores' screenshots and graphics; 8-bit RGB is safest."""
    facts = row.facts
    if facts is None:
        return
    name = f'{row.target} {row.path.name}'
    if facts.alpha and not alpha_ok:
        what = ('a transparent colour (tRNS chunk)' if facts.transparent_colour
                and facts.png_colour_type not in (4, 6) else f'an alpha channel ({facts.colour})')
        report.add('BLOCK', f'{name} has {what}: {store} refuses alpha. Flatten it onto a '
                            'background and save it as RGB.', row)
    elif facts.colour == 'CMYK':
        report.add('BLOCK', f'{name} is CMYK: save it as RGB.', row)
    elif facts.colour not in ('RGB', 'RGBA'):
        report.add('WARN', f'{name} is {facts.colour}, not 24-bit RGB: save it as RGB to be safe.', row)
    elif facts.depth not in (8,):
        report.add('WARN', f'{name} has {facts.depth} bits per channel: save it as 8-bit.', row)


def _order(report: Report, label: str, files: list[Path]) -> None:
    names = [p.name for p in files]
    natural = sorted(names, key=_natural)
    if names != natural:
        report.add('WARN', f'{label}: uploads go in file name order, which is {", ".join(names)}; '
                           f'the numbers say {", ".join(natural)}. Pad the numbers (01-, 02-, ...) '
                           'so the order is the one intended.')


def _check_ios(report: Report, folder: Path, app: App) -> None:
    sets, problems, how = ios_layout(folder)
    if not folder.is_dir():
        problems = [f'No folder at {app.shown(folder)} (screenshots.ios).']
    for problem in problems:
        report.add('BLOCK', f'App Store: {problem}')
    for display, files in sets.items():
        label, sizes = DISPLAY_SIZES.get(display, (display, ()))
        allowed = _both_ways(sizes)
        for path in files:
            row = _picture(report, display, path)
            if row.facts is None:
                continue
            if sizes and (row.facts.width, row.facts.height) not in allowed:
                report.add('BLOCK', f'{display} {path.name} is {row.facts.width}x{row.facts.height}: '
                                    f'{label} takes ' + ', '.join(f'{w}x{h}' for w, h in sizes)
                                    + ' (or landscape).', row)
            elif not sizes:
                report.add('WARN', f'{display} {path.name}: this tool does not know the sizes for '
                                   f'{display}, so its size is not checked.', row)
            _colour(report, row, 'the App Store')
        _order(report, f'App Store {display}', files)
        if len(files) <= APPLE_MAX_PER_SET:
            report.add('OK', f'App Store {display} ({label}, by {how[display]}): {len(files)} '
                             f'screenshot{"s" if len(files) != 1 else ""} (1 to {APPLE_MAX_PER_SET}), '
                             f'in this order: {", ".join(p.name for p in files)}')
    if sets and not any(t in sets for t in IPHONE_REQUIRED):
        report.add('WARN', 'App Store: no 6.9-inch (APP_IPHONE_67) or 6.5-inch (APP_IPHONE_65) set. '
                           'An iPhone app needs one; an iPad-only app can ignore this.')


def _check_android(report: Report, app: App) -> None:
    folder = app.screenshots_android
    if folder is None:
        report.add('WARN', f'Google Play: no screenshots.android in the config for {app.key}.')
    elif not folder.is_dir():
        report.add('BLOCK', f'Google Play: no folder at {app.shown(folder)} (screenshots.android).')
    else:
        for sub, kind in PLAY_GROUPS.items():
            where = folder / sub if sub else folder
            files = _images(where) if where.is_dir() else []
            for path in files:
                row = _picture(report, kind, path)
                if row.facts is None:
                    continue
                w, h = row.facts.width, row.facts.height
                short, long = min(w, h), max(w, h)
                if short < 320 or long > 3840 or long > 2 * short:
                    report.add('BLOCK', f'{kind} {path.name} is {w}x{h}: Play takes each side from '
                                        '320 to 3840 px, the long side at most twice the short.', row)
                if row.facts.bytes > PLAY_SHOT_MAX_BYTES:
                    report.add('BLOCK', f'{kind} {path.name} is over 8 MB, Play\'s limit.', row)
                _colour(report, row, 'Google Play')
            if files:
                _order(report, f'Google Play {kind}', files)
            if len(files) > PLAY_MAX_PER_TYPE:
                report.add('BLOCK', f'Google Play {kind}: {len(files)} pictures; Play takes '
                                    f'{PLAY_MAX_PER_TYPE} at most.')
            elif kind == 'phoneScreenshots' and len(files) < PLAY_MIN_PHONE:
                report.add('BLOCK', f'Google Play {kind}: {len(files)} in {app.shown(where)}; Play needs '
                                    f'at least {PLAY_MIN_PHONE}.')
            elif files:
                report.add('OK', f'Google Play {kind}: {len(files)} ({"2" if kind == "phoneScreenshots" else "0"} '
                                 f'to {PLAY_MAX_PER_TYPE}), in this order: {", ".join(p.name for p in files)}')

    for target, path, size, limit, alpha_ok in (
            ('featureGraphic', app.play_feature_graphic, PLAY_FEATURE, PLAY_FEATURE_MAX_BYTES, False),
            ('icon', app.play_icon, PLAY_ICON, PLAY_ICON_MAX_BYTES, True)):
        setting = 'play_feature_graphic' if target == 'featureGraphic' else 'play_icon'
        if path is None:
            report.add('WARN', f'Google Play {target}: no {setting} in the config, so screenshots '
                               'leaves the one on Play as it is.')
            continue
        if not path.is_file():
            report.add('WARN', f'Google Play {target}: {setting} names {app.shown(path)}, which does not exist: '
                               'screenshots leaves the one on Play as it is.')
            continue
        row = _picture(report, target, path)
        if row.facts is None:
            continue
        if (row.facts.width, row.facts.height) != size:
            report.add('BLOCK', f'{target} {path.name} is {row.facts.width}x{row.facts.height}: '
                                f'Play takes exactly {size[0]}x{size[1]}.', row)
        if target == 'icon' and row.facts.format != 'PNG':
            report.add('BLOCK', f'icon {path.name} is a {row.facts.format}: Play takes a 32-bit PNG.', row)
        if row.facts.bytes > limit:
            report.add('BLOCK', f'{target} {path.name} is {row.facts.bytes // 1024} KB: Play takes '
                                f'{limit // 1024} KB at most.', row)
        _colour(report, row, 'Google Play', alpha_ok=alpha_ok)
        if row.verdict == 'OK':
            report.add('OK', f'Google Play {target}: {path.name}, {row.facts.width}x{row.facts.height} '
                             f'{row.facts.format} {row.facts.colour}')


def check(app: App, ios: bool, android: bool) -> Report:
    """Every picture the screenshots command would upload, checked on disk."""
    report = Report()
    if ios:
        if app.screenshots_ios is None:
            report.add('WARN', f'App Store: no screenshots.ios in the config for {app.key}.')
        else:
            _check_ios(report, app.screenshots_ios, app)
    if android:
        _check_android(report, app)
    return report
