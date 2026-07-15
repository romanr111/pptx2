#!/usr/bin/env python3
"""Prepare full-resolution logo-corner and decorative-edge QA crops."""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

import build_deck
from common import PROJECT_ROOT


def _natural_key(path):
    match = re.search(r"(\d+)$", Path(path).stem)
    return (int(match.group(1)) if match else 0, Path(path).name)


def _safe(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_")


def _pixel_box(box, slide, width, height):
    x0 = round(box["x"] / slide["width_emu"] * width)
    y0 = round(box["y"] / slide["height_emu"] * height)
    x1 = round((box["x"] + box["cx"]) / slide["width_emu"] * width)
    y1 = round((box["y"] + box["cy"]) / slide["height_emu"] * height)
    return (
        max(0, min(width, x0)), max(0, min(height, y0)),
        max(0, min(width, x1)), max(0, min(height, y1)),
    )


def _bounded(x0, y0, x1, y1, width, height):
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(width, x1), min(height, y1)
    if x1 <= x0 or y1 <= y0:
        return None
    return tuple(map(int, (x0, y0, x1, y1)))


def _logo_corner_bounds(pixel_box, width, height, pad_x, pad_y):
    x0, y0, x1, y1 = pixel_box
    on_left = (x0 + x1) / 2 < width / 2
    on_top = (y0 + y1) / 2 < height / 2
    return _bounded(
        0 if on_left else x0 - pad_x,
        0 if on_top else y0 - pad_y,
        x1 + pad_x if on_left else width,
        y1 + pad_y if on_top else height,
        width, height,
    )


def _edge_bounds(side, pixel_box, width, height, pad_x, pad_y):
    x0, y0, x1, y1 = pixel_box
    if side == "left":
        return _bounded(x0 - pad_x, y0 - pad_y, x0 + pad_x,
                        y1 + pad_y, width, height)
    if side == "right":
        return _bounded(x1 - pad_x, y0 - pad_y, x1 + pad_x,
                        y1 + pad_y, width, height)
    if side == "top":
        return _bounded(x0 - pad_x, y0 - pad_y, x1 + pad_x,
                        y0 + pad_y, width, height)
    return _bounded(x0 - pad_x, y1 - pad_y, x1 + pad_x,
                    y1 + pad_y, width, height)


def _publish_directory(staging, target):
    backup = target.with_name(
        f".{target.name}.backup-{os.getpid()}-{time.time_ns()}")
    had_previous = target.exists()
    if had_previous:
        os.replace(target, backup)
    try:
        os.replace(staging, target)
    except Exception:
        if had_previous and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def generate_crops(deck_spec, render_dir, output_root,
                   project_root=PROJECT_ROOT):
    deck_spec = Path(deck_spec)
    render_dir = Path(render_dir)
    output_root = Path(output_root)
    project_root = Path(project_root)
    deck = json.loads(deck_spec.read_text())
    slide_paths = [project_root / path for path in deck.get("slides", [])]
    pages = sorted(render_dir.glob("*.png"), key=_natural_key)
    if len(pages) != len(slide_paths):
        raise RuntimeError(
            f"crop evidence found {len(pages)} pages for {len(slide_paths)} slides")

    target = output_root / "qa_crops"
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "deck_spec": str(deck_spec.resolve()),
        "source_pages": [str(page.resolve()) for page in pages],
        "crops": [],
    }
    with tempfile.TemporaryDirectory(
            prefix=".qa_crops.stage-", dir=target.parent) as temporary:
        staging = Path(temporary)
        for slide_index, (spec_path, page_path) in enumerate(
                zip(slide_paths, pages), start=1):
            spec = json.loads(spec_path.read_text())
            with Image.open(page_path) as source:
                page = source.convert("RGB")
            width, height = page.size
            pad_x = max(16, round(width * 0.03))
            pad_y = max(16, round(height * 0.03))
            elements = [
                element for element in spec.get("elements", [])
                if element.get("type") == "image"
            ]
            if spec.get("background"):
                elements.insert(0, {
                    "id": "background", "role": "background",
                    "type": "image", **spec["background"],
                })
            for element in elements:
                asset_path = project_root / element["asset"]
                with Image.open(asset_path) as asset:
                    asset_width, asset_height = asset.size
                fit = element.get("fit", "stretch")
                anchor = element.get("anchor", "center")
                geometry = build_deck.fitted_image_geometry(
                    element["box"], asset_width, asset_height,
                    fit=fit, anchor=anchor)
                placed = geometry["placed_box"]
                pixel_box = _pixel_box(placed, spec["slide"], width, height)
                role = (element.get("role") or "").lower()
                crop_requests = []
                if "logo" in role:
                    crop_requests.append((
                        "logo_corner",
                        _logo_corner_bounds(
                            pixel_box, width, height, pad_x, pad_y),
                    ))
                else:
                    sw = spec["slide"]["width_emu"]
                    sh = spec["slide"]["height_emu"]
                    internal = {
                        "left": placed["x"] > 0,
                        "top": placed["y"] > 0,
                        "right": placed["x"] + placed["cx"] < sw,
                        "bottom": placed["y"] + placed["cy"] < sh,
                    }
                    for side in ("left", "top", "right", "bottom"):
                        if internal[side]:
                            crop_requests.append((
                                f"decorative_edge_{side}",
                                _edge_bounds(
                                    side, pixel_box, width, height, pad_x, pad_y),
                            ))
                for crop_type, bounds in crop_requests:
                    if bounds is None:
                        continue
                    x0, y0, x1, y1 = bounds
                    filename = (
                        f"slide-{slide_index:02d}_{_safe(element['id'])}_"
                        f"{crop_type}.png")
                    page.crop(bounds).save(staging / filename)
                    manifest["crops"].append({
                        "slide": slide_index,
                        "slide_spec": str(spec_path.resolve()),
                        "element_id": element["id"],
                        "crop_type": crop_type,
                        "file": filename,
                        "source_page": str(page_path.resolve()),
                        "render_dimensions": {"width": width, "height": height},
                        "pixel_bounds": {
                            "x": x0, "y": y0,
                            "cx": x1 - x0, "cy": y1 - y0,
                        },
                        "fit": fit,
                        "anchor": anchor,
                        "source_crop": geometry["source_crop"],
                    })
        (staging / "manifest.json").write_text(json.dumps(
            manifest, ensure_ascii=False, indent=2))
        _publish_directory(staging, target)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deck_spec", type=Path)
    parser.add_argument("--render-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    manifest = generate_crops(
        args.deck_spec, render_dir=args.render_dir,
        output_root=args.output_root)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
