#!/usr/bin/env python3
"""Render a spec's per-state snapshot decks and compare each against hand
captured expected screenshots (assets/expected_result/1st_slide{n}.jpg).

This is the title-slide regression fixture check (Phase 0): it knows the
title slide's specific region layout (speaker photo, logo, text column) the
same way render_compare.py did. A future slide's spec would need its own
verify script, or this one generalized once a second reference-checked slide
exists -- premature to abstract further with only one fixture in hand.

Writes to output/compare/:
  state{n}.png        LibreOffice render at 2560x1440
  side_state{n}.png   expected (top) vs render (bottom) strip
Prints per-region RMSE (0-255; <=12 is a close visual match, jpeg noise floor
is ~4-6). Exit code 0 = all checks pass.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imaging import line_bands, new_ink  # noqa: E402
from render import render  # noqa: E402

from common import PROJECT_ROOT
STATES = PROJECT_ROOT / "output" / "states" / "title_slide"
COMPARE = PROJECT_ROOT / "output" / "compare"
EXPECTED = PROJECT_ROOT / "assets" / "expected_result"
SPEC = PROJECT_ROOT / "specs" / "title_slide.spec.json"
W, H = 2560, 1440
EMU_PER_PX = 12192000 / W


def box_to_px(box):
    x0 = round(box["x"] / EMU_PER_PX)
    y0 = round(box["y"] / EMU_PER_PX)
    x1 = round((box["x"] + box["cx"]) / EMU_PER_PX)
    y1 = round((box["y"] + box["cy"]) / EMU_PER_PX)
    return (x0, y0, x1, y1)


def tile_rmse(exp: np.ndarray, got: np.ndarray, box, search=20):
    """Best-shift RMSE of one tile (translation only)."""
    x0, y0, x1, y1 = box
    ref = got[y0:y1, x0:x1]
    best = np.inf
    for dy in range(-search, search + 1, 2):
        for dx in range(-search, search + 1, 2):
            cand = exp[y0 + dy:y1 + dy, x0 + dx:x1 + dx]
            r = ((ref - cand) ** 2).mean()
            best = min(best, r)
    return float(np.sqrt(best))


def region_rmse(exp: np.ndarray, got: np.ndarray, box, search=20, tile=200):
    """Mean of per-tile best-shift RMSEs.

    The expected screenshots drift in scale by ~0.3% between captures, which
    a single translation cannot absorb over a large region; per-tile
    alignment can, while local content differences still register.
    """
    x0, y0, x1, y1 = box
    x0, y0 = max(x0, search), max(y0, search)
    x1, y1 = min(x1, W - search), min(y1, H - search)
    scores = []
    for ty in range(y0, y1, tile):
        for tx in range(x0, x1, tile):
            tx1, ty1 = min(tx + tile, x1), min(ty + tile, y1)
            if (tx1 - tx) < 60 or (ty1 - ty) < 60:  # skip slivers
                continue
            scores.append(tile_rmse(exp, got, (tx, ty, tx1, ty1), search))
    return float(np.mean(scores)) if scores else 0.0


def global_prealign(exp: np.ndarray, got: np.ndarray, search=60):
    """Coarse whole-image shift of `exp` onto `got` (downsampled search)."""
    e = exp[::4, ::4].mean(axis=2)
    g = got[::4, ::4].mean(axis=2)
    s = search // 4
    h, w = g.shape
    ref = g[s:h - s, s:w - s]
    best = (np.inf, 0, 0)
    for dy in range(-s, s + 1):
        for dx in range(-s, s + 1):
            cand = e[s + dy:h - s + dy, s + dx:w - s + dx]
            r = ((ref - cand) ** 2).mean()
            if r < best[0]:
                best = (r, dx, dy)
    _, dx, dy = best
    return np.roll(exp, (-dy * 4, -dx * 4), axis=(0, 1)), (dx * 4, dy * 4)


def merge_bands(bands, min_gap=10):
    """Merge nearly-touching line bands (diacritics render as separate bands
    in the sharper image)."""
    out = []
    for b in bands:
        if out and b[0] - out[-1][1] < min_gap:
            out[-1] = (out[-1][0], b[1])
        else:
            out.append(tuple(b))
    return out


def text_structure_issues(exp3, exp2, got3, got2):
    """Compare the text block line-by-line instead of by pixels: the art
    behind the text drifts nonlinearly between the hand-taken captures, so
    pixel RMSE cannot separate text errors from capture artifacts.

    The render text mask is exact (state3 - state2 renders differ only by
    text). The expected mask is conservative: over dark art it loses ink, so
    it is checked for *coverage* by the render mask rather than equality.
    """
    got_mask = np.abs(got3.astype(np.int16) - got2.astype(np.int16)).sum(axis=2) > 90
    got_mask[:, :1100] = False
    exp_ink = new_ink(exp3.astype(np.int16), exp2.astype(np.int16), (1100, 0, W, H))
    eb, gb = merge_bands(line_bands(exp_ink)), merge_bands(line_bands(got_mask))
    if len(eb) != len(gb):
        return [f"line count: render {len(gb)} vs expected {len(eb)}"]

    got_near = np.asarray(
        Image.fromarray(got_mask.astype(np.uint8) * 255).filter(
            ImageFilter.MaxFilter(11))) > 0

    def left_edge(mask, band):
        return int(np.nonzero(mask[band[0]:band[1]].any(axis=0))[0].min())

    issues = []
    for (e0, e1), (g0, g1) in zip(eb, gb):
        if abs(g0 - e0) > 10:
            issues.append(f"line@y{e0}: top off {g0 - e0:+d}px")
        if abs(left_edge(got_mask, (g0, g1)) - left_edge(exp_ink, (e0, e1))) > 8:
            issues.append(f"line@y{e0}: left edge off")
        # row-align the two bands by their own tops (the captures drift
        # vertically by ~10px across the page) and allow a small dx
        h = min(e1 - e0, H - g0)
        band_exp = exp_ink[e0:e0 + h]
        band_got = got_near[g0:g0 + h]
        denom = max(1, band_exp.sum())
        cov = max(
            float((band_exp & np.roll(band_got, dx, axis=1)).sum()) / denom
            for dx in range(-8, 9, 2))
        # floor calibrated against the closest-matching Geologica static:
        # per-glyph width differences vs the (unknown) expected font build
        # cost up to ~11%; a wrong font/size/position scores far lower
        if cov < 0.85:
            issues.append(f"line@y{e0}: only {cov:.0%} of expected ink covered")
    return issues


def main():
    COMPARE.mkdir(parents=True, exist_ok=True)
    spec = json.loads(SPEC.read_text())
    el_box = {e["id"]: e["box"] for e in spec["elements"]}
    face_box = (1300, 0, 2560, 1440)
    man_px, logo_px = box_to_px(el_box["man"]), box_to_px(el_box["logo"])
    regions_by_state = {
        1: [("face", face_box), ("man", man_px)],
        2: [("face", face_box), ("man", man_px), ("logo", logo_px)],
        # state 3 face/text zones overlap; text is checked structurally below
        3: [("man", man_px), ("logo", logo_px)],
    }

    failures = []
    raw = {}
    blur = ImageFilter.GaussianBlur(2)
    for n in (1, 2, 3):
        png = render(STATES / f"state{n}.pptx", COMPARE)
        got_img = Image.open(png).convert("RGB").resize((W, H))
        exp_img = Image.open(EXPECTED / f"1st_slide{n}.jpg").convert("RGB").resize((W, H))
        raw[n] = (np.asarray(exp_img), np.asarray(got_img))
        # a mild blur washes out sub-pixel edge aliasing from the differing
        # capture scales; real mismatches (>2-3px) still register
        got = np.asarray(got_img.filter(blur), dtype=np.float64)
        exp = np.asarray(exp_img.filter(blur), dtype=np.float64)
        exp, (gdx, gdy) = global_prealign(exp, got)

        scores = [(name, region_rmse(exp, got, box))
                  for name, box in regions_by_state[n]]
        line = "  ".join(f"{name}={rmse:5.2f}" for name, rmse in scores)
        print(f"state{n}:  {line}   (global shift {gdx:+d},{gdy:+d})")
        failures += [f"state{n}/{name}={r:.1f}" for name, r in scores if r > 12]

        side = Image.new("RGB", (W, H * 2 + 8), (255, 0, 0))
        side.paste(exp_img, (0, 0))
        side.paste(got_img, (0, H + 8))
        side.resize((W // 2, H + 4)).save(COMPARE / f"side_state{n}.png")

    text_issues = text_structure_issues(raw[3][0], raw[2][0],
                                        raw[3][1], raw[2][1])
    print("state3 text structure:",
          "ok" if not text_issues else "; ".join(text_issues))
    failures += [f"state3/text: {i}" for i in text_issues]

    if failures:
        print("FAILURES:", "; ".join(failures))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
