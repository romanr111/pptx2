"""Item 1: the full template media census must surface EVERY embedded image
(all formats, including media referenced by no slide) so the designer never
sees a ranked/logo-filtered subset -- that filter once hid the template's
premium white-studio `.jpg` renders.
"""
import io
import zipfile

from PIL import Image

import template_style


def _img_bytes(fmt, color, size=(8, 8)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


def test_media_census_extracts_all_formats_and_builds_sheet(tmp_path):
    zpath = tmp_path / "template.pptx"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("ppt/media/image1.png", _img_bytes("PNG", (200, 30, 30)))
        z.writestr("ppt/media/image2.jpg", _img_bytes("JPEG", (30, 200, 30)))
        z.writestr("ppt/media/image3.bmp", _img_bytes("BMP", (30, 30, 200)))
        z.writestr("ppt/media/image4.emf", b"not-a-raster")   # excluded by regex
        z.writestr("ppt/slides/slide1.xml", "<p:sld/>")        # not media

    slide_media_map = {"ppt/slides/slide1.xml": ["ppt/media/image1.png"]}
    out_dir = tmp_path / "census"
    sheet = tmp_path / "census.png"

    with zipfile.ZipFile(zpath) as z:
        census = template_style.dump_media_census(
            z, z.namelist(), slide_media_map, out_dir=out_dir, sheet_path=sheet)

    names = {e["media"].split("/")[-1] for e in census}
    # png AND jpg AND bmp all present; the .emf and the slide xml are not media
    assert names == {"image1.png", "image2.jpg", "image3.bmp"}
    for base in names:
        assert (out_dir / base).is_file()
    assert sheet.is_file()

    by_file = {e["media"]: e for e in census}
    # reuse count comes from slide_media_map: image1 used once, image2 by no slide
    assert by_file["ppt/media/image1.png"]["n_slides_used"] == 1
    assert by_file["ppt/media/image1.png"]["used_on_slides"] == ["slide1.xml"]
    assert by_file["ppt/media/image2.jpg"]["n_slides_used"] == 0
    assert by_file["ppt/media/image2.jpg"]["size"] == [8, 8]


def test_media_census_wired_into_template_style_json(tmp_path, monkeypatch):
    """extract() records media_census + media_census_sheet in the facts dict."""
    zpath = tmp_path / "template.pptx"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("ppt/media/image9.jpg", _img_bytes("JPEG", (10, 10, 10)))

    captured = {}

    def fake_dump(z, names, slide_media_map, **kwargs):
        captured["called"] = True
        return [{"media": "ppt/media/image9.jpg"}]

    # isolate: stub the heavy pptx/zip-walk helpers, keep dump_media_census wiring
    monkeypatch.setattr(template_style, "dump_media_census", fake_dump)
    monkeypatch.setattr(template_style, "Presentation", lambda p: _FakePrs())
    monkeypatch.setattr(template_style, "extract_layout_geometry", lambda prs: [])
    monkeypatch.setattr(template_style, "infer_margins", lambda layouts: {})
    monkeypatch.setattr(template_style, "extract_themes", lambda z, n: [])
    monkeypatch.setattr(template_style, "rank_slide_usage",
                        lambda z, n: (_C(), _C(), {}))
    monkeypatch.setattr(template_style, "flag_font_mixing", lambda p, t: [])
    monkeypatch.setattr(template_style, "classify_logo_media", lambda z, n: [])
    monkeypatch.setattr(template_style, "extract_animation_exemplars", lambda z, n: [])
    monkeypatch.setattr(template_style, "map_slides_to_media", lambda z, n: {})
    monkeypatch.setattr(template_style, "rank_media_reuse", lambda m: [])
    monkeypatch.setattr(template_style, "map_slides_to_layouts", lambda z, n, l: {})
    monkeypatch.setattr(template_style, "_file_hash", lambda p: "hash")

    style = template_style.extract(zpath, with_thumbnails=False)

    assert captured.get("called")
    assert style["media_census"] == [{"media": "ppt/media/image9.jpg"}]
    assert style["media_census_sheet"] == "out/media_census.png"


class _FakePrs:
    slide_width = 12192000
    slide_height = 6858000


class _C(dict):
    def most_common(self, n=None):
        return []
