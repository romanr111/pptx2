#!/usr/bin/env python3
"""Derive build inputs for the title slide from the project assets.

Reads:
  assets/expected_result/1st_slide{1,2,3}.jpg  (progressive animation states)
  assets/images/extracted_man_transparent.png  (speaker cut-out)
  assets/Шаблон*.pptx                          (conference template; logo + theme)
  assets/slides_text.rtf                       (slide copy)

Writes to output/work/:
  background_title.png  full-bleed slide background (face art + spheres, man erased)
  man_cropped.png       speaker photo cropped to its alpha bounding box
  logo_black.png        template logo recolored black, cropped to alpha bbox
  geometry.json         element placements in EMU + measured text metrics
  content.json          title lines / speaker name / credential bullets
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

W, H = 2560, 1440                 # canonical pixel space for all measurements
EMU_PER_PX = 12192000 / W          # == 6858000 / 1440 == 4762.5
PROJECT_ROOT = Path(__file__).resolve().parents[4]
ASSETS = PROJECT_ROOT / "assets"
WORK = PROJECT_ROOT / "output" / "work"

sys.path.insert(0, str(PROJECT_ROOT / ".claude" / "skills" / "pptx-deck" / "scripts"))
from imaging import alpha_bbox, bbox_of, dilate, line_bands, new_ink  # noqa: E402


def load_shot(n: int) -> np.ndarray:
    path = ASSETS / "expected_result" / f"1st_slide{n}.jpg"
    img = Image.open(path).convert("RGB").resize((W, H), Image.LANCZOS)
    return np.asarray(img).astype(np.int16)


def px_rect_to_emu(x0, y0, x1, y1):
    return {
        "x": round(x0 * EMU_PER_PX), "y": round(y0 * EMU_PER_PX),
        "cx": round((x1 - x0) * EMU_PER_PX), "cy": round((y1 - y0) * EMU_PER_PX),
        "px": [int(x0), int(y0), int(x1), int(y1)],
    }


def find_man_placement(shot: np.ndarray, man: Image.Image):
    """Locate the speaker cut-out in the screenshot via masked template match.

    The cut-out is the same photograph that was placed on the slide, so a
    grayscale search over position and scale recovers the exact placement.
    Returns (x0, y0, drawn_w, drawn_h) in canvas px; the drawn rect may
    extend below the canvas (the photo bleeds off the slide bottom).
    """
    shot_g = shot.mean(axis=2)
    man_rgb = Image.fromarray(np.asarray(man.convert("RGB")).mean(axis=2).astype(np.uint8))
    man_a = Image.fromarray((np.asarray(man.split()[-1]) > 128).astype(np.uint8) * 255)

    cache = {}

    def scaled(scale):
        if scale not in cache:
            w = max(2, int(round(man.width * scale)))
            h = max(2, int(round(man.height * scale)))
            m = np.asarray(man_rgb.resize((w, h))).astype(np.float64)
            a = np.asarray(man_a.resize((w, h))) > 128
            cache[scale] = (m, a, w, h)
        return cache[scale]

    def score_at(scale, x0, y0):
        m, a, w, h = scaled(scale)
        vis_h, vis_w = min(h, H - y0), min(w, W - x0)
        if vis_h <= 0 or vis_w <= 0 or x0 < 0 or y0 < 0:
            return np.inf
        aa = a[:vis_h, :vis_w]
        if aa.sum() < 500:
            return np.inf
        patch = shot_g[y0:y0 + vis_h, x0:x0 + vis_w]
        return float(np.abs(patch - m[:vis_h, :vis_w])[aa].mean())

    best = (np.inf, None)
    for scale in [round(s, 3) for s in np.linspace(1.1, 1.8, 29)]:
        for y0 in range(410, 510, 6):
            for x0 in range(160, 460, 6):
                s = score_at(scale, x0, y0)
                if s < best[0]:
                    best = (s, (scale, x0, y0))
    scale, bx, by = best[1]
    for ds in np.linspace(-0.049, 0.049, 9):  # refine
        for y0 in range(by - 9, by + 10, 3):
            for x0 in range(bx - 9, bx + 10, 3):
                s = score_at(round(scale + ds, 4), x0, y0)
                if s < best[0]:
                    best = (s, (round(scale + ds, 4), x0, y0))
    scale, x0, y0 = best[1]
    _, _, w, h = scaled(scale)
    return best[0], (x0, y0, w, h)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    shot1, shot2, shot3 = load_shot(1), load_shot(2), load_shot(3)

    # --- speaker photo placement: template-match the cut-out in state 1
    man_img = Image.open(ASSETS / "images" / "extracted_man_transparent.png").convert("RGBA")
    man_img = man_img.crop(alpha_bbox(man_img))
    match_err, (mx0, my0, man_w, man_h) = find_man_placement(shot1.astype(np.float64), man_img)
    man_rect = {
        "x": round(mx0 * EMU_PER_PX), "y": round(my0 * EMU_PER_PX),
        "cx": round(man_w * EMU_PER_PX), "cy": round(man_h * EMU_PER_PX),
        "px": [mx0, my0, mx0 + man_w, my0 + man_h],
        "match_err": round(match_err, 2),
    }

    # --- logo placement: black ink new in state 2 (top-left quadrant)
    logo_mask = new_ink(shot2, shot1, window=(120, 40, 1250, 620))
    lx0, ly0, lx1, ly1 = bbox_of(logo_mask)
    logo_rect = px_rect_to_emu(lx0, ly0, lx1, ly1)

    # --- text block: dark ink new in state 3 (right column)
    text_mask = new_ink(shot3, shot2, window=(1100, 0, W, H))
    tx0, ty0, tx1, ty1 = bbox_of(text_mask)
    bands = line_bands(text_mask)

    # classify bands: first 5 = title lines, next = speaker name, rest = bullets
    if len(bands) < 7:
        raise SystemExit(f"expected >=7 text line bands, got {len(bands)}: {bands}")
    title_bands, name_band, bullet_bands = bands[:5], bands[5], bands[6:]
    title_top, title_bottom = title_bands[0][0], title_bands[-1][1]
    title_pitch = (title_bands[-1][0] - title_bands[0][0]) / (len(title_bands) - 1)
    # left edge of the text column (from title lines only, name/bullets share it)
    tcol_x0 = int(np.nonzero(text_mask[title_bands[0][0]:title_bands[-1][1]].any(axis=0))[0].min())

    def band_caps_pt(band):  # cap-height of an uppercase band -> points
        return (band[1] - band[0]) * 540 / H  # 540pt slide height

    pt_per_px = 540 / H
    metrics = {
        "text_col_left_px": tcol_x0,
        "title": {
            "top_px": title_top, "bottom_px": title_bottom,
            "pitch_pt": round(title_pitch * pt_per_px, 1),
            # second-smallest band height: bands with Ц/Щ descenders overshoot
            # the cap height, so the small bands are the true caps
            "cap_pt": round(sorted(band_caps_pt(b) for b in title_bands)[1], 1),
            "bands_px": title_bands,
        },
        "name": {"band_px": name_band, "cap_pt": round(band_caps_pt(name_band), 1)},
    }
    # group bullet line bands into items: the gap between items is clearly
    # larger than the line pitch inside an item; split at the midpoint
    pitches = np.diff([b[0] for b in bullet_bands])
    split_at = (pitches.min() + pitches.max()) / 2
    metrics["bullets"] = {
        "bands_px": bullet_bands,
        "line_pitch_px": round(float(np.median(pitches[pitches < split_at])), 1) if (pitches < split_at).any() else float(pitches.min()),
        "item_pitch_px": round(float(np.median(pitches[pitches >= split_at])), 1),
        "item_tops_px": [bullet_bands[0][0]] + [
            b[0] for prev, b in zip(bullet_bands, bullet_bands[1:])
            if b[0] - prev[0] >= split_at
        ],
    }

    # --- ink colors (median of dark diff pixels per region)
    def region_color(mask, y0, y1):
        # 15th percentile per channel: stroke cores, not anti-aliased edges
        m = mask.copy(); m[:y0] = False; m[y1:] = False
        px = shot3[m]
        px = px[px.sum(axis=1) < 360]
        return "%02X%02X%02X" % tuple(int(c) for c in np.percentile(px, 15, axis=0))
    title_color = region_color(text_mask, title_top, title_bottom)
    bullet_color = region_color(text_mask, bullet_bands[0][0], bullet_bands[-1][1])

    # --- background plate: state 1 with the man erased. Erase through his
    # dilated silhouette (not the bbox) so nearby spheres survive intact.
    from PIL import ImageFilter
    sil = man_img.split()[-1].resize((man_w, man_h)).point(lambda v: 255 if v > 8 else 0)
    sil = sil.filter(ImageFilter.MaxFilter(13))
    bg = Image.fromarray(shot1.astype(np.uint8))
    white = Image.new("RGB", sil.size, (255, 255, 255))
    bg.paste(white, (mx0, my0), sil)
    bg.save(WORK / "background_title.png")

    # --- speaker cut-out cropped to visible pixels
    man_img.save(WORK / "man_cropped.png")

    # --- logo: lifted from state-2 screenshot. The template ships only a
    # white horizontal logo (image24) and a black *stacked* variant (image1),
    # neither matching the kerning of the black horizontal logo the expected
    # design uses, so the screenshot is the only faithful source.
    # Alpha comes from the grayscale (anti-aliased edges survive), restricted
    # to the new-ink mask so the man's hair below the logo is not swept in.
    lift = dilate(logo_mask, 5)
    gray = shot2.mean(axis=2)
    alpha = np.where(lift, np.clip(255 - gray, 0, 255), 0).astype(np.uint8)
    logo_rgba = np.zeros((H, W, 4), np.uint8)
    logo_rgba[..., 3] = alpha
    Image.fromarray(logo_rgba[ly0:ly1, lx0:lx1]).save(WORK / "logo_black.png")
    logo_rect = px_rect_to_emu(lx0, ly0, lx1, ly1)

    # --- slide copy from the rtf
    txt = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", str(ASSETS / "slides_text.rtf")],
        capture_output=True, text=True, check=True).stdout
    blocks = [b.strip("\n") for b in re.split(r"\n{2,}", txt) if b.strip()]
    title_lines = [l.strip() for l in blocks[0].splitlines() if l.strip()]
    name = blocks[1].strip()
    bullets, cur = [], None
    for line in "\n".join(blocks[2:]).splitlines():
        if not line.strip():
            continue
        if line.lstrip().startswith("-"):
            if cur: bullets.append(cur)
            cur = [line.lstrip()[1:].strip()]
        else:
            cur.append(line.strip())
    if cur: bullets.append(cur)

    geometry = {
        "slide_emu": [12192000, 6858000],
        "canvas_px": [W, H],
        "background": px_rect_to_emu(0, 0, W, H),
        "man": man_rect,
        "logo": logo_rect,
        "text_block": px_rect_to_emu(tx0, ty0, tx1, ty1),
        "metrics": metrics,
        "colors": {"title": title_color, "bullets": bullet_color},
    }
    (WORK / "geometry.json").write_text(json.dumps(geometry, indent=2))
    content = {"title_lines": title_lines, "name": name, "bullets": bullets}
    (WORK / "content.json").write_text(json.dumps(content, ensure_ascii=False, indent=2))

    print(json.dumps(geometry, indent=2))
    print(json.dumps(content, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
