#!/usr/bin/env python3
"""common.py — shared constants and primitives for the pptx-deck scripts.

These were previously copy-pasted across the pipeline (PROJECT_ROOT in 11
files, the EMU/px conversion constants in several, the textutil RTF→txt
invocation in two). Keeping one definition each stops them from drifting.

`PROJECT_ROOT` resolves the same way from any script in this directory:
this file lives in `<root>/.claude/skills/pptx-deck/scripts/`, so
`parents[4]` is the repository root.
"""
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]

# Slide geometry: a 960x540pt canvas (12192000x6858000 EMU) rendered at
# 2560x1440px. These are the exact conversion constants the whole pipeline
# shares; deriving them anywhere else risks a rounding mismatch.
EMU_PER_INCH = 914400
EMU_PER_PT = 12700
EMU_PER_PX = 4762.5          # 12192000 / 2560
PX_PER_PT = 2560 / 960       # 2.6667, px/pt at the render resolution


def textutil_to_txt(path: Path) -> str:
    """Convert an RTF (or other rich-text) file to plain text via macOS
    `textutil`. Raises `FileNotFoundError` (textutil absent) or
    `subprocess.CalledProcessError` (conversion failed) — callers that need
    a graceful fallback must catch those and read the file directly.
    """
    return subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", str(path)],
        capture_output=True, text=True, check=True).stdout
