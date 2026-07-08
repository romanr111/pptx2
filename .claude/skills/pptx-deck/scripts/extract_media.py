#!/usr/bin/env python3
"""Materialize one template-embedded media file as a real on-disk PNG, so a
spec's image `asset` field can reference it.

`out/template_style.json`'s `logo_candidates` (and any other template media)
are only known by their in-archive path (e.g. "ppt/media/image24.png") --
nothing else pulls one out of the .pptx zip onto disk.

Usage:
  extract_media.py <template.pptx> <ppt/media/imageN.png> <out.png> [--recolor dark|light]

--recolor fills the image's RGB channels uniformly black (dark) or white
(light) while preserving its existing alpha channel, so a logo candidate's
ink color can be flipped to suit the background it's placed on (e.g. the
template's only horizontal wordmark is light_ink/white -- unusable as-is on
a light slide).
"""
import argparse
import sys
import zipfile
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def extract(template_path: Path, media_path: str, out_path: Path, recolor: str = None):
    with zipfile.ZipFile(template_path) as z:
        data = z.read(media_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if recolor is None:
        out_path.write_bytes(data)
        return out_path

    import io
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    r, g, b, a = img.split()
    fill = 0 if recolor == "dark" else 255
    solid = Image.new("L", img.size, fill)
    Image.merge("RGBA", (solid, solid, solid, a)).save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("template", type=Path, help="path to the template .pptx")
    ap.add_argument("media_path", help="in-archive path, e.g. ppt/media/image24.png")
    ap.add_argument("out", type=Path, help="output PNG path")
    ap.add_argument("--recolor", choices=["dark", "light"], default=None,
                     help="fill RGB uniformly black/white, keep alpha")
    args = ap.parse_args()

    out_path = extract(args.template, args.media_path, args.out, args.recolor)
    print("wrote", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
