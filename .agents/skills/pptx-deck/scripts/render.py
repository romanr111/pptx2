#!/usr/bin/env python3
"""Render .pptx files to PNG via headless LibreOffice.

Two paths:
  - render(pptx, outdir) -> Path   — single-slide .pptx → one PNG (LO PNG export)
  - render_all(pptx, outdir) -> [Path] — multi-slide .pptx → one PNG per slide
    via PDF→pdftoppm (LO PNG export only produces the first slide)

Shared by verify_reference.py (screenshot-reference regression),
lint_render.py (deterministic checks with no reference screenshot), and
deck_qa.py (full-deck QA render).

render_all caches by file hash so re-running deck_qa doesn't re-render
an unchanged deck.
"""
import hashlib
import subprocess
from pathlib import Path

W, H = 2560, 1440

PNG_FILTER = (f'png:impress_png_Export:{{"PixelWidth":{{"type":"long","value":{W}}},'
              f'"PixelHeight":{{"type":"long","value":{H}}}}}')

# pdftoppm DPI that produces ~2560px wide images from 10in slides
PDFTOPPM_DPI = 256


def render(pptx: Path, outdir: Path) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["soffice", "--headless", "--convert-to", PNG_FILTER,
         "--outdir", str(outdir), str(pptx)],
        check=True, capture_output=True, timeout=180)
    return outdir / (pptx.stem + ".png")


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def render_all(pptx: Path, outdir: Path) -> list[Path]:
    """Render a multi-slide .pptx to one PNG per slide via PDF→pdftoppm.

    LibreOffice's PNG export only produces the first slide, so the path
    is: soffice → PDF → pdftoppm → <stem>-1.png, <stem>-2.png, ...

    Caches by file hash: if <outdir>/<hash>.json exists and lists the same
    PNGs, they are returned without re-rendering.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    h = _file_hash(pptx)
    cache_file = outdir / f".render_cache_{h}.json"

    import json
    if cache_file.is_file():
        try:
            entry = json.loads(cache_file.read_text())
            pngs = [outdir / p for p in entry.get("pngs", [])]
            if all(p.is_file() for p in pngs):
                return pngs
        except (json.JSONDecodeError, KeyError):
            pass

    # stale pages from a previous (longer) version of the deck would
    # otherwise survive the re-render, get globbed into the result, and
    # inflate the reported slide count
    for old in outdir.glob(f"{pptx.stem}_page*.png"):
        old.unlink()

    pdf_path = outdir / (pptx.stem + ".pdf")
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "pdf",
         "--outdir", str(outdir), str(pptx)],
        check=True, capture_output=True, timeout=300)

    prefix = outdir / (pptx.stem + "_page")
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(PDFTOPPM_DPI), str(pdf_path), str(prefix)],
        check=True, capture_output=True, timeout=300)

    pngs = sorted(outdir.glob(f"{pptx.stem}_page-*.png"))
    if not pngs:
        pngs = sorted(outdir.glob(f"{pptx.stem}_page*.png"))

    cache_file.write_text(json.dumps(
        {"hash": h, "pptx": str(pptx),
         "pngs": [p.name for p in pngs]}, indent=2))
    return pngs