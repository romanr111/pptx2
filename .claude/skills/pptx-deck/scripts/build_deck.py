#!/usr/bin/env python3
"""Generic spec-driven .pptx builder.

Executes a slide spec (validated against specs/spec.schema.json) and nothing
more: it does not decide layout, does not pick fonts/colors, does not choose
animation choreography. Those are upstream decisions (human or designer
skill) already frozen into the spec file.

Usage:
  build_deck.py specs/title_slide.spec.json
      writes output/<spec-stem>.pptx (with animation timing)
  build_deck.py specs/title_slide.spec.json --states
      also writes output/states/<spec-stem>/state{1..N}.pptx, static decks
      of each animation step for rendering/verification
  build_deck.py specs/title_slide.spec.json --check-only
      validate only, do not build
"""
import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

import jsonschema
from lxml import etree
from PIL import Image as PILImage
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR
from pptx.util import Emu, Pt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_packaging import apply_packaging  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = PROJECT_ROOT / "specs" / "spec.schema.json"
DECK_SCHEMA_PATH = PROJECT_ROOT / "specs" / "deck.schema.json"
OUT = PROJECT_ROOT / "output"

A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P_NS = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
EP_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}"


class SpecError(Exception):
    """Raised with a list of human-readable, actionable problems."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(errors))


def load_schema():
    return json.loads(SCHEMA_PATH.read_text())


def validate_spec(spec, project_root=PROJECT_ROOT):
    """Schema validation + cross-checks the schema itself can't express.

    Returns a list of error strings (empty = valid). Never raises.
    """
    errors = []
    validator_cls = jsonschema.validators.validator_for(load_schema())
    validator = validator_cls(load_schema())
    for err in validator.iter_errors(spec):
        errors.append(f"schema: {err.message} (at {'/'.join(str(p) for p in err.path)})")
    if errors:
        # further cross-checks assume a schema-valid shape; bail out early
        return errors

    ids = ([e["id"] for e in spec["elements"]]
           + [b["id"] for b in spec.get("image_briefs", [])])
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        errors.append(f"duplicate element/brief id(s): {sorted(dupes)}")
    id_set = set(ids)

    for el in spec["elements"]:
        if el["type"] == "image":
            asset_path = project_root / el["asset"]
            if not asset_path.is_file():
                errors.append(f"element '{el['id']}': asset not found: {el['asset']}")
        if el["type"] == "table":
            n_cols = len(el["table"]["columns_emu"])
            for ri, row in enumerate(el["table"]["rows"]):
                if len(row) != n_cols:
                    errors.append(f"element '{el['id']}': row {ri} has {len(row)} "
                                   f"cells, expected {n_cols} (columns_emu)")
        if el["type"] == "chart":
            errors.append(f"element '{el['id']}': type 'chart' is reserved, "
                           f"not implemented by build_deck.py yet")

    if spec.get("background"):
        bg_path = project_root / spec["background"]["asset"]
        if not bg_path.is_file():
            errors.append(f"background: asset not found: {spec['background']['asset']}")

    theme_src = spec.get("packaging", {}).get("theme_source")
    if theme_src and theme_src["kind"] == "template":
        tpl = project_root / theme_src["path"]
        if not tpl.is_file():
            errors.append(f"packaging: template not found: {theme_src['path']}")
    for entry in spec.get("packaging", {}).get("embed_fonts", []):
        slots = [k for k in ("regular", "bold", "italic", "bold_italic") if entry.get(k)]
        if not slots:
            errors.append(f"packaging: embed_fonts '{entry['family']}' names no font file")
        for k in slots:
            if not (project_root / entry[k]).is_file():
                errors.append(f"packaging: embed_fonts '{entry['family']}' {k} "
                               f"file not found: {entry[k]}")

    sw, sh = spec["slide"]["width_emu"], spec["slide"]["height_emu"]
    for el in spec["elements"]:
        box = el["box"]
        bleed = set(box.get("allow_offslide_bleed", []))
        if box["x"] < 0 and "left" not in bleed:
            errors.append(f"element '{el['id']}': box.x < 0 without allow_offslide_bleed:left")
        if box["y"] < 0 and "top" not in bleed:
            errors.append(f"element '{el['id']}': box.y < 0 without allow_offslide_bleed:top")
        if box["x"] + box["cx"] > sw and "right" not in bleed:
            errors.append(f"element '{el['id']}': box extends past right edge "
                           f"without allow_offslide_bleed:right")
        if box["y"] + box["cy"] > sh and "bottom" not in bleed:
            errors.append(f"element '{el['id']}': box extends past bottom edge "
                           f"without allow_offslide_bleed:bottom")

    acknowledged = set(spec.get("meta", {}).get("acknowledged_briefs", []))
    absent_briefs = {b["id"] for b in spec.get("image_briefs", [])
                     if b["id"] in acknowledged
                     and not (project_root / b["asset"]).is_file()}
    for step in spec.get("animations", []):
        for t in step["targets"]:
            if t not in id_set:
                errors.append(f"animation step {step['step']}: unknown target id '{t}'")
            elif t in absent_briefs:
                errors.append(f"animation step {step['step']}: target '{t}' is an "
                               f"acknowledged unfilled brief — it won't exist on the "
                               f"slide, so it can't be animated")
        if step["effect"] != "fade":
            errors.append(f"animation step {step['step']}: effect '{step['effect']}' "
                           f"not yet implemented by build_deck.py (fade only for now)")
        # reject rather than silently ignore what the builder can't execute
        if step.get("trigger", "click") != "click":
            errors.append(f"animation step {step['step']}: trigger '{step['trigger']}' "
                           f"not yet implemented by build_deck.py (click only for now)")
        if step.get("direction") is not None:
            errors.append(f"animation step {step['step']}: 'direction' only applies to "
                           f"wipe/fly effects, which are not implemented yet")

    return errors


def validate_deck(deck, project_root=PROJECT_ROOT):
    """Deck-schema validation + member-slide loading/validation.

    Returns (errors, slide_specs). slide_specs is empty when errors exist.
    """
    errors = []
    schema = json.loads(DECK_SCHEMA_PATH.read_text())
    validator_cls = jsonschema.validators.validator_for(schema)
    for err in validator_cls(schema).iter_errors(deck):
        errors.append(f"deck schema: {err.message} "
                      f"(at {'/'.join(str(p) for p in err.path)})")
    if errors:
        return errors, []

    if deck.get("packaging"):
        # deck packaging must satisfy the slide schema's packaging shape
        pkg_schema = load_schema()["properties"]["packaging"]
        for err in jsonschema.Draft202012Validator(pkg_schema).iter_errors(deck["packaging"]):
            errors.append(f"deck packaging: {err.message}")

    slide_specs = []
    for path_str in deck["slides"]:
        path = project_root / path_str
        if not path.is_file():
            errors.append(f"deck: slide spec not found: {path_str}")
            continue
        spec = json.loads(path.read_text())
        spec_errors = validate_spec(spec, project_root)
        for e in spec_errors:
            errors.append(f"{path_str}: {e}")
        # spec_errors non-empty means spec may not even have a well-formed
        # "slide" object (e.g. missing width_emu/height_emu) -- comparing
        # geometry against a schema-invalid spec would crash instead of
        # reporting a clean error, so skip it; the schema error already
        # reported above is the actionable one.
        if not spec_errors and (
                spec["slide"]["width_emu"] != deck["slide"]["width_emu"]
                or spec["slide"]["height_emu"] != deck["slide"]["height_emu"]):
            errors.append(f"{path_str}: slide is "
                          f"{spec['slide']['width_emu']}x{spec['slide']['height_emu']} EMU, "
                          f"deck demands {deck['slide']['width_emu']}x{deck['slide']['height_emu']}")
        slide_specs.append(spec)
    return errors, ([] if errors else slide_specs)


def emu_box(box):
    return Emu(box["x"]), Emu(box["y"]), Emu(box["cx"]), Emu(box["cy"])


def contain_box(box, img_w, img_h, anchor="center"):
    """Largest box preserving img_w/img_h's aspect ratio that fits inside
    `box`, positioned per `anchor`. Used for fit:"contain" -- natural
    proportions instead of always stretching to the declared box."""
    box_aspect = box["cx"] / box["cy"]
    img_aspect = img_w / img_h
    if img_aspect > box_aspect:
        cx = box["cx"]
        cy = round(cx / img_aspect)
    else:
        cy = box["cy"]
        cx = round(cy * img_aspect)
    x = box["x"] + (box["cx"] - cx) // 2
    y = box["y"] + (box["cy"] - cy) // 2
    if anchor == "top":
        y = box["y"]
    elif anchor == "bottom":
        y = box["y"] + box["cy"] - cy
    elif anchor == "left":
        x = box["x"]
    elif anchor == "right":
        x = box["x"] + box["cx"] - cx
    return {"x": x, "y": y, "cx": cx, "cy": cy}


EMU_PER_INCH = 914400
MEDIA_CACHE = OUT / "media_cache"


def _optimize_image(path, box, fit, media_opt, anchor="center"):
    """Opt-in media pass (forensic F5): bake cover crops into pixels and
    downscale to the DPI budget. Returns (path_to_embed, effective_fit) —
    originals are never modified; derivatives land in output/media_cache.
    """
    dpi = media_opt.get("dpi_budget", 200)
    quality = media_opt.get("jpeg_quality", 88)
    bake = media_opt.get("bake_crops", True)
    target_w = box["cx"] / EMU_PER_INCH * dpi
    target_h = box["cy"] / EMU_PER_INCH * dpi

    with PILImage.open(path) as img:
        iw, ih = img.size
        img_aspect, box_aspect = iw / ih, box["cx"] / box["cy"]
        work = None
        effective_fit = fit

        if fit == "cover" and bake:
            if img_aspect > box_aspect:
                crop_w = round(ih * box_aspect)
                x0 = {"left": 0, "right": iw - crop_w}.get(anchor, (iw - crop_w) // 2)
                work = img.crop((x0, 0, x0 + crop_w, ih))
            else:
                crop_h = round(iw / box_aspect)
                y0 = {"top": 0, "bottom": ih - crop_h}.get(anchor, (ih - crop_h) // 2)
                work = img.crop((0, y0, 0 + iw, y0 + crop_h))
            effective_fit = "stretch"  # box matches the baked aspect now

        base = work if work is not None else img
        # 1.3x headroom: don't churn files for marginal savings
        if base.size[0] > target_w * 1.3 and base.size[1] > target_h * 1.3:
            scale = max(target_w / base.size[0], target_h / base.size[1])
            new_size = (max(1, round(base.size[0] * scale)),
                        max(1, round(base.size[1] * scale)))
            base = base.resize(new_size, PILImage.LANCZOS)
            work = base

        if work is None:
            return path, fit  # nothing worth doing

        has_alpha = work.mode in ("RGBA", "LA", "PA") or (
            work.mode == "P" and "transparency" in work.info)
        stamp = hashlib.sha256(
            f"{path}|{Path(path).stat().st_mtime_ns}|{fit}|{dpi}|{quality}|"
            f"{box['cx']}x{box['cy']}".encode()).hexdigest()[:16]
        MEDIA_CACHE.mkdir(parents=True, exist_ok=True)
        if has_alpha:
            out_path = MEDIA_CACHE / f"{stamp}.png"
            if not out_path.is_file():
                work.save(out_path, format="PNG", optimize=True)
        else:
            out_path = MEDIA_CACHE / f"{stamp}.jpg"
            if not out_path.is_file():
                work.convert("RGB").save(out_path, format="JPEG",
                                         quality=quality, optimize=True)
        return str(out_path), effective_fit


def add_picture_fitted(slide, path, box, fit="stretch", anchor="center",
                       media_opt=None):
    """fit:"stretch" (default) preserves the exact prior behavior (always
    stretch to box.cx/cy). fit:"contain" places the image at its natural
    aspect ratio, anchored within the box (letterboxed, never distorted).
    fit:"cover" fills the box exactly via python-pptx's crop_* properties
    (symmetric center crop), never distorted either. media_opt (the spec's
    packaging.media_optimization) may swap in a baked/downscaled
    derivative before placement.
    """
    if media_opt is not None:
        # media_opt may be {} (schema-legal: "opt in with defaults") --
        # `if media_opt:` would treat that as falsy and silently skip
        # optimization, so check presence, not truthiness.
        path, fit = _optimize_image(path, box, fit, media_opt, anchor=anchor)
    if fit == "stretch":
        return slide.shapes.add_picture(path, *emu_box(box))
    with PILImage.open(path) as img:
        iw, ih = img.size
    if fit == "contain":
        return slide.shapes.add_picture(path, *emu_box(contain_box(box, iw, ih, anchor)))
    # fit == "cover" — anchor picks which side survives the crop
    pic = slide.shapes.add_picture(path, *emu_box(box))
    img_aspect, box_aspect = iw / ih, box["cx"] / box["cy"]
    if img_aspect > box_aspect:
        total = 1 - box_aspect / img_aspect
        if anchor == "left":
            pic.crop_right = total
        elif anchor == "right":
            pic.crop_left = total
        else:
            pic.crop_left = pic.crop_right = total / 2
    else:
        total = 1 - img_aspect / box_aspect
        if anchor == "top":
            pic.crop_bottom = total
        elif anchor == "bottom":
            pic.crop_top = total
        else:
            pic.crop_top = pic.crop_bottom = total / 2
    return pic


SHAPE_TYPE_MAP = {
    "ellipse": MSO_SHAPE.OVAL,
    "rectangle": MSO_SHAPE.RECTANGLE,
    "rounded_rectangle": MSO_SHAPE.ROUNDED_RECTANGLE,
}


def build_shape(slide, el):
    """Plain vector shape (no image asset) -- decorative accents/panels."""
    shp = slide.shapes.add_shape(SHAPE_TYPE_MAP[el["shape_type"]], *emu_box(el["box"]))
    shp.shadow.inherit = False
    fill = el["fill"]
    if fill.get("color2"):
        shp.fill.gradient()
        stops = shp.fill.gradient_stops
        stops[0].color.rgb = RGBColor.from_string(fill["color"])
        stops[0].position = 0.0
        stops[-1].color.rgb = RGBColor.from_string(fill["color2"])
        stops[-1].position = 1.0
        if fill.get("gradient_angle") is not None:
            shp.fill.gradient_angle = fill["gradient_angle"]
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = RGBColor.from_string(fill["color"])
    line = el.get("line")
    if line:
        shp.line.color.rgb = RGBColor.from_string(line["color"])
        shp.line.width = Pt(line["width_pt"])
    else:
        shp.line.fill.background()
    return shp


def _set_cell_border(cell, color_hex, width_pt):
    """Uniform grid border on one cell (lnL/lnR/lnT/lnB in tcPr)."""
    tcPr = cell._tc.get_or_add_tcPr()
    w = str(int(width_pt * 12700))
    for i, tag in enumerate(("lnL", "lnR", "lnT", "lnB")):
        el = tcPr.find(A_NS + tag)
        if el is not None:
            tcPr.remove(el)
        ln = etree.SubElement(tcPr, A_NS + tag)
        ln.set("w", w)
        fill = etree.SubElement(ln, A_NS + "solidFill")
        srgb = etree.SubElement(fill, A_NS + "srgbClr")
        srgb.set("val", color_hex.upper())
        # OOXML CT_TableCellProperties requires lnL/lnR/lnT/lnB (in that
        # order) before the fill -- insert at the running index i, not
        # always 0, or the four borders end up in reverse order and
        # PowerPoint may repair/drop them on open.
        tcPr.insert(i, ln)


def build_table(slide, el):
    """Data table, fully styled from the spec (no theme table styles)."""
    t = el["table"]
    style = t["style"]
    rows, cols = t["rows"], t["columns_emu"]
    gf = slide.shapes.add_table(len(rows), len(cols), *emu_box(el["box"]))
    table = gf.table
    # kill banding flags so the spec's explicit fills are the only styling
    table.first_row = False
    table.horz_banding = False
    for j, w in enumerate(cols):
        table.columns[j].width = Emu(w)
    if t.get("row_height_emu"):
        for row in table.rows:
            row.height = Emu(t["row_height_emu"])

    has_header = t.get("header", True)
    for i, row_vals in enumerate(rows):
        is_header = has_header and i == 0
        for j, text in enumerate(row_vals):
            cell = table.cell(i, j)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = cell.text_frame.paragraphs[0]
            run = p.add_run()
            run.text = text
            style_run(run, {
                "font": style["font"],
                "size_pt": style["size_pt"],
                "color": style.get("header_color", style["text_color"])
                          if is_header else style["text_color"],
                "bold": style.get("header_bold", True) if is_header else False,
            })
            fill = None
            if is_header:
                fill = style.get("header_fill")
            elif style.get("alt_row_fill") is not None and (i - int(has_header)) % 2 == 1:
                fill = style.get("alt_row_fill")
            else:
                fill = style.get("row_fill")
            if fill:
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor.from_string(fill)
            else:
                cell.fill.background()
            if style.get("border_color"):
                _set_cell_border(cell, style["border_color"],
                                 style.get("border_pt", 0.75))
    return gf


def set_body_props(tf, wrap="none", insets_zero=True):
    bodyPr = tf._txBody.find(A_NS + "bodyPr")
    if insets_zero:
        for k in ("lIns", "tIns", "rIns", "bIns"):
            bodyPr.set(k, "0")
    bodyPr.set("wrap", wrap)


def line_spacing_exact(paragraph, points):
    pPr = paragraph._p.get_or_add_pPr()
    el = pPr.find(A_NS + "lnSpc")
    if el is not None:
        pPr.remove(el)
    lnSpc = etree.SubElement(pPr, A_NS + "lnSpc")
    spcPts = etree.SubElement(lnSpc, A_NS + "spcPts")
    spcPts.set("val", str(int(points * 100)))
    pPr.insert(0, lnSpc)


def space_before_exact(paragraph, points):
    pPr = paragraph._p.get_or_add_pPr()
    spcBef = etree.SubElement(pPr, A_NS + "spcBef")
    spcPts = etree.SubElement(spcBef, A_NS + "spcPts")
    spcPts.set("val", str(int(points * 100)))


def apply_bullet(paragraph, bullet):
    pPr = paragraph._p.get_or_add_pPr()
    hang = bullet["hang_emu"]
    pPr.set("marL", str(hang))
    pPr.set("indent", str(-hang))
    # child order matters in CT_TextParagraphProperties: buClr < buFont < buChar
    if bullet.get("color"):
        buClr = etree.SubElement(pPr, A_NS + "buClr")
        srgb = etree.SubElement(buClr, A_NS + "srgbClr")
        srgb.set("val", bullet["color"].upper())
    buFont = etree.SubElement(pPr, A_NS + "buFont")
    buFont.set("typeface", bullet["font"])
    buChar = etree.SubElement(pPr, A_NS + "buChar")
    buChar.set("char", bullet["char"])


def style_run(run, run_spec):
    run.font.name = run_spec["font"]
    run.font.size = Pt(run_spec["size_pt"])
    run.font.bold = run_spec.get("bold", False)
    run.font.color.rgb = RGBColor.from_string(run_spec["color"])
    tracking = run_spec.get("tracking_pt")
    if tracking is not None:
        run.font._rPr.set("spc", str(int(tracking * 100)))


def build_textbox(slide, el):
    box = slide.shapes.add_textbox(*emu_box(el["box"]))
    tf = box.text_frame
    set_body_props(tf, wrap=el.get("wrap", "none"), insets_zero=el.get("insets_zero", True))
    for i, para_spec in enumerate(el["paragraphs"]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        if para_spec.get("line_spacing_pt") is not None:
            line_spacing_exact(p, para_spec["line_spacing_pt"])
        if para_spec.get("space_before_pt"):
            space_before_exact(p, para_spec["space_before_pt"])
        if para_spec.get("bullet"):
            apply_bullet(p, para_spec["bullet"])
        for j, run_spec in enumerate(para_spec["lines"]):
            if j:
                etree.SubElement(p._p, A_NS + "br")
            run = p.add_run()
            run.text = run_spec["text"]
            style_run(run, run_spec)
    return box


TIMING_TEMPLATE_HEAD = (
    '<p:timing xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
    '<p:tnLst><p:par>'
    '<p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
    '<p:seq concurrent="1" nextAc="seek">'
    '<p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
)
TIMING_TEMPLATE_TAIL = (
    '</p:childTnLst></p:cTn>'
    '<p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
    '<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst>'
    '</p:seq></p:childTnLst></p:cTn></p:par></p:tnLst>{bld}</p:timing>'
)


def effect_par(cid, spid, node_type, dur_ms):
    """Fade entrance; the only effect build_deck.py implements today."""
    return (
        f'<p:par><p:cTn id="{cid}" presetID="10" presetClass="entr" presetSubtype="0" '
        f'fill="hold" grpId="0" nodeType="{node_type}">'
        f'<p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
        f'<p:set><p:cBhvr><p:cTn id="{cid + 1}" dur="1" fill="hold">'
        f'<p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>'
        f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>'
        f'<p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>'
        f'<p:to><p:strVal val="visible"/></p:to></p:set>'
        f'<p:animEffect transition="in" filter="fade"><p:cBhvr>'
        f'<p:cTn id="{cid + 2}" dur="{dur_ms}"/>'
        f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl></p:cBhvr></p:animEffect>'
        f'</p:childTnLst></p:cTn></p:par>'
    )


def build_timing(clicks):
    """clicks: list of (shape_ids, duration_ms); each entry = one click step."""
    xml, cid = TIMING_TEMPLATE_HEAD, 3
    for shape_ids, dur_ms in clicks:
        xml += (f'<p:par><p:cTn id="{cid}" fill="hold">'
                f'<p:stCondLst><p:cond delay="indefinite"/></p:stCondLst><p:childTnLst>')
        cid += 1
        xml += (f'<p:par><p:cTn id="{cid}" fill="hold">'
                f'<p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>')
        cid += 1
        for j, spid in enumerate(shape_ids):
            xml += effect_par(cid, spid, "clickEffect" if j == 0 else "withEffect",
                              dur_ms=dur_ms)
            cid += 3
        xml += '</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>'
    bld = ('<p:bldLst>' + ''.join(
        f'<p:bldP spid="{s}" grpId="0"/>' for c, _ in clicks for s in c) + '</p:bldLst>')
    return xml + TIMING_TEMPLATE_TAIL.format(bld=bld)


def visible_ids_for_state(spec, state):
    """Entrance-only visibility model: an element is visible at state k if it
    isn't animated at all, or its earliest entrance step is <= k. (Phase 2
    will need to extend this once exit/emphasis effects exist.)
    """
    earliest_step = {}
    for step in spec.get("animations", []):
        for t in step["targets"]:
            earliest_step[t] = min(earliest_step.get(t, step["step"]), step["step"])
    all_ids = ({e["id"] for e in spec["elements"]}
               | {b["id"] for b in spec.get("image_briefs", [])})
    if state is None:
        return all_ids
    return {i for i in all_ids if i not in earliest_step or earliest_step[i] <= state}


def stamp_doc_props(prs, spec, n_slides=1):
    """Professional package metadata: without this, every deliverable ships
    python-pptx's frozen boilerplate ('Steve Canny', 2013 dates, 'generated
    using python-pptx', 'On-screen Show (4:3)', 'Slides: 0')."""
    dp = spec.get("meta", {}).get("doc_props", {})
    core = prs.core_properties
    core.title = dp.get("title", "")
    core.author = dp.get("author", "")
    core.subject = dp.get("subject", "")
    core.last_modified_by = dp.get("author", "")
    spec_hash = hashlib.sha256(
        json.dumps(spec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    core.comments = f"built by pptx2 build_deck.py; spec sha256:{spec_hash}"
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    core.created = now
    core.modified = now
    core.revision = 1

    # p:sldSz keeps type="screen4x3" from the stock scaffold even at 16:9
    sldSz = prs.slides._sldIdLst.getparent().find(P_NS + "sldSz")
    if sldSz is not None and "type" in sldSz.attrib:
        del sldSz.attrib["type"]

    # docProps/app.xml is a plain (non-XML-mapped) part in python-pptx
    ratio = spec["slide"]["width_emu"] / spec["slide"]["height_emu"]
    if abs(ratio - 16 / 9) < 0.01:
        fmt = "On-screen Show (16:9)"
    elif abs(ratio - 4 / 3) < 0.01:
        fmt = "On-screen Show (4:3)"
    else:
        fmt = "Custom"
    for part in prs.part.package.iter_parts():
        if str(part.partname) == "/docProps/app.xml":
            root = etree.fromstring(part.blob)
            for tag, val in ((EP_NS + "Slides", str(n_slides)),
                             (EP_NS + "PresentationFormat", fmt),
                             (EP_NS + "Application", "pptx2 (python-pptx)")):
                el = root.find(tag)
                if el is not None:
                    el.text = val
            part._blob = etree.tostring(root, xml_declaration=True,
                                        encoding="UTF-8", standalone=True)


PLACEHOLDER_FILL = "C9C2B8"
PLACEHOLDER_INK = "4A443C"


def build_brief_placeholder(slide, brief):
    """Dev-render stand-in for an unfilled, unacknowledged image brief.
    Deliberately unmissable; lint_render blocks shipping it. Fixed neutral
    styling — this is tooling output, not a design decision."""
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, *emu_box(brief["box"]))
    shp.shadow.inherit = False
    shp.fill.solid()
    shp.fill.fore_color.rgb = RGBColor.from_string(PLACEHOLDER_FILL)
    shp.line.color.rgb = RGBColor.from_string(PLACEHOLDER_INK)
    shp.line.width = Pt(1.0)
    tf = shp.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = (f"IMAGE BRIEF '{brief['id']}': {brief['subject']} "
                f"[{brief['aspect']}, {brief['medical_class']}] -> {brief['asset']}")
    style_run(run, {"font": "Arial", "size_pt": 12,
                    "color": PLACEHOLDER_INK, "bold": True})
    return shp


def add_slide_from_spec(prs, spec, state=None, project_root=PROJECT_ROOT,
                        media_opt=None):
    """Append one slide described by a slide spec to an open presentation."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    if media_opt is None:
        media_opt = spec.get("packaging", {}).get("media_optimization")

    if spec.get("background"):
        add_picture_fitted(slide, str(project_root / spec["background"]["asset"]),
                           spec["background"]["box"], fit="stretch",
                           media_opt=media_opt)

    acknowledged = set(spec.get("meta", {}).get("acknowledged_briefs", []))
    renderables = list(spec["elements"])
    for brief in spec.get("image_briefs", []):
        if (project_root / brief["asset"]).is_file():
            renderables.append({"id": brief["id"], "type": "image",
                                "asset": brief["asset"], "box": brief["box"],
                                "z": brief.get("z", 0),
                                "fit": brief.get("fit", "cover"),
                                "anchor": brief.get("anchor", "center")})
        elif brief["id"] not in acknowledged:
            renderables.append({"id": brief["id"], "type": "_brief_placeholder",
                                "z": brief.get("z", 0), "box": brief["box"],
                                "_brief": brief})
        # acknowledged + missing: ships without it, on purpose

    visible = visible_ids_for_state(spec, state)
    shape_id_by_el = {}
    for el in sorted(renderables, key=lambda e: e.get("z", 0)):
        if el["id"] not in visible:
            continue
        if el["type"] == "_brief_placeholder":
            shape_id_by_el[el["id"]] = build_brief_placeholder(slide, el["_brief"]).shape_id
            continue
        if el["type"] == "image":
            shp = add_picture_fitted(slide, str(project_root / el["asset"]), el["box"],
                                      fit=el.get("fit", "stretch"), anchor=el.get("anchor", "center"),
                                      media_opt=media_opt)
        elif el["type"] == "textbox":
            shp = build_textbox(slide, el)
        elif el["type"] == "shape":
            shp = build_shape(slide, el)
        elif el["type"] == "table":
            shp = build_table(slide, el)
        else:
            raise SpecError([f"element '{el['id']}': type '{el['type']}' not implemented"])
        shape_id_by_el[el["id"]] = shp.shape_id

    if state is None:
        clicks = [([shape_id_by_el[t] for t in step["targets"]],
                   step.get("duration_ms", 500))
                  for step in sorted(spec.get("animations", []), key=lambda s: s["step"])]
        if clicks:
            timing = etree.fromstring(build_timing(clicks))
            slide._element.append(timing)
    return slide


def build(spec, state=None, project_root=PROJECT_ROOT):
    """state=None: full deck with animation timing. state=k: static snapshot
    of the deck after animation step k has played.
    """
    prs = Presentation()
    prs.slide_width = Emu(spec["slide"]["width_emu"])
    prs.slide_height = Emu(spec["slide"]["height_emu"])
    add_slide_from_spec(prs, spec, state=state, project_root=project_root)
    stamp_doc_props(prs, spec, n_slides=1)
    return prs


def build_deck(deck, slide_specs, project_root=PROJECT_ROOT):
    """All slides of a deck spec into one presentation, in order."""
    first = slide_specs[0]
    prs = Presentation()
    prs.slide_width = Emu(first["slide"]["width_emu"])
    prs.slide_height = Emu(first["slide"]["height_emu"])
    deck_media_opt = deck.get("packaging", {}).get("media_optimization")
    for spec in slide_specs:
        add_slide_from_spec(prs, spec, state=None, project_root=project_root,
                            media_opt=deck_media_opt)
    stamp_doc_props(prs, deck, n_slides=len(slide_specs))
    return prs


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("spec", type=Path,
                     help="path to a slide spec or deck spec JSON file")
    ap.add_argument("--states", action="store_true",
                     help="also write per-animation-step static snapshot decks")
    ap.add_argument("--check-only", action="store_true", help="validate only, do not build")
    ap.add_argument("--out", type=Path, default=None, help="override output .pptx path")
    args = ap.parse_args()

    spec = json.loads(args.spec.read_text())

    if "deck_version" in spec:
        errors, slide_specs = validate_deck(spec, PROJECT_ROOT)
        if errors:
            print(f"INVALID DECK: {args.spec}", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            return 1
        print(f"valid deck: {args.spec} ({len(slide_specs)} slide(s))")
        if args.check_only:
            return 0
        stem = args.spec.stem.replace(".deck", "")
        out_path = args.out or (OUT / f"{stem}.pptx")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        prs = build_deck(spec, slide_specs)
        prs.save(out_path)
        if spec.get("packaging"):
            apply_packaging(out_path, spec["packaging"], PROJECT_ROOT)
        print("wrote", out_path)
        return 0

    errors = validate_spec(spec, PROJECT_ROOT)
    if errors:
        print(f"INVALID SPEC: {args.spec}", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"valid: {args.spec}")
    if args.check_only:
        return 0

    stem = args.spec.stem.replace(".spec", "")
    out_path = args.out or (OUT / f"{stem}.pptx")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs = build(spec, state=None)
    prs.save(out_path)
    if spec.get("packaging"):
        apply_packaging(out_path, spec["packaging"], PROJECT_ROOT)
    print("wrote", out_path)

    if args.states:
        n_steps = max((s["step"] for s in spec.get("animations", [])), default=0)
        states_dir = OUT / "states" / stem
        states_dir.mkdir(parents=True, exist_ok=True)
        for k in range(1, n_steps + 1):
            prs_k = build(spec, state=k)
            state_path = states_dir / f"state{k}.pptx"
            prs_k.save(state_path)
            if spec.get("packaging"):
                apply_packaging(state_path, spec["packaging"], PROJECT_ROOT)
            print("wrote", state_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
