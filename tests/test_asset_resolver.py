import argparse
import json
from pathlib import Path

from PIL import Image

import asset_resolver
import build_deck
import lint_render


def _brief(asset="assets/generated/hero.png", medical_class="decorative"):
    return {
        "id": "hero",
        "asset": asset,
        "box": {"x": 1000000, "y": 1000000, "cx": 3000000, "cy": 4000000},
        "subject": "temporomandibular joint anatomy",
        "aspect": "3:4",
        "medical_class": medical_class,
        "style": "premium medical presentation, soft clinical lighting",
        "negative": "no text, no watermarks, no logos",
    }


def _spec(asset="assets/generated/hero.png", medical_class="decorative"):
    return {
        "spec_version": 1,
        "slide": {"width_emu": 12192000, "height_emu": 6858000},
        "elements": [
            {
                "id": "caption",
                "type": "textbox",
                "box": {"x": 100000, "y": 100000, "cx": 1000000, "cy": 300000},
                "paragraphs": [{"lines": [{"text": "x", "font": "Arial", "size_pt": 12, "color": "000000"}]}],
            }
        ],
        "image_briefs": [_brief(asset=asset, medical_class=medical_class)],
    }


def _write_spec(path: Path, spec):
    path.write_text(json.dumps(spec))


def _make_image(path: Path, size=(300, 400), color="white"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def test_plan_lists_open_briefs_and_candidates(tmp_path, monkeypatch, capsys):
    spec_path = tmp_path / "slide.spec.json"
    _write_spec(spec_path, _spec())
    assets_json = tmp_path / "assets.json"
    assets_json.write_text(json.dumps({
        "images": [
            {
                "file": "assets/images/tmj_anatomy.png",
                "classification": "content_illustration",
                "aspect": 0.75,
                "watermark_suspected": False,
            }
        ]
    }))
    template_style = tmp_path / "template_style.json"
    template_style.write_text(json.dumps({
        "logo_candidates": [{"media": "ppt/media/image1.png", "aspect": 1.0, "size": [100, 100]}],
        "media_reuse_ranked": [{"media": "ppt/media/image2.png", "n_slides": 3}],
    }))
    monkeypatch.setattr(asset_resolver, "ASSETS_JSON", assets_json)
    monkeypatch.setattr(asset_resolver, "TEMPLATE_STYLE_JSON", template_style)

    asset_resolver.command_plan(argparse.Namespace(spec=str(spec_path)))
    result = json.loads(capsys.readouterr().out)

    assert result["resolver_order"] == ["local", "template", "web", "generated"]
    assert result["open_briefs"][0]["id"] == "hero"
    assert result["open_briefs"][0]["local_candidates"][0]["asset"] == "assets/images/tmj_anatomy.png"
    assert "temporomandibular joint anatomy" in result["open_briefs"][0]["suggested_search_queries"][0]


def test_import_copies_asset_and_writes_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(asset_resolver, "PROJECT_ROOT", tmp_path)
    spec_path = tmp_path / "slide.spec.json"
    _write_spec(spec_path, _spec())
    source = tmp_path / "candidate.png"
    _make_image(source)

    asset_resolver.command_import(argparse.Namespace(
        spec=str(spec_path),
        brief_id="hero",
        source=str(source),
        source_type="web",
        source_url="https://example.test/image.png",
        prompt=None,
        rationale="Best candidate after visual comparison.",
        verification="Checked anatomy relevance, no text, no visible watermark.",
        warning=["Medical visual should be reviewed by the presenter."],
    ))

    asset = tmp_path / "assets/generated/hero.png"
    sidecar = asset_resolver.provenance_path(asset)
    assert asset.is_file()
    data = json.loads(sidecar.read_text())
    assert data["source_type"] == "web"
    assert data["source_url"] == "https://example.test/image.png"
    assert data["verification_notes"].startswith("Checked anatomy")


def test_report_includes_provenance_status(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(asset_resolver, "PROJECT_ROOT", tmp_path)
    spec_path = tmp_path / "slide.spec.json"
    _write_spec(spec_path, _spec())
    asset = tmp_path / "assets/generated/hero.png"
    _make_image(asset)
    asset_resolver.provenance_path(asset).write_text(json.dumps({
        "brief_id": "hero",
        "brief_hash": "fixture",
        "source_type": "generated",
        "selected_rationale": "Clean conceptual image.",
        "verification_notes": "Checked against brief.",
    }))

    asset_resolver.command_report(argparse.Namespace(spec=str(spec_path)))
    result = json.loads(capsys.readouterr().out)

    assert result["briefs"][0]["filled"] is True
    assert result["briefs"][0]["provenance"]["exists"] is True
    assert result["briefs"][0]["provenance"]["missing"] == []


def test_resolver_import_build_and_lint_integration(tmp_path, monkeypatch):
    monkeypatch.setattr(asset_resolver, "PROJECT_ROOT", tmp_path)
    spec = _spec()
    spec_path = tmp_path / "slide.spec.json"
    _write_spec(spec_path, spec)
    source = tmp_path / "candidate.png"
    _make_image(source)

    asset_resolver.command_import(argparse.Namespace(
        spec=str(spec_path),
        brief_id="hero",
        source=str(source),
        source_type="generated",
        source_url=None,
        prompt="Generate a premium clinical abstract image.",
        rationale="Matches slide subject and aspect.",
        verification="No text, no logo, no visible watermark; matches brief.",
        warning=[],
    ))

    spec = json.loads(spec_path.read_text())
    errors = build_deck.validate_spec(spec, project_root=tmp_path)
    findings = []
    lint_render.check_image_briefs(spec, findings, project_root=tmp_path)
    lint_render.check_ai_generated_review(spec, findings, project_root=tmp_path)

    assert errors == []
    assert not any(f["severity"] == "error" for f in findings)
