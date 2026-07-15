"""Client-install bootstrap coverage."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETUP = PROJECT_ROOT / "scripts" / "setup_client.py"


def load_setup_module():
    spec = importlib.util.spec_from_file_location("setup_client", SETUP)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_client_setup_exposes_template_preflight_options():
    """A new client can discover the one-command setup and preflight path."""
    result = subprocess.run(
        [sys.executable, str(SETUP), "--help"],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )

    assert result.returncode == 0
    assert "--template" in result.stdout
    assert "--output-root" in result.stdout


def test_setup_stops_with_an_actionable_error_when_schema_contract_is_missing(tmp_path):
    setup = load_setup_module()

    with pytest.raises(setup.SetupError, match="spec.schema.json"):
        setup.validate_project_contract(tmp_path)
