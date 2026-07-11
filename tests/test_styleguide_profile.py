import json

import asset_resolver
import lint_render
import styleguide_profile


def test_build_profile_extracts_design_contract():
    text = """
    Medical Luxury Aesthetic. 70% premium graphic, 30% negative space.
    Maximum 1 main idea per slide. No fluff. No more than 6 lines.
    Surgical precision graphics with thin elegant linework.
    """

    profile = styleguide_profile.build_profile(text, styleguide_profile.DEFAULT_SOURCE)

    assert profile["style_name"] == "Medical Luxury Aesthetic"
    assert profile["layout_rules"]["visual_ratio_target"] == 0.70
    assert profile["layout_rules"]["negative_space_target"] == 0.30
    assert profile["text_rules"]["max_text_lines_per_slide"] == 6
    assert "surgical precision graphics" in profile["image_brief_defaults"]["style"]


def test_asset_resolver_plan_uses_styleguide_profile(tmp_path, monkeypatch, capsys):
    spec_path = tmp_path / "slide.spec.json"
    spec_path.write_text(json.dumps({
        "spec_version": 1,
        "slide": {"width_emu": 1000, "height_emu": 1000},
        "elements": [],
        "image_briefs": [{
            "id": "hero",
            "asset": "assets/generated/hero.png",
            "box": {"x": 0, "y": 0, "cx": 700, "cy": 1000},
            "subject": "cardiac anatomy",
            "aspect": "7:10",
            "medical_class": "anatomical",
        }],
    }))
    profile_path = tmp_path / "styleguide_profile.json"
    profile_path.write_text(json.dumps({
        "style_name": "Medical Luxury Aesthetic",
        "source": "assets/styleguide.rtf",
        "image_brief_defaults": {
            "style": "surgical precision graphics",
            "negative": "no watermarks",
        },
    }))

    monkeypatch.setattr(asset_resolver, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(asset_resolver, "ASSETS_JSON", tmp_path / "missing_assets.json")
    monkeypatch.setattr(asset_resolver, "TEMPLATE_STYLE_JSON", tmp_path / "missing_template.json")
    monkeypatch.setattr(asset_resolver, "STYLEGUIDE_PROFILE_JSON", profile_path)

    asset_resolver.command_plan(type("Args", (), {"spec": str(spec_path)})())
    result = json.loads(capsys.readouterr().out)

    plan = result["open_briefs"][0]
    assert result["styleguide_profile"]["style_name"] == "Medical Luxury Aesthetic"
    assert plan["styleguide_context"]["image_style"] == "surgical precision graphics"
    assert any("surgical precision graphics" in q for q in plan["suggested_search_queries"])
    assert "surgical precision graphics" in plan["suggested_generation_prompt"]


def test_styleguide_lint_warns_and_can_be_satisfied():
    profile = {
        "style_name": "Medical Luxury Aesthetic",
        "layout_rules": {"visual_ratio_target": 0.70},
        "text_rules": {"max_text_lines_per_slide": 2},
    }
    spec = {
        "spec_version": 1,
        "slide": {"width_emu": 1000, "height_emu": 1000},
        "elements": [{
            "id": "copy",
            "type": "textbox",
            "box": {"x": 0, "y": 0, "cx": 500, "cy": 500},
            "paragraphs": [{"lines": [
                {"text": "one", "font": "Arial", "size_pt": 10, "color": "000000"},
                {"text": "two", "font": "Arial", "size_pt": 10, "color": "000000"},
                {"text": "three", "font": "Arial", "size_pt": 10, "color": "000000"},
            ]}],
        }],
    }

    findings = []
    lint_render.check_styleguide_application(spec, findings, profile)

    checks = {finding["check"] for finding in findings}
    assert "styleguide_application" in checks
    assert "styleguide_text_budget" in checks
    assert "styleguide_visual_weight" in checks

    spec["meta"] = {
        "styleguide_profile": "Medical Luxury Aesthetic",
        "styleguide_application": "Visual-led layout with compressed copy.",
    }
    spec["elements"].append({
        "id": "hero",
        "type": "image",
        "asset": "assets/hero.png",
        "box": {"x": 0, "y": 0, "cx": 700, "cy": 1000},
    })
    spec["elements"][0]["paragraphs"][0]["lines"] = spec["elements"][0]["paragraphs"][0]["lines"][:2]

    findings = []
    lint_render.check_styleguide_application(spec, findings, profile)
    assert findings == []
