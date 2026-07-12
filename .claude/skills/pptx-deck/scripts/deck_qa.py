#!/usr/bin/env python3
"""deck_qa.py — one-command deck build + QA.

The single entry point for delivering a deck. Chains the four pipeline
steps that were previously coordinated by hand:

    1. build_deck.py  — validate + build the full deck .pptx and per-slide
                        .pptx files (lint_render's check_render_structure
                        needs the per-slide files).
    2. lint_render.py — per-slide deterministic lint on every slide spec.
    3. lint_deck.py   — cross-slide deck lint.
    4. Consolidate    — one qa_report.json with all findings; exit 1 on
                        any error, 0 otherwise.

Usage:
    deck_qa.py <name.deck.json> [--out qa_report.json]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
from common import PROJECT_ROOT  # noqa: E402  (SCRIPTS_DIR is on sys.path as __main__)
OUT = PROJECT_ROOT / "output"


def run_build_deck(deck_path):
    """Build the full deck .pptx via build_deck.py CLI."""
    r = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "build_deck.py"), str(deck_path)],
        capture_output=True, text=True,
    )
    return {"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}


def spec_paths_from_deck(deck_path):
    """Return list of (stem, abs_spec_path) from the deck spec's slides[] list."""
    deck = json.loads(Path(deck_path).read_text())
    paths = []
    for slide_rel in deck.get("slides", []):
        spec_path = PROJECT_ROOT / slide_rel
        stem = spec_path.stem.replace(".spec", "")
        paths.append((stem, spec_path))
    return paths


def run_lint_render(spec_path, deck_path):
    """Run lint_render.py on a single slide spec, return parsed report.

    Passes --deck so palette/packaging checks judge against the deck's own
    tokens instead of the template theme (explicit context, no global state).
    """
    r = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "lint_render.py"), str(spec_path),
         "--deck", str(deck_path)],
        capture_output=True, text=True,
    )
    if r.returncode not in (0, 1):
        return {"ok": False, "error": f"lint_render crashed: {r.stderr}",
                "counts": {"error": 1, "warn": 0}, "findings": []}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"lint_render produced no JSON: {r.stdout[:200]}",
                "counts": {"error": 1, "warn": 0}, "findings": []}


def run_lint_deck(deck_path):
    """Run lint_deck.py on the deck spec, return parsed report."""
    r = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "lint_deck.py"), str(deck_path)],
        capture_output=True, text=True,
    )
    if r.returncode not in (0, 1):
        return {"n_errors": 1, "n_warns": 0, "findings": [],
                "error": f"lint_deck crashed: {r.stderr}"}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"n_errors": 1, "n_warns": 0, "findings": [],
                "error": f"lint_deck produced no JSON: {r.stdout[:200]}"}


def check_external_tools():
    """Verify required external binaries are on PATH.

    - soffice: LibreOffice headless, used by render.py and template_style.py
    - pdftoppm: poppler, used by template_style.py for thumbnail generation
    - textutil: macOS, used by inventory.py and styleguide_profile.py for
      .rtf/.docx text extraction
    """
    import shutil
    tools = ["soffice", "pdftoppm", "textutil"]
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        return [f"required binary '{t}' not found on PATH" for t in missing]
    return []


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("deck", type=Path, help="path to a deck spec JSON file")
    ap.add_argument("--out", type=Path, default=None,
                    help="write consolidated QA report JSON here")
    args = ap.parse_args()

    deck_path = args.deck.resolve()
    report = {
        "deck": str(deck_path),
        "tool_checks": {},
        "build": {},
        "slides": [],
        "deck_lint": {},
        "ok": True,
        "total_errors": 0,
    }

    # 0. External tool checks
    tool_issues = check_external_tools()
    report["tool_checks"] = {"missing": tool_issues}
    if tool_issues:
        report["ok"] = False
        report["total_errors"] = len(tool_issues)

    # 1. Build the full deck
    build_result = run_build_deck(deck_path)
    report["build"] = {
        "returncode": build_result["returncode"],
        "stdout": build_result["stdout"],
        "stderr": build_result["stderr"],
    }
    if build_result["returncode"] != 0:
        report["ok"] = False
        report["total_errors"] += 1

    # 2. Build per-slide .pptx files (lint_render needs output/<stem>.pptx)
    try:
        slide_paths = spec_paths_from_deck(deck_path)
    except Exception as e:
        report["ok"] = False
        report["total_errors"] += 1
        report["slides"] = [{"stem": "*", "spec": str(deck_path),
                             "error": f"deck spec is not valid: {e}"}]
        slide_paths = []
    for stem, spec_path in slide_paths:
        r = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "build_deck.py"), str(spec_path)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            report["slides"].append({
                "stem": stem, "spec": str(spec_path),
                "build_error": r.stderr, "lint_render": {"ok": False, "counts": {"error": 1, "warn": 0}},
            })
            report["ok"] = False
            report["total_errors"] += 1

    # 3. lint_render on each slide
    for stem, spec_path in slide_paths:
        if any(s.get("stem") == stem and s.get("build_error") for s in report["slides"]):
            continue
        lint_report = run_lint_render(spec_path, deck_path)
        slide_entry = {
            "stem": stem,
            "spec": str(spec_path),
            "lint_render": lint_report,
        }
        # Merge into report — reuse an existing (build_error) entry or append
        entry = next((s for s in report["slides"] if s.get("stem") == stem), None)
        if entry:
            entry["lint_render"] = lint_report
        else:
            entry = slide_entry
            report["slides"].append(entry)
        if not lint_report.get("ok", False):
            report["ok"] = False
        report["total_errors"] += lint_report.get("counts", {}).get("error", 0)
        # Track visual review status for the summary (a check=="visual_review"
        # finding means it's missing or malformed)
        if any(f["check"] == "visual_review" for f in lint_report.get("findings", [])):
            entry["visual_review"] = "missing"

    # 4. lint_deck
    deck_lint_report = run_lint_deck(deck_path)
    report["deck_lint"] = deck_lint_report
    if deck_lint_report.get("n_errors", 0) > 0:
        report["ok"] = False
    report["total_errors"] += deck_lint_report.get("n_errors", 0)

    # 5. Render all slides via render_all (PDF→pdftoppm, cached by hash)
    report["render"] = {"pngs": [], "error": None}
    stem = deck_path.stem.replace(".deck", "")
    deck_pptx = OUT / f"{stem}.pptx"
    if deck_pptx.is_file():
        try:
            sys.path.insert(0, str(SCRIPTS_DIR))
            from render import render_all
            render_dir = OUT / "rendered" / f"{stem}_qa"
            pngs = render_all(deck_pptx, render_dir)
            report["render"]["pngs"] = [str(p) for p in pngs]
            report["render"]["n_slides"] = len(pngs)
        except Exception as e:
            report["render"]["error"] = str(e)
            report["ok"] = False
            report["total_errors"] += 1
    else:
        report["render"]["error"] = f"{deck_pptx} not found"
        report["ok"] = False
        report["total_errors"] += 1

    # 6. Write consolidated report
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({
        "ok": report["ok"],
        "total_errors": report["total_errors"],
        "slides": [{"stem": s["stem"],
                      "errors": s.get("lint_render", {}).get("counts", {}).get("error", 0),
                      "visual_review": s.get("visual_review", "present")}
                    for s in report["slides"]],
        "deck_lint_errors": deck_lint_report.get("n_errors", 0),
        "tool_issues": tool_issues,
        "render": {"n_slides": report["render"].get("n_slides", 0),
                   "error": report["render"].get("error")},
    }, ensure_ascii=False, indent=2))

    return 1 if not report["ok"] else 0


if __name__ == "__main__":
    sys.exit(main())