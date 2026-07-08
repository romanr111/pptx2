"""Behavioral tests for reference_style.py — the design-reference ingestion
path (advisory facts from a PDF look-and-feel reference).

Contract under test: extract_reference(pdf, event, out_json, thumbs_dir,
assets_dir) writes out a design_reference JSON (a contract deliberately
separate from template_style.json), per-page thumbnails, and harvested
images with provenance sidecars carrying the licensing guard.

Fixture: a synthetic 2-page PDF built with PyMuPDF so tests are fast and
independent of gitignored client materials.
"""
import io
import json
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

PAGE_W_PT, PAGE_H_PT = 960, 540  # 16:9
BRAND_HEX = "1c4587"  # dominant painted color on page 1


@pytest.fixture(scope="module")
def reference_pdf(tmp_path_factory):
    """Two 16:9 pages: page 1 mostly one brand color + text; page 2 embeds
    a small raster image (a stand-in for a harvestable logo)."""
    pdf_path = tmp_path_factory.mktemp("ref") / "synthetic_reference.pdf"
    doc = pymupdf.open()

    page1 = doc.new_page(width=PAGE_W_PT, height=PAGE_H_PT)
    r, g, b = (0x1C / 255, 0x45 / 255, 0x87 / 255)
    page1.draw_rect(pymupdf.Rect(0, 0, PAGE_W_PT, PAGE_H_PT), color=None,
                    fill=(r, g, b))
    page1.insert_text((100, 100), "Dental Clinic 2026", fontsize=40,
                      fontname="helv", color=(1, 1, 1))

    page2 = doc.new_page(width=PAGE_W_PT, height=PAGE_H_PT)
    img = Image.new("RGB", (64, 48), (200, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    page2.insert_image(pymupdf.Rect(50, 50, 178, 146), stream=buf.getvalue())

    doc.save(pdf_path)
    doc.close()
    return pdf_path


@pytest.fixture()
def extraction(reference_pdf, tmp_path):
    from reference_style import extract_reference
    out_json = tmp_path / "out" / "design_reference.json"
    thumbs_dir = tmp_path / "out" / "thumbnails" / "reference" / "dental"
    assets_dir = tmp_path / "assets" / "reference" / "dental"
    result = extract_reference(reference_pdf, event="dental",
                               out_json=out_json, thumbs_dir=thumbs_dir,
                               assets_dir=assets_dir)
    return result, out_json, thumbs_dir, assets_dir


def test_writes_design_reference_contract(extraction):
    result, out_json, _, _ = extraction
    assert out_json.is_file()
    on_disk = json.loads(out_json.read_text())
    assert on_disk == result
    # the contract is self-identifying and explicitly advisory, so it can
    # never be mistaken for the authoritative .pptx template facts
    assert on_disk["contract"] == "design_reference"
    assert on_disk["authority"] == "advisory"
    assert on_disk["event"] == "dental"
    assert on_disk["n_pages"] == 2


def test_page_geometry_in_emu(extraction):
    result, _, _, _ = extraction
    size = result["page_size"]
    assert size["width_pt"] == PAGE_W_PT
    assert size["height_pt"] == PAGE_H_PT
    assert size["width_emu"] == PAGE_W_PT * 12700
    assert size["height_emu"] == PAGE_H_PT * 12700


def test_renders_one_thumbnail_per_page(extraction):
    result, _, thumbs_dir, _ = extraction
    thumbs = sorted(thumbs_dir.glob("page-*.png"))
    assert len(thumbs) == 2
    with Image.open(thumbs[0]) as im:
        w, h = im.size
    assert w >= 800  # readable for by-eye catalog work
    assert abs(w / h - PAGE_W_PT / PAGE_H_PT) < 0.02
    recorded = [p["thumbnail"] for p in result["pages"]]
    assert [str(t) for t in thumbs] == recorded


def test_extracts_dominant_palette(extraction):
    result, _, _, _ = extraction
    page1 = result["pages"][0]
    top = page1["palette"][0]
    # dominant color of page 1 is the painted brand blue
    got = int(top["hex"], 16)
    want = int(BRAND_HEX, 16)
    for shift in (16, 8, 0):
        assert abs(((got >> shift) & 0xFF) - ((want >> shift) & 0xFF)) <= 8
    assert top["frac"] > 0.5


def test_collects_font_names_without_subset_prefix(extraction):
    result, _, _, _ = extraction
    fonts = result["fonts_all"]
    assert fonts, "expected at least the fixture's text font"
    assert all("+" not in f for f in fonts)


def test_harvests_images_with_licensing_sidecar(extraction):
    result, _, _, assets_dir = extraction
    harvested = result["harvested_images"]
    assert len(harvested) == 1
    entry = harvested[0]
    img_path = Path(entry["path"])
    assert img_path.is_file() and img_path.parent == assets_dir
    with Image.open(img_path) as im:
        assert im.size == (64, 48)
    sidecar = json.loads(Path(entry["provenance"]).read_text())
    assert sidecar["page"] == 2
    assert Path(sidecar["source_pdf"]).name == "synthetic_reference.pdf"
    # the licensing note must travel with every harvested asset
    assert "presumed cleared" in sidecar["license"].lower()
    assert "watermark" in sidecar["license"].lower()
