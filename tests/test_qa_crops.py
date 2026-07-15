from pathlib import Path
import json

from PIL import Image
import pytest

import qa_crops


PROJECT_ROOT = Path(__file__).resolve().parents[1]
QA_CROPS_SCRIPT = (
    PROJECT_ROOT / ".claude" / "skills" / "pptx-deck" / "scripts"
    / "qa_crops.py"
)


def test_qa_crops_tool_is_available():
    assert QA_CROPS_SCRIPT.is_file()


def _crop_fixture(tmp_path, dimensions):
    project = tmp_path / "project"
    assets = project / "assets"
    specs = project / "specs"
    render_dir = project / "rendered"
    output_root = project / "output"
    for directory in (assets, specs, render_dir):
        directory.mkdir(parents=True)
    Image.new("RGBA", (200, 100), "purple").save(assets / "wide.png")
    Image.new("RGBA", (100, 200), "green").save(assets / "tall.png")
    spec = {
        "slide": {"width_emu": 1000, "height_emu": 1000},
        "elements": [
            {
                "id": "logo", "type": "image", "role": "event-logo",
                "asset": "assets/wide.png",
                "box": {"x": 700, "y": 0, "cx": 300, "cy": 200},
                "fit": "contain", "anchor": "top",
            },
            {
                "id": "hero", "type": "image", "role": "template-figure",
                "asset": "assets/wide.png",
                "box": {
                    "x": -100, "y": 200, "cx": 800, "cy": 600,
                    "allow_offslide_bleed": ["left"],
                },
                "fit": "cover", "anchor": "right",
            },
            {
                "id": "accent", "type": "image", "role": "decorative",
                "asset": "assets/tall.png",
                "box": {
                    "x": 100, "y": 850, "cx": 200, "cy": 200,
                    "allow_offslide_bleed": ["bottom"],
                },
                "fit": "stretch", "anchor": "center",
            },
        ],
    }
    spec_path = specs / "slide.spec.json"
    spec_path.write_text(json.dumps(spec))
    deck_path = specs / "demo.deck.json"
    deck_path.write_text(json.dumps({
        "slides": ["specs/slide.spec.json"],
    }))
    page = render_dir / "demo_page-1.png"
    Image.new("RGB", dimensions, "white").save(page)
    return project, deck_path, render_dir, output_root, page


@pytest.mark.parametrize("dimensions", [(2560, 1440), (3414, 1920)])
def test_generate_crops_uses_actual_dimensions_fit_anchors_and_bleed(
        tmp_path, dimensions):
    project, deck, render_dir, output_root, page = _crop_fixture(
        tmp_path, dimensions
    )

    manifest = qa_crops.generate_crops(
        deck, render_dir=render_dir, output_root=output_root,
        project_root=project,
    )

    assert manifest["source_pages"] == [str(page.resolve())]
    assert len(manifest["crops"]) == 7
    by_element = {}
    for crop in manifest["crops"]:
        by_element.setdefault(crop["element_id"], set()).add(crop["crop_type"])
        assert crop["render_dimensions"] == {
            "width": dimensions[0], "height": dimensions[1],
        }
        bounds = crop["pixel_bounds"]
        assert 0 <= bounds["x"] < bounds["x"] + bounds["cx"] <= dimensions[0]
        assert 0 <= bounds["y"] < bounds["y"] + bounds["cy"] <= dimensions[1]
        crop_path = output_root / "qa_crops" / crop["file"]
        with Image.open(crop_path) as image:
            assert image.size == (bounds["cx"], bounds["cy"])

    assert by_element["logo"] == {"logo_corner"}
    assert by_element["hero"] == {
        "decorative_edge_top", "decorative_edge_right",
        "decorative_edge_bottom",
    }
    assert by_element["accent"] == {
        "decorative_edge_left", "decorative_edge_top",
        "decorative_edge_right",
    }
    assert (output_root / "qa_crops" / "manifest.json").is_file()
