#!/usr/bin/env python3
"""Validate reviewed template assets and font starters before authoring."""

import hashlib
import json
from pathlib import Path

from common import PROJECT_ROOT
from render import _file_hash


def _finding(severity, check, item, message):
    return {
        "severity": severity,
        "check": check,
        "item": item,
        "message": message,
    }


def _report(catalog_path, findings):
    counts = {
        "error": sum(f["severity"] == "error" for f in findings),
        "warn": sum(f["severity"] == "warn" for f in findings),
    }
    return {
        "catalog": str(catalog_path),
        "ok": counts["error"] == 0,
        "counts": counts,
        "findings": findings,
    }


def validate_registry(catalog_path, template_style_path, assets_json_path,
                      slide_specs=None, project_root=PROJECT_ROOT):
    catalog_path = Path(catalog_path)
    catalog = json.loads(catalog_path.read_text())
    findings = []
    template_style = json.loads(Path(template_style_path).read_text())
    identity_issues = []
    catalog_template = catalog.get("template")
    if not catalog_template or not (Path(project_root) / catalog_template).is_file():
        identity_issues.append(f"catalog template is missing: {catalog_template!r}")
    else:
        template_path = Path(project_root) / catalog_template
        if Path(catalog_template).name != template_style.get("template_file"):
            identity_issues.append(
                f"catalog template {Path(catalog_template).name!r} != facts template "
                f"{template_style.get('template_file')!r}")
        actual_fingerprint = _file_hash(template_path)
        facts_fingerprint = template_style.get("template_fingerprint")
        catalog_fingerprint = catalog.get("template_fingerprint")
        if not facts_fingerprint and catalog_fingerprint:
            identity_issues.append("template facts lack a content fingerprint")
        elif (facts_fingerprint
              and actual_fingerprint != facts_fingerprint):
            identity_issues.append(
                f"current template fingerprint {actual_fingerprint!r} != facts "
                f"fingerprint {facts_fingerprint!r}")
        if (catalog_fingerprint
                and catalog_fingerprint != actual_fingerprint):
            identity_issues.append(
                f"catalog fingerprint {catalog_fingerprint!r} != current template "
                f"fingerprint {actual_fingerprint!r}")
    expected_slides = len(template_style.get("thumbnails", []))
    if catalog.get("n_slides_total") != expected_slides:
        identity_issues.append(
            f"catalog slide count {catalog.get('n_slides_total')!r} != "
            f"facts thumbnail count {expected_slides}")
    if identity_issues:
        findings.append(_finding(
            "error", "template_registry_identity", "template",
            "; ".join(identity_issues)))
    missing_sections = [
        section for section in (
            "template_fingerprint", "approved_assets", "approved_fonts",
        )
        if section not in catalog
    ]
    if missing_sections:
        findings.append(_finding(
            "warn", "template_registry_incomplete", "registry",
            f"reviewed starter registry is incomplete; missing: {missing_sections}"))
    for entry in catalog.get("approved_assets", []):
        canonical = Path(project_root) / entry["canonical_path"]
        if not canonical.is_file():
            findings.append(_finding(
                "error", "approved_asset_exists", entry.get("id"),
                f"registered asset is missing: {entry['canonical_path']}"))
            continue
        actual_hash = hashlib.sha256(canonical.read_bytes()).hexdigest()
        if actual_hash != entry.get("sha256"):
            findings.append(_finding(
                "error", "approved_asset_hash", entry.get("id"),
                f"registered asset hash changed: {entry['canonical_path']}"))
        sidecar = Path(project_root) / entry["provenance_sidecar_path"]
        if not sidecar.is_file():
            findings.append(_finding(
                "error", "approved_asset_provenance", entry.get("id"),
                f"registered asset provenance is missing: "
                f"{entry['provenance_sidecar_path']}"))
            continue
        try:
            provenance = json.loads(sidecar.read_text())
        except (OSError, json.JSONDecodeError) as error:
            findings.append(_finding(
                "error", "approved_asset_provenance", entry.get("id"),
                f"registered asset provenance is not valid JSON: {error}"))
            continue
        required = (
            "source_type", "source_template", "source_media_path",
            "license", "selected_rationale",
        )
        missing = [field for field in required if not provenance.get(field)]
        mismatched = []
        if provenance.get("source_type") not in (None, "template"):
            mismatched.append("source_type")
        if provenance.get("source_template") not in (None, catalog.get("template")):
            mismatched.append("source_template")
        if provenance.get("source_media_path") not in (
                None, entry.get("source_media_path")):
            mismatched.append("source_media_path")
        if missing or mismatched:
            findings.append(_finding(
                "error", "approved_asset_provenance", entry.get("id"),
                f"registered asset provenance is incomplete or stale; "
                f"missing={missing}, mismatched={mismatched}"))

    approved_fonts = catalog.get("approved_fonts")
    if approved_fonts:
        assets_json = json.loads(Path(assets_json_path).read_text())
        inventoried = {
            font.get("family") for font in assets_json.get("fonts", [])
            if font.get("family")
        }
        permitted = set(approved_fonts.get("permitted_families", []))
        heading = approved_fonts.get("heading_family")
        body = approved_fonts.get("body_family")
        missing_inventory = sorted(permitted - inventoried)
        if not heading or not body or heading not in permitted or body not in permitted:
            findings.append(_finding(
                "error", "approved_font_roles", "approved_fonts",
                "heading_family and body_family must be exact permitted families"))
        if missing_inventory:
            findings.append(_finding(
                "error", "approved_font_inventory", "approved_fonts",
                f"approved fonts are absent from assets.json: {missing_inventory}"))
        budget = approved_fonts.get("max_family_budget")
        if (isinstance(budget, bool) or not isinstance(budget, int)
                or budget < 1 or len(permitted) > budget):
            findings.append(_finding(
                "error", "approved_font_budget", "approved_fonts",
                f"permitted family count {len(permitted)} exceeds or invalidates "
                f"budget {budget!r}"))
        rejected = {
            trap.get("reject") for trap in approved_fonts.get("known_naming_traps", [])
            if isinstance(trap, dict) and trap.get("reject")
        }
        used = set()
        for spec in slide_specs or []:
            for element in spec.get("elements", []):
                if element.get("type") == "textbox":
                    for paragraph in element.get("paragraphs", []):
                        used.update(
                            line.get("font") for line in paragraph.get("lines", [])
                            if line.get("font"))
                        bullet_font = paragraph.get("bullet", {}).get("font")
                        if bullet_font:
                            used.add(bullet_font)
                elif element.get("type") == "table":
                    table_font = element.get("table", {}).get("style", {}).get("font")
                    if table_font:
                        used.add(table_font)
        for family in sorted(used):
            if family not in permitted or family in rejected:
                findings.append(_finding(
                    "error", "approved_font_family", family,
                    f"font family is not approved for this template: {family}"))
    return _report(catalog_path, findings)
