#!/usr/bin/env python3
"""Deterministic critique of a slide spec, for a designer (human or skill) to
react to without a reference screenshot to compare against.

Usage:
  lint_render.py specs/<name>.spec.json [--out PATH]

Assumes `build_deck.py <spec> --states` has already produced
output/<stem>.pptx (stem = spec filename with the .spec suffix stripped) --
run that first if it hasn't.

Prints one JSON report to stdout (`--out` also writes it to a file):
  {"spec": str, "ok": bool, "counts": {"error": n, "warn": n},
   "findings": [{"severity", "check", "element_id", "message"}]}
"severity" is one of "error" (must fix before the next iteration), "warn"
(advisory -- react only if you agree, otherwise record the disagreement in
the spec's own meta.designer_rationale), or "info" (e.g. a font got
auto-installed; never affects ok/counts). Exit code 0 iff zero "error"
findings, matching build_deck.py's 0/1 convention.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont
from PIL import Image, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asset_resolver  # noqa: E402
import build_deck  # noqa: E402
from imaging import line_bands  # noqa: E402
from render import render  # noqa: E402

from common import PROJECT_ROOT, EMU_PER_PX, EMU_PER_PT, PX_PER_PT
OUT = PROJECT_ROOT / "output"
ASSETS_JSON_PATH = PROJECT_ROOT / "out" / "assets.json"
TEMPLATE_STYLE_JSON_PATH = PROJECT_ROOT / "out" / "template_style.json"
STYLEGUIDE_PROFILE_JSON_PATH = PROJECT_ROOT / "out" / "styleguide_profile.json"
FONTS_DIR = Path.home() / "Library" / "Fonts"


def finding(severity, check, element_id, message):
    return {"severity": severity, "check": check, "element_id": element_id, "message": message}


def stem_of(spec_path: Path) -> str:
    return spec_path.stem.replace(".spec", "")


def font_lookup(assets_json):
    """family name -> repo-relative .ttf path, from the facts layer."""
    return {f["family"]: f["file"] for f in assets_json.get("fonts", []) if f.get("family")}


def resolve_font_path(family, lookup):
    rel = lookup.get(family)
    return (PROJECT_ROOT / rel) if rel else None


def boxes_overlap_emu(a, b):
    """Intersection area (EMU^2) of two boxes; 0 if they don't overlap."""
    ax0, ay0, ax1, ay1 = a["x"], a["y"], a["x"] + a["cx"], a["y"] + a["cy"]
    bx0, by0, bx1, by1 = b["x"], b["y"], b["x"] + b["cx"], b["y"] + b["cy"]
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    return ix * iy


# ------------------------------------------------------------------ checks --

def check_build_validate(spec, findings):
    for err in build_deck.validate_spec(spec, PROJECT_ROOT):
        findings.append(finding("error", "build_validate", None, err))


def check_font_conformance(spec, lookup, findings):
    """Every run/bullet font must be an exact assets.json family key -- the
    naming-trap catcher (e.g. 'Geologica SemiBold' is not the same key as
    'Geologica Roman SemiBold'). Returns the set of (element_id, font) pairs
    that failed, so later checks can skip trying to open a font that isn't
    resolvable.
    """
    failed = set()
    for el in spec["elements"]:
        if el["type"] != "textbox":
            continue
        for para in el["paragraphs"]:
            for run in para["lines"]:
                if run["font"] not in lookup:
                    failed.add((el["id"], run["font"]))
            bullet = para.get("bullet")
            if bullet and bullet["font"] not in lookup:
                findings.append(finding(
                    "error", "font_conformance", el["id"],
                    f"bullet font '{bullet['font']}' has no exact match in assets.json "
                    f"fonts[].family"))
    for el_id, font in sorted(failed):
        findings.append(finding(
            "error", "font_conformance", el_id,
            f"font '{font}' has no exact match in assets.json fonts[].family "
            f"(naming-trap risk: check for the Roman/Cursive/Auto variant that matches)"))
    return failed


def check_glyph_coverage(spec, lookup, failed_fonts, findings):
    cmap_cache = {}
    for el in spec["elements"]:
        if el["type"] != "textbox":
            continue
        for para in el["paragraphs"]:
            for run in para["lines"]:
                font = run["font"]
                if (el["id"], font) in failed_fonts:
                    continue  # already reported as unresolvable by check_font_conformance
                if font not in cmap_cache:
                    path = resolve_font_path(font, lookup)
                    try:
                        tt = TTFont(str(path), lazy=True, fontNumber=0)
                        cmap_cache[font] = set(tt.getBestCmap() or {})
                    except Exception as e:
                        cmap_cache[font] = None
                        findings.append(finding(
                            "warn", "glyph_coverage", el["id"],
                            f"could not open font '{font}' to check glyph coverage: {e}"))
                cmap = cmap_cache[font]
                if cmap is None:
                    continue
                missing = sorted({c for c in run["text"] if not c.isspace() and ord(c) not in cmap})
                if missing:
                    findings.append(finding(
                        "error", "glyph_coverage", el["id"],
                        f"font '{font}' has no glyph for: {''.join(missing)!r}"))


def check_text_fit(spec, lookup, failed_fonts, findings):
    """Render-free geometric estimate. getlength() returns px; box.cx/cy are
    EMU -- both axes are explicitly converted via EMU_PER_PX/EMU_PER_PT
    rather than left implicit. 1.03x tolerance calibrated against the known
    good title_slide.spec.json fixture's own worst-case line (~0.95 of its
    box width) -- tight enough to catch real overflow, loose enough not to
    false-positive on it.
    """
    for el in spec["elements"]:
        if el["type"] != "textbox":
            continue
        box = el["box"]
        total_h_emu = 0.0
        for pi, para in enumerate(el["paragraphs"]):
            line_spacing_pt = para.get("line_spacing_pt")
            for li, run in enumerate(para["lines"]):
                size_pt = run["size_pt"]
                lh_pt = line_spacing_pt if line_spacing_pt is not None else 1.2 * size_pt
                total_h_emu += lh_pt * EMU_PER_PT

                font = run["font"]
                if (el["id"], font) in failed_fonts:
                    continue
                path = resolve_font_path(font, lookup)
                try:
                    pil_font = ImageFont.truetype(str(path), max(1, round(size_pt * PX_PER_PT)))
                except Exception:
                    continue
                px_width = pil_font.getlength(run["text"])
                emu_width = px_width * EMU_PER_PX
                tracking_pt = run.get("tracking_pt") or 0.0
                if tracking_pt and len(run["text"]) > 1:
                    emu_width += tracking_pt * PX_PER_PT * EMU_PER_PX * (len(run["text"]) - 1)
                if emu_width > 1.03 * box["cx"]:
                    findings.append(finding(
                        "error", "text_fit", el["id"],
                        f"paragraph {pi + 1} line {li + 1} ('{run['text'][:30]}') estimated "
                        f"width {emu_width:.0f} EMU exceeds box.cx {box['cx']} EMU "
                        f"(ratio {emu_width / box['cx']:.2f})"))
            if para.get("space_before_pt"):
                total_h_emu += para["space_before_pt"] * EMU_PER_PT
        if total_h_emu > 1.03 * box["cy"]:
            findings.append(finding(
                "error", "text_fit", el["id"],
                f"estimated total text height {total_h_emu:.0f} EMU exceeds box.cy "
                f"{box['cy']} EMU (ratio {total_h_emu / box['cy']:.2f})"))


def check_bbox_overlap(spec, findings):
    """Pairwise AABB intersection. Threshold calibrated against the known
    good fixture: 'name'/'bullets' legitimately overlap ~9% (textbox boxes
    carry vertical padding beyond their actual glyph ink) and 'logo'/'man'
    overlap ~11% (intentional corner layering) -- neither is a bug, so the
    threshold sits above both. A full-bleed element (box covers the whole
    slide, e.g. a background shape/panel) is exempt entirely -- like the
    schema's own dedicated `background` field, it's meant to sit under
    everything, so "overlapping" it isn't a meaningful signal.
    """
    sw, sh = spec["slide"]["width_emu"], spec["slide"]["height_emu"]

    def is_full_bleed_backdrop(el):
        b = el["box"]
        return b["x"] <= 0 and b["y"] <= 0 and b["cx"] >= sw and b["cy"] >= sh

    elements = [e for e in spec["elements"] if not is_full_bleed_backdrop(e)]
    for i in range(len(elements)):
        for j in range(i + 1, len(elements)):
            a, b = elements[i], elements[j]
            inter = boxes_overlap_emu(a["box"], b["box"])
            if inter <= 0:
                continue
            area_a = a["box"]["cx"] * a["box"]["cy"]
            area_b = b["box"]["cx"] * b["box"]["cy"]
            frac = inter / min(area_a, area_b)
            if frac < 0.15:
                continue
            severity = "error" if a["type"] == "textbox" and b["type"] == "textbox" else "warn"
            findings.append(finding(
                severity, "bbox_overlap", f"{a['id']}+{b['id']}",
                f"'{a['id']}' ({a['type']}) and '{b['id']}' ({b['type']}) overlap "
                f"{frac:.0%} of the smaller box's area"))


def check_font_role_alignment(spec, assets_json, findings):
    """Nudge toward font_roles.heading/.body; never blocking -- the theme's
    declared intent is aspirational, not mandatory (this template's own
    execution is inconsistent), and the known-good fixture itself deviates
    (title uses a Geologica weight, not the theme's HeliosCond heading).
    """
    heading = assets_json.get("font_roles", {}).get("heading")
    body = assets_json.get("font_roles", {}).get("body")
    role_expect = {"title": heading, "heading": heading, "subtitle": body}
    for el in spec["elements"]:
        if el["type"] != "textbox":
            continue
        expected = role_expect.get(el.get("role"), body)
        if not expected:
            continue
        fonts_used = sorted({r["font"] for p in el["paragraphs"] for r in p["lines"]})
        if not any(f.startswith(expected) for f in fonts_used):
            findings.append(finding(
                "warn", "font_role_alignment", el["id"],
                f"fonts {fonts_used} don't start with the theme's expected family "
                f"'{expected}' for role '{el.get('role')}'"))


def check_color_conformance(spec, assets_json, template_style, findings, deck=None):
    """Warn when a run color is not in the allowed palette.

    Priority of allowed set:
    1. The owning deck's tokens.palette_roles, when the deck spec is passed
       explicitly (`--deck`, which deck_qa.py always does). When present,
       this IS the standard and the template theme is ignored.
    2. Template theme colors + top explicit colors (when no deck palette).
    3. {000000, FFFFFF} (always allowed).
    """
    deck_palette = (deck or {}).get("tokens", {}).get("palette_roles", {})
    allowed = {"000000", "FFFFFF"}
    if deck_palette:
        allowed.update(c.upper() for c in deck_palette.values())
    else:
        theme_used = assets_json.get("font_roles", {}).get("theme_used")
        theme = next((t for t in template_style.get("themes", []) if t["name"] == theme_used), None)
        if theme:
            allowed.update(v.upper() for v in theme["colors"].values())
        allowed.update(c["hex"].upper() for c in template_style.get("explicit_colors_ranked", []))
    flagged = set()
    for el in spec["elements"]:
        if el["type"] != "textbox":
            continue
        for para in el["paragraphs"]:
            for run in para["lines"]:
                color = run["color"].upper()
                if color not in allowed and (el["id"], color) not in flagged:
                    flagged.add((el["id"], color))
                    source = "deck palette_roles" if deck_palette else "template theme"
                    findings.append(finding(
                        "warn", "color_conformance", el["id"],
                        f"run color '{run['color']}' is not in the {source} — "
                        f"off-palette one-offs erode the brand read"))


def _srgb_to_linear(c8):
    c = c8 / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance_hex(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return (0.2126 * _srgb_to_linear(r) + 0.7152 * _srgb_to_linear(g)
            + 0.0722 * _srgb_to_linear(b))


def _contrast_ratio(l1, l2):
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def check_contrast(spec, findings):
    """For each textbox, find whatever image sits directly behind it in
    z-order (a lower-z image element, else the full-bleed background) and
    sample its median luminance directly from the source PNG on disk -- no
    rendering needed. Warn-only: median luminance of a busy region is an
    approximation, and the crop-to-box mapping is only geometrically exact
    for fit:stretch (the only fit build_deck.py actually implements today);
    if contain/cover is ever used this degrades to a same-severity estimate,
    not a silent skip.
    """
    elements = spec["elements"]
    slide = spec["slide"]
    for el in elements:
        if el["type"] != "textbox":
            continue
        z = el.get("z", 0)
        behind_asset, behind_box = None, None
        candidates = [e for e in elements if e["type"] == "image" and e.get("z", 0) < z
                      and boxes_overlap_emu(e["box"], el["box"]) > 0]
        if candidates:
            top = max(candidates, key=lambda e: e.get("z", 0))
            behind_asset, behind_box = top["asset"], top["box"]
        elif spec.get("background"):
            behind_asset, behind_box = spec["background"]["asset"], spec["background"]["box"]
        if not behind_asset:
            continue
        img_path = PROJECT_ROOT / behind_asset
        if not img_path.is_file():
            continue
        try:
            img = Image.open(img_path).convert("RGB")
            iw, ih = img.size
            sw, sh = slide["width_emu"], slide["height_emu"]
            box = el["box"]
            x0 = max(0, int(box["x"] / sw * iw))
            y0 = max(0, int(box["y"] / sh * ih))
            x1 = min(iw, int((box["x"] + box["cx"]) / sw * iw))
            y1 = min(ih, int((box["y"] + box["cy"]) / sh * ih))
            if x1 <= x0 or y1 <= y0:
                continue
            crop = np.asarray(img.crop((x0, y0, x1, y1))).astype(np.float64)
            lum = (0.2126 * crop[..., 0] + 0.7152 * crop[..., 1] + 0.0722 * crop[..., 2]) / 255.0
            bg_lum = float(np.median(lum))
        except Exception:
            continue
        for para in el["paragraphs"]:
            for run in para["lines"]:
                ratio = _contrast_ratio(bg_lum, _relative_luminance_hex(run["color"]))
                if ratio < 3.0:
                    findings.append(finding(
                        "warn", "contrast", el["id"],
                        f"estimated contrast ratio {ratio:.2f} between run color "
                        f"'{run['color']}' and what's behind it ('{behind_asset}') is low "
                        f"(< 3.0); sampling assumes fit:stretch"))


def check_asset_inventory(spec, assets_json, findings):
    """Warn when a placed image is absent from assets.json's inventory.

    Previously this was a silent gap: watermark_usage and asset_duplication
    checks do `by_file.get(el["asset"])` and silently skip on None, so
    images placed from subdirectories the inventory didn't scan (e.g.
    assets/designer_extracted/) bypassed every safety check.
    """
    known = {img["file"] for img in assets_json.get("images", [])}
    for el in spec["elements"]:
        if el["type"] != "image":
            continue
        asset = el["asset"]
        if asset not in known:
            findings.append(finding(
                "warn", "asset_not_in_inventory", el["id"],
                f"asset '{asset}' is not in assets.json's image inventory -- "
                f"re-run inventory.py to include it, or watermark/duplicate "
                f"checks will silently skip it"))
    bg = spec.get("background")
    if bg and bg.get("asset") not in known:
        findings.append(finding(
            "warn", "asset_not_in_inventory", None,
            f"background asset '{bg['asset']}' is not in assets.json's image "
            f"inventory -- re-run inventory.py to include it"))


def check_watermark_usage(spec, assets_json, findings):
    """Shipping a stock illustration with a visible copyright watermark is a
    production-readiness problem, not a cosmetic one -- flag it loudly
    rather than let it slip through silently. Warn-only because there are
    legitimate cases (a placeholder pending licensed art, explicitly noted
    in meta.asset_gaps) where using it briefly is a deliberate, documented
    choice, not an oversight.
    """
    by_file = {img["file"]: img for img in assets_json.get("images", [])}
    for el in spec["elements"]:
        if el["type"] != "image":
            continue
        img = by_file.get(el["asset"])
        if img and img.get("watermark_suspected"):
            findings.append(finding(
                "warn", "watermark_usage", el["id"],
                f"asset '{el['asset']}' is flagged watermark_suspected in assets.json -- "
                f"confirm this is licensed/cleared before shipping, or note the gap in "
                f"meta.asset_gaps if it's a placeholder"))
    bg = spec.get("background")
    if bg:
        img = by_file.get(bg["asset"])
        if img and img.get("watermark_suspected"):
            findings.append(finding(
                "warn", "watermark_usage", None,
                f"background asset '{bg['asset']}' is flagged watermark_suspected in "
                f"assets.json -- confirm this is licensed/cleared before shipping, or note "
                f"the gap in meta.asset_gaps if it's a placeholder"))


def check_asset_duplication(spec, assets_json, findings):
    by_file = {img["file"]: img for img in assets_json.get("images", [])}

    def key(img):
        return (tuple(img["size"]), img["mode"], img["has_alpha"], tuple(img["dominant_colors"]))

    used = [(el["id"], el["asset"]) for el in spec["elements"] if el["type"] == "image"]
    for i in range(len(used)):
        for j in range(i + 1, len(used)):
            id_a, file_a = used[i]
            id_b, file_b = used[j]
            if file_a == file_b:
                continue
            ia, ib = by_file.get(file_a), by_file.get(file_b)
            if not ia or not ib:
                continue
            if key(ia) == key(ib):
                findings.append(finding(
                    "warn", "asset_duplication", f"{id_a}+{id_b}",
                    f"'{id_a}' and '{id_b}' reference different files ('{file_a}' vs "
                    f"'{file_b}') that are indistinguishable in measured fields "
                    f"(size/alpha/dominant colors) -- confirm this isn't accidental reuse"))


def _needed_fonts(spec):
    needed = set()
    for el in spec["elements"]:
        if el["type"] != "textbox":
            continue
        for para in el["paragraphs"]:
            for run in para["lines"]:
                needed.add(run["font"])
            if para.get("bullet"):
                needed.add(para["bullet"]["font"])
    return needed


def ensure_fonts_installed(spec, lookup, findings):
    """Idempotent copy-if-missing, generalized from setup_env.sh's hardcoded
    7-file list to whatever this particular spec actually references, so
    check_render_structure doesn't produce noise from LibreOffice silently
    substituting a fallback for a font it doesn't have installed.
    """
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    for family in _needed_fonts(spec):
        src = resolve_font_path(family, lookup)
        if not src or not src.is_file():
            continue
        dst = FONTS_DIR / src.name
        if not dst.exists():
            dst.write_bytes(src.read_bytes())
            findings.append(finding("info", "font_install", None,
                                     f"installed {src.name} to {FONTS_DIR}"))


def _merge_close_bands(bands, min_gap=10):
    """Merge nearly-touching ink bands -- a diacritic or a font's own
    crossbar/stroke gap can otherwise register as a spurious extra line
    (same technique verify_reference.py uses for the same reason)."""
    out = []
    for b in bands:
        if out and b[0] - out[-1][1] < min_gap:
            out[-1] = (out[-1][0], b[1])
        else:
            out.append(tuple(b))
    return out


def check_render_structure(spec, spec_path, lookup, findings):
    """Secondary, best-effort confirming check (the geometric check in
    check_text_fit is the primary line of defense and doesn't depend on OS
    font state): render the already-built pptx, crop each textbox's box, and
    compare detected ink-line-band count to the declared line count.
    """
    pptx_path = OUT / f"{stem_of(spec_path)}.pptx"
    if not pptx_path.is_file():
        findings.append(finding("warn", "render_structure", None,
                                 f"skipped: {pptx_path} not found -- run build_deck.py first"))
        return
    try:
        ensure_fonts_installed(spec, lookup, findings)
        png_path = render(pptx_path, OUT / "lint_render_tmp")
        img = np.asarray(Image.open(png_path).convert("RGB"))
    except Exception as e:
        findings.append(finding("warn", "render_structure", None, f"skipped: {e}"))
        return

    sw, sh = spec["slide"]["width_emu"], spec["slide"]["height_emu"]
    ih, iw = img.shape[0], img.shape[1]
    for el in spec["elements"]:
        if el["type"] != "textbox":
            continue
        box = el["box"]
        x0 = max(0, int(box["x"] / sw * iw))
        y0 = max(0, int(box["y"] / sh * ih))
        x1 = min(iw, int((box["x"] + box["cx"]) / sw * iw))
        y1 = min(ih, int((box["y"] + box["cy"]) / sh * ih))
        if x1 <= x0 or y1 <= y0:
            continue
        crop = img[y0:y1, x0:x1]
        # adaptive vs. a fixed dark-pixel threshold: light text on a dark
        # background (e.g. a full-bleed dark `shape` backdrop) needs the
        # opposite polarity, and a fixed threshold silently detects nothing
        # in that case. The crop's own median luminance is a good proxy for
        # "background" since text covers a small fraction of its box.
        lum = crop.mean(axis=2)
        bg_estimate = np.median(lum)
        ink_mask = np.abs(lum - bg_estimate) > 40
        bands = _merge_close_bands(line_bands(ink_mask))
        declared_lines = sum(len(p["lines"]) for p in el["paragraphs"])
        if len(bands) != declared_lines:
            findings.append(finding(
                "warn", "render_structure", el["id"],
                f"rendered ink-line-band count {len(bands)} != declared line count "
                f"{declared_lines} (possible unexpected wrap/clip)"))


LICENSE_FILENAMES = ("OFL.txt", "LICENSE", "LICENSE.txt", "LICENSE.md",
                     "COPYING", "COPYING.txt", "UFL.txt")


def check_embed_font_licenses(spec, findings, project_root=PROJECT_ROOT):
    """Embedding redistributes font software inside a client file. Warn
    whenever no license evidence sits next to an embedded font file —
    prompting a human to verify redistribution rights, not blocking."""
    for entry in spec.get("packaging", {}).get("embed_fonts", []):
        for key in ("regular", "bold", "italic", "bold_italic"):
            path = entry.get(key)
            if not path:
                continue
            font_path = project_root / path
            if not font_path.is_file():
                continue  # existence is validate_spec's error, not ours
            search_dirs = [font_path.parent, font_path.parent.parent]
            if not any((d / n).is_file() for d in search_dirs
                       for n in LICENSE_FILENAMES):
                findings.append(finding(
                    "warn", "embed_font_license", entry["family"],
                    f"embedding '{path}' with no license file "
                    f"({'/'.join(LICENSE_FILENAMES[:3])}...) found beside it — "
                    f"verify redistribution rights before shipping"))


def check_font_embedding_decision(spec, lookup, findings, deck=None):
    """Non-system fonts (fonts with a local .ttf in assets/fonts/) must be
    either embedded via packaging.embed_fonts or explicitly opted out via
    meta.font_embedding_opt_out with a reason. A deck that uses 80 runs of
    Geologica + HeliosCond and ships with zero fntdata renders wrong on
    every machine that doesn't have those fonts installed.

    For deck members, packaging lives at DECK level (the deck's packaging
    supersedes per-slide packaging at build time), so when the owning deck
    spec is passed (`--deck`, deck_qa.py always does) its embed_fonts and
    meta.font_embedding_opt_out count too — otherwise every member slide
    would warn forever even after the deck embeds the fonts.
    """
    # Collect all fonts used in the spec
    used_fonts = set()
    for el in spec["elements"]:
        if el["type"] != "textbox":
            continue
        for para in el["paragraphs"]:
            for run in para["lines"]:
                used_fonts.add(run["font"])
            bullet = para.get("bullet")
            if bullet:
                used_fonts.add(bullet["font"])
    for el in spec["elements"]:
        if el["type"] == "table":
            used_fonts.add(el["table"]["style"]["font"])

    # Non-system = fonts that have a local .ttf in assets/fonts/
    non_system = {f for f in used_fonts if f in lookup}

    if not non_system:
        return

    embedded = {e["family"] for e in spec.get("packaging", {}).get("embed_fonts", [])}
    embedded.update(e["family"] for e in
                    (deck or {}).get("packaging", {}).get("embed_fonts", []))
    opt_out = (spec.get("meta", {}).get("font_embedding_opt_out", False)
               or (deck or {}).get("meta", {}).get("font_embedding_opt_out", False))

    unembedded = non_system - embedded
    if not unembedded or opt_out:
        return

    findings.append(finding(
        "warn", "font_embedding_decision", None,
        f"spec uses non-system fonts {sorted(unembedded)} but has no "
        f"packaging.embed_fonts entry for them — the deck will render with "
        f"fallback fonts on machines without these installed. Either add "
        f"embed_fonts entries or set meta.font_embedding_opt_out with a reason."))


def _text_line_count(spec):
    count = 0
    for el in spec.get("elements", []):
        if el.get("type") != "textbox":
            continue
        for para in el.get("paragraphs", []):
            count += len(para.get("lines", []))
    return count


def _visual_area_ratio(spec):
    slide = spec.get("slide", {})
    slide_area = max(1, slide.get("width_emu", 0) * slide.get("height_emu", 0))
    visual_area = 0
    if isinstance(slide.get("background"), dict):
        visual_area += slide_area
    for el in spec.get("elements", []):
        if el.get("type") != "image":
            continue
        box = el.get("box", {})
        visual_area += max(0, box.get("cx", 0) * box.get("cy", 0))
    for brief in spec.get("image_briefs", []):
        box = brief.get("box", {})
        visual_area += max(0, box.get("cx", 0) * box.get("cy", 0))
    return min(1.0, visual_area / slide_area)


def check_styleguide_application(spec, findings, styleguide):
    if not styleguide:
        return
    meta = spec.get("meta", {})
    style_name = styleguide.get("style_name", "styleguide")
    if not meta.get("styleguide_profile"):
        findings.append(finding(
            "warn", "styleguide_application", "meta",
            f"styleguide profile '{style_name}' is available but "
            "meta.styleguide_profile is not recorded"))
    if not meta.get("styleguide_application"):
        findings.append(finding(
            "warn", "styleguide_application", "meta",
            "record how the slide applies the styleguide in "
            "meta.styleguide_application"))

    max_lines = styleguide.get("text_rules", {}).get("max_text_lines_per_slide")
    if max_lines and _text_line_count(spec) > max_lines:
        findings.append(finding(
            "warn", "styleguide_text_budget", "slide",
            f"styleguide text budget is {max_lines} lines; spec has "
            f"{_text_line_count(spec)} text lines"))

    target_visual = styleguide.get("layout_rules", {}).get("visual_ratio_target")
    if target_visual and _visual_area_ratio(spec) < min(0.35, target_visual / 2):
        findings.append(finding(
            "warn", "styleguide_visual_weight", "slide",
            "styleguide expects a visual-led composition, but this spec has "
            "no substantial image/background/image_brief area"))


def check_image_briefs(spec, findings, project_root=PROJECT_ROOT):
    """No deck ships with a silent hole: an unfilled brief is an error
    unless its id is in meta.acknowledged_briefs (an explicit, reviewable
    'ships without it' decision — then it's a warn-level reminder)."""
    acknowledged = set(spec.get("meta", {}).get("acknowledged_briefs", []))
    for brief in spec.get("image_briefs", []):
        filled = (project_root / brief["asset"]).is_file()
        if filled:
            continue
        if brief["id"] in acknowledged:
            findings.append(finding(
                "warn", "image_brief_open", brief["id"],
                f"brief '{brief['id']}' ({brief['subject']}) acknowledged as "
                f"shipping unfilled — the slide intentionally has no image here"))
        else:
            findings.append(finding(
                "error", "image_brief_open", brief["id"],
                f"unfilled image brief '{brief['id']}': wanted '{brief['subject']}' "
                f"at {brief['asset']} — fill it, or acknowledge shipping without "
                f"it via meta.acknowledged_briefs"))


def _asset_sidecar(asset_path):
    for sidecar in (asset_path.with_suffix(asset_path.suffix + ".json"),
                    asset_path.with_suffix(".json")):
        if not sidecar.is_file():
            continue
        try:
            return json.loads(sidecar.read_text())
        except json.JSONDecodeError:
            return {"_invalid_json": True}
    return {}


def _needs_provenance(asset, sidecar):
    source_type = sidecar.get("source_type")
    return (
        asset.startswith("assets/generated/")
        or sidecar.get("ai_generated")
        or source_type in {"web", "generated"}
    )


def _is_template_image(el):
    """Template-extracted images (logos, molecular visuals from
    assets/designer_extracted/) don't need provenance sidecars — their
    source is the conference template, not third-party content. Role match
    is prefix/exact, not substring, so an unrelated role that merely
    contains the word doesn't slip through."""
    asset = el.get("asset", "")
    role = el.get("role", "") or ""
    return (asset.startswith("assets/designer_extracted/")
            or role.startswith("template")
            or role == "event-logo")


def check_placed_image_provenance(spec, findings, project_root=PROJECT_ROOT):
    """Directly placed non-template images need a provenance sidecar
    (asset.ext.json with source_type, source_url, license, date,
    rationale). Template-extracted visuals (logos, molecular backgrounds
    from assets/designer_extracted/) are exempt — their origin is the
    conference template itself.
    """
    for el in spec.get("elements", []):
        if el.get("type") != "image":
            continue
        if _is_template_image(el):
            continue
        asset = el["asset"]
        if asset.startswith("output/"):
            # pipeline-internal artifact (e.g. the title-slide spike's
            # screenshot-lifted plates under output/work/) — provenance is
            # the pipeline itself, and erroring here would break the
            # documented lint flow on the regression fixture
            continue
        path = project_root / asset
        if not path.is_file():
            continue
        # Already checked by check_ai_generated_review if generated/web
        sidecar = _asset_sidecar(path)
        if _needs_provenance(asset, sidecar):
            continue  # handled by check_ai_generated_review
        if not sidecar:
            findings.append(finding(
                "error", "placed_image_provenance", el["id"],
                f"placed image '{asset}' has no provenance sidecar — "
                f"record source, license, and rationale in a "
                f"{path.name}.json sidecar"))


def check_ai_generated_review(spec, findings, project_root=PROJECT_ROOT):
    """Resolver-filled external/generated images need provenance.

    Medical/anatomical external/generated visuals are allowed after the agent's
    verification layer, but remain warn-level because medical accuracy is a
    user-facing caveat.
    """
    class_by_asset = {b["asset"]: b["medical_class"] for b in spec.get("image_briefs", [])}
    brief_by_asset = {b["asset"]: b for b in spec.get("image_briefs", [])}
    reviews = {r.get("asset"): r for r in spec.get("meta", {}).get("image_reviews", [])}
    assets = {el["asset"] for el in spec.get("elements", []) if el.get("type") == "image"}
    assets.update(class_by_asset)
    for asset in sorted(assets):
        path = project_root / asset
        if not path.is_file():
            continue
        sidecar = _asset_sidecar(path)
        if not _needs_provenance(asset, sidecar):
            continue
        if not sidecar:
            findings.append(finding(
                "error", "asset_provenance", asset,
                f"external/generated image '{asset}' has no provenance sidecar"))
            continue
        if sidecar.get("_invalid_json"):
            findings.append(finding(
                "error", "asset_provenance", asset,
                f"external/generated image '{asset}' has invalid provenance JSON"))
            continue

        required = ["brief_id", "brief_hash", "source_type", "selected_rationale"]
        missing = [key for key in required if not sidecar.get(key)]
        source_type = sidecar.get("source_type")
        if source_type in {"web", "generated"} and not sidecar.get("verification_notes"):
            missing.append("verification_notes")
        if missing:
            findings.append(finding(
                "error", "asset_provenance", asset,
                f"external/generated image '{asset}' provenance missing: "
                f"{', '.join(sorted(set(missing)))}"))
            continue

        brief = brief_by_asset.get(asset)
        if brief is not None:
            current_hash = asset_resolver.brief_hash(brief)
            if sidecar.get("brief_hash") != current_hash:
                findings.append(finding(
                    "error", "asset_provenance_stale", asset,
                    f"provenance for '{asset}' was recorded for a different "
                    f"version of its image_brief (brief_hash mismatch) -- the "
                    f"brief changed since this image was approved; re-review "
                    f"the image against the current brief and re-run "
                    f"asset_resolver.py import"))
                continue

        med = class_by_asset.get(asset) or sidecar.get("medical_class", "decorative")
        review = reviews.get(asset)
        if med == "anatomical":
            findings.append(finding(
                "warn", "medical_visual_review", asset,
                f"medical/anatomical image '{asset}' was selected from "
                f"{source_type}; verification notes are present, but accuracy "
                f"still needs user review before final delivery"))
        elif source_type == "generated" and not review:
            findings.append(finding(
                "warn", "ai_review_reminder", asset,
                f"AI-generated image '{asset}' ({med}) — double-check it before "
                f"the deck ships; record meta.image_reviews to silence this"))


MAX_VISUAL_REVIEW_ITERATIONS = 3


def check_visual_review(spec, findings):
    """Visual review must be recorded as a structured artifact, not prose.

    meta.visual_review = {
        "iteration": 1,
        "verdict": "pass" | "fail" | "pass_with_notes",
        "findings": [
            {"element_id": "headline", "issue": "text overlaps molecule"},
            ...
        ]
    }

    - Missing visual_review → warn (not yet reviewed)
    - iteration > 3 → error (too many iterations without resolution)
    - verdict "fail" → error (unresolved visual issue)
    """
    review = spec.get("meta", {}).get("visual_review")
    if not review:
        findings.append(finding(
            "warn", "visual_review", "meta",
            f"no meta.visual_review recorded — visual review is required "
            f"before delivery; record iteration, verdict, and findings"))
        return

    iteration = review.get("iteration", 0)
    if not isinstance(iteration, int) or iteration < 1:
        findings.append(finding(
            "warn", "visual_review", "meta",
            f"meta.visual_review.iteration should be a positive integer, "
            f"got {iteration!r}"))
        return

    if iteration > MAX_VISUAL_REVIEW_ITERATIONS:
        findings.append(finding(
            "error", "visual_review_iterations", "meta",
            f"visual review iteration {iteration} exceeds the limit of "
            f"{MAX_VISUAL_REVIEW_ITERATIONS} — too many review cycles without "
            f"resolution; stop and reassess the slide design"))

    verdict = review.get("verdict", "")
    if verdict == "fail":
        issues = "; ".join(f.get("issue", "?") for f in review.get("findings", []))
        findings.append(finding(
            "error", "visual_review_failed", "meta",
            f"visual review verdict is 'fail' with unresolved issues: {issues}"))

    review_findings = review.get("findings", [])
    if not isinstance(review_findings, list):
        findings.append(finding(
            "warn", "visual_review", "meta",
            f"meta.visual_review.findings should be a list of "
            f"{{element_id, issue}} objects"))


# -------------------------------------------------------------------- main --

def lint(spec_path: Path, deck_path: Path = None):
    """deck_path: the owning deck spec, when this slide is a deck member —
    supplies the deck's palette_roles / packaging context to the checks
    that would otherwise judge against the wrong standard. deck_qa.py
    always passes it; standalone slide lint runs without it."""
    spec = json.loads(spec_path.read_text())
    deck = json.loads(deck_path.read_text()) if deck_path else None
    assets_json = json.loads(ASSETS_JSON_PATH.read_text())
    template_style = json.loads(TEMPLATE_STYLE_JSON_PATH.read_text())
    styleguide = {}
    if STYLEGUIDE_PROFILE_JSON_PATH.is_file():
        styleguide = json.loads(STYLEGUIDE_PROFILE_JSON_PATH.read_text())
    lookup = font_lookup(assets_json)
    findings = []

    check_build_validate(spec, findings)
    if any(f["message"].startswith("schema:") for f in findings):
        return finalize(spec_path, findings)  # cross-checks below assume schema-valid shape

    failed_fonts = check_font_conformance(spec, lookup, findings)
    check_glyph_coverage(spec, lookup, failed_fonts, findings)
    check_text_fit(spec, lookup, failed_fonts, findings)
    check_bbox_overlap(spec, findings)
    check_font_role_alignment(spec, assets_json, findings)
    check_color_conformance(spec, assets_json, template_style, findings, deck=deck)
    check_contrast(spec, findings)
    check_styleguide_application(spec, findings, styleguide)
    check_watermark_usage(spec, assets_json, findings)
    check_asset_duplication(spec, assets_json, findings)
    check_asset_inventory(spec, assets_json, findings)
    check_image_briefs(spec, findings)
    check_ai_generated_review(spec, findings)
    check_placed_image_provenance(spec, findings)
    check_visual_review(spec, findings)
    check_embed_font_licenses(spec, findings)
    check_font_embedding_decision(spec, lookup, findings, deck=deck)
    check_render_structure(spec, spec_path, lookup, findings)

    return finalize(spec_path, findings)


def finalize(spec_path, findings):
    counts = {"error": sum(1 for f in findings if f["severity"] == "error"),
              "warn": sum(1 for f in findings if f["severity"] == "warn")}
    return {"spec": str(spec_path), "ok": counts["error"] == 0,
            "counts": counts, "findings": findings}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("spec", type=Path, help="path to a slide spec JSON file")
    ap.add_argument("--deck", type=Path, default=None,
                    help="owning deck spec (deck_qa passes this so palette/"
                         "packaging checks judge against the deck's own tokens)")
    ap.add_argument("--out", type=Path, default=None, help="also write the report JSON here")
    args = ap.parse_args()

    report = lint(args.spec, deck_path=args.deck)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
