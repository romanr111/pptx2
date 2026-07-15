import json
import os
from pathlib import Path
import subprocess
import sys

import deck_qa
import render


def test_static_errors_publish_complete_report_without_build_or_render(
        tmp_path, monkeypatch):
    deck_path = tmp_path / "invalid.deck.json"
    deck_path.write_text(json.dumps({"slides": []}))
    output_root = tmp_path / "run"

    def forbidden(*args, **kwargs):
        raise AssertionError("static blocking errors did not stop execution")

    monkeypatch.setattr(deck_qa, "run_build_deck", forbidden)
    monkeypatch.setattr(deck_qa, "spec_paths_from_deck", lambda path: [])
    monkeypatch.setattr(deck_qa, "run_lint_deck", lambda path, **kwargs: {
        "n_errors": 1,
        "n_warns": 0,
        "findings": [{
            "severity": "error",
            "check": "deck_valid",
            "where": "deck",
            "message": "invalid deck fixture",
        }],
    })
    monkeypatch.setattr(sys, "argv", [
        "deck_qa.py", str(deck_path), "--output-root", str(output_root),
    ])

    assert deck_qa.main() == 1

    report_path = output_root / "qa_report.json"
    report = json.loads(report_path.read_text())
    assert not (output_root / "qa_report.partial.json").exists()
    assert report["render"]["status"] == "skipped_static_errors"
    assert report["run"]["pid"] == os.getpid()
    assert report["stages"]
    assert report["total_errors"] == 1


def test_static_stage_collects_every_slide_error_before_stopping(
        tmp_path, monkeypatch):
    deck_path = tmp_path / "sample.deck.json"
    deck_path.write_text(json.dumps({"slides": ["a", "b"]}))
    specs = []
    for name in ("a", "b"):
        path = tmp_path / f"{name}.spec.json"
        path.write_text("{}")
        specs.append((name, path))
    output_root = tmp_path / "run"
    observed = []

    def forbidden(*args, **kwargs):
        raise AssertionError("static slide errors did not stop execution")

    def fake_lint(spec, deck, **kwargs):
        observed.append((spec, kwargs))
        return {
            "ok": False,
            "counts": {"error": 1, "warn": 0},
            "findings": [{
                "severity": "error", "check": "text_fit",
                "element_id": "title", "message": f"{spec.stem} is invalid",
            }],
        }

    monkeypatch.setattr(deck_qa, "run_build_deck", forbidden)
    monkeypatch.setattr(deck_qa, "spec_paths_from_deck", lambda path: specs)
    monkeypatch.setattr(deck_qa, "run_lint_render", fake_lint)
    monkeypatch.setattr(deck_qa, "run_lint_deck", lambda path, **kwargs: {
        "n_errors": 0, "n_warns": 0, "findings": [],
    })
    monkeypatch.setattr(sys, "argv", [
        "deck_qa.py", str(deck_path), "--output-root", str(output_root),
    ])

    assert deck_qa.main() == 1

    report = json.loads((output_root / "qa_report.json").read_text())
    assert [spec for spec, _ in observed] == [specs[0][1], specs[1][1]]
    assert all(call["static_only"] for _, call in observed)
    assert [slide["stem"] for slide in report["slides"]] == ["a", "b"]
    assert report["total_errors"] == 2
    assert report["render"]["status"] == "skipped_static_errors"


def test_static_only_clean_run_finishes_without_build_or_render(tmp_path, monkeypatch):
    deck_path = tmp_path / "sample.deck.json"
    deck_path.write_text(json.dumps({"slides": ["slide"]}))
    spec_path = tmp_path / "slide.spec.json"
    spec_path.write_text("{}")
    output_root = tmp_path / "run"

    def forbidden(*args, **kwargs):
        raise AssertionError("--static-only continued into execution")

    monkeypatch.setattr(deck_qa, "run_build_deck", forbidden)
    monkeypatch.setattr(
        deck_qa, "spec_paths_from_deck", lambda path: [("slide", spec_path)]
    )
    monkeypatch.setattr(deck_qa, "run_lint_render", lambda *args, **kwargs: {
        "ok": True, "counts": {"error": 0, "warn": 0}, "findings": [],
    })
    monkeypatch.setattr(deck_qa, "run_lint_deck", lambda path, **kwargs: {
        "n_errors": 0, "n_warns": 0, "findings": [],
    })
    monkeypatch.setattr(sys, "argv", [
        "deck_qa.py", str(deck_path), "--static-only",
        "--output-root", str(output_root),
    ])

    assert deck_qa.main() == 0

    report = json.loads((output_root / "qa_report.json").read_text())
    assert report["ok"] is True
    assert report["render"]["status"] == "not_requested"
    assert report["slides"][0]["static_lint"]["ok"] is True


def test_clean_deck_builds_and_renders_once_then_lints_assembled_pages(
        tmp_path, monkeypatch):
    deck_path = tmp_path / "sample.deck.json"
    deck_path.write_text(json.dumps({"slides": ["a", "b"]}))
    specs = []
    for name in ("a", "b"):
        path = tmp_path / f"{name}.spec.json"
        path.write_text("{}")
        specs.append((name, path))
    output_root = tmp_path / "run"
    pages = [tmp_path / "page-1.png", tmp_path / "page-2.png"]
    calls = {
        "build": 0, "render": 0, "crops": 0,
        "static": [], "rendered": [],
    }

    def fake_build(path, env=None):
        calls["build"] += 1
        output_root.mkdir(parents=True, exist_ok=True)
        (output_root / "sample.pptx").write_bytes(b"assembled")
        return {"returncode": 0, "stdout": "built", "stderr": ""}

    def fake_lint(spec, deck, **kwargs):
        if kwargs.get("static_only"):
            calls["static"].append(spec)
        else:
            calls["rendered"].append((spec, kwargs.get("rendered_page")))
        return {
            "ok": True, "counts": {"error": 0, "warn": 0}, "findings": [],
        }

    def fake_render(*args, **kwargs):
        calls["render"] += 1
        return pages

    def fake_crops(*args, **kwargs):
        calls["crops"] += 1
        return {"source_pages": [str(page) for page in pages], "crops": []}

    monkeypatch.setattr(deck_qa, "spec_paths_from_deck", lambda path: specs)
    monkeypatch.setattr(deck_qa, "run_build_deck", fake_build)
    monkeypatch.setattr(deck_qa, "run_lint_render", fake_lint)
    monkeypatch.setattr(deck_qa, "run_lint_deck", lambda path, **kwargs: {
        "n_errors": 0, "n_warns": 0, "findings": [],
    })
    monkeypatch.setattr(deck_qa, "run_qa_crops", fake_crops)
    monkeypatch.setattr(render, "render_all", fake_render)
    monkeypatch.setattr(
        deck_qa.subprocess, "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("deck QA invoked a standalone slide subprocess")
        ),
    )
    monkeypatch.setattr(sys, "argv", [
        "deck_qa.py", str(deck_path), "--output-root", str(output_root),
    ])

    assert deck_qa.main() == 0

    assert calls["build"] == 1
    assert calls["render"] == 1
    assert calls["crops"] == 1
    assert calls["static"] == [specs[0][1], specs[1][1]]
    assert calls["rendered"] == [
        (specs[0][1], pages[0]),
        (specs[1][1], pages[1]),
    ]


def test_same_output_root_rejects_concurrent_qa_with_owner_details(
        tmp_path, monkeypatch, capsys):
    deck_path = tmp_path / "sample.deck.json"
    deck_path.write_text(json.dumps({"slides": []}))
    output_root = tmp_path / "run"
    output_root.mkdir()

    with deck_qa.qa_run_lock(output_root, deck_path):
        monkeypatch.setattr(sys, "argv", [
            "deck_qa.py", str(deck_path), "--output-root", str(output_root),
        ])
        assert deck_qa.main() == 2

    error = capsys.readouterr().err
    assert str(os.getpid()) in error
    assert str(deck_path) in error
    assert "started_at" in error


def test_execution_failure_keeps_partial_report_and_no_final(tmp_path, monkeypatch):
    deck_path = tmp_path / "sample.deck.json"
    deck_path.write_text(json.dumps({"slides": ["slide"]}))
    spec_path = tmp_path / "slide.spec.json"
    spec_path.write_text("{}")
    output_root = tmp_path / "run"

    monkeypatch.setattr(
        deck_qa, "spec_paths_from_deck", lambda path: [("slide", spec_path)]
    )
    monkeypatch.setattr(deck_qa, "run_lint_render", lambda *args, **kwargs: {
        "ok": True, "counts": {"error": 0, "warn": 0}, "findings": [],
    })
    monkeypatch.setattr(deck_qa, "run_lint_deck", lambda *args, **kwargs: {
        "n_errors": 0, "n_warns": 0, "findings": [],
    })
    monkeypatch.setattr(
        deck_qa, "run_build_deck",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("simulated build interruption")
        ),
    )
    monkeypatch.setattr(sys, "argv", [
        "deck_qa.py", str(deck_path), "--output-root", str(output_root),
    ])

    assert deck_qa.main() == 1

    partial = json.loads((output_root / "qa_report.partial.json").read_text())
    assert partial["stages"][-1]["status"] == "failed"
    assert not (output_root / "qa_report.json").exists()


def test_linter_process_failure_keeps_partial_report_and_no_final(
        tmp_path, monkeypatch):
    deck_path = tmp_path / "sample.deck.json"
    deck_path.write_text(json.dumps({"slides": []}))
    output_root = tmp_path / "run"
    monkeypatch.setattr(
        deck_qa.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 2, "", "simulated linter crash",
        ),
    )
    monkeypatch.setattr(sys, "argv", [
        "deck_qa.py", str(deck_path), "--output-root", str(output_root),
    ])

    assert deck_qa.main() == 1

    partial = json.loads((output_root / "qa_report.partial.json").read_text())
    assert partial["stages"][-1]["status"] == "failed"
    assert not (output_root / "qa_report.json").exists()


def test_linter_invalid_json_keeps_partial_report_and_no_final(
        tmp_path, monkeypatch):
    deck_path = tmp_path / "sample.deck.json"
    deck_path.write_text(json.dumps({"slides": []}))
    output_root = tmp_path / "run"
    monkeypatch.setattr(
        deck_qa.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, "not-json", "",
        ),
    )
    monkeypatch.setattr(sys, "argv", [
        "deck_qa.py", str(deck_path), "--output-root", str(output_root),
    ])

    assert deck_qa.main() == 1

    partial = json.loads((output_root / "qa_report.partial.json").read_text())
    assert partial["stages"][-1]["status"] == "failed"
    assert not (output_root / "qa_report.json").exists()


def test_slide_linter_process_failure_keeps_partial_report_and_no_final(
        tmp_path, monkeypatch):
    deck_path = tmp_path / "sample.deck.json"
    deck_path.write_text(json.dumps({"slides": ["slide"]}))
    spec_path = tmp_path / "slide.spec.json"
    spec_path.write_text("{}")
    output_root = tmp_path / "run"

    def fake_subprocess(command, **kwargs):
        if Path(command[1]).name == "lint_deck.py":
            return subprocess.CompletedProcess(
                command, 0,
                json.dumps({"n_errors": 0, "n_warns": 0, "findings": []}),
                "",
            )
        return subprocess.CompletedProcess(
            command, 2, "", "simulated slide linter crash",
        )

    monkeypatch.setattr(
        deck_qa, "spec_paths_from_deck", lambda path: [("slide", spec_path)],
    )
    monkeypatch.setattr(deck_qa, "run_template_registry", lambda paths: {
        "ok": True, "counts": {"error": 0, "warn": 0}, "findings": [],
    })
    monkeypatch.setattr(deck_qa.subprocess, "run", fake_subprocess)
    monkeypatch.setattr(sys, "argv", [
        "deck_qa.py", str(deck_path), "--output-root", str(output_root),
    ])

    assert deck_qa.main() == 1

    partial = json.loads((output_root / "qa_report.partial.json").read_text())
    assert partial["stages"][-1]["status"] == "failed"
    assert not (output_root / "qa_report.json").exists()


def test_slide_linter_invalid_json_keeps_partial_report_and_no_final(
        tmp_path, monkeypatch):
    deck_path = tmp_path / "sample.deck.json"
    deck_path.write_text(json.dumps({"slides": ["slide"]}))
    spec_path = tmp_path / "slide.spec.json"
    spec_path.write_text("{}")
    output_root = tmp_path / "run"

    def fake_subprocess(command, **kwargs):
        if Path(command[1]).name == "lint_deck.py":
            return subprocess.CompletedProcess(
                command, 0,
                json.dumps({"n_errors": 0, "n_warns": 0, "findings": []}),
                "",
            )
        return subprocess.CompletedProcess(command, 0, "not-json", "")

    monkeypatch.setattr(
        deck_qa, "spec_paths_from_deck", lambda path: [("slide", spec_path)],
    )
    monkeypatch.setattr(deck_qa, "run_template_registry", lambda paths: {
        "ok": True, "counts": {"error": 0, "warn": 0}, "findings": [],
    })
    monkeypatch.setattr(deck_qa.subprocess, "run", fake_subprocess)
    monkeypatch.setattr(sys, "argv", [
        "deck_qa.py", str(deck_path), "--output-root", str(output_root),
    ])

    assert deck_qa.main() == 1

    partial = json.loads((output_root / "qa_report.partial.json").read_text())
    assert partial["stages"][-1]["status"] == "failed"
    assert not (output_root / "qa_report.json").exists()
