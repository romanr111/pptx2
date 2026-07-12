#!/usr/bin/env python3
"""Bake a decorative image into a slide-seamless PNG (pptx-designer's
"Seamless image integration" rule made executable).

A solid-background source (a light "studio" JPG on a white slide, a dark
render on a black slide) shows its rectangular edge if placed as-is. This
produces a derivative that:
  - crops to the target panel's aspect ratio (anchored so foreign objects /
    dark corners fall outside the visible area),
  - repaints the background to the slide colour (--bg white|black) using a
    luminance+saturation mask that protects the colourful/metallic/skin
    subject, so no tonal block remains,
  - feathers the chosen internal edges (--feather left,top,...) with a
    directional smooth-step alpha ramp so the object dissolves into the slide,
  - leaves the other edges hard, to be OVERSCANNED off-slide in the spec
    (box.allow_offslide_bleed) so they are clipped by the canvas, not seen.

Place the output with fit:"stretch" at a box whose aspect == --aspect and
whose non-feathered edges bleed past the slide. Always confirm in the render.

Example (a right-side hero on a white slide, box aspect 3942000/7298000,
left edge internal, other edges overscanned off-slide):
  seamless_hero.py in.jpg out.png --aspect 0.5402 --bg white \
    --feather left --crop center
"""
import argparse
from pathlib import Path
import numpy as np
from PIL import Image
Image.MAX_IMAGE_PIXELS = None


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def bake(src, out, aspect, bg="white", crop="center", crop_frac=None,
         flip=False, feather=("left",), feather_frac=0.16, bw=1500,
         whiten_lum=(165, 216), sat_gate=(0.06, 0.17)):
    keep_alpha = bg == "none"
    im = Image.open(src).convert("RGBA" if keep_alpha else "RGB")
    iw, ih = im.size
    tw = ih * aspect
    if tw <= iw:  # target narrower -> crop width
        if crop_frac is not None:
            x0 = (iw - tw) * float(crop_frac)
        else:
            x0 = {"right": iw - tw, "left": 0}.get(crop, (iw - tw) / 2)
        im = im.crop((int(x0), 0, int(x0 + tw), ih))
    else:         # target taller -> crop height
        th = iw / aspect
        y0 = {"bottom": ih - th, "top": 0}.get(crop, (ih - th) / 2)
        im = im.crop((0, int(y0), iw, int(y0 + th)))
    if flip:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    bh = round(bw / aspect)
    im = im.resize((bw, bh), Image.LANCZOS)
    arr = np.asarray(im).astype(np.float64)
    src_alpha = arr[..., 3] if keep_alpha else None
    if keep_alpha:
        arr = arr[..., :3]

    lum = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    mx, mn = arr.max(2), arr.min(2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1.0), 0.0)
    subj_protect = 1.0 - smoothstep(sat_gate[0], sat_gate[1], sat)  # 1=bg, 0=subject
    if bg == "white":
        w = (smoothstep(whiten_lum[0], whiten_lum[1], lum) * subj_protect)[..., None]
        arr = arr * (1 - w) + 255.0 * w
    elif bg == "black":
        # darken low-contrast light-to-mid background toward true black
        w = (smoothstep(whiten_lum[1], whiten_lum[0], lum) * subj_protect)[..., None]
        arr = arr * (1 - w)
    rgb = np.clip(arr, 0, 255).astype(np.uint8)

    # start from the source's own alpha (transparent PNG) or fully opaque
    alpha = src_alpha.copy() if src_alpha is not None else np.full((bh, bw), 255.0)
    if "left" in feather:
        f = max(1, int(bw * feather_frac)); r = smoothstep(0, f, np.arange(bw))
        alpha *= r[None, :]
    if "right" in feather:
        f = max(1, int(bw * feather_frac)); r = smoothstep(0, f, (bw - 1 - np.arange(bw)))
        alpha *= r[None, :]
    if "top" in feather:
        f = max(1, int(bh * feather_frac)); r = smoothstep(0, f, np.arange(bh))
        alpha *= r[:, None]
    if "bottom" in feather:
        f = max(1, int(bh * feather_frac)); r = smoothstep(0, f, (bh - 1 - np.arange(bh)))
        alpha *= r[:, None]
    Image.fromarray(np.dstack([rgb, alpha.astype(np.uint8)]), "RGBA").save(out)
    print(f"wrote {out}  ({bw}x{bh}, bg={bg}, feather={','.join(feather)})")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--aspect", type=float, required=True, help="target box cx/cy")
    ap.add_argument("--bg", choices=["white", "black", "none"], default="white")
    ap.add_argument("--crop", choices=["center", "left", "right", "top", "bottom"],
                    default="center")
    ap.add_argument("--crop-frac", type=float, default=None,
                    help="horizontal crop anchor 0..1 (overrides --crop for width crops)")
    ap.add_argument("--flip", action="store_true", help="mirror horizontally")
    ap.add_argument("--feather", default="left",
                    help="comma list of internal edges to dissolve, e.g. left,top")
    ap.add_argument("--feather-frac", type=float, default=0.16)
    args = ap.parse_args()
    bake(str(args.src), str(args.out), args.aspect, bg=args.bg, crop=args.crop,
         crop_frac=args.crop_frac, flip=args.flip,
         feather=tuple(s.strip() for s in args.feather.split(",") if s.strip()),
         feather_frac=args.feather_frac)


if __name__ == "__main__":
    main()
