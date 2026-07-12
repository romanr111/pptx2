#!/usr/bin/env python3
"""One-time(ish) migration: freeze output/work/geometry.json + content.json
(produced by the pptx-title-slide skill's extract_assets.py, which measures
the title slide off the expected-result screenshots) into a spec-driven
specs/title_slide.spec.json that build_deck.py can execute generically.

This is where the spike's font-size/position derivation math (cap-height ->
point size, ascent padding, line pitch...) lives now: it runs once, here, and
its output is frozen numbers in the spec -- build_deck.py itself never
re-derives anything from measurements.

Usage:
  geometry_to_spec.py   writes specs/title_slide.spec.json
"""
import json
import sys
from pathlib import Path

from common import PROJECT_ROOT, EMU_PER_PX, EMU_PER_PT
WORK = PROJECT_ROOT / "output" / "work"
SPECS = PROJECT_ROOT / "specs"

# family names as declared inside assets/fonts static TTFs (name id 1)
TITLE_FONT = "Geologica Roman SemiBold"
TITLE_TRACKING_PT = 0.5
NAME_FONT = "Geologica Roman"
NAME_BOLD = True
BULLET_FONT = "Geologica Roman Light"
BULLET_SIZE_PT = 14
BULLET_TRACKING_PT = 0.4

PT_PER_PX = 540 / 1440
CAP_RATIO = 0.70                 # Geologica cap-height fraction of em
ASCENT_PAD = 0.26                # box-top -> cap-top gap, as a fraction of font size

SLIDE_W_EMU, SLIDE_H_EMU = 12192000, 6858000


def clean_box(rect):
    return {"x": int(rect["x"]), "y": int(rect["y"]),
            "cx": int(rect["cx"]), "cy": int(rect["cy"])}


def main():
    geo = json.loads((WORK / "geometry.json").read_text())
    content = json.loads((WORK / "content.json").read_text())
    met = geo["metrics"]

    col_x = met["text_col_left_px"] * EMU_PER_PX
    right_margin_emu = 190500
    text_w = SLIDE_W_EMU - col_x - right_margin_emu

    # -- title: one paragraph, one run per line, joined by explicit breaks
    title_size = round(met["title"]["cap_pt"] / CAP_RATIO)
    title_pitch = met["title"]["pitch_pt"]
    cap_top_px = met["title"]["bands_px"][0][0]
    title_y = cap_top_px * EMU_PER_PX - title_size * ASCENT_PAD * EMU_PER_PT
    title_el = {
        "id": "title", "type": "textbox", "role": "title", "z": 2,
        "box": clean_box({"x": col_x, "y": title_y, "cx": text_w, "cy": 2000000}),
        "paragraphs": [{
            "line_spacing_pt": title_pitch,
            "lines": [
                {"text": line, "font": TITLE_FONT, "size_pt": title_size,
                 "color": geo["colors"]["title"], "tracking_pt": TITLE_TRACKING_PT}
                for line in content["title_lines"]
            ],
        }],
    }

    # -- speaker name: one paragraph, one run, no explicit line spacing
    name_size = round(met["name"]["cap_pt"] / CAP_RATIO)
    name_y = met["name"]["band_px"][0] * EMU_PER_PX - name_size * ASCENT_PAD * EMU_PER_PT
    name_el = {
        "id": "name", "type": "textbox", "role": "speaker_name", "z": 2,
        "box": clean_box({"x": col_x, "y": name_y, "cx": 5000000, "cy": 600000}),
        "paragraphs": [{
            "lines": [{"text": content["name"], "font": NAME_FONT, "size_pt": name_size,
                       "color": geo["colors"]["title"], "bold": NAME_BOLD}],
        }],
    }

    # -- credential bullets: one paragraph per item, dash bullet, hanging indent
    b = met["bullets"]
    line_pitch_pt = round(b["line_pitch_px"] * PT_PER_PX, 3)
    item_gap_pt = round((b["item_pitch_px"] - b["line_pitch_px"]) * PT_PER_PX, 3)
    bullets_y = b["bands_px"][0][0] * EMU_PER_PX - BULLET_SIZE_PT * ASCENT_PAD * EMU_PER_PT
    bullet_paragraphs = []
    for i, item in enumerate(content["bullets"]):
        para = {
            "line_spacing_pt": line_pitch_pt,
            "bullet": {"char": "-", "hang_emu": 152400, "font": BULLET_FONT},
            "lines": [
                {"text": line, "font": BULLET_FONT, "size_pt": BULLET_SIZE_PT,
                 "color": geo["colors"]["bullets"], "tracking_pt": BULLET_TRACKING_PT}
                for line in item
            ],
        }
        if i:
            para["space_before_pt"] = item_gap_pt
        bullet_paragraphs.append(para)
    bullets_el = {
        "id": "bullets", "type": "textbox", "role": "credentials", "z": 2,
        "box": clean_box({"x": col_x, "y": bullets_y, "cx": text_w, "cy": 3200000}),
        "paragraphs": bullet_paragraphs,
    }

    logo_el = {
        "id": "logo", "type": "image", "role": "logo", "z": 0,
        "asset": "output/work/logo_black.png",
        "box": clean_box(geo["logo"]),
    }
    man_el = {
        "id": "man", "type": "image", "role": "figure", "z": 1,
        "asset": "output/work/man_cropped.png",
        "box": clean_box(geo["man"]),
    }

    spec = {
        "spec_version": 1,
        "meta": {
            "source": "migrated from output/work/geometry.json + content.json "
                      "by geometry_to_spec.py (Phase 0 fixture, not designer output)",
        },
        "slide": {"width_emu": SLIDE_W_EMU, "height_emu": SLIDE_H_EMU},
        "background": {
            "asset": "output/work/background_title.png",
            "box": clean_box(geo["background"]),
        },
        "elements": [logo_el, man_el, title_el, name_el, bullets_el],
        "animations": [
            {"step": 1, "targets": ["man"], "effect": "fade", "duration_ms": 500},
            {"step": 2, "targets": ["logo"], "effect": "fade", "duration_ms": 500},
            {"step": 3, "targets": ["title", "name", "bullets"], "effect": "fade", "duration_ms": 500},
        ],
    }

    SPECS.mkdir(exist_ok=True)
    out = SPECS / "title_slide.spec.json"
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    print("wrote", out)


if __name__ == "__main__":
    sys.exit(main())
