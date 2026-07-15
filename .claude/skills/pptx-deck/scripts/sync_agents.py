#!/usr/bin/env python3
"""sync_agents.py — sync .agents/skills from .claude/skills.

The .agents/ directory is a legacy copy of .claude/skills that drifted
out of sync (missing border-order fixes, media_opt handling, brief_hash
checks). Rather than maintaining two trees by hand, this script
atomically replaces .agents/skills with a fresh copy of .claude/skills.

Run after updating .claude/skills:
    python3 .claude/skills/pptx-deck/scripts/sync_agents.py
"""
import shutil
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SRC = PROJECT_ROOT / ".claude" / "skills"
DST = PROJECT_ROOT / ".agents" / "skills"


def _remove_pycache(root: Path) -> None:
    # Remove __pycache__ from the copy to avoid stale .pyc drift
    for pycache in root.rglob("__pycache__"):
        shutil.rmtree(pycache)


def sync(source: Path = SRC, destination: Path = DST) -> None:
    """Copy source to destination without leaving a half-written mirror."""
    if not source.is_dir():
        raise FileNotFoundError(f"source not found: {source}")

    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    stage_root = Path(tempfile.mkdtemp(prefix=".skills-sync-", dir=parent))
    staged = stage_root / "skills"
    backup_root = Path(tempfile.mkdtemp(prefix=".skills-sync-backup-", dir=parent))
    backup = backup_root / "skills"
    try:
        shutil.copytree(source, staged, symlinks=True)
        _remove_pycache(staged)

        if destination.exists() or destination.is_symlink():
            destination.replace(backup)
        staged.replace(destination)
    except Exception:
        if backup.exists() and not destination.exists():
            backup.replace(destination)
        raise
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)

    shutil.rmtree(backup_root)


def main():
    try:
        sync()
    except (FileNotFoundError, OSError) as error:
        print(f"skill synchronization failed: {error}", flush=True)
        print("The .agents directory must be writable. In a managed sandbox, "
              "run setup from the client's normal checkout instead.", flush=True)
        return 1
    print(f"synced: {DST} <- {SRC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
