import json
import subprocess
import sys

import deck_qa
import render


def _report(png_count=1):
    return {
        "build": {"returncode": 0},
        "slides": [{"lint_render": {"counts": {"error": 0}}}],
        "deck_lint": {"n_errors": 0},
        "render": {"error": None, "pngs": ["slide.png"] * png_count},
    }


def test_delivery_rejects_missing_visual_review_even_when_normal_lint_only_warns(tmp_path):
    spec_path = tmp_path / "slide.spec.json"
    spec_path.write_text(json.dumps({"meta": {}}))

    issues = deck_qa.delivery_issues(_report(), [("slide", spec_path)])

    assert any("meta.visual_review" in issue for issue in issues)


def test_delivery_rejects_incomplete_rendering(tmp_path):
    spec_a = tmp_path / "a.spec.json"
    spec_b = tmp_path / "b.spec.json"
    reviewed = {"meta": {"visual_review": {"iteration": 1, "verdict": "pass"}}}
    spec_a.write_text(json.dumps(reviewed))
    spec_b.write_text(json.dumps(reviewed))

    issues = deck_qa.delivery_issues(_report(), [("a", spec_a), ("b", spec_b)])

    assert "render produced 1 PNGs for 2 slides" in issues


def test_delivery_cli_returns_nonzero_for_a_missing_review(tmp_path, monkeypatch):
    spec_path = tmp_path / "slide.spec.json"
    spec_path.write_text(json.dumps({"meta": {}}))
    deck_path = tmp_path / "sample.deck.json"
    deck_path.write_text(json.dumps({"slides": ["ignored"]}))
    output_root = tmp_path / "run"
    output_root.mkdir()
    (output_root / "sample.pptx").write_bytes(b"deck")

    monkeypatch.setattr(deck_qa, "spec_paths_from_deck", lambda path: [("slide", spec_path)])
    monkeypatch.setattr(deck_qa, "run_build_deck", lambda path, **kwargs: {
        "returncode": 0, "stdout": "", "stderr": "",
    })
    monkeypatch.setattr(deck_qa, "run_lint_render", lambda spec, deck, **kwargs: {
        "ok": True, "counts": {"error": 0, "warn": 1}, "findings": [],
    })
    monkeypatch.setattr(deck_qa, "run_lint_deck", lambda path, **kwargs: {
        "n_errors": 0, "n_warns": 0, "findings": [],
    })
    monkeypatch.setattr(deck_qa.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, "", ""))
    monkeypatch.setattr(render, "render_all", lambda *args, **kwargs: [tmp_path / "slide.png"])
    monkeypatch.setattr(deck_qa, "run_qa_crops", lambda *args, **kwargs: {
        "source_pages": [str(tmp_path / "slide.png")], "crops": [],
    })
    monkeypatch.setattr(sys, "argv", [
        "deck_qa.py", str(deck_path), "--delivery",
        "--output-root", str(output_root),
    ])

    assert deck_qa.main() == 1


def test_normal_qa_keeps_missing_review_as_a_warning(tmp_path, monkeypatch):
    spec_path = tmp_path / "slide.spec.json"
    spec_path.write_text(json.dumps({"meta": {}}))
    deck_path = tmp_path / "sample.deck.json"
    deck_path.write_text(json.dumps({"slides": ["ignored"]}))
    output_root = tmp_path / "run"
    output_root.mkdir()
    (output_root / "sample.pptx").write_bytes(b"deck")
    observed = {}

    monkeypatch.setattr(deck_qa, "spec_paths_from_deck", lambda path: [("slide", spec_path)])
    def fake_build(path, **kwargs):
        observed.update(kwargs["env"])
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(deck_qa, "run_build_deck", fake_build)
    monkeypatch.setattr(deck_qa, "run_lint_render", lambda spec, deck, **kwargs: {
        "ok": True, "counts": {"error": 0, "warn": 1}, "findings": [{
            "check": "visual_review", "severity": "warn",
        }],
    })
    monkeypatch.setattr(deck_qa, "run_lint_deck", lambda path, **kwargs: {
        "n_errors": 0, "n_warns": 0, "findings": [],
    })
    monkeypatch.setattr(deck_qa.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, "", ""))
    monkeypatch.setattr(render, "render_all", lambda *args, **kwargs: [tmp_path / "slide.png"])
    monkeypatch.setattr(deck_qa, "run_qa_crops", lambda *args, **kwargs: {
        "source_pages": [str(tmp_path / "slide.png")], "crops": [],
    })
    monkeypatch.setattr(sys, "argv", [
        "deck_qa.py", str(deck_path), "--output-root", str(output_root),
    ])

    assert deck_qa.main() == 0
    assert observed["PPTX_DECK_OUTPUT_ROOT"] == str(output_root.resolve())
    report = json.loads((output_root / "qa_report.json").read_text())
    assert report["slides"][0]["visual_review"] == "missing"
