"""Item 2: the styleguide visual bar is a delivery gate.

`lint_render` keeps `styleguide_visual_weight` / `styleguide_text_budget` as
warns (so the build/lint loop isn't hard-blocked), but a `meta.styleguide_waiver`
downgrades them to info; `deck_qa --delivery` blocks on any unwaived gate finding
and surfaces every waiver under `delivery.styleguide`.
"""
import json

import common
import deck_qa
import lint_render


def _by_check(findings):
    return {f["check"]: f["severity"] for f in findings}


def _text_only_spec(meta):
    # no image/background/brief -> visual ratio 0; 8 lines -> over a 6-line budget
    return {
        "spec_version": 1,
        "slide": {"width_emu": 12192000, "height_emu": 6858000},
        "meta": meta,
        "elements": [{
            "id": "t", "type": "textbox",
            "box": {"x": 0, "y": 0, "cx": 6000000, "cy": 6000000},
            "paragraphs": [{"lines": [
                {"text": f"line {i}", "font": "Geologica", "size_pt": 12,
                 "color": "111111"} for i in range(8)]}],
        }],
    }


_STYLEGUIDE = {
    "layout_rules": {"visual_ratio_target": 0.7},
    "text_rules": {"max_text_lines_per_slide": 6},
}


def test_emitted_gate_checks_match_the_shared_constant():
    # the aesthetic findings lint_render emits are exactly the checks deck_qa
    # gates delivery on -- a single source (common.STYLEGUIDE_GATE_CHECKS) so
    # the emitter and the gate can't drift.
    spec = _text_only_spec({"styleguide_profile": "x", "styleguide_application": "y"})
    findings = []
    lint_render.check_styleguide_application(spec, findings, _STYLEGUIDE)
    emitted = {f["check"] for f in findings if f["check"] != "styleguide_application"}
    assert emitted == set(common.STYLEGUIDE_GATE_CHECKS)


def test_gate_findings_are_warn_without_a_waiver():
    spec = _text_only_spec({"styleguide_profile": "x", "styleguide_application": "y"})
    findings = []
    lint_render.check_styleguide_application(spec, findings, _STYLEGUIDE)
    sev = _by_check(findings)
    assert sev.get("styleguide_visual_weight") == "warn"
    assert sev.get("styleguide_text_budget") == "warn"


def test_waiver_downgrades_gate_findings_to_info():
    spec = _text_only_spec({
        "styleguide_profile": "x", "styleguide_application": "y",
        "styleguide_waiver": [
            {"check": "styleguide_visual_weight", "reason": "deliberate full-bleed statement"},
            {"check": "styleguide_text_budget", "reason": "clinical checklist"},
        ],
    })
    findings = []
    lint_render.check_styleguide_application(spec, findings, _STYLEGUIDE)
    sev = _by_check(findings)
    assert sev.get("styleguide_visual_weight") == "info"
    assert sev.get("styleguide_text_budget") == "info"
    waived = [f for f in findings if f["check"] == "styleguide_visual_weight"][0]
    assert "WAIVED" in waived["message"]


def _report_with_finding(severity):
    return {
        "build": {"returncode": 0},
        "deck_lint": {"n_errors": 0},
        "render": {"error": None, "pngs": ["slide.png"]},
        "slides": [{
            "stem": "s1",
            "lint_render": {"counts": {"error": 0}, "findings": [{
                "severity": severity, "check": "styleguide_visual_weight",
                "element_id": "slide", "message": "not visual-led",
            }]},
        }],
    }


def _reviewed_spec(tmp_path):
    p = tmp_path / "s1.spec.json"
    p.write_text(json.dumps({"meta": {"visual_review": {"iteration": 1, "verdict": "pass"}}}))
    return p


def test_delivery_blocks_unwaived_styleguide_gate(tmp_path):
    report = _report_with_finding("warn")
    issues = deck_qa.delivery_issues(report, [("s1", _reviewed_spec(tmp_path))])
    assert any("styleguide gate (styleguide_visual_weight)" in i for i in issues)
    assert report["styleguide_gate"]["blocking"]
    assert not report["styleguide_gate"]["waived"]


def test_delivery_passes_when_gate_is_waived(tmp_path):
    # a waived finding arrives as info from lint_render
    report = _report_with_finding("info")
    issues = deck_qa.delivery_issues(report, [("s1", _reviewed_spec(tmp_path))])
    assert not any("styleguide gate" in i for i in issues)
    assert report["styleguide_gate"]["waived"]
    assert not report["styleguide_gate"]["blocking"]
