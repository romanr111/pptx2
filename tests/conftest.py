"""Test bootstrap: make the pptx-deck skill scripts importable.

The scripts live in .claude/skills/pptx-deck/scripts/ (not a package) and
import each other as plain top-level modules, so tests do the same.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / ".claude" / "skills" / "pptx-deck" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
