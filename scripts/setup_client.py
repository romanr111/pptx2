#!/usr/bin/env python3
"""Set up a clean pptx2 workspace and optionally preflight a client template.

Run from a fresh checkout:
  python3 scripts/setup_client.py --template path/to/template.pptx \
    --output-root output/<client-run>
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILES = ("spec.schema.json", "deck.schema.json")


class SetupError(RuntimeError):
    """A local prerequisite is unavailable or the checkout is incomplete."""


def validate_project_contract(project_root: Path) -> None:
    """Fail before installation work when the pipeline contract is incomplete."""
    missing = [project_root / "specs" / name for name in SCHEMA_FILES
               if not (project_root / "specs" / name).is_file()]
    if missing:
        names = ", ".join(str(path.relative_to(project_root)) for path in missing)
        raise SetupError(
            f"required pipeline files are missing: {names}\n"
            "Use a clean checkout, or restore the files before running setup."
        )


def _run(command: list[str], description: str) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except OSError as error:
        raise SetupError(f"{description} could not start: {error}") from error
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        suffix = f"\n{detail}" if detail else ""
        raise SetupError(f"{description} failed (exit {result.returncode}).{suffix}")
    return result


def _require_command(name: str, install_hint: str) -> None:
    if shutil.which(name) is None:
        raise SetupError(f"required command not found: {name}\n{install_hint}")


def _sync_skills(project_root: Path) -> None:
    _run(
        [sys.executable, str(project_root / ".claude" / "skills" / "pptx-deck" /
                            "scripts" / "sync_agents.py")],
        "skill mirror synchronization",
    )


def _ensure_venv(project_root: Path) -> Path:
    venv = project_root / ".venv"
    python = venv / "bin" / "python"
    if not python.is_file():
        _run([sys.executable, "-m", "venv", str(venv)], "virtual-environment creation")
    _run([str(python), "-m", "pip", "install", "--upgrade", "pip"], "pip upgrade")
    _run([str(python), "-m", "pip", "install", "-r", str(project_root / "requirements.txt")],
         "Python dependency installation")
    return python


def _ensure_renderer(project_root: Path, renderer: str, pull_image: bool) -> None:
    if renderer == "host":
        _require_command("soffice", "Install LibreOffice, then rerun with --renderer host.")
        return

    _require_command(
        "docker",
        "Install the Docker CLI and start a Docker-compatible daemon "
        "(for example Docker Desktop, Colima, or OrbStack), then rerun setup.",
    )
    _run(["docker", "info"], "Docker daemon check")
    scripts_dir = project_root / ".claude" / "skills" / "pptx-deck" / "scripts"
    sys.path.insert(0, str(scripts_dir))
    from render import DOCKER_IMAGE

    inspect = subprocess.run(["docker", "image", "inspect", DOCKER_IMAGE],
                             capture_output=True, text=True)
    if inspect.returncode:
        if not pull_image:
            raise SetupError(
                f"pinned delivery image is not available: {DOCKER_IMAGE}\n"
                "Rerun without --no-pull after the Docker-compatible daemon is ready."
            )
        _run(["docker", "pull", DOCKER_IMAGE], "pinned LibreOffice image download")


def setup_workspace(project_root: Path, renderer: str, pull_image: bool) -> Path:
    """Install the project prerequisites and return the workspace Python."""
    validate_project_contract(project_root)
    _sync_skills(project_root)
    python = _ensure_venv(project_root)
    _require_command("pdftoppm", "Install Poppler (macOS: brew install poppler).")
    _require_command("textutil", "Use macOS, where textutil is built in and available on PATH.")
    _ensure_renderer(project_root, renderer, pull_image)
    return python


def _run_preflight(python: Path, project_root: Path, template: Path,
                   output_root: Path, renderer: str) -> None:
    if not template.is_file():
        raise SetupError(f"template not found: {template}")
    result = _run(
        [str(python), str(project_root / ".claude" / "skills" / "pptx-deck" /
                          "scripts" / "preflight.py"),
         "--template", str(template), "--renderer", renderer,
         "--output-root", str(output_root)],
        "template preflight",
    )
    if result.stdout:
        print(result.stdout, end="")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path,
                        help="actual client template to preflight after setup")
    parser.add_argument("--output-root", type=Path,
                        help="execution root for the optional template preflight")
    parser.add_argument("--renderer", choices=("docker", "host"), default="docker",
                        help="docker is the delivery default; host is development only")
    parser.add_argument("--no-pull", action="store_true",
                        help="do not pull the pinned Docker renderer image when absent")
    args = parser.parse_args()
    if args.output_root and not args.template:
        parser.error("--output-root requires --template")

    try:
        python = setup_workspace(PROJECT_ROOT, args.renderer, not args.no_pull)
        if args.template:
            output_root = args.output_root or PROJECT_ROOT / "output" / "preflight"
            _run_preflight(python, PROJECT_ROOT, args.template, output_root, args.renderer)
    except SetupError as error:
        print(f"SETUP FAILED: {error}", file=sys.stderr)
        return 1

    print("Setup complete.")
    if not args.template:
        print("Next, run this command with the actual client template:")
        print("  python3 scripts/setup_client.py --template path/to/template.pptx "
              "--output-root output/<client-run>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
