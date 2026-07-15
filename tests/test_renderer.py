from pathlib import Path
import json
import multiprocessing
import subprocess
import time
import zipfile

from PIL import Image
import pytest

import render


def _acquire_renderer_lock(lock_path, acquired, queue):
    metrics = {}
    with render.renderer_lock("docker", lock_path=lock_path, metrics=metrics):
        acquired.set()
        queue.put(metrics["renderer_queue_s"])


def test_docker_pdf_conversion_uses_isolated_pinned_renderer(tmp_path):
    """Delivery conversion must not expose the network or writable sources."""
    source_dir = tmp_path / "client"
    source_dir.mkdir()
    pptx = source_dir / "deck.pptx"
    pptx.write_bytes(b"fixture")
    output_dir = tmp_path / "execution" / "rendered"

    command = render.conversion_command(pptx, output_dir, "pdf", renderer="docker")

    assert command[:5] == ["docker", "run", "--rm", "--network", "none"]
    assert f"type=bind,src={source_dir.resolve()},dst=/input,readonly" in command
    assert f"type=bind,src={output_dir.resolve()},dst=/output" in command
    assert "--user" in command
    assert "HOME=/tmp" in command
    assert "-env:UserInstallation=file:///tmp/lo_profile" in command
    assert "@sha256:" in render.DOCKER_IMAGE
    assert command[command.index("--entrypoint") + 1] == "soffice"
    assert command[-8:] == [
        render.DOCKER_IMAGE,
        "-env:UserInstallation=file:///tmp/lo_profile",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        "/output",
        "/input/deck.pptx",
    ]


def test_render_all_defaults_to_docker_with_a_bounded_conversion(tmp_path, monkeypatch):
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"fixture")
    outdir = tmp_path / "rendered"
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "pdftoppm":
            prefix = Path(command[-1])
            Image.new("RGB", (2560, 1440), "white").save(
                prefix.with_name(prefix.name + "-1.png")
            )
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(render.subprocess, "run", fake_run)

    pngs = render.render_all(deck, outdir)

    assert pngs == [outdir / "deck_page-1.png"]
    assert calls[0][0][0:2] == ["docker", "run"]
    assert calls[0][1]["timeout"] == 300
    assert calls[0][1]["capture_output"] is True


def test_renderer_environment_allows_explicit_host_development_fallback(tmp_path, monkeypatch):
    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"fixture")
    monkeypatch.setenv("PPTX_DECK_RENDERER", "host")

    command = render.conversion_command(pptx, tmp_path / "rendered", "pdf")

    assert command[0] == "soffice"


def test_renderer_cache_is_invalidated_when_pinned_image_identity_changes(tmp_path, monkeypatch):
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"fixture")
    output = tmp_path / "rendered"
    output.mkdir()
    cached_png = output / "deck_page-1.png"
    Image.new("RGB", (64, 36), "red").save(cached_png)
    host_cache = output / f".render_cache_{render._file_hash(deck)}_docker.json"
    host_cache.write_text(json.dumps({"pngs": [cached_png.name]}))
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[0] == "pdftoppm":
            prefix = Path(command[-1])
            Image.new("RGB", (2560, 1440), "white").save(
                prefix.with_name(prefix.name + "-1.png")
            )
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(render.subprocess, "run", fake_run)

    render.render_all(deck, output, renderer="docker")

    assert calls[0][:2] == ["docker", "run"]


def test_render_cache_hash_ignores_nonvisual_package_metadata(tmp_path):
    first = tmp_path / "first.pptx"
    second = tmp_path / "second.pptx"
    for path, modified in ((first, "2026-01-01"), (second, "2026-07-15")):
        with zipfile.ZipFile(path, "w") as package:
            package.writestr("ppt/slides/slide1.xml", "<slide>same</slide>")
            package.writestr(
                "docProps/core.xml", f"<core><modified>{modified}</modified></core>"
            )

    assert first.read_bytes() != second.read_bytes()
    assert render._file_hash(first) == render._file_hash(second)


def test_failed_render_keeps_previous_published_pages(tmp_path, monkeypatch):
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"fixture")
    output = tmp_path / "rendered"
    output.mkdir()
    old_page = output / "deck_page-1.png"
    Image.new("RGB", (64, 36), "red").save(old_page)
    old_bytes = old_page.read_bytes()

    def fake_run(command, **kwargs):
        if command[0] == "pdftoppm":
            prefix = Path(command[-1])
            prefix.with_name(prefix.name + "-1.png").write_bytes(b"not-a-png")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(render.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="readable PNG"):
        render.render_all(deck, output, renderer="docker", expected_pages=1)

    assert old_page.read_bytes() == old_bytes
    assert not list(output.parent.glob(f".{output.name}.stage-*"))


def test_known_page_count_rasterizes_pages_independently(tmp_path, monkeypatch):
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"fixture")
    output = tmp_path / "rendered"
    raster_commands = []

    def fake_run(command, **kwargs):
        if command[0] == "pdftoppm":
            raster_commands.append(command)
            page = command[command.index("-f") + 1]
            Image.new("RGB", (2560, 1440), "white").save(
                Path(str(command[-1]) + ".png")
            )
            assert command[command.index("-l") + 1] == page
            assert "-singlefile" in command
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(render.subprocess, "run", fake_run)

    pages = render.render_all(
        deck, output, renderer="docker", expected_pages=3
    )

    assert [path.name for path in pages] == [
        "deck_page-1.png", "deck_page-2.png", "deck_page-3.png",
    ]
    assert {command[command.index("-f") + 1] for command in raster_commands} == {
        "1", "2", "3",
    }


@pytest.mark.filterwarnings(
    r"ignore:This process .* is multi-threaded, use of fork\(\) may lead to deadlocks.*:DeprecationWarning"
)
def test_docker_renderer_lock_serializes_different_output_roots(tmp_path):
    context = multiprocessing.get_context("fork")
    acquired = context.Event()
    queue = context.Queue()
    lock_path = tmp_path / "renderer.lock"
    process = context.Process(
        target=_acquire_renderer_lock, args=(lock_path, acquired, queue)
    )

    with render.renderer_lock("docker", lock_path=lock_path):
        process.start()
        time.sleep(0.1)
        assert not acquired.is_set()

    assert acquired.wait(2)
    process.join(timeout=2)
    assert process.exitcode == 0
    assert queue.get(timeout=1) >= 0.05
