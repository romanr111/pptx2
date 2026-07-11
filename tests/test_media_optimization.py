"""Media optimization (forensic F5): baked crops, DPI downscale, alpha
preservation — strictly opt-in, originals untouched."""
import re
import zipfile
from pathlib import Path

import pytest
from PIL import Image

import build_deck


def _spec(fit, media_opt=None, box=None):
    spec = {
        "spec_version": 1,
        "slide": {"width_emu": 12192000, "height_emu": 6858000},
        "elements": [
            {"id": "img", "type": "image", "asset": "assets/big.png",
             "fit": fit,
             "box": box or {"x": 0, "y": 0, "cx": 2000000, "cy": 2000000}},
        ],
    }
    if media_opt is not None:
        spec["packaging"] = {"media_optimization": media_opt}
    return spec


@pytest.fixture()
def project(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    Image.new("RGB", (4000, 3000), (10, 120, 200)).save(tmp_path / "assets/big.png")
    monkeypatch.setattr(build_deck, "MEDIA_CACHE", tmp_path / "cache")
    return tmp_path


def _built_media(spec, project, tmp_path):
    out = tmp_path / "m.pptx"
    build_deck.build(spec, project_root=project).save(out)
    with zipfile.ZipFile(out) as z:
        media = [n for n in z.namelist() if n.startswith("ppt/media/")]
        blobs = {n: z.read(n) for n in media}
        xml = re.sub(rb">\s+<", b"><", z.read("ppt/slides/slide1.xml"))
    return blobs, xml


def test_default_is_byte_faithful(project, tmp_path):
    blobs, xml = _built_media(_spec("cover"), project, tmp_path)
    original = (project / "assets/big.png").read_bytes()
    assert list(blobs.values())[0] == original          # untouched bytes
    assert b"srcRect" in xml                             # metadata crop


def test_cover_crop_baked_and_downscaled(project, tmp_path):
    blobs, xml = _built_media(
        _spec("cover", media_opt={"dpi_budget": 150}), project, tmp_path)
    assert b"srcRect" not in xml                         # crop baked to pixels
    blob = list(blobs.values())[0]
    import io
    with Image.open(io.BytesIO(blob)) as im:
        w, h = im.size
        # square box at 2000000 EMU = 2.19in -> ~328px at 150dpi
        assert abs(w / h - 1.0) < 0.01                   # baked to box aspect
        assert w < 500                                   # actually downscaled
    original = (project / "assets/big.png").read_bytes()
    assert len(blob) < len(original) / 10
    # original asset untouched on disk
    assert (project / "assets/big.png").read_bytes() == original


def test_empty_dict_opts_in_with_defaults(project, tmp_path):
    """packaging.media_optimization: {} is schema-legal ("enable with
    defaults") -- `if media_opt:` treated it as falsy and silently
    skipped optimization; it must behave like an explicit default dict."""
    blobs, xml = _built_media(_spec("cover", media_opt={}), project, tmp_path)
    assert b"srcRect" not in xml                         # crop baked to pixels
    original = (project / "assets/big.png").read_bytes()
    assert len(list(blobs.values())[0]) < len(original) / 10


def test_alpha_preserved_as_png(project, tmp_path):
    Image.new("RGBA", (3000, 3000), (10, 120, 200, 128)).save(
        project / "assets/big.png")
    blobs, _ = _built_media(
        _spec("stretch", media_opt={"dpi_budget": 96}), project, tmp_path)
    name, blob = next(iter(blobs.items()))
    assert name.endswith(".png")
    import io
    with Image.open(io.BytesIO(blob)) as im:
        assert im.mode == "RGBA"


def test_small_images_left_alone_even_when_enabled(project, tmp_path):
    Image.new("RGB", (300, 300), (1, 2, 3)).save(project / "assets/big.png")
    blobs, _ = _built_media(
        _spec("stretch", media_opt={"dpi_budget": 200}), project, tmp_path)
    assert list(blobs.values())[0] == (project / "assets/big.png").read_bytes()
