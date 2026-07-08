#!/usr/bin/env python3
"""Render a .pptx to a PNG at a fixed resolution via headless LibreOffice.

Shared by verify_reference.py (screenshot-reference regression) and
lint_render.py (deterministic checks with no reference screenshot).
"""
import subprocess
from pathlib import Path

W, H = 2560, 1440

PNG_FILTER = (f'png:impress_png_Export:{{"PixelWidth":{{"type":"long","value":{W}}},'
              f'"PixelHeight":{{"type":"long","value":{H}}}}}')


def render(pptx: Path, outdir: Path) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["soffice", "--headless", "--convert-to", PNG_FILTER,
         "--outdir", str(outdir), str(pptx)],
        check=True, capture_output=True, timeout=180)
    return outdir / (pptx.stem + ".png")
