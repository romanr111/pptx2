#!/usr/bin/env python3
"""Convert a free-form presentation styleguide into a structured profile.

The design skill uses this profile as a compact taste contract. It is
deliberately deterministic: no model call, no provider dependency.
"""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


from common import PROJECT_ROOT, textutil_to_txt
DEFAULT_SOURCE = PROJECT_ROOT / "assets" / "styleguide.rtf"
DEFAULT_OUT = PROJECT_ROOT / "out" / "styleguide_profile.json"


def _project_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def read_styleguide(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"styleguide not found: {path}")

    if path.suffix.lower() == ".rtf":
        try:
            return textutil_to_txt(path)
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

    return path.read_text(errors="replace")


def normalize_text(text: str) -> str:
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)
    text = re.sub(r"[{}]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _has(text: str, *needles: str) -> bool:
    lower = text.lower()
    return any(needle.lower() in lower for needle in needles)


def build_profile(text: str, source: Path) -> dict:
    normalized = normalize_text(text)
    style_name = "Medical Luxury Aesthetic"
    if not _has(normalized, style_name):
        style_name = "Presentation Styleguide"

    max_lines = 6 if _has(normalized, "6 ряд", "6 lines", "6 рядків") else None
    visual_ratio = 0.70 if _has(normalized, "70%") else None
    negative_space = 0.30 if _has(normalized, "30%") else None

    profile = {
        "profile_version": 1,
        "source": _project_path(source),
        "source_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16],
        "style_name": style_name,
        "aesthetic": {
            "positioning": "ultra-premium medical congress presentation",
            "quality_bar": "Apple Keynote / Nature Medicine editorial polish",
            "mood": "minimal, precise, high-contrast, clinical-luxury",
        },
        "layout_rules": {
            "visual_ratio_target": visual_ratio,
            "negative_space_target": negative_space,
            "wide_margins": _has(normalized, "wide", "відступ"),
            "minimal_clutter": _has(normalized, "мінімал", "clutter", "clean"),
        },
        "text_rules": {
            "one_main_idea_per_slide": _has(normalized, "1 голов", "one main"),
            "max_text_lines_per_slide": max_lines,
            "reduce_fluff": _has(normalized, "вод", "fluff"),
        },
        "visual_rules": {
            "preferred_visuals": [
                "premium medical 3D render",
                "anatomical or scientific schema",
                "surgical precision linework",
                "clean medical interface graphics",
            ],
            "linework": "thin, elegant, surgical-equipment precision",
            "avoid": ["watermarks", "logos", "generic stock-photo look", "visual clutter"],
        },
        "image_brief_defaults": {
            "style": (
                "ultra-premium medical congress visual, clean clinical luxury, "
                "surgical precision graphics, thin elegant linework"
            ),
            "negative": "no text, no watermarks, no logos, no clutter, no generic stock look",
        },
        "qa_checks": [
            "one clear idea",
            "visual-led composition with deliberate negative space",
            "premium medically relevant main visual",
            "conference-keynote typography, not document typography",
            "motion builds meaning rather than decoration",
        ],
    }

    return profile


def write_json(data: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build out/styleguide_profile.json")
    parser.add_argument("source", nargs="?", default=str(DEFAULT_SOURCE))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    source = Path(args.source)
    out = Path(args.out)
    profile = build_profile(read_styleguide(source), source)
    write_json(profile, out)
    print(json.dumps({"profile": _project_path(out), "style_name": profile["style_name"]}, indent=2))


if __name__ == "__main__":
    main()
