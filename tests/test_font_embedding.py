"""Font embedding: fntdata parts + embeddedFontLst wiring + license gate."""
import zipfile
from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from pptx import Presentation

import build_deck
import lint_render
from native_packaging import apply_packaging

MINIMAL_SPEC = {
    "spec_version": 1,
    "slide": {"width_emu": 12192000, "height_emu": 6858000},
    "elements": [
        {"id": "t", "type": "textbox",
         "box": {"x": 0, "y": 0, "cx": 1000000, "cy": 500000},
         "paragraphs": [{"lines": [{"text": "x", "font": "TestFace",
                                    "size_pt": 12, "color": "000000"}]}]},
    ],
}


def _make_ttf(path):
    """Minimal valid TTF via fontTools (hermetic, no repo/system fonts)."""
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "x"])
    fb.setupCharacterMap({ord("x"): "x"})
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0)); pen.lineTo((0, 700)); pen.lineTo((500, 700))
    pen.lineTo((500, 0)); pen.closePath()
    glyph = pen.glyph()
    fb.setupGlyf({".notdef": glyph, "x": glyph})
    fb.setupHorizontalMetrics({".notdef": (600, 0), "x": (600, 50)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "TestFace", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    fb.save(str(path))
    return path


@pytest.fixture()
def project(tmp_path):
    fonts = tmp_path / "assets" / "fonts" / "test"
    fonts.mkdir(parents=True)
    _make_ttf(fonts / "TestFace-Regular.ttf")
    _make_ttf(fonts / "TestFace-Bold.ttf")
    return tmp_path


def _packaging():
    return {"embed_fonts": [
        {"family": "TestFace",
         "regular": "assets/fonts/test/TestFace-Regular.ttf",
         "bold": "assets/fonts/test/TestFace-Bold.ttf"}]}


def test_fonts_embedded_and_wired(project, tmp_path):
    spec = dict(MINIMAL_SPEC, packaging=_packaging())
    assert build_deck.validate_spec(spec, project_root=project) == []
    out = tmp_path / "embedded.pptx"
    build_deck.build(spec, project_root=project).save(out)
    apply_packaging(out, spec["packaging"], project)

    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        pres = z.read("ppt/presentation.xml").decode()
        rels = z.read("ppt/_rels/presentation.xml.rels").decode()
        cts = z.read("[Content_Types].xml").decode()
        font1 = z.read("ppt/fonts/font1.fntdata")

    assert "ppt/fonts/font1.fntdata" in names and "ppt/fonts/font2.fntdata" in names
    assert font1[:4] == b"\x00\x01\x00\x00"          # raw TTF, not obfuscated
    assert 'embedTrueTypeFonts="1"' in pres
    assert '<p:font typeface="TestFace"/>' in pres.replace("\n", "")
    assert "<p:regular" in pres and "<p:bold" in pres
    assert 'Extension="fntdata"' in cts
    assert 'Target="fonts/font1.fntdata"' in rels
    # embeddedFontLst must come after notesSz per CT_Presentation order
    assert pres.index("notesSz") < pres.index("embeddedFontLst")
    assert Presentation(out).slides is not None      # package still opens


def test_missing_font_file_is_validation_error(project):
    pkg = _packaging()
    pkg["embed_fonts"][0]["bold"] = "assets/fonts/test/Nope.ttf"
    spec = dict(MINIMAL_SPEC, packaging=pkg)
    errors = build_deck.validate_spec(spec, project_root=project)
    assert any("Nope.ttf" in e for e in errors)


def test_license_gate_warns_without_evidence_and_passes_with(project):
    spec = dict(MINIMAL_SPEC, packaging=_packaging())
    findings = []
    lint_render.check_embed_font_licenses(spec, findings, project_root=project)
    assert any(f["check"] == "embed_font_license" and f["severity"] == "warn"
               for f in findings)

    (project / "assets" / "fonts" / "test" / "OFL.txt").write_text("SIL OFL 1.1")
    findings = []
    lint_render.check_embed_font_licenses(spec, findings, project_root=project)
    assert findings == []
