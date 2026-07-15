#!/usr/bin/env python3
"""deck_qa.py - one-command static-first deck build and QA.

The single entry point for delivering a deck. Chains the four pipeline
steps that were previously coordinated by hand:

    1. Static validation - registry, every slide, and cross-slide tokens.
    2. Build - one assembled deck only when static validation is clean.
    3. Render - one authoritative staged full-deck render.
    4. Rendered QA - actual assembled pages, crops, package, and delivery.
    5. Consolidate - atomic partial report promoted only on completion.

Usage:
    deck_qa.py <name.deck.json> [--static-only | --delivery]
      [--output-root output] [--out qa_report.json]
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
from common import (PROJECT_ROOT, OUTPUT_ROOT_ENV, STYLEGUIDE_GATE_CHECKS,  # noqa: E402
                    resolve_output_root)
OUT = resolve_output_root()


class QALockBusy(RuntimeError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def qa_run_lock(output_root, deck_path):
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    lock_path = output_root / ".deck_qa.lock"
    handle = lock_path.open("a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            handle.seek(0)
            owner_text = handle.read().strip()
            try:
                owner = json.loads(owner_text) if owner_text else {}
            except json.JSONDecodeError:
                owner = {"raw": owner_text}
            raise QALockBusy(
                f"deck QA output root is already locked: {lock_path}; "
                f"owner={json.dumps(owner, ensure_ascii=False)}") from error
        owner = {
            "pid": os.getpid(),
            "started_at": utc_now(),
            "deck": str(Path(deck_path).resolve()),
        }
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(owner, ensure_ascii=False))
        handle.flush()
        yield owner
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def atomic_write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    os.replace(temporary, path)


def report_paths(output_root, explicit_path=None):
    final_path = explicit_path or output_root / "qa_report.json"
    partial_path = final_path.with_name(
        "qa_report.partial.json" if final_path.name == "qa_report.json"
        else f"{final_path.stem}.partial{final_path.suffix}"
    )
    return final_path, partial_path


def record_stage(report, partial_path, name, action, current_slide=None):
    stage = {
        "name": name,
        "status": "running",
        "started_at": utc_now(),
        "completed_at": None,
        "active_s": 0.0,
        "renderer_queue_s": 0.0,
    }
    if current_slide is not None:
        stage["current_slide"] = current_slide
    report["stages"].append(stage)
    print(f"[deck_qa] stage={name} status=start"
          + (f" slide={current_slide}" if current_slide else ""),
          file=sys.stderr, flush=True)
    atomic_write_json(partial_path, report)
    started = time.monotonic()
    try:
        result = action()
    except Exception:
        stage["status"] = "failed"
        stage["completed_at"] = utc_now()
        stage["active_s"] = round(time.monotonic() - started, 6)
        report["timings"]["active_s"] = round(
            report["timings"]["active_s"] + stage["active_s"], 6)
        atomic_write_json(partial_path, report)
        print(f"[deck_qa] stage={name} status=failed "
              f"active_s={stage['active_s']:.3f}", file=sys.stderr, flush=True)
        raise
    stage["status"] = "complete"
    stage["completed_at"] = utc_now()
    stage["active_s"] = round(time.monotonic() - started, 6)
    report["timings"]["active_s"] = round(
        report["timings"]["active_s"] + stage["active_s"], 6)
    atomic_write_json(partial_path, report)
    print(f"[deck_qa] stage={name} status=complete "
          f"active_s={stage['active_s']:.3f}", file=sys.stderr, flush=True)
    return result


def configure_output_root(value=None):
    global OUT
    OUT = resolve_output_root(value)
    return OUT


def run_build_deck(deck_path, env=None):
    """Build the full deck .pptx via build_deck.py CLI."""
    r = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "build_deck.py"), str(deck_path)],
        capture_output=True, text=True,
        env=env,
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


def run_template_registry(slide_paths):
    from template_registry import validate_registry
    catalog = PROJECT_ROOT / "out" / "template_visual_catalog.json"
    template_style = PROJECT_ROOT / "out" / "template_style.json"
    assets_json = PROJECT_ROOT / "out" / "assets.json"
    missing = [path for path in (catalog, template_style, assets_json)
               if not path.is_file()]
    if missing:
        finding = {
            "severity": "warn",
            "check": "template_registry_unavailable",
            "item": "registry",
            "message": f"reviewed template registry could not be checked; missing: "
                       f"{[str(path) for path in missing]}",
        }
        return {
            "catalog": str(catalog), "ok": True,
            "counts": {"error": 0, "warn": 1}, "findings": [finding],
        }
    slide_specs = [json.loads(path.read_text()) for _, path in slide_paths]
    return validate_registry(
        catalog, template_style, assets_json,
        slide_specs=slide_specs, project_root=PROJECT_ROOT)


def run_qa_crops(deck_path, render_dir, output_root):
    from qa_crops import generate_crops
    return generate_crops(
        deck_path, render_dir=render_dir,
        output_root=output_root, project_root=PROJECT_ROOT)


def run_lint_render(spec_path, deck_path, env=None, static_only=False,
                    rendered_page=None):
    """Run lint_render.py on a single slide spec, return parsed report.

    Passes --deck so palette/packaging checks judge against the deck's own
    tokens instead of the template theme (explicit context, no global state).
    """
    command = [
        sys.executable, str(SCRIPTS_DIR / "lint_render.py"), str(spec_path),
        "--deck", str(deck_path),
    ]
    if static_only:
        command.append("--static-only")
    if rendered_page is not None:
        command.extend(["--rendered-page", str(rendered_page)])
    r = subprocess.run(
        command,
        capture_output=True, text=True,
        env=env,
    )
    if r.returncode not in (0, 1):
        detail = r.stderr.strip() or r.stdout.strip() or "no child output"
        raise RuntimeError(
            f"lint_render exited {r.returncode}: {detail}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"lint_render produced invalid JSON: {r.stdout[:200]!r}") from error


def run_lint_deck(deck_path, env=None, static_only=False, package_only=False):
    """Run lint_deck.py on the deck spec, return parsed report."""
    command = [sys.executable, str(SCRIPTS_DIR / "lint_deck.py"), str(deck_path)]
    if static_only:
        command.append("--static-only")
    if package_only:
        command.append("--package-only")
    r = subprocess.run(
        command,
        capture_output=True, text=True,
        env=env,
    )
    if r.returncode not in (0, 1):
        detail = r.stderr.strip() or r.stdout.strip() or "no child output"
        raise RuntimeError(
            f"lint_deck exited {r.returncode}: {detail}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"lint_deck produced invalid JSON: {r.stdout[:200]!r}") from error


def delivery_issues(report, slide_paths):
    """Return delivery-only gate failures without changing normal QA policy."""
    issues = []
    if report.get("build", {}).get("returncode") != 0:
        issues.append("deck build did not succeed")
    if report.get("deck_lint", {}).get("n_errors", 0):
        issues.append("deck lint has errors")
    for slide in report.get("slides", []):
        if slide.get("lint_render", {}).get("counts", {}).get("error", 0):
            issues.append(f"slide {slide.get('stem', '?')} lint has errors")

    render = report.get("render", {})
    if render.get("error"):
        issues.append(f"render failed: {render['error']}")
    elif len(render.get("pngs", [])) != len(slide_paths):
        issues.append(
            f"render produced {len(render.get('pngs', []))} PNGs for "
            f"{len(slide_paths)} slides")

    for stem, spec_path in slide_paths:
        try:
            review = json.loads(spec_path.read_text()).get("meta", {}).get("visual_review")
        except (OSError, json.JSONDecodeError) as error:
            issues.append(f"slide {stem} visual review could not be read: {error}")
            continue
        if not isinstance(review, dict):
            issues.append(f"slide {stem} lacks meta.visual_review")
            continue
        iteration = review.get("iteration")
        verdict = review.get("verdict")
        if isinstance(iteration, bool) or not isinstance(iteration, int) or not 1 <= iteration <= 3:
            issues.append(f"slide {stem} meta.visual_review.iteration must be 1-3")
        if verdict not in {"pass", "pass_with_notes"}:
            issues.append(
                f"slide {stem} meta.visual_review.verdict must be pass or pass_with_notes")

    # Styleguide aesthetic gate: unwaived visual-ratio / text-budget findings
    # block delivery (mirrors the visual_review gate). meta.styleguide_waiver
    # downgrades a finding warn->info in lint_render, so only genuinely
    # unaddressed shortfalls surface here; every waiver is echoed for review.
    summary = {"blocking": [], "waived": []}
    for slide in report.get("slides", []):
        stem = slide.get("stem", "?")
        for f in slide.get("lint_render", {}).get("findings", []):
            check = f.get("check")
            if check not in STYLEGUIDE_GATE_CHECKS:
                continue
            if f.get("severity") == "warn":
                summary["blocking"].append({"slide": stem, "check": check})
                issues.append(
                    f"slide {stem} fails styleguide gate ({check}) with no "
                    f"meta.styleguide_waiver -- add a hero visual or record a waiver")
            elif f.get("severity") == "info":
                summary["waived"].append(
                    {"slide": stem, "check": check, "note": f.get("message", "")})
    report["styleguide_gate"] = summary
    return issues


def _run_qa(args):
    deck_path = args.deck.resolve()
    output_root = configure_output_root(args.output_root)
    child_env = os.environ.copy()
    child_env[OUTPUT_ROOT_ENV] = str(output_root)
    child_env["PPTX_DECK_RENDERER"] = args.renderer
    report_path, partial_path = report_paths(output_root, args.out)
    if report_path.exists():
        report_path.unlink()
    report = {
        "deck": str(deck_path),
        "renderer": args.renderer,
        "run": {"pid": os.getpid(), "started_at": utc_now()},
        "stages": [],
        "timings": {"active_s": 0.0, "renderer_queue_s": 0.0},
        "build": {},
        "slides": [],
        "deck_lint": {},
        "template_registry": {},
        "render": {"status": "not_run", "pngs": [], "error": None},
        "crops": {"status": "not_run", "manifest": None, "n_crops": 0},
        "ok": True,
        "total_errors": 0,
    }
    atomic_write_json(partial_path, report)

    # Static deck validation and token conformance block all execution work.
    deck_lint_report = record_stage(
        report, partial_path, "static_deck_lint",
        lambda: run_lint_deck(deck_path, env=child_env, static_only=True),
    )
    report["deck_lint"] = deck_lint_report
    static_errors = deck_lint_report.get("n_errors", 0)
    report["total_errors"] += static_errors
    if static_errors:
        report["ok"] = False
        report["render"]["status"] = "skipped_static_errors"
        atomic_write_json(partial_path, report)
        os.replace(partial_path, report_path)
        return 1

    try:
        slide_paths = spec_paths_from_deck(deck_path)
    except Exception as error:
        report["ok"] = False
        report["total_errors"] += 1
        report["slides"] = [{
            "stem": "*", "spec": str(deck_path),
            "error": f"deck spec is not valid: {error}",
        }]
        slide_paths = []

    registry_report = record_stage(
        report, partial_path, "template_registry",
        lambda: run_template_registry(slide_paths),
    )
    report["template_registry"] = registry_report
    report["total_errors"] += registry_report.get("counts", {}).get("error", 0)

    for stem, spec_path in slide_paths:
        lint_report = record_stage(
            report, partial_path, "static_slide_lint",
            lambda path=spec_path: run_lint_render(
                path, deck_path, env=child_env, static_only=True),
            current_slide=stem,
        )
        entry = {
            "stem": stem,
            "spec": str(spec_path),
            "static_lint": lint_report,
            "lint_render": lint_report,
        }
        if any(f.get("check") == "visual_review"
               for f in lint_report.get("findings", [])):
            entry["visual_review"] = "missing"
        report["slides"].append(entry)
        report["total_errors"] += lint_report.get("counts", {}).get("error", 0)

    if report["total_errors"]:
        report["ok"] = False
        report["render"]["status"] = "skipped_static_errors"
        atomic_write_json(partial_path, report)
        os.replace(partial_path, report_path)
        return 1

    if args.static_only:
        report["render"]["status"] = "not_requested"
        atomic_write_json(partial_path, report)
        os.replace(partial_path, report_path)
        return 0

    # Execution starts only after every static blocker has been collected.
    build_result = record_stage(
        report, partial_path, "build_assembled_deck",
        lambda: run_build_deck(deck_path, env=child_env),
    )
    report["build"] = {
        "returncode": build_result["returncode"],
        "stdout": build_result["stdout"],
        "stderr": build_result["stderr"],
    }
    if build_result["returncode"] != 0:
        report["ok"] = False
        report["total_errors"] += 1
        report["render"]["status"] = "skipped_build_error"
        atomic_write_json(partial_path, report)
        return 1

    deck_lint_report = report["deck_lint"]
    report["render"] = {"status": "running", "pngs": [], "error": None}
    stem = deck_path.stem.replace(".deck", "")
    deck_pptx = OUT / f"{stem}.pptx"
    if not deck_pptx.is_file():
        report["render"]["error"] = f"{deck_pptx} not found"
        report["render"]["status"] = "failed"
        report["ok"] = False
        report["total_errors"] += 1
        atomic_write_json(partial_path, report)
        return 1

    sys.path.insert(0, str(SCRIPTS_DIR))
    from render import render_all
    render_dir = OUT / "rendered" / f"{stem}_qa"
    render_metrics = {}
    try:
        pngs = record_stage(
            report, partial_path, "render_assembled_deck",
            lambda: render_all(
                deck_pptx, render_dir, renderer=args.renderer,
                expected_pages=len(slide_paths), metrics=render_metrics),
        )
    except Exception as error:
        report["render"]["error"] = str(error)
        report["render"]["status"] = "failed"
        report["ok"] = False
        report["total_errors"] += 1
        atomic_write_json(partial_path, report)
        return 1

    queue_s = round(render_metrics.get("renderer_queue_s", 0.0), 6)
    render_stage = report["stages"][-1]
    render_stage["renderer_queue_s"] = queue_s
    render_stage["active_s"] = round(max(0.0, render_stage["active_s"] - queue_s), 6)
    report["timings"]["active_s"] = round(
        max(0.0, report["timings"]["active_s"] - queue_s), 6)
    report["timings"]["renderer_queue_s"] = queue_s
    print(
        f"[deck_qa] stage=render_assembled_deck status=timing "
        f"active_s={render_stage['active_s']:.3f} "
        f"renderer_queue_s={queue_s:.3f}",
        file=sys.stderr, flush=True,
    )
    report["render"]["pngs"] = [str(path) for path in pngs]
    report["render"]["n_slides"] = len(pngs)
    report["render"]["status"] = (
        "cached" if render_metrics.get("cache_hit") else "published")
    report["render"]["timings"] = {
        key: round(value, 6)
        for key, value in render_metrics.items()
        if key.endswith("_s")
    }
    atomic_write_json(partial_path, report)

    for (slide_stem, spec_path), png_path in zip(slide_paths, pngs):
        rendered_report = record_stage(
            report, partial_path, "rendered_page_lint",
            lambda path=spec_path, page=png_path: run_lint_render(
                path, deck_path, env=child_env, rendered_page=page),
            current_slide=slide_stem,
        )
        entry = next(s for s in report["slides"] if s["stem"] == slide_stem)
        entry["rendered_lint"] = rendered_report
        static_report = entry["static_lint"]
        findings = (list(static_report.get("findings", []))
                    + list(rendered_report.get("findings", [])))
        errors = sum(1 for finding in findings if finding.get("severity") == "error")
        warns = sum(1 for finding in findings if finding.get("severity") == "warn")
        entry["lint_render"] = {
            "spec": str(spec_path),
            "ok": errors == 0,
            "counts": {"error": errors, "warn": warns},
            "findings": findings,
        }
        report["total_errors"] += rendered_report.get("counts", {}).get("error", 0)
        if not rendered_report.get("ok", False):
            report["ok"] = False

    try:
        crop_manifest = record_stage(
            report, partial_path, "qa_crops",
            lambda: run_qa_crops(deck_path, render_dir, output_root),
        )
    except Exception as error:
        report["crops"] = {
            "status": "failed", "manifest": None,
            "n_crops": 0, "error": str(error),
        }
        report["ok"] = False
        report["total_errors"] += 1
        atomic_write_json(partial_path, report)
        return 1
    report["crops"] = {
        "status": "published",
        "manifest": str((output_root / "qa_crops" / "manifest.json").resolve()),
        "n_crops": len(crop_manifest.get("crops", [])),
        "source_pages": crop_manifest.get("source_pages", []),
    }
    atomic_write_json(partial_path, report)

    package_report = record_stage(
        report, partial_path, "package_lint",
        lambda: run_lint_deck(
            deck_path, env=child_env, package_only=True),
    )
    static_deck_report = report["deck_lint"]
    deck_lint_report = {
        "deck": str(deck_path),
        "n_errors": (static_deck_report.get("n_errors", 0)
                     + package_report.get("n_errors", 0)),
        "n_warns": (static_deck_report.get("n_warns", 0)
                    + package_report.get("n_warns", 0)),
        "findings": (list(static_deck_report.get("findings", []))
                     + list(package_report.get("findings", []))),
        "static": static_deck_report,
        "package": package_report,
    }
    report["deck_lint"] = deck_lint_report
    report["total_errors"] += package_report.get("n_errors", 0)
    if package_report.get("n_errors", 0):
        report["ok"] = False

    # Apply the opt-in delivery contract after normal QA has reported all
    # findings. Default QA still treats a missing review as a warning.
    if args.delivery:
        issues = delivery_issues(report, slide_paths)
        report["delivery"] = {"ok": not issues, "issues": issues,
                              "styleguide": report.pop("styleguide_gate", {})}
        if issues:
            report["ok"] = False
            report["total_errors"] += len(issues)

    # 7. Write consolidated report
    atomic_write_json(partial_path, report)
    os.replace(partial_path, report_path)
    print(json.dumps({
        "ok": report["ok"],
        "total_errors": report["total_errors"],
        "slides": [{"stem": s["stem"],
                      "errors": s.get("lint_render", {}).get("counts", {}).get("error", 0),
                      "visual_review": s.get("visual_review", "present")}
                    for s in report["slides"]],
        "deck_lint_errors": deck_lint_report.get("n_errors", 0),
        "delivery": report.get("delivery"),
        "render": {"n_slides": report["render"].get("n_slides", 0),
                   "error": report["render"].get("error")},
    }, ensure_ascii=False, indent=2))

    return 1 if not report["ok"] else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("deck", type=Path, help="path to a deck spec JSON file")
    ap.add_argument("--out", type=Path, default=None,
                    help="write consolidated QA report JSON here")
    ap.add_argument("--output-root", type=Path, default=None,
                    help="root for assembled decks, renders, and the default QA report")
    ap.add_argument("--renderer", choices=("docker", "host"), default="docker",
                    help="renderer for QA evidence; docker is the delivery default")
    ap.add_argument("--delivery", action="store_true",
                    help="require reviewed slides and complete rendered evidence")
    ap.add_argument("--static-only", action="store_true",
                    help="run all render-free QA checks and stop before build/render")
    args = ap.parse_args()
    if args.static_only and args.delivery:
        ap.error("--static-only cannot be combined with --delivery")
    output_root = resolve_output_root(args.output_root)
    try:
        with qa_run_lock(output_root, args.deck):
            return _run_qa(args)
    except QALockBusy as error:
        print(f"deck_qa: {error}", file=sys.stderr, flush=True)
        return 2
    except Exception as error:
        print(f"deck_qa: execution failed: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
