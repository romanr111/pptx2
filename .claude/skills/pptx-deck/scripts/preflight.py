#!/usr/bin/env python3
"""Prove a deck-delivery environment can render a real template.

Usage:
  preflight.py --template assets/template.pptx --renderer docker --output-root output
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from pptx import Presentation

from common import PROJECT_ROOT
from render import PDFTOPPM_DPI, conversion_command


def _check_output_root(output_root: Path) -> dict:
    try:
        output_root.mkdir(parents=True, exist_ok=True)
        probe = output_root / ".preflight-write-probe"
        probe.write_text("ok")
        probe.unlink()
    except OSError as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, "path": str(output_root)}


def _result_details(command: list[str], result: subprocess.CompletedProcess) -> dict:
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout or "",
        "stderr": result.stderr or "",
    }


def _run(command: list[str], timeout: int) -> dict:
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=timeout)
    except subprocess.TimeoutExpired as error:
        return {
            "command": command,
            "returncode": None,
            "stdout": error.stdout or "",
            "stderr": error.stderr or "",
            "error": f"conversion timed out after {timeout} seconds",
        }
    except OSError as error:
        return {
            "command": command,
            "returncode": None,
            "stdout": "",
            "stderr": str(error),
            "error": "could not start converter",
        }
    return _result_details(command, result)


def run_preflight(template: Path, renderer: str, output_root: Path,
                  project_root: Path = PROJECT_ROOT) -> dict:
    """Return evidence that this template can be converted to a PNG locally."""
    template = template.resolve()
    output_root = output_root.resolve()
    checks = {}

    try:
        Presentation(str(template))
    except Exception as error:
        checks["template"] = {"ok": False, "error": str(error)}
    else:
        checks["template"] = {"ok": True, "path": str(template)}

    missing_schemas = [str(project_root / "specs" / name) for name in
                       ("spec.schema.json", "deck.schema.json")
                       if not (project_root / "specs" / name).is_file()]
    checks["schemas"] = {"ok": not missing_schemas, "missing": missing_schemas}
    checks["output_root"] = _check_output_root(output_root)

    work_dir = output_root / "preflight"
    if checks["template"]["ok"] and checks["output_root"]["ok"]:
        work_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = work_dir / f"{template.stem}.pdf"
        convert = _run(conversion_command(template, work_dir, "pdf", renderer), 300)
        pdf_bytes = pdf_path.stat().st_size if pdf_path.is_file() else 0
        convert["pdf"] = str(pdf_path)
        convert["pdf_bytes"] = pdf_bytes
        convert["ok"] = convert["returncode"] == 0 and pdf_bytes > 0
        if not convert["ok"] and "error" not in convert:
            convert["error"] = "converter did not produce a non-empty PDF"
        checks["conversion"] = convert

        if convert["ok"]:
            prefix = work_dir / f"{template.stem}_page"
            png_path = Path(f"{prefix}.png")
            png_path.unlink(missing_ok=True)
            raster = _run(
                ["pdftoppm", "-f", "1", "-l", "1", "-singlefile",
                 "-png", "-r", str(PDFTOPPM_DPI),
                 str(pdf_path), str(prefix)], 300)
            pngs = [png_path] if png_path.is_file() else []
            raster["pngs"] = [str(path) for path in pngs]
            raster["png_count"] = len(pngs)
            raster["ok"] = raster["returncode"] == 0 and bool(pngs)
            if not raster["ok"] and "error" not in raster:
                raster["error"] = "pdftoppm did not produce a PNG"
            checks["rasterization"] = raster
        else:
            checks["rasterization"] = {"ok": False, "error": "conversion failed"}
    else:
        checks["conversion"] = {"ok": False, "error": "template or output root is unavailable"}
        checks["rasterization"] = {"ok": False, "error": "conversion did not run"}

    return {
        "ok": all(check["ok"] for check in checks.values()),
        "template": str(template),
        "renderer": renderer,
        "output_root": str(output_root),
        "checks": checks,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--renderer", choices=("docker", "host"), default="docker")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    report = run_preflight(args.template, args.renderer, args.output_root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
