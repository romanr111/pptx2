from pathlib import Path
import hashlib
import json

from pptx import Presentation

import template_registry
import template_style


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_SCRIPT = (
    PROJECT_ROOT / ".claude" / "skills" / "pptx-deck" / "scripts"
    / "template_registry.py"
)


def test_template_registry_validator_is_available():
    assert REGISTRY_SCRIPT.is_file()


def _registry_fixture(tmp_path):
    project = tmp_path / "project"
    assets_dir = project / "assets"
    extracted = assets_dir / "designer_extracted" / "event"
    extracted.mkdir(parents=True)
    template = assets_dir / "template.pptx"
    template.write_bytes(b"template")
    template_fingerprint = hashlib.sha256(template.read_bytes()).hexdigest()[:16]
    asset = extracted / "logo.png"
    asset.write_bytes(b"reviewed-logo")
    sidecar = extracted / "logo.png.json"
    sidecar.write_text(json.dumps({
        "source_type": "template",
        "source_template": "assets/template.pptx",
        "source_media_path": "ppt/media/image1.png",
        "license": "organizer-provided template",
        "selected_rationale": "Reviewed event wordmark",
    }))
    catalog = project / "out" / "template_visual_catalog.json"
    catalog.parent.mkdir()
    catalog.write_text(json.dumps({
        "template": "assets/template.pptx",
        "template_fingerprint": template_fingerprint,
        "n_slides_total": 1,
        "approved_assets": [{
            "id": "event-logo-dark",
            "role": "event-logo",
            "background_variant": "dark",
            "source_media_path": "ppt/media/image1.png",
            "canonical_path": "assets/designer_extracted/event/logo.png",
            "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
            "provenance_sidecar_path": (
                "assets/designer_extracted/event/logo.png.json"
            ),
            "usage_notes": "Use in the upper-right clear corner.",
        }],
        "approved_fonts": {
            "heading_family": "Heading Exact",
            "body_family": "Body Exact",
            "permitted_families": ["Heading Exact", "Body Exact"],
            "max_family_budget": 2,
            "known_naming_traps": [{
                "reject": "Heading Guess", "use": "Heading Exact",
            }],
        },
    }))
    template_style = project / "out" / "template_style.json"
    template_style.write_text(json.dumps({
        "template_file": "template.pptx",
        "template_fingerprint": template_fingerprint,
        "thumbnails": ["slide-1.png"],
    }))
    assets_json = project / "out" / "assets.json"
    assets_json.write_text(json.dumps({
        "fonts": [{"family": "Heading Exact"}, {"family": "Body Exact"}],
    }))
    return project, catalog, template_style, assets_json, asset, sidecar


def test_registry_reports_a_missing_registered_asset(tmp_path):
    project, catalog, template_style, assets_json, asset, _ = _registry_fixture(
        tmp_path
    )
    asset.unlink()

    report = template_registry.validate_registry(
        catalog, template_style, assets_json, project_root=project,
    )

    assert report["counts"]["error"] == 1
    assert report["findings"][0]["check"] == "approved_asset_exists"


def test_registry_reports_a_changed_registered_asset_hash(tmp_path):
    project, catalog, template_style, assets_json, asset, _ = _registry_fixture(
        tmp_path
    )
    asset.write_bytes(b"changed-after-review")

    report = template_registry.validate_registry(
        catalog, template_style, assets_json, project_root=project,
    )

    assert {finding["check"] for finding in report["findings"]} == {
        "approved_asset_hash"
    }


def test_registry_reports_an_absent_provenance_sidecar(tmp_path):
    project, catalog, template_style, assets_json, _, sidecar = _registry_fixture(
        tmp_path
    )
    sidecar.unlink()

    report = template_registry.validate_registry(
        catalog, template_style, assets_json, project_root=project,
    )

    assert {finding["check"] for finding in report["findings"]} == {
        "approved_asset_provenance"
    }


def test_registry_reports_incomplete_provenance_content(tmp_path):
    project, catalog, template_style, assets_json, _, sidecar = _registry_fixture(
        tmp_path
    )
    sidecar.write_text("{}")

    report = template_registry.validate_registry(
        catalog, template_style, assets_json, project_root=project,
    )

    assert {finding["check"] for finding in report["findings"]} == {
        "approved_asset_provenance"
    }


def test_registry_rejects_unapproved_slide_font_families(tmp_path):
    project, catalog, template_style, assets_json, _, _ = _registry_fixture(
        tmp_path
    )
    slides = [{
        "elements": [{
            "type": "textbox",
            "paragraphs": [{
                "lines": [{"font": "Unapproved Family"}],
                "bullet": {"font": "Heading Exact"},
            }],
        }],
    }]

    report = template_registry.validate_registry(
        catalog, template_style, assets_json,
        slide_specs=slides, project_root=project,
    )

    assert {finding["check"] for finding in report["findings"]} == {
        "approved_font_family"
    }


def test_registry_reports_stale_template_identity(tmp_path):
    project, catalog, template_style, assets_json, _, _ = _registry_fixture(
        tmp_path
    )
    template_style.write_text(json.dumps({
        "template_file": "different-template.pptx",
        "thumbnails": ["slide-1.png", "slide-2.png"],
    }))

    report = template_registry.validate_registry(
        catalog, template_style, assets_json, project_root=project,
    )

    assert {finding["check"] for finding in report["findings"]} == {
        "template_registry_identity"
    }


def test_registry_reports_same_name_same_count_template_drift(tmp_path):
    project, catalog, template_style_path, assets_json, _, _ = _registry_fixture(
        tmp_path
    )
    template = project / "assets" / "template.pptx"
    Presentation().save(template)
    facts = template_style.extract(template, with_thumbnails=False)
    template_style_path.write_text(json.dumps(facts))
    catalog_data = json.loads(catalog.read_text())
    catalog_data["n_slides_total"] = 0
    catalog_data["template_fingerprint"] = facts["template_fingerprint"]
    catalog.write_text(json.dumps(catalog_data))

    changed = Presentation(template)
    changed.slide_width += 1
    changed.save(template)

    report = template_registry.validate_registry(
        catalog, template_style_path, assets_json, project_root=project,
    )

    assert {finding["check"] for finding in report["findings"]} == {
        "template_registry_identity"
    }


def test_legacy_catalog_without_reviewed_starters_warns(tmp_path):
    project, catalog, template_style, assets_json, _, _ = _registry_fixture(
        tmp_path
    )
    data = json.loads(catalog.read_text())
    data.pop("template_fingerprint")
    data.pop("approved_assets")
    data.pop("approved_fonts")
    catalog.write_text(json.dumps(data))
    facts = json.loads(template_style.read_text())
    facts.pop("template_fingerprint")
    template_style.write_text(json.dumps(facts))

    report = template_registry.validate_registry(
        catalog, template_style, assets_json, project_root=project,
    )

    assert report["counts"] == {"error": 0, "warn": 1}
    assert report["findings"][0]["check"] == "template_registry_incomplete"
