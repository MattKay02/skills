"""Emulator screenshots that are safe to read back.

    python shot.py capture shots/home.png              # full size + a small copy to Read
    python shot.py shrink shots/pulled.png             # a small copy of a PNG you already have
    python shot.py set screens.txt .tmp-verify/ui/before --component com.example.app/.MainActivity --base https://example.com
    python shot.py sheet .tmp-verify/ui/before         # one picture of a folder
    python shot.py sheet .tmp-verify/ui/before .tmp-verify/ui/after   # each screen, before beside after

Every capture is saved twice: NAME.png at full size, for records and
before/after, and NAME.small.png, shrunk by a whole number so its long edge is
at most --max (1200 by default; a 1080x2400 phone becomes 540x1200, half
size). Read only the small one. Tap coordinates taken from it are multiplied by
the factor printed (x2 for half size) to get device pixels.

`capture` calls adb itself and keeps the bytes, so no shell redirect is
involved and it works the same from PowerShell and bash.

`set` opens each screen in a list by deep link and captures it. The list is one
screen per line, `name route`, with `scroll` after the route to swipe one
screen down before capturing. Lines starting with # are skipped:

    01-home        /
    02-settings    /settings
    03-settings-2  /settings  scroll

`sheet` writes sheet-<folder>.png beside the folder (more pages as
sheet-<folder>-2.png and so on), each page at most 2000px on a side.

Needs Pillow, and adb on the PATH for capture and set.
"""
import argparse
import math
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont, ImageOps

PNG = b'\x89PNG\r\n\x1a\n'
SHEET_MAX = 2000


def win_path(p):
    """Windows-native Python can't open Git Bash's /c/... paths. Git Bash rewrites a
    bare argument for you, but not a path built inside a script or a `python -c` string."""
    m = re.match(r'^/([a-zA-Z])/(.*)$', p)
    return f'{m.group(1).upper()}:/{m.group(2)}' if os.name == 'nt' and m else p


def natural(name):
    return [int(part) if part.isdigit() else part for part in re.split(r'(\d+)', name)]


def adb(serial):
    return ['adb'] + (['-s', serial] if serial else [])


def grab(serial):
    """The screen as PNG bytes. exec-out is raw; if it comes back wrong, go via the device."""
    run = subprocess.run(adb(serial) + ['exec-out', 'screencap', '-p'], capture_output=True)
    data = run.stdout
    if not data.startswith(PNG):
        subprocess.run(adb(serial) + ['shell', 'screencap', '-p', '/sdcard/_shot.png'], check=True)
        with tempfile.TemporaryDirectory() as tmp:
            local = os.path.join(tmp, 'shot.png')
            subprocess.run(adb(serial) + ['pull', '/sdcard/_shot.png', local], check=True, capture_output=True)
            with open(local, 'rb') as f:
                data = f.read()
        subprocess.run(adb(serial) + ['shell', 'rm', '/sdcard/_shot.png'], capture_output=True)
    if not data.startswith(PNG):
        sys.exit(f'adb did not return a PNG. {run.stderr.decode(errors="replace").strip()}')
    return data


def small_path(full):
    root, ext = os.path.splitext(full)
    return f'{root}.small{ext or ".png"}'


def shrink(full, max_edge):
    """Write the small copy beside `full`. Returns (path, factor, full size, small size)."""
    image = Image.open(full)
    factor = max(1, math.ceil(max(image.size) / max_edge))
    small = image.resize((image.width // factor, image.height // factor), Image.LANCZOS)
    out = small_path(full)
    small.save(out)
    return out, factor, image.size, small.size


def report(full, max_edge):
    out, factor, (w, h), (sw, sh) = shrink(full, max_edge)
    print(f'{full}  {w}x{h}  (keep; do not Read)')
    print(f'{out}  {sw}x{sh}  <- Read this one. Device px = small px x {factor}')


def save_capture(path, serial, max_edge):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(grab(serial))
    report(path, max_edge)


def device_size(serial):
    out = subprocess.run(adb(serial) + ['shell', 'wm', 'size'], capture_output=True, text=True).stdout
    sizes = re.findall(r'(\d+)x(\d+)', out)  # an override size, if set, is listed last
    if not sizes:
        sys.exit(f'Could not read the screen size from `adb shell wm size`: {out.strip()}')
    return tuple(int(n) for n in sizes[-1])


def open_link(serial, url, component):
    # One string for the device shell, with the URL quoted, so ? and & survive it.
    remote = f'am start -a android.intent.action.VIEW -d {shlex.quote(url)} -n {component}'
    run = subprocess.run(adb(serial) + ['shell', remote], capture_output=True, text=True)
    said = (run.stdout + run.stderr).strip()
    if run.returncode != 0 or 'Error' in said:
        sys.exit(f'Deep link failed for {url}:\n{said}')


def capture_set(args):
    screens = []
    with open(args.list, encoding='utf-8') as f:
        for line in f:
            parts = line.split('#', 1)[0].split()
            if parts:
                screens.append(parts)
    if not screens:
        sys.exit(f'No screens listed in {args.list}.')
    os.makedirs(args.out, exist_ok=True)
    width, height = device_size(args.serial)
    for parts in screens:
        name, route = parts[0], parts[1] if len(parts) > 1 else '/'
        url = args.base.rstrip('/') + '/' + route.lstrip('/')
        open_link(args.serial, url, args.component)
        time.sleep(args.wait)
        if 'scroll' in parts[2:]:
            x = str(width // 2)
            subprocess.run(adb(args.serial) + ['shell', 'input', 'swipe', x, str(height * 3 // 4), x, str(height // 4), '400'], check=True)
            time.sleep(1.5)
        save_capture(os.path.join(args.out, f'{name}.png'), args.serial, args.max)


def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow before 10.1
        return ImageFont.load_default()


def stills(folder):
    return {
        n: os.path.join(folder, n)
        for n in os.listdir(folder)
        if n.lower().endswith('.png') and not n.endswith('.small.png') and not n.startswith('sheet-')
    }


def sheet(args):
    folders = [os.path.normpath(d) for d in args.folders]
    found = [stills(d) for d in folders]
    names = sorted(set().union(*found), key=natural)
    if not names:
        sys.exit(f'No PNGs to put on a sheet in {", ".join(folders)}.')

    label_h, gap, th = 24, 6, 560
    first = Image.open(next(iter((found[0] or found[-1]).values())))
    tw = round(first.width * th / first.height)
    cell_w = len(folders) * tw + (len(folders) - 1) * 2
    cell_h = label_h + th
    columns = max(1, (SHEET_MAX + gap) // (cell_w + gap))
    rows = max(1, (SHEET_MAX + gap) // (cell_h + gap))
    per_page = columns * rows
    pages = [names[i:i + per_page] for i in range(0, len(names), per_page)]

    base = '-'.join(os.path.basename(d) for d in folders)
    out_dir = os.path.dirname(os.path.abspath(folders[0]))
    text = font(16)
    for p, page in enumerate(pages, 1):
        cols = min(columns, len(page))
        page_rows = -(-len(page) // cols)
        canvas = Image.new('RGB', (cols * (cell_w + gap) - gap, page_rows * (cell_h + gap) - gap), (40, 40, 40))
        draw = ImageDraw.Draw(canvas)
        for i, name in enumerate(page):
            x0 = (i % cols) * (cell_w + gap)
            y0 = (i // cols) * (cell_h + gap)
            draw.text((x0 + 4, y0 + 3), os.path.splitext(name)[0], fill=(255, 220, 0), font=text)
            for k, shots in enumerate(found):
                x = x0 + k * (tw + 2)
                if name in shots:
                    tile = ImageOps.contain(Image.open(shots[name]).convert('RGB'), (tw, th), Image.LANCZOS)
                    canvas.paste(tile, (x, y0 + label_h))
                else:
                    draw.rectangle([x, y0 + label_h, x + tw - 1, y0 + cell_h - 1], fill=(90, 30, 30))
                    draw.text((x + 8, y0 + label_h + 8), f'missing in\n{os.path.basename(folders[k])}', fill=(255, 255, 255), font=text)
        suffix = '' if len(pages) == 1 else f'-{p}'
        out = os.path.join(out_dir, f'sheet-{base}{suffix}.png')
        canvas.save(out)
        print(out, canvas.size, f'{len(page)} screens')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('capture', help='screenshot the device: full size + a small copy')
    p.add_argument('out')
    p = sub.add_parser('shrink', help='write a small copy of a PNG you already have')
    p.add_argument('png')
    p = sub.add_parser('set', help='open each listed screen by deep link and capture it')
    p.add_argument('list', help='a text file, one `name route [scroll]` per line')
    p.add_argument('out', help='folder for the captures, e.g. .tmp-verify/v2-ui/before')
    p.add_argument('--component', required=True, help='package/activity, e.g. com.example.app/.MainActivity')
    p.add_argument('--base', required=True, help='what each route is added to, e.g. https://example.com or myapp://app')
    p.add_argument('--wait', type=float, default=5, help='seconds to let each screen load (default 5)')
    p = sub.add_parser('sheet', help='one picture of a folder, or of two side by side')
    p.add_argument('folders', nargs='+', help='a folder, or a before and an after folder')
    for name, p in sub.choices.items():
        if name != 'sheet':
            p.add_argument('--max', type=int, default=1200, help='long edge of the small copy (default 1200)')
        if name in ('capture', 'set'):
            p.add_argument('--serial', help='adb device, e.g. emulator-5554, when more than one is attached')
    args = parser.parse_args()

    for key in ('out', 'png', 'list'):
        if getattr(args, key, None):
            setattr(args, key, win_path(getattr(args, key)))
    if args.command == 'capture':
        save_capture(args.out, args.serial, args.max)
    elif args.command == 'shrink':
        report(args.png, args.max)
    elif args.command == 'set':
        capture_set(args)
    else:
        args.folders = [win_path(d) for d in args.folders]
        if len(args.folders) > 2:
            sys.exit('sheet takes one folder, or two (before and after).')
        sheet(args)


if __name__ == '__main__':
    main()
