"""Image briefs: fill-by-file contract, placeholder rendering, and the
open-brief + AI-medical-review lint gates."""
import re
from pathlib import Path

import pytest
from PIL import Image

import build_deck
import lint_render


def _spec(brief_overrides=None, meta=None):
    brief = {
        "id": "hero", "asset": "assets/generated/hero.png",
        "box": {"x": 7000000, "y": 0, "cx": 5192000, "cy": 6858000},
        "subject": "warm clinic photo", "aspect": "3:4",
        "medical_class": "decorative",
    }
    brief.update(brief_overrides or {})
    spec = {
        "spec_version": 1,
        "slide": {"width_emu": 12192000, "height_emu": 6858000},
        "elements": [
            {"id": "t", "type": "textbox",
             "box": {"x": 500000, "y": 500000, "cx": 4000000, "cy": 600000},
             "paragraphs": [{"lines": [{"text": "x", "font": "Arial",
                                        "size_pt": 20, "color": "000000"}]}]},
        ],
        "image_briefs": [brief],
    }
    if meta:
        spec["meta"] = meta
    return spec


def _slide_xml(spec, project):
    prs = build_deck.build(spec, project_root=project)
    return re.sub(r">\s+<", "><", prs.slides[0]._element.xml)


def _fill(project, asset="assets/generated/hero.png"):
    p = project / asset
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (60, 80), (90, 70, 50)).save(p)
    return p


def test_unfilled_brief_renders_placeholder(tmp_path):
    xml = _slide_xml(_spec(), tmp_path)
    assert "IMAGE BRIEF" in xml and "warm clinic photo" in xml
    assert "<p:pic>" not in xml


def test_acknowledged_brief_renders_nothing(tmp_path):
    xml = _slide_xml(_spec(meta={"acknowledged_briefs": ["hero"]}), tmp_path)
    assert "IMAGE BRIEF" not in xml
    assert "<p:pic>" not in xml


def test_filled_brief_places_image_without_spec_edit(tmp_path):
    _fill(tmp_path)
    xml = _slide_xml(_spec(), tmp_path)
    assert "IMAGE BRIEF" not in xml
    assert "<p:pic>" in xml


def test_open_brief_is_lint_error_until_acknowledged(tmp_path):
    findings = []
    lint_render.check_image_briefs(_spec(), findings, project_root=tmp_path)
    assert any(f["severity"] == "error" and f["check"] == "image_brief_open"
               for f in findings)

    findings = []
    lint_render.check_image_briefs(
        _spec(meta={"acknowledged_briefs": ["hero"]}), findings,
        project_root=tmp_path)
    assert [f["severity"] for f in findings] == ["warn"]


def test_animating_acknowledged_absent_brief_is_validation_error(tmp_path):
    """Regression: this used to validate clean and then KeyError in build()."""
    spec = _spec(meta={"acknowledged_briefs": ["hero"]})
    spec["animations"] = [{"step": 1, "targets": ["hero"], "effect": "fade"}]
    errors = build_deck.validate_spec(spec, project_root=tmp_path)
    assert any("can't be animated" in e for e in errors)
    # filling the brief resolves it with no spec change
    _fill(tmp_path)
    assert build_deck.validate_spec(spec, project_root=tmp_path) == []


def test_anatomical_ai_image_blocks_until_reviewed(tmp_path):
    _fill(tmp_path)
    spec = _spec({"medical_class": "anatomical"})
    findings = []
    lint_render.check_ai_generated_review(spec, findings, project_root=tmp_path)
    assert any(f["severity"] == "error" and f["check"] == "ai_medical_review"
               for f in findings)

    spec = _spec({"medical_class": "anatomical"},
                 meta={"image_reviews": [{"asset": "assets/generated/hero.png",
                                          "reviewed_by": "Dr. R. Nestor",
                                          "date": "2026-07-08"}]})
    findings = []
    lint_render.check_ai_generated_review(spec, findings, project_root=tmp_path)
    assert findings == []


def test_decorative_ai_image_gets_review_reminder_warn(tmp_path):
    _fill(tmp_path)
    findings = []
    lint_render.check_ai_generated_review(_spec(), findings, project_root=tmp_path)
    assert [f["check"] for f in findings] == ["ai_review_reminder"]
    assert findings[0]["severity"] == "warn"
