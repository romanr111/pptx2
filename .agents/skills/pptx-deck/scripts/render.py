#!/usr/bin/env python3
"""Render .pptx files to PNG via headless LibreOffice.

Two paths:
  - render(pptx, outdir) -> Path   — single-slide .pptx → one PNG (LO PNG export)
  - render_all(pptx, outdir) -> [Path] — multi-slide .pptx → one PNG per slide
    via PDF→pdftoppm (LO PNG export only produces the first slide)

Shared by verify_reference.py (screenshot-reference regression),
lint_render.py (deterministic checks with no reference screenshot), and
deck_qa.py (full-deck QA render).

render_all caches by file hash, serializes Docker LibreOffice conversions,
validates staged page evidence, and publishes a complete render set only.
"""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from PIL import Image

W, H = 2560, 1440

PNG_FILTER = (f'png:impress_png_Export:{{"PixelWidth":{{"type":"long","value":{W}}},'
              f'"PixelHeight":{{"type":"long","value":{H}}}}}')

# pdftoppm DPI that produces ~2560px wide images from 10in slides
PDFTOPPM_DPI = 256

# linuxserver/libreoffice 25.8.7.3-r0, pinned to its multi-architecture
# manifest. The digest, rather than the mutable tag, is the delivery
# renderer contract.
DOCKER_IMAGE = (
    "linuxserver/libreoffice:25.8.7@"
    "sha256:49128be9da2e82ec26413f3854a273d023c7c7a0a5ddb4b4e9705903d318dd0f"
)
RENDERER_ENV = "PPTX_DECK_RENDERER"
RENDERER_LOCK_PATH = Path(tempfile.gettempdir()) / "pptx-deck-docker-renderer.lock"


def resolve_renderer(renderer: str | None = None) -> str:
    return renderer or os.environ.get(RENDERER_ENV, "docker")


@contextmanager
def renderer_lock(renderer: str, lock_path: Path | None = None,
                  metrics: dict | None = None):
    """Serialize Docker LibreOffice conversions across output roots."""
    if renderer != "docker":
        if metrics is not None:
            metrics["renderer_queue_s"] = 0.0
        yield
        return
    path = Path(lock_path or RENDERER_LOCK_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    queued_at = time.monotonic()
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        queue_s = time.monotonic() - queued_at
        if metrics is not None:
            metrics["renderer_queue_s"] = queue_s
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({"pid": os.getpid(), "started_at": time.time()}))
        handle.flush()
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _renderer_cache_key(renderer: str) -> str:
    """Tie Docker evidence to the exact pinned image, not just its mode."""
    image_key = DOCKER_IMAGE if renderer == "docker" else renderer
    return f"{renderer}_{hashlib.sha256(image_key.encode()).hexdigest()[:12]}"


def conversion_command(pptx: Path, outdir: Path, output_format: str,
                       renderer: str | None = None) -> list[str]:
    """Return the isolated LibreOffice command for one conversion.

    Docker is the delivery default. It mounts the input directory read-only,
    exposes only the destination directory for writes, and disables networking.
    Host LibreOffice remains available for explicit local development fallback.
    """
    renderer = resolve_renderer(renderer)
    pptx = pptx.resolve()
    outdir = outdir.resolve()
    if renderer == "host":
        return ["soffice", "--headless", "--convert-to", output_format,
                "--outdir", str(outdir), str(pptx)]
    if renderer != "docker":
        raise ValueError(f"unknown renderer {renderer!r}; expected 'docker' or 'host'")
    user = f"{os.getuid()}:{os.getgid()}"
    return [
        "docker", "run", "--rm", "--network", "none",
        "--user", user, "--env", "HOME=/tmp",
        "--entrypoint", "soffice",
        "--mount", f"type=bind,src={pptx.parent},dst=/input,readonly",
        "--mount", f"type=bind,src={outdir},dst=/output",
        DOCKER_IMAGE,
        "-env:UserInstallation=file:///tmp/lo_profile",
        "--headless", "--convert-to", output_format,
        "--outdir", "/output", f"/input/{pptx.name}",
    ]


def render(pptx: Path, outdir: Path, renderer: str | None = None) -> Path:
    renderer = resolve_renderer(renderer)
    outdir.mkdir(parents=True, exist_ok=True)
    with renderer_lock(renderer):
        subprocess.run(
            conversion_command(pptx, outdir, PNG_FILTER, renderer=renderer),
            check=True, capture_output=True, timeout=180)
    return outdir / (pptx.stem + ".png")


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with zipfile.ZipFile(path) as package:
            names = sorted(
                name for name in package.namelist()
                if not name.endswith("/") and not name.startswith("docProps/"))
            for name in names:
                h.update(name.encode("utf-8"))
                h.update(b"\0")
                h.update(package.read(name))
    except zipfile.BadZipFile:
        with open(path, "rb") as source:
            for chunk in iter(lambda: source.read(65536), b""):
                h.update(chunk)
    return h.hexdigest()[:16]


def _page_sort_key(path: Path):
    match = re.search(r"(?:page)?-?(\d+)$", path.stem)
    return int(match.group(1)) if match else path.name


def _validate_pages(pngs: list[Path], expected_pages: int | None = None):
    if expected_pages is not None and len(pngs) != expected_pages:
        raise RuntimeError(
            f"render produced {len(pngs)} PNGs for {expected_pages} expected pages")
    if not pngs:
        raise RuntimeError("render produced no PNG pages")
    dimensions = []
    for path in pngs:
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"rendered page is empty or missing: {path}")
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                width, height = image.size
        except Exception as error:
            raise RuntimeError(f"rendered page is not a readable PNG: {path}: {error}") from error
        if width <= 0 or height <= 0:
            raise RuntimeError(f"rendered page has invalid dimensions: {path}: {width}x{height}")
        dimensions.append((width, height))
    if len(set(dimensions)) != 1:
        raise RuntimeError(f"rendered pages have inconsistent dimensions: {dimensions}")
    return dimensions[0]


def _publish_render_directory(staging: Path, outdir: Path):
    backup = outdir.with_name(
        f".{outdir.name}.backup-{os.getpid()}-{time.time_ns()}")
    had_previous = outdir.exists()
    if had_previous:
        os.replace(outdir, backup)
    try:
        os.replace(staging, outdir)
    except Exception:
        if had_previous and backup.exists() and not outdir.exists():
            os.replace(backup, outdir)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def render_all(pptx: Path, outdir: Path, renderer: str | None = None,
               expected_pages: int | None = None, metrics: dict | None = None) -> list[Path]:
    """Render a multi-slide .pptx to one PNG per slide via PDF→pdftoppm.

    LibreOffice's PNG export only produces the first slide, so the path
    is: soffice → PDF → pdftoppm → <stem>-1.png, <stem>-2.png, ...

    Caches by file hash and renderer: cached PNGs are never shared between
    host fallback and Docker delivery evidence.
    """
    renderer = resolve_renderer(renderer)
    outdir = outdir.resolve()
    outdir.parent.mkdir(parents=True, exist_ok=True)
    if metrics is not None:
        metrics.clear()
        metrics.update({"cache_hit": False, "renderer_queue_s": 0.0})
    h = _file_hash(pptx)
    cache_file = outdir / f".render_cache_{h}_{_renderer_cache_key(renderer)}.json"

    if cache_file.is_file():
        try:
            entry = json.loads(cache_file.read_text())
            pngs = [outdir / p for p in entry.get("pngs", [])]
            _validate_pages(pngs, expected_pages=expected_pages)
            if metrics is not None:
                metrics["cache_hit"] = True
                metrics["dimensions"] = entry.get("dimensions")
            return pngs
        except (json.JSONDecodeError, KeyError, RuntimeError):
            pass

    with tempfile.TemporaryDirectory(
            prefix=f".{outdir.name}.stage-", dir=outdir.parent) as temporary:
        staging = Path(temporary)
        pdf_path = staging / (pptx.stem + ".pdf")
        lock_metrics = {}
        conversion_started = time.monotonic()
        with renderer_lock(renderer, metrics=lock_metrics):
            subprocess.run(
                conversion_command(pptx, staging, "pdf", renderer=renderer),
                check=True, capture_output=True, timeout=300)
        if metrics is not None:
            metrics["renderer_queue_s"] = lock_metrics["renderer_queue_s"]
            metrics["conversion_s"] = time.monotonic() - conversion_started

        prefix = staging / (pptx.stem + "_page")
        raster_started = time.monotonic()
        if expected_pages is None:
            subprocess.run(
                ["pdftoppm", "-png", "-r", str(PDFTOPPM_DPI),
                 str(pdf_path), str(prefix)],
                check=True, capture_output=True, timeout=300)
        else:
            def rasterize_page(page_number):
                page_prefix = staging / f"{pptx.stem}_page-{page_number}"
                subprocess.run(
                    ["pdftoppm", "-png", "-r", str(PDFTOPPM_DPI),
                     "-f", str(page_number), "-l", str(page_number),
                     "-singlefile", str(pdf_path), str(page_prefix)],
                    check=True, capture_output=True, timeout=300)

            workers = min(expected_pages, max(1, min(os.cpu_count() or 1, 6)))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                list(executor.map(rasterize_page, range(1, expected_pages + 1)))
        if metrics is not None:
            metrics["rasterize_s"] = time.monotonic() - raster_started

        pngs = sorted(staging.glob(f"{pptx.stem}_page-*.png"), key=_page_sort_key)
        if not pngs:
            pngs = sorted(staging.glob(f"{pptx.stem}_page*.png"), key=_page_sort_key)
        validation_started = time.monotonic()
        dimensions = _validate_pages(pngs, expected_pages=expected_pages)
        if metrics is not None:
            metrics["validation_s"] = time.monotonic() - validation_started
        staging_cache = staging / cache_file.name
        staging_cache.write_text(json.dumps(
            {"hash": h, "pptx": str(pptx),
             "dimensions": list(dimensions),
             "pngs": [path.name for path in pngs]}, indent=2))
        names = [path.name for path in pngs]
        publish_started = time.monotonic()
        _publish_render_directory(staging, outdir)
        if metrics is not None:
            metrics["publish_s"] = time.monotonic() - publish_started

    if metrics is not None:
        metrics["dimensions"] = list(dimensions)
    return [outdir / name for name in names]
