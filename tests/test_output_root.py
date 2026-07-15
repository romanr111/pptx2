import sys
from pathlib import Path

from pptx import Presentation

import build_deck
import common
import lint_deck


def test_output_root_explicit_value_overrides_orchestrator_environment(tmp_path, monkeypatch):
    inherited_root = tmp_path / "from-orchestrator"
    explicit_root = tmp_path / "explicit"
    monkeypatch.setenv(common.OUTPUT_ROOT_ENV, str(inherited_root))

    resolved = common.resolve_output_root(explicit_root)

    assert resolved == explicit_root.resolve()


def test_output_root_uses_orchestrator_environment_before_legacy_default(tmp_path, monkeypatch):
    inherited_root = tmp_path / "from-orchestrator"
    monkeypatch.setenv(common.OUTPUT_ROOT_ENV, str(inherited_root))

    resolved = common.resolve_output_root()

    assert resolved == inherited_root.resolve()


def test_build_cli_writes_a_noncanonical_run_only_to_output_root(tmp_path, monkeypatch):
    spec_path = tmp_path / "custom-name.spec.json"
    spec_path.write_text("{}")
    default_root = tmp_path / "legacy-output"
    run_root = tmp_path / "output_gpt-5.6-terra-xhigh"
    monkeypatch.setattr(build_deck, "OUT", default_root)
    monkeypatch.setattr(build_deck, "MEDIA_CACHE", default_root / "media_cache")
    monkeypatch.setattr(build_deck, "validate_spec", lambda spec, root: [])
    monkeypatch.setattr(build_deck, "build", lambda spec, state=None: Presentation())
    monkeypatch.setattr(sys, "argv", [
        "build_deck.py", str(spec_path), "--output-root", str(run_root),
    ])

    assert build_deck.main() == 0

    assert (run_root / "custom-name.pptx").is_file()
    assert not default_root.exists()


def test_deck_package_size_uses_the_orchestrated_output_root(tmp_path, monkeypatch):
    """Deck lint must inspect the same built deck that deck_qa produced."""
    project = tmp_path / "project"
    run_root = tmp_path / "output_gpt5.6_terra_xhigh"
    run_root.mkdir()
    (run_root / "client-deck.pptx").write_bytes(b"deck")
    monkeypatch.setenv(common.OUTPUT_ROOT_ENV, str(run_root))
    findings = []

    lint_deck.check_package_size(
        {"packaging": {"max_package_mb": 1}},
        project / "specs" / "client-deck.deck.json", findings, project,
    )

    assert findings == []


def test_deck_package_size_uses_the_project_output_root_by_default(tmp_path, monkeypatch):
    """Direct callers retain the historical project-relative output lookup."""
    project = tmp_path / "project"
    built = project / "output" / "client-deck.pptx"
    built.parent.mkdir(parents=True)
    built.write_bytes(b"deck")
    monkeypatch.delenv(common.OUTPUT_ROOT_ENV, raising=False)
    findings = []

    lint_deck.check_package_size(
        {"packaging": {"max_package_mb": 1}},
        project / "specs" / "client-deck.deck.json", findings, project,
    )

    assert findings == []
