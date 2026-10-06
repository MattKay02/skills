"""Contact sheets, for checking a render by eye before anyone is shown it.

    python contact_sheet.py film out/reel.mp4                # a frame a second
    python contact_sheet.py film out/reel.mp4 --every 0.5 --zones reel
    python contact_sheet.py stills out/carousel/             # a folder of pictures, side by side
    python contact_sheet.py film out/logo.mp4 --ruler        # a line every 10%, to measure with

Writes sheet-<name>.png beside the input (or to --out) and prints its path.

A film's sheet is its frames in order, each stamped with its time. With
`--zones reel` each frame also carries lines for what a 9:16 platform covers
with its own buttons and caption, so a word that has strayed out of the clear
part shows at once. The lines are fractions of the frame, so any size works.

Needs Pillow, and ffmpeg and ffprobe on the PATH for films.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

# What a platform lays over an upright video, as fractions of the frame:
# everything above `top` and below `bottom` is trimmed on a profile grid or
# sits under the caption, and everything right of `right` is under buttons.
# Worked to in October 2026. Platforms move these; check before relying on them.
ZONES = {
    'reel': {'top': 240 / 1920, 'bottom': 1480 / 1920, 'right': 950 / 1080},
}


def natural(name):
    return [int(part) if part.isdigit() else part for part in re.split(r'(\d+)', name)]


def frames_of(film, every):
    probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', film],
        capture_output=True, text=True, check=True,
    )
    duration = float(json.loads(probe.stdout)['format']['duration'])
    shots, t = [], 0.0
    with tempfile.TemporaryDirectory() as tmp:
        while t < duration - 0.05:
            out = os.path.join(tmp, f'{int(t * 1000):08d}.png')
            subprocess.run(
                ['ffmpeg', '-loglevel', 'error', '-y', '-ss', f'{t}', '-i', film, '-vframes', '1', out],
                check=True,
            )
            shots.append((f'{t:.1f}s', Image.open(out).convert('RGB').copy()))
            t += every
    return shots, duration


def stills_of(folder):
    names = sorted(
        (n for n in os.listdir(folder) if n.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))),
        key=natural,
    )
    return [(os.path.splitext(n)[0], Image.open(os.path.join(folder, n)).convert('RGB')) for n in names]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('kind', choices=['film', 'stills'])
    parser.add_argument('source', help='a video file, or a folder of pictures')
    parser.add_argument('--every', type=float, default=1.0, help='seconds between frames of a film')
    parser.add_argument('--zones', choices=['none', *ZONES], default='none')
    parser.add_argument('--ruler', action='store_true', help='draw a line every 10% of the height')
    parser.add_argument('--scale', type=float, default=None, help='size of each tile, as a share of the original')
    parser.add_argument('--columns', type=int, default=12)
    parser.add_argument('--out')
    args = parser.parse_args()

    if args.kind == 'film':
        shots, duration = frames_of(args.source, args.every)
        note = f'{duration:.2f}s'
    else:
        shots = stills_of(args.source)
        note = 'stills'
    if not shots:
        sys.exit(f'Nothing to put on a sheet in {args.source}.')

    width, height = shots[0][1].size
    scale = args.scale or min(1.0, 560 / height if args.kind == 'film' else 680 / height)
    tw, th = int(width * scale), int(height * scale)
    columns = min(len(shots), args.columns)
    rows = -(-len(shots) // columns)
    gap = 4
    sheet = Image.new('RGB', (columns * (tw + gap) - gap, rows * (th + gap) - gap), (70, 70, 70))
    for i, (label, image) in enumerate(shots):
        tile = image.resize((tw, th), Image.LANCZOS)
        draw = ImageDraw.Draw(tile)
        if args.ruler:
            for tenth in range(1, 10):
                y = th * tenth / 10
                draw.line([(0, y), (tw, y)], fill=(90, 200, 255), width=1)
                draw.text((tw - 30, y + 2), f'{tenth * 10}%', fill=(90, 200, 255))
        if args.zones != 'none':
            zone = ZONES[args.zones]
            for y in (zone['top'], zone['bottom']):
                draw.line([(0, th * y), (tw, th * y)], fill=(255, 80, 80), width=1)
            draw.line([(tw * zone['right'], 0), (tw * zone['right'], th)], fill=(255, 80, 80), width=1)
        draw.text((6, 4), label, fill=(255, 255, 0))
        sheet.paste(tile, ((i % columns) * (tw + gap), (i // columns) * (th + gap)))

    name = os.path.splitext(os.path.basename(os.path.normpath(args.source)))[0]
    out = args.out or os.path.join(os.path.dirname(os.path.normpath(args.source)) or '.', f'sheet-{name}.png')
    sheet.save(out)
    print(out, sheet.size, f'{len(shots)} tiles', note)


if __name__ == '__main__':
    main()
