import json
import sys

import lint_render
import lint_deck
from PIL import Image


def write_static_spec(path):
    path.write_text(json.dumps({
        "spec_version": 1,
        "slide": {"width_emu": 12192000, "height_emu": 6858000},
        "elements": [],
    }))
    return path


def test_static_lint_never_renders_or_installs_fonts(tmp_path, monkeypatch):
    spec = write_static_spec(tmp_path / "slide.spec.json")

    def forbidden(*args, **kwargs):
        raise AssertionError("static lint invoked a render-dependent side effect")

    monkeypatch.setattr(lint_render, "render", forbidden)
    monkeypatch.setattr(lint_render, "ensure_fonts_installed", forbidden)

    report = lint_render.lint_static(spec)

    assert "render_structure" not in {
        finding["check"] for finding in report["findings"]
    }


def test_static_lint_reports_missing_facts_without_side_effects(tmp_path, monkeypatch):
    spec = write_static_spec(tmp_path / "slide.spec.json")

    def forbidden(*args, **kwargs):
        raise AssertionError("static lint invoked a render-dependent side effect")

    monkeypatch.setattr(lint_render, "render", forbidden)
    monkeypatch.setattr(lint_render, "ensure_fonts_installed", forbidden)
    monkeypatch.setattr(lint_render, "ASSETS_JSON_PATH", tmp_path / "assets.json")
    monkeypatch.setattr(lint_render, "TEMPLATE_STYLE_JSON_PATH",
                        tmp_path / "template_style.json")

    report = lint_render.lint_static(spec)

    assert report["ok"] is False
    assert {finding["check"] for finding in report["findings"]} == {
        "facts_assets_missing", "facts_template_style_missing",
    }


def test_legacy_lint_stops_after_any_static_error(tmp_path, monkeypatch):
    spec_path = tmp_path / "slide.spec.json"
    spec_path.write_text("{}")
    expected = {
        "spec": str(spec_path),
        "ok": False,
        "counts": {"error": 1, "warn": 0},
        "findings": [{"check": "facts_assets_missing", "severity": "error"}],
    }

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy lint continued after a static error")

    (tmp_path / "assets.json").write_text('{"fonts": []}')
    monkeypatch.setattr(lint_render, "lint_static", lambda *args, **kwargs: expected)
    monkeypatch.setattr(lint_render, "ASSETS_JSON_PATH", tmp_path / "assets.json")
    monkeypatch.setattr(lint_render, "check_render_structure", forbidden)

    assert lint_render.lint(spec_path) == expected


def test_rendered_lint_reads_the_supplied_assembled_page(tmp_path, monkeypatch):
    spec_path = tmp_path / "slide.spec.json"
    spec_path.write_text(
        """{
          "slide": {"width_emu": 1000, "height_emu": 1000},
          "elements": [{
            "id": "title",
            "type": "textbox",
            "box": {"x": 100, "y": 100, "cx": 800, "cy": 300},
            "paragraphs": [{"lines": [{"text": "Expected line"}]}]
          }]
        }"""
    )
    rendered_page = tmp_path / "assembled-page-2.png"
    Image.new("RGB", (3414, 1920), "white").save(rendered_page)

    def forbidden(*args, **kwargs):
        raise AssertionError("rendered-page lint invoked a new conversion")

    monkeypatch.setattr(lint_render, "render", forbidden)
    monkeypatch.setattr(lint_render, "ensure_fonts_installed", forbidden)

    report = lint_render.lint_rendered(spec_path, rendered_page)

    assert report["rendered_page"] == str(rendered_page)
    assert {finding["check"] for finding in report["findings"]} == {
        "render_structure"
    }


def test_static_only_cli_selects_static_stage(tmp_path, monkeypatch, capsys):
    spec_path = tmp_path / "slide.spec.json"
    spec_path.write_text("{}")
    expected = {
        "spec": str(spec_path),
        "ok": True,
        "counts": {"error": 0, "warn": 0},
        "findings": [],
    }
    monkeypatch.setattr(lint_render, "lint_static", lambda *args, **kwargs: expected)
    monkeypatch.setattr(
        lint_render, "lint", lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy full lint was selected")
        )
    )
    monkeypatch.setattr(sys, "argv", [
        "lint_render.py", str(spec_path), "--static-only",
    ])

    assert lint_render.main() == 0
    assert json.loads(capsys.readouterr().out) == expected


def test_rendered_page_cli_selects_only_rendered_stage(tmp_path, monkeypatch, capsys):
    spec_path = tmp_path / "slide.spec.json"
    page_path = tmp_path / "page.png"
    spec_path.write_text("{}")
    page_path.write_bytes(b"page")
    expected = {
        "spec": str(spec_path),
        "rendered_page": str(page_path),
        "ok": True,
        "counts": {"error": 0, "warn": 0},
        "findings": [],
    }
    observed = {}

    def fake_rendered(spec, page):
        observed["paths"] = (spec, page)
        return expected

    monkeypatch.setattr(lint_render, "lint_rendered", fake_rendered)
    monkeypatch.setattr(
        lint_render, "lint", lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy full lint was selected")
        )
    )
    monkeypatch.setattr(sys, "argv", [
        "lint_render.py", str(spec_path), "--rendered-page", str(page_path),
    ])

    assert lint_render.main() == 0
    assert observed["paths"] == (spec_path, page_path)
    assert json.loads(capsys.readouterr().out) == expected


def test_deck_static_and_package_stages_are_separate(tmp_path, monkeypatch):
    deck_path = tmp_path / "sample.deck.json"
    deck_path.write_text(json.dumps({
        "slides": [],
        "slide": {"width_emu": 1000, "height_emu": 1000},
        "packaging": {"max_package_mb": 1},
    }))
    monkeypatch.setattr(lint_deck, "validate_deck", lambda *args: ([], []))

    static_report = lint_deck.lint_deck(deck_path, static_only=True)
    package_report = lint_deck.lint_deck(deck_path, package_only=True)

    assert "package_size" not in {
        finding["check"] for finding in static_report["findings"]
    }
    assert {finding["check"] for finding in package_report["findings"]} == {
        "package_size"
    }
