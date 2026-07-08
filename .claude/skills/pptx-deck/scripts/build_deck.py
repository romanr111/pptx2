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
import json
import sys
from pathlib import Path

import jsonschema
from lxml import etree
from PIL import Image as PILImage
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Emu, Pt

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = PROJECT_ROOT / "specs" / "spec.schema.json"
OUT = PROJECT_ROOT / "output"

A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


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

    ids = [e["id"] for e in spec["elements"]]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        errors.append(f"duplicate element id(s): {sorted(dupes)}")
    id_set = set(ids)

    for el in spec["elements"]:
        if el["type"] == "image":
            asset_path = project_root / el["asset"]
            if not asset_path.is_file():
                errors.append(f"element '{el['id']}': asset not found: {el['asset']}")
        if el["type"] in ("table", "chart"):
            errors.append(f"element '{el['id']}': type '{el['type']}' is reserved, "
                           f"not implemented by build_deck.py yet")

    if spec.get("background"):
        bg_path = project_root / spec["background"]["asset"]
        if not bg_path.is_file():
            errors.append(f"background: asset not found: {spec['background']['asset']}")

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

    for step in spec.get("animations", []):
        for t in step["targets"]:
            if t not in id_set:
                errors.append(f"animation step {step['step']}: unknown target id '{t}'")
        if step["effect"] != "fade":
            errors.append(f"animation step {step['step']}: effect '{step['effect']}' "
                           f"not yet implemented by build_deck.py (fade only for now)")

    return errors


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


def add_picture_fitted(slide, path, box, fit="stretch", anchor="center"):
    """fit:"stretch" (default) preserves the exact prior behavior (always
    stretch to box.cx/cy). fit:"contain" places the image at its natural
    aspect ratio, anchored within the box (letterboxed, never distorted).
    fit:"cover" fills the box exactly via python-pptx's crop_* properties
    (symmetric center crop), never distorted either.
    """
    if fit == "stretch":
        return slide.shapes.add_picture(path, *emu_box(box))
    with PILImage.open(path) as img:
        iw, ih = img.size
    if fit == "contain":
        return slide.shapes.add_picture(path, *emu_box(contain_box(box, iw, ih, anchor)))
    # fit == "cover"
    pic = slide.shapes.add_picture(path, *emu_box(box))
    img_aspect, box_aspect = iw / ih, box["cx"] / box["cy"]
    if img_aspect > box_aspect:
        crop = (1 - box_aspect / img_aspect) / 2
        pic.crop_left, pic.crop_right = crop, crop
    else:
        crop = (1 - img_aspect / box_aspect) / 2
        pic.crop_top, pic.crop_bottom = crop, crop
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


def effect_par(cid, spid, node_type, dur_ms=500):
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
    """clicks: list of lists of shape ids; each inner list = one click step."""
    xml, cid = TIMING_TEMPLATE_HEAD, 3
    for shape_ids in clicks:
        xml += (f'<p:par><p:cTn id="{cid}" fill="hold">'
                f'<p:stCondLst><p:cond delay="indefinite"/></p:stCondLst><p:childTnLst>')
        cid += 1
        xml += (f'<p:par><p:cTn id="{cid}" fill="hold">'
                f'<p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>')
        cid += 1
        for j, spid in enumerate(shape_ids):
            xml += effect_par(cid, spid, "clickEffect" if j == 0 else "withEffect")
            cid += 3
        xml += '</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>'
    bld = ('<p:bldLst>' + ''.join(
        f'<p:bldP spid="{s}" grpId="0"/>' for c in clicks for s in c) + '</p:bldLst>')
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
    all_ids = {e["id"] for e in spec["elements"]}
    if state is None:
        return all_ids
    return {i for i in all_ids if i not in earliest_step or earliest_step[i] <= state}


def build(spec, state=None, project_root=PROJECT_ROOT):
    """state=None: full deck with animation timing. state=k: static snapshot
    of the deck after animation step k has played.
    """
    prs = Presentation()
    prs.slide_width = Emu(spec["slide"]["width_emu"])
    prs.slide_height = Emu(spec["slide"]["height_emu"])
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank

    if spec.get("background"):
        slide.shapes.add_picture(str(project_root / spec["background"]["asset"]),
                                  *emu_box(spec["background"]["box"]))

    visible = visible_ids_for_state(spec, state)
    shape_id_by_el = {}
    for el in sorted(spec["elements"], key=lambda e: e.get("z", 0)):
        if el["id"] not in visible:
            continue
        if el["type"] == "image":
            shp = add_picture_fitted(slide, str(project_root / el["asset"]), el["box"],
                                      fit=el.get("fit", "stretch"), anchor=el.get("anchor", "center"))
        elif el["type"] == "textbox":
            shp = build_textbox(slide, el)
        elif el["type"] == "shape":
            shp = build_shape(slide, el)
        else:
            raise SpecError([f"element '{el['id']}': type '{el['type']}' not implemented"])
        shape_id_by_el[el["id"]] = shp.shape_id

    if state is None:
        clicks = [[shape_id_by_el[t] for t in step["targets"]]
                  for step in sorted(spec.get("animations", []), key=lambda s: s["step"])]
        if clicks:
            timing = etree.fromstring(build_timing(clicks))
            slide._element.append(timing)

    return prs


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("spec", type=Path, help="path to a slide spec JSON file")
    ap.add_argument("--states", action="store_true",
                     help="also write per-animation-step static snapshot decks")
    ap.add_argument("--check-only", action="store_true", help="validate only, do not build")
    ap.add_argument("--out", type=Path, default=None, help="override output .pptx path")
    args = ap.parse_args()

    spec = json.loads(args.spec.read_text())
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
    print("wrote", out_path)

    if args.states:
        n_steps = max((s["step"] for s in spec.get("animations", [])), default=0)
        states_dir = OUT / "states" / stem
        states_dir.mkdir(parents=True, exist_ok=True)
        for k in range(1, n_steps + 1):
            prs_k = build(spec, state=k)
            state_path = states_dir / f"state{k}.pptx"
            prs_k.save(state_path)
            print("wrote", state_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
