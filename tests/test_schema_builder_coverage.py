"""Schema↔builder coverage: every field spec.schema.json accepts must be
either observably honored by build_deck.py or loudly rejected by
validate_spec — never silently ignored.

Motivation (docs/IMPROVEMENT_PLAN.md F4): the pipeline's ancestor shipped a
bullet-color parameter that was accepted and did nothing. This suite builds
one maximal spec exercising every schema field and asserts each field's
observable effect in the produced package, so that bug class can't recur.

Documented exemptions (fields that are *specified* as builder-inert):
  - element.role  — semantic tag for cross-slide review, not rendering
  - meta.*        — designer rationale; EXCEPT meta.doc_props (stamped
                    into docProps, asserted below)
"""
import json
import re
import zipfile
from pathlib import Path

import pytest
from PIL import Image

import build_deck


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    """A throwaway project root with tiny generated image assets."""
    root = tmp_path_factory.mktemp("proj")
    (root / "assets").mkdir()
    Image.new("RGBA", (100, 50), (10, 20, 30, 255)).save(root / "assets" / "wide.png")
    Image.new("RGBA", (50, 100), (30, 20, 10, 255)).save(root / "assets" / "tall.png")
    return root


@pytest.fixture(scope="module")
def maximal_spec():
    return {
        "spec_version": 1,
        "meta": {
            "designer_rationale": "coverage fixture",
            "doc_props": {"title": "Talk Title", "author": "Dr. Speaker",
                          "subject": "Coverage"},
        },
        "slide": {"width_emu": 12192000, "height_emu": 6858000},
        "background": {"asset": "assets/wide.png",
                       "box": {"x": 0, "y": 0, "cx": 12192000, "cy": 6858000}},
        "elements": [
            {"id": "img_stretch", "type": "image", "role": "figure", "z": 1,
             "asset": "assets/wide.png", "fit": "stretch",
             "box": {"x": 0, "y": 0, "cx": 1000000, "cy": 1000000}},
            {"id": "img_contain", "type": "image", "z": 2,
             "asset": "assets/tall.png", "fit": "contain", "anchor": "bottom",
             "box": {"x": 1000000, "y": 0, "cx": 1000000, "cy": 1000000}},
            {"id": "img_cover", "type": "image", "z": 3,
             "asset": "assets/wide.png", "fit": "cover",
             "box": {"x": 2000000, "y": 0, "cx": 1000000, "cy": 1000000}},
            {"id": "img_cover_right", "type": "image", "z": 3,
             "asset": "assets/wide.png", "fit": "cover", "anchor": "right",
             "box": {"x": 3200000, "y": 0, "cx": 500000, "cy": 500000}},
            {"id": "img_bleed", "type": "image", "z": 0,
             "asset": "assets/wide.png",
             "box": {"x": -50000, "y": 0, "cx": 1000000, "cy": 1000000,
                     "allow_offslide_bleed": ["left"]}},
            {"id": "txt", "type": "textbox", "z": 4, "wrap": "square",
             "insets_zero": True,
             "box": {"x": 3000000, "y": 1000000, "cx": 4000000, "cy": 3000000},
             "paragraphs": [
                 {"lines": [
                     {"text": "Line one", "font": "Arial", "size_pt": 30,
                      "color": "112233", "bold": True, "tracking_pt": 2.5},
                     {"text": "Line two", "font": "Arial", "size_pt": 30,
                      "color": "112233"}],
                  "line_spacing_pt": 34.5},
                 {"lines": [{"text": "Bullet text", "font": "Arial",
                             "size_pt": 14, "color": "445566"}],
                  "space_before_pt": 8,
                  "bullet": {"char": "-", "hang_emu": 137160,
                             "font": "Arial", "color": "ABCDEF"}},
             ]},
            {"id": "shp_grad", "type": "shape", "z": 5,
             "shape_type": "ellipse",
             "fill": {"color": "AA0000", "color2": "00AA00",
                      "gradient_angle": 45.0},
             "box": {"x": 8000000, "y": 1000000, "cx": 500000, "cy": 500000}},
            {"id": "shp_line", "type": "shape", "z": 6,
             "shape_type": "rounded_rectangle",
             "fill": {"color": "0000AA"},
             "line": {"color": "FF00FF", "width_pt": 2.0},
             "box": {"x": 9000000, "y": 1000000, "cx": 500000, "cy": 500000}},
            {"id": "tbl", "type": "table", "z": 7,
             "box": {"x": 500000, "y": 4500000, "cx": 3000000, "cy": 1500000},
             "table": {
                 "columns_emu": [1500000, 1500000],
                 "rows": [["Показник", "Значення"],
                          ["A", "1"],
                          ["B", "2"]],
                 "header": True,
                 "row_height_emu": 500000,
                 "style": {"font": "Arial", "size_pt": 12,
                           "text_color": "222222", "header_fill": "6A5337",
                           "header_color": "FAF5E8", "header_bold": True,
                           "alt_row_fill": "EEEEEE",
                           "border_color": "A68A69", "border_pt": 1.0}}},
        ],
        "animations": [
            {"step": 1, "targets": ["txt"], "effect": "fade",
             "duration_ms": 700},
        ],
    }


@pytest.fixture(scope="module")
def built(project, maximal_spec, tmp_path_factory):
    errors = build_deck.validate_spec(maximal_spec, project_root=project)
    assert errors == [], f"maximal spec must validate: {errors}"
    prs = build_deck.build(maximal_spec, project_root=project)
    out = tmp_path_factory.mktemp("out") / "maximal.pptx"
    prs.save(out)
    slide_xml = re.sub(r">\s+<", "><", prs.slides[0]._element.xml)
    return prs, out, slide_xml


def test_run_styling_fields(built):
    _, _, xml = built
    assert 'sz="3000"' in xml           # size_pt
    assert 'b="1"' in xml               # bold
    assert 'val="112233"' in xml        # color
    assert 'spc="250"' in xml           # tracking_pt -> rPr/@spc
    assert 'typeface="Arial"' in xml    # font


def test_paragraph_fields(built):
    _, _, xml = built
    assert '<a:lnSpc><a:spcPts val="3450"/>' in xml   # line_spacing_pt
    assert '<a:spcBef><a:spcPts val="800"/>' in xml   # space_before_pt
    assert xml.count("<a:br/>") == 1                  # lines joined by <a:br>


def test_bullet_fields_including_color(built):
    """F4 regression: bullet color must actually reach the XML."""
    _, _, xml = built
    assert 'marL="137160"' in xml and 'indent="-137160"' in xml  # hang_emu
    assert '<a:buChar char="-"/>' in xml
    assert '<a:buFont typeface="Arial"/>' in xml
    assert '<a:buClr><a:srgbClr val="ABCDEF"/></a:buClr>' in xml
    # OOXML child order: buClr must precede buFont/buChar
    assert xml.index("a:buClr") < xml.index("a:buFont")


def test_textbox_body_fields(built):
    _, _, xml = built
    assert 'wrap="square"' in xml
    assert 'lIns="0"' in xml and 'bIns="0"' in xml    # insets_zero


def test_image_fit_modes(built):
    prs, _, xml = built
    shapes = {s.name: s for s in prs.slides[0].shapes}
    by_offset = {(s.left, s.top): s for s in prs.slides[0].shapes
                 if s.shape_type is not None}
    # contain: tall image (1:2) in square box, anchored bottom ->
    # width halves, bottom edge stays at box bottom
    contain = next(s for s in prs.slides[0].shapes
                   if s.left == 1250000 and s.width == 500000)
    assert contain.height == 1000000
    assert contain.top + contain.height == 1000000  # bottom-anchored
    # cover: wide image (2:1) center-cropped left/right, box kept exact
    assert 'srcRect l="25000" r="25000"' in xml
    # cover + anchor:right — the right side survives, all crop on the left
    # (this was a schema-promised field the builder silently ignored)
    assert 'srcRect l="50000"/>' in xml


def test_shape_fill_gradient_and_line(built):
    _, _, xml = built
    assert "<a:gradFill" in xml
    assert 'val="AA0000"' in xml and 'val="00AA00"' in xml
    assert "prstGeom prst=\"ellipse\"" in xml
    assert "prstGeom prst=\"roundRect\"" in xml
    assert 'val="FF00FF"' in xml        # line color
    assert 'w="25400"' in xml           # line width 2pt in EMU


def test_z_order(built):
    """Elements must enter the shape tree by ascending z, not spec order.
    img_bleed (z=0) is declared AFTER img_stretch/img_contain/img_cover in
    the spec but must render beneath them — identify each picture by its
    unique x offset in the serialized tree."""
    _, _, xml = built
    assert xml.index('x="-50000"') < xml.index('x="1250000"')  # z0 before z2
    # txt (z=4) precedes the gradient ellipse (z=5)
    assert xml.index('wrap="square"') < xml.index("<a:gradFill")


def test_table_fields(built):
    _, _, xml = built
    assert "<a:tbl>" in xml
    assert xml.count('<a:gridCol w="1500000"') == 2      # columns_emu
    assert "Показник" in xml and "Значення" in xml       # header row text
    # header fill + header text color + bold
    assert 'val="6A5337"' in xml and 'val="FAF5E8"' in xml
    # alternating data-row fill
    assert 'val="EEEEEE"' in xml
    # grid borders: width 1pt = 12700 EMU on lnL/lnR/lnT/lnB
    assert '<a:lnL w="12700"' in xml and '<a:lnB w="12700"' in xml
    assert 'val="A68A69"' in xml
    # banding flags killed so spec styling is the only styling
    assert 'firstRow="1"' not in xml


def test_animation_duration_reaches_timing_xml(built):
    """duration_ms was a silently-dead schema field before this test."""
    _, _, xml = built
    assert 'dur="700"' in xml
    assert 'dur="500"' not in xml


def test_doc_props_stamped(built, maximal_spec):
    prs, out, _ = built
    core = prs.core_properties
    assert core.title == "Talk Title"
    assert core.author == "Dr. Speaker"
    assert core.subject == "Coverage"
    assert core.last_modified_by == "Dr. Speaker"
    assert "spec sha256:" in core.comments
    assert core.created.year >= 2026   # not the 2013 boilerplate
    with zipfile.ZipFile(out) as z:
        app = z.read("docProps/app.xml").decode()
        core_xml = z.read("docProps/core.xml").decode()
        pres = z.read("ppt/presentation.xml").decode()
    assert "<Slides>1</Slides>" in app
    assert "On-screen Show (16:9)" in app
    assert "Steve Canny" not in core_xml
    assert "generated using python-pptx" not in core_xml
    assert 'type="screen4x3"' not in pres


def test_unimplemented_fields_reject_loudly(project, maximal_spec):
    """Reserved/unimplemented schema constructs must fail validation, not
    silently no-op."""
    import copy
    for mutate, needle in [
        (lambda s: s["elements"].append(
            {"id": "cht", "type": "chart",
             "box": {"x": 0, "y": 0, "cx": 100, "cy": 100}}), "reserved"),
        (lambda s: s["animations"].append(
            {"step": 2, "targets": ["txt"], "effect": "wipe"}), "not yet implemented"),
        (lambda s: s["animations"].append(
            {"step": 2, "targets": ["txt"], "effect": "fade",
             "trigger": "with_previous"}), "trigger"),
        (lambda s: s["animations"].append(
            {"step": 2, "targets": ["txt"], "effect": "fade",
             "direction": "left"}), "direction"),
        (lambda s: s["elements"][0]["box"].pop("allow_offslide_bleed", None)
            or s["elements"][0]["box"].update(x=-1), "allow_offslide_bleed"),
    ]:
        spec = copy.deepcopy(maximal_spec)
        mutate(spec)
        errors = build_deck.validate_spec(spec, project_root=project)
        assert any(needle in e for e in errors), \
            f"expected a loud rejection mentioning '{needle}', got: {errors}"
