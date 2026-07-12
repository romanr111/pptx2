#!/usr/bin/env python3
"""Shared pixel-level helpers used by asset inventory, spec conversion, and
reference verification. Pulled out as a single source of truth so the
title-slide fixture pipeline and the generic pptx-deck pipeline never drift
against each other.
"""
import numpy as np
from PIL import Image, ImageFilter


def bbox_of(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def alpha_bbox(img: Image.Image):
    a = np.asarray(img.split()[-1])
    return bbox_of(a > 8)


def dilate(mask: np.ndarray, size=9) -> np.ndarray:
    img = Image.fromarray((mask * 255).astype(np.uint8))
    return np.asarray(img.filter(ImageFilter.MaxFilter(size))) > 0


def line_bands(mask: np.ndarray, min_gap=6, min_rows=4, min_cols=12):
    """Split a text mask into horizontal bands (text lines) separated by gaps."""
    rows = np.nonzero(mask.sum(axis=1) >= min_cols)[0]
    if not len(rows):
        return []
    bands, start, prev = [], rows[0], rows[0]
    for r in rows[1:]:
        if r - prev > min_gap:
            if prev - start + 1 >= min_rows:
                bands.append((int(start), int(prev) + 1))
            start = r
        prev = r
    if prev - start + 1 >= min_rows:
        bands.append((int(start), int(prev) + 1))
    return bands


def new_ink(curr: np.ndarray, prev: np.ndarray, window, ink_thr=120, prev_thr=170):
    """Dark pixels present in `curr` but absent (even dilated) from `prev`.

    Comparing ink masks with dilation absorbs a few pixels of misalignment
    between two captures of the same underlying content.
    """
    x0, y0, x1, y1 = window
    win = np.zeros(curr.shape[:2], bool)
    win[y0:y1, x0:x1] = True
    return (curr.min(axis=2) < ink_thr) & ~dilate(prev.min(axis=2) < prev_thr) & win
