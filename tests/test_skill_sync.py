"""Skill-mirror installation coverage."""
import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYNC_SCRIPT = (PROJECT_ROOT / ".claude" / "skills" / "pptx-deck" /
               "scripts" / "sync_agents.py")


def load_sync_module():
    spec = importlib.util.spec_from_file_location("sync_agents", SYNC_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_sync_replaces_a_stale_skill_mirror_from_the_authoritative_source(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "mirror"
    (source / "pptx-deck").mkdir(parents=True)
    (source / "pptx-deck" / "SKILL.md").write_text("authoritative")
    (destination / "pptx-deck").mkdir(parents=True)
    (destination / "pptx-deck" / "SKILL.md").write_text("stale")
    (destination / "obsolete").mkdir()

    sync_agents = load_sync_module()
    sync_agents.sync(source, destination)

    assert (destination / "pptx-deck" / "SKILL.md").read_text() == "authoritative"
    assert not (destination / "obsolete").exists()


def test_sync_does_not_remove_an_unrelated_previous_sync_backup(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "mirror"
    (source / "pptx-deck").mkdir(parents=True)
    (source / "pptx-deck" / "SKILL.md").write_text("authoritative")
    (destination / "pptx-deck").mkdir(parents=True)
    backup = tmp_path / ".skills-sync-backup"
    backup.mkdir()
    marker = backup / "keep.txt"
    marker.write_text("previous interrupted sync")

    sync_agents = load_sync_module()
    sync_agents.sync(source, destination)

    assert marker.read_text() == "previous interrupted sync"
