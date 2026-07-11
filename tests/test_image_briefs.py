"""Image briefs: fill-by-file contract, resolver provenance, and lint gates."""

import json
from pathlib import Path

from PIL import Image

import asset_resolver
import build_deck
import lint_render


def _brief(**brief_overrides):
    brief = {
        "id": "hero",
        "asset": "assets/generated/hero.png",
        "box": {"x": 7000000, "y": 1000000, "cx": 3000000, "cy": 4000000},
        "subject": "warm clinic photo",
        "aspect": "3:4",
        "medical_class": "decorative",
    }
    brief.update(brief_overrides)
    return brief


def _spec(brief_overrides=None, meta=None):
    brief_overrides = brief_overrides or {}
    spec = {
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
        "image_briefs": [_brief(**brief_overrides)],
        "animations": [{"step": 1, "targets": ["hero"], "effect": "fade"}],
    }
    if meta is not None:
        spec["meta"] = meta
    return spec


def _fill(project_root, asset="assets/generated/hero.png"):
    path = project_root / asset
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (300, 400), "white").save(path)
    return path


def _write_provenance(asset_path: Path, **overrides):
    data = {
        "brief_id": "hero",
        "brief_hash": "fixturehash",
        "source_type": "generated",
        "selected_rationale": "Best match for the requested slide brief.",
        "verification_notes": "Visually checked against the brief; no labels, logos, or watermarks.",
        "medical_class": "decorative",
        "ai_generated": True,
    }
    data.update(overrides)
    sidecar = asset_resolver.provenance_path(asset_path)
    sidecar.write_text(json.dumps(data))
    return sidecar


def test_unfilled_brief_is_rendered_as_placeholder_and_lint_error(tmp_path):
    spec = _spec()
    slide = build_deck.build(spec, project_root=tmp_path).slides[0]

    assert any("IMAGE BRIEF 'hero'" in shape.text for shape in slide.shapes if hasattr(shape, "text"))

    findings = []
    lint_render.check_image_briefs(spec, findings, project_root=tmp_path)
    assert any(f["severity"] == "error" and f["check"] == "image_brief_open" for f in findings)


def test_acknowledged_missing_brief_warns_and_cannot_be_animated(tmp_path):
    spec = _spec(meta={"acknowledged_briefs": ["hero"]})
    findings = []
    lint_render.check_image_briefs(spec, findings, project_root=tmp_path)
    assert any(f["severity"] == "warn" and f["check"] == "image_brief_open" for f in findings)

    errors = build_deck.validate_spec(spec, project_root=tmp_path)
    assert any("can't be animated" in e for e in errors)


def test_filled_brief_can_be_animated(tmp_path):
    spec = _spec()
    _fill(tmp_path)
    assert build_deck.validate_spec(spec, project_root=tmp_path) == []


def test_filled_local_asset_without_sidecar_passes_review_lint(tmp_path):
    spec = _spec({"asset": "assets/images/local.png"})
    _fill(tmp_path, asset="assets/images/local.png")

    findings = []
    lint_render.check_ai_generated_review(spec, findings, project_root=tmp_path)
    assert findings == []


def test_generated_asset_without_sidecar_errors(tmp_path):
    spec = _spec()
    _fill(tmp_path)

    findings = []
    lint_render.check_ai_generated_review(spec, findings, project_root=tmp_path)
    assert any(f["severity"] == "error" and f["check"] == "asset_provenance" for f in findings)


def test_generated_asset_missing_verification_errors(tmp_path):
    spec = _spec()
    asset = _fill(tmp_path)
    _write_provenance(asset, verification_notes="")

    findings = []
    lint_render.check_ai_generated_review(spec, findings, project_root=tmp_path)
    assert any("verification_notes" in f["message"] for f in findings)


def test_generated_decorative_asset_with_provenance_warns_for_ai_review(tmp_path):
    spec = _spec()
    asset = _fill(tmp_path)
    _write_provenance(asset)

    findings = []
    lint_render.check_ai_generated_review(spec, findings, project_root=tmp_path)
    assert [f["check"] for f in findings] == ["ai_review_reminder"]
    assert findings[0]["severity"] == "warn"


def test_generated_anatomical_asset_with_verification_warns_not_errors(tmp_path):
    spec = _spec({"medical_class": "anatomical"})
    asset = _fill(tmp_path)
    _write_provenance(asset, medical_class="anatomical")

    findings = []
    lint_render.check_ai_generated_review(spec, findings, project_root=tmp_path)
    assert [f["check"] for f in findings] == ["medical_visual_review"]
    assert findings[0]["severity"] == "warn"
