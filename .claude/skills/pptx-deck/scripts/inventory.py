#!/usr/bin/env python3
"""Facts layer: walk assets/ and the template .pptx, write out/assets.json
and out/template_style.json. Cheap heuristics only -- classification/role
guesses are labelled with a confidence and "unknown" is allowed; a human or
the (future) designer skill resolves ambiguity by looking at the thumbnails
this script also produces, not by this script guessing harder.

Usage:
  inventory.py --template path/to/template.pptx [--renderer docker|host]
                          writes out/assets.json + out/template_style.json
  inventory.py --no-thumbnails   skip the (slow) template render pass
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import template_style  # noqa: E402

from common import PROJECT_ROOT, textutil_to_txt  # noqa: E402
ASSETS = PROJECT_ROOT / "assets"
OUT = PROJECT_ROOT / "out"

SLIDE_ASPECT = 16 / 9
FONT_EXTS = {".ttf", ".otf"}
TEXT_EXTS = {".rtf", ".txt", ".docx", ".doc"}


# ---------------------------------------------------------------- images --

def alpha_bbox_frac(alpha, thr=8):
    mask = alpha > thr
    if not mask.any():
        return 0.0
    ys, xs = np.nonzero(mask)
    area = (xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1)
    return area / (alpha.shape[0] * alpha.shape[1])


def watermark_signal(rgb):
    """Faint gray overlay tiled across an otherwise-white background --
    catches stock-illustration copyright watermarks without OCR. Calibrated
    against this project's kenhub.com-watermarked illustrations: their
    near-white pixels are ~14-16% non-pure-white (anti-aliased watermark
    ink); clean cutout/photo backgrounds measure ~6%.
    """
    gray = rgb.mean(axis=2)
    near_white = gray > 236
    pure_white = gray > 251
    cov = float(near_white.mean())
    if near_white.sum() == 0:
        return False, 0.0, cov
    faint_ratio = float((near_white & ~pure_white).sum()) / float(near_white.sum())
    suspected = cov > 0.15 and faint_ratio > 0.08
    return suspected, round(faint_ratio, 4), round(cov, 4)


def dominant_colors(rgb, k=3):
    img = Image.fromarray(rgb.astype(np.uint8)).convert("RGB")
    small = img.resize((64, 64))
    quant = small.quantize(colors=k, method=Image.MEDIANCUT)
    palette = quant.getpalette()[: k * 3]
    counts = sorted(quant.getcolors(), reverse=True)
    return ["%02X%02X%02X" % tuple(palette[c[1] * 3: c[1] * 3 + 3]) for c in counts]


def classify_image(path: Path):
    img = Image.open(path)
    w, h = img.size
    mode = img.mode
    rgba = img.convert("RGBA")
    arr = np.asarray(rgba)
    alpha = arr[..., 3]
    rgb = arr[..., :3]
    has_alpha = mode in ("RGBA", "LA") or "transparency" in img.info
    transparent_frac = round(float((alpha < 250).mean()), 3) if has_alpha else 0.0
    bbox_frac = alpha_bbox_frac(alpha) if has_alpha else 1.0
    aspect = round(w / h, 3)
    watermarked, faint_ratio, white_cov = watermark_signal(rgb.astype(np.float64))

    label, confidence = "unknown", 0.3
    if has_alpha and transparent_frac > 0.02:
        if 0.5 <= aspect <= 1.0 and h >= w and max(w, h) >= 400:
            label, confidence = "portrait_cutout", 0.85
        elif max(w, h) < 400:
            label, confidence = "logo", 0.4
        else:
            label, confidence = "content_illustration", 0.5
    else:
        if abs(aspect - SLIDE_ASPECT) < 0.05 and max(w, h) >= 1200:
            label, confidence = "background_art", 0.8
        elif 0.55 <= aspect <= 0.85 and max(w, h) < 1000:
            label, confidence = "photo", 0.55
        elif 0.85 <= aspect <= 1.15 and max(w, h) >= 1000:
            label, confidence = "content_illustration", 0.6
        else:
            label, confidence = "unknown", 0.3

    return {
        "file": str(path.relative_to(PROJECT_ROOT)),
        "size": [w, h],
        "mode": mode,
        "has_alpha": has_alpha,
        "transparent_frac": transparent_frac,
        "alpha_bbox_coverage": round(bbox_frac, 3),
        "aspect": aspect,
        "classification": label,
        "confidence": confidence,
        "dominant_colors": dominant_colors(rgb),
        "watermark_suspected": watermarked,
        "watermark_signal": {"faint_ratio": faint_ratio, "near_white_coverage": white_cov},
    }


def inventory_images():
    """Scan all of assets/ (except fonts/) for images, not just assets/images/.

    Previously only assets/images/ was scanned, so images placed from
    assets/designer_extracted/ (template molecule visuals, logo marks,
    etc.) were invisible to the inventory -- watermark/duplicate checks
    silently skipped them.
    """
    if not ASSETS.is_dir():
        return []
    out = []
    for p in sorted(ASSETS.rglob("*")):
        if "fonts" in p.parts:
            continue
        if p.suffix.lower() in (".png", ".jpg", ".jpeg"):
            out.append(classify_image(p))
    return out


# ----------------------------------------------------------------- fonts --

NAME_IDS = {1: "family", 2: "subfamily", 4: "full_name", 16: "typo_family", 17: "typo_subfamily"}


def font_facts(path: Path):
    tt = TTFont(str(path), lazy=True, fontNumber=0)
    name = tt["name"]
    facts = {nid: name.getDebugName(nid) for nid in NAME_IDS}
    weight = tt["OS/2"].usWeightClass if "OS/2" in tt else None
    italic = bool(tt["OS/2"].fsSelection & 0x1) if "OS/2" in tt else None
    return {
        "file": str(path.relative_to(PROJECT_ROOT)),
        "family": facts[1],
        "subfamily": facts[2],
        "full_name": facts[4],
        "typographic_family": facts[16],
        "typographic_subfamily": facts[17],
        "weight_class": weight,
        "italic": italic,
    }


def guess_role_from_folder(folder_name: str):
    low = folder_name.lower()
    if "загол" in low or "heading" in low:
        return "heading"
    if "текст" in low or "body" in low or "основн" in low:
        return "body"
    return None


def inventory_fonts(themes=None):
    themes = themes or []
    fonts_dir = ASSETS / "fonts"
    if not fonts_dir.is_dir():
        return {"fonts": [], "font_roles": {}}
    fonts = []
    naming_trap_flags = []
    for p in sorted(fonts_dir.rglob("*")):
        if p.suffix.lower() not in FONT_EXTS:
            continue
        try:
            f = font_facts(p)
        except Exception as e:
            fonts.append({"file": str(p.relative_to(PROJECT_ROOT)), "error": str(e)})
            continue
        f["folder_role_guess"] = guess_role_from_folder(str(p.relative_to(fonts_dir)))
        fonts.append(f)
        if f["family"] and f["typographic_family"] and f["family"] != f["typographic_family"]:
            naming_trap_flags.append(
                f"{f['file']}: legacy family '{f['family']}' != typographic family "
                f"'{f['typographic_family']}' -- renderers using the legacy name table "
                f"(id 1) won't group this with its family unless you reference "
                f"'{f['family']}' exactly")

    # authoritative role mapping: match discovered families against each of
    # the template's themes (not just the first one -- this template alone
    # has 3), falling back to folder-name guesses. A theme only "counts" if
    # assets/fonts actually contains a font for it; picking by evidence
    # avoids silently trusting file-name order (theme1.xml isn't always the
    # brand theme) when a template ships more than one theme.
    families = {f["family"] for f in fonts if f.get("family")}

    def match_family(theme_font):
        if not theme_font:
            return None
        core = theme_font.split()[0]
        matches = sorted({fam for fam in families if fam.split()[0] == core})
        return matches[0] if matches else None

    theme_matches = []
    for t in themes:
        heading = match_family(t.get("major_font"))
        body = match_family(t.get("minor_font"))
        if heading or body:
            theme_matches.append({
                "theme": t.get("name") or t.get("file"),
                "heading": heading, "body": body,
            })

    chosen = theme_matches[0] if theme_matches else None
    heading_family = chosen["heading"] if chosen else None
    body_family = chosen["body"] if chosen else None
    font_roles = {
        "heading": heading_family or next(
            (f["family"] for f in fonts if f.get("folder_role_guess") == "heading"), None),
        "body": body_family or next(
            (f["family"] for f in fonts if f.get("folder_role_guess") == "body"), None),
        "source": "template_theme_match" if chosen else "folder_name_guess",
        "theme_used": chosen["theme"] if chosen else None,
    }
    if len(theme_matches) > 1:
        font_roles["ambiguous_theme_matches"] = theme_matches
    return {"fonts": fonts, "font_roles": font_roles, "naming_trap_flags": naming_trap_flags}


# ------------------------------------------------------------------ text --

def convert_to_txt(path: Path) -> str:
    return textutil_to_txt(path)


def parse_text_blocks(raw: str):
    import re
    blocks = [b.strip("\n") for b in re.split(r"\n{2,}", raw) if b.strip()]
    out = []
    for b in blocks:
        lines = [l for l in b.splitlines() if l.strip()]
        if not lines:
            continue
        letters = "".join(c for c in b if c.isalpha())
        all_caps = bool(letters) and letters == letters.upper()
        bullet_lines = sum(1 for l in lines if l.lstrip().startswith(("-", "•", "*")))
        out.append({
            "text": b,
            "line_count": len(lines),
            "all_caps": all_caps,
            "bullet_marker_lines": bullet_lines,
            "looks_like_bullet_list": bullet_lines >= max(1, len(lines) - 1) and len(lines) > 1,
        })
    return out


def inventory_text():
    out = []
    for p in sorted(ASSETS.rglob("*")):
        if p.suffix.lower() not in TEXT_EXTS or p.is_dir():
            continue
        try:
            raw = convert_to_txt(p)
        except subprocess.CalledProcessError as e:
            out.append({"file": str(p.relative_to(PROJECT_ROOT)), "error": str(e)})
            continue
        out.append({
            "file": str(p.relative_to(PROJECT_ROOT)),
            "blocks": parse_text_blocks(raw),
        })
    return out


# ------------------------------------------------------------------ main --

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=template_style.DEFAULT_TEMPLATE,
                        help="production template to inventory")
    parser.add_argument("--no-thumbnails", action="store_true",
                        help="skip the slow template render pass")
    parser.add_argument("--renderer", choices=("docker", "host"), default="docker",
                        help="thumbnail renderer; docker is the delivery default")
    args = parser.parse_args()
    template_path = args.template.resolve()
    OUT.mkdir(parents=True, exist_ok=True)

    print("extracting template style guide...")
    style = template_style.extract(template_path, with_thumbnails=not args.no_thumbnails,
                                   renderer=args.renderer)
    (OUT / "template_style.json").write_text(json.dumps(style, ensure_ascii=False, indent=2))
    print("wrote", OUT / "template_style.json")
    census = style.get("media_census", [])
    if census:
        print(f"media census: {len(census)} template images -> "
              f"{style.get('media_census_sheet', 'out/media_census.png')} "
              f"(view every tile before designing; ranking is a hint, not a filter)")

    print("classifying images...")
    images = inventory_images()
    print("reading fonts...")
    fonts = inventory_fonts(themes=style["themes"])
    print("parsing text...")
    text = inventory_text()

    assets = {"images": images, "fonts": fonts["fonts"], "font_roles": fonts["font_roles"],
              "font_naming_trap_flags": fonts["naming_trap_flags"], "text": text}
    (OUT / "assets.json").write_text(json.dumps(assets, ensure_ascii=False, indent=2))
    print("wrote", OUT / "assets.json")

    print()
    print(f"images: {len(images)} "
          f"({sum(1 for i in images if i['watermark_suspected'])} watermark-suspected)")
    print(f"fonts: {len(fonts['fonts'])} files, "
          f"{len(fonts['naming_trap_flags'])} legacy-name/typographic-name mismatches")
    print(f"font_roles: {fonts['font_roles']}")
    print(f"text files parsed: {len(text)}")
    print(f"template consistency flags: {len(style['consistency_flags'])}")


if __name__ == "__main__":
    sys.exit(main())
