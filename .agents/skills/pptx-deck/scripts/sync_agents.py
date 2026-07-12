#!/usr/bin/env python3
"""sync_agents.py — sync .agents/skills from .claude/skills.

The .agents/ directory is a legacy copy of .claude/skills that drifted
out of sync (missing border-order fixes, media_opt handling, brief_hash
checks). Rather than maintaining two trees by hand, this script
replaces .agents/skills with a fresh copy of .claude/skills.

Run after updating .claude/skills:
    python3 .claude/skills/pptx-deck/scripts/sync_agents.py
"""
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SRC = PROJECT_ROOT / ".claude" / "skills"
DST = PROJECT_ROOT / ".agents" / "skills"


def main():
    if not SRC.is_dir():
        print(f"source not found: {SRC}", flush=True)
        return 1
    DST.parent.mkdir(parents=True, exist_ok=True)
    if DST.exists() or DST.is_symlink():
        shutil.rmtree(DST)
    shutil.copytree(SRC, DST, symlinks=True)
    # Remove __pycache__ from the copy to avoid stale .pyc drift
    for pycache in DST.rglob("__pycache__"):
        shutil.rmtree(pycache)
    print(f"synced: {DST} <- {SRC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())