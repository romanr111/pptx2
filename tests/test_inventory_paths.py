import json
import subprocess
import sys
from pathlib import Path

import inventory
import template_style


def test_inventory_passes_explicit_template_to_style_extractor(tmp_path, monkeypatch):
    template = tmp_path / "client-template-final.pptx"
    template.write_bytes(b"template")
    facts_root = tmp_path / "out"
    calls = {}

    def fake_extract(template_path, *, with_thumbnails, renderer):
        calls["template"] = template_path
        calls["with_thumbnails"] = with_thumbnails
        calls["renderer"] = renderer
        return {"themes": [], "consistency_flags": []}

    monkeypatch.setattr(inventory, "OUT", facts_root)
    monkeypatch.setattr(inventory.template_style, "extract", fake_extract)
    monkeypatch.setattr(inventory, "inventory_images", lambda: [])
    monkeypatch.setattr(inventory, "inventory_fonts", lambda themes: {
        "fonts": [], "font_roles": {}, "naming_trap_flags": [],
    })
    monkeypatch.setattr(inventory, "inventory_text", lambda: [])
    monkeypatch.setattr(sys, "argv", [
        "inventory.py", "--template", str(template), "--no-thumbnails",
    ])

    inventory.main()

    assert calls == {"template": template.resolve(), "with_thumbnails": False,
                     "renderer": "docker"}
    assert json.loads((facts_root / "template_style.json").read_text())["themes"] == []


def test_inventory_thumbnail_render_uses_the_docker_delivery_renderer(tmp_path, monkeypatch):
    template = tmp_path / "client-template-final.pptx"
    template.write_bytes(b"template")
    output = tmp_path / "out"
    thumbnails = output / "thumbnails" / "template"
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[0] == "docker":
            mount = next(part for part in command
                         if part.startswith("type=bind,src=") and part.endswith("dst=/output"))
            pdf_dir = Path(mount.split(",")[1].removeprefix("src="))
            pdf_dir.mkdir(parents=True, exist_ok=True)
            (pdf_dir / "client-template-final.pdf").write_bytes(b"pdf")
        elif command[0] == "pdftoppm":
            prefix = Path(command[-1])
            prefix.parent.mkdir(parents=True, exist_ok=True)
            (prefix.parent / f"{prefix.name}-1.png").write_bytes(b"png")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(template_style, "OUT", output)
    monkeypatch.setattr(template_style, "THUMB_DIR", thumbnails)
    monkeypatch.setattr(template_style, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(template_style.subprocess, "run", fake_run)

    rendered = template_style.render_thumbnails(template)

    assert len(rendered) == 1
    assert rendered[0].startswith("out/thumbnails/template/")
    assert "docker_" in rendered[0]
    assert calls[0][:5] == ["docker", "run", "--rm", "--network", "none"]


def test_inventory_thumbnail_cache_isolated_by_template_and_renderer(tmp_path, monkeypatch):
    template = tmp_path / "client-template-final.pptx"
    template.write_bytes(b"template")
    output = tmp_path / "out"
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[0] == "pdftoppm":
            prefix = Path(command[-1])
            prefix.parent.mkdir(parents=True, exist_ok=True)
            (prefix.parent / f"{prefix.name}-1.png").write_bytes(b"png")
        elif command[0] == "soffice":
            pdf_dir = Path(command[command.index("--outdir") + 1])
            pdf_dir.mkdir(parents=True, exist_ok=True)
            (pdf_dir / "client-template-final.pdf").write_bytes(b"pdf")
        else:
            mount = next(part for part in command
                         if part.startswith("type=bind,src=") and part.endswith("dst=/output"))
            pdf_dir = Path(mount.split(",")[1].removeprefix("src="))
            pdf_dir.mkdir(parents=True, exist_ok=True)
            (pdf_dir / "client-template-final.pdf").write_bytes(b"pdf")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(template_style, "OUT", output)
    monkeypatch.setattr(template_style, "THUMB_DIR", output / "thumbnails" / "template")
    monkeypatch.setattr(template_style, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(template_style.subprocess, "run", fake_run)

    host = template_style.render_thumbnails(template, renderer="host")
    docker = template_style.render_thumbnails(template, renderer="docker")
    template.write_bytes(b"updated template")
    updated = template_style.render_thumbnails(template, renderer="host")

    assert host != docker
    assert host != updated
    assert any(command[0] == "docker" for command in calls)
