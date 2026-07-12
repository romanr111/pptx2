#!/bin/bash
# Sets up the Python environment and fonts needed by the pptx pipeline.
# Idempotent: safe to re-run.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
VENV="$PROJECT_ROOT/.venv"

if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$PROJECT_ROOT/requirements.txt"

# Check external binaries
MISSING=""
for tool in soffice pdftoppm textutil; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    MISSING="$MISSING $tool"
  fi
done
if [ -n "$MISSING" ]; then
  echo "ERROR: required binaries not found:$MISSING" >&2
  echo "  soffice  — LibreOffice (brew install --cask libreoffice)" >&2
  echo "  pdftoppm — poppler     (brew install poppler)" >&2
  echo "  textutil — macOS built-in (should be on PATH)" >&2
  exit 1
fi

# Install the template fonts (user-level) so LibreOffice/PowerPoint render
# the generated deck with the intended typefaces. The template's own first
# slide instructs presenters to install these fonts.
FONTS_DIR="$HOME/Library/Fonts"
mkdir -p "$FONTS_DIR"
GEOLOGICA_DIR="$PROJECT_ROOT/assets/fonts/основной текст Geologica 2/static"
HELIOS_DIR="$PROJECT_ROOT/assets/fonts/заголовки HeliosCond"
for f in "Geologica-Light.ttf" "Geologica-Regular.ttf" "Geologica-Medium.ttf" "Geologica-SemiBold.ttf" "Geologica-Bold.ttf"; do
  [ -f "$FONTS_DIR/$f" ] || cp "$GEOLOGICA_DIR/$f" "$FONTS_DIR/$f"
done
for f in "HeliosCond.ttf" "HeliosCond-Bold.ttf"; do
  [ -f "$FONTS_DIR/$f" ] || cp "$HELIOS_DIR/$f" "$FONTS_DIR/$f"
done

echo "venv: $VENV"
echo "fonts installed to $FONTS_DIR (Geologica Light/Regular/Medium/SemiBold/Bold, HeliosCond, HeliosCond-Bold)"
"$VENV/bin/python" -c "import pptx, PIL, numpy, jsonschema, fontTools, lxml, pymupdf, pytest; print('all deps OK')"
