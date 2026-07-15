#!/bin/bash
# Sets up the Python environment and fixture fonts needed by the pptx pipeline.
# Idempotent: safe to re-run. Docker is the default renderer.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
VENV="$PROJECT_ROOT/.venv"
RENDERER="${PPTX_DECK_RENDERER:-docker}"
python3 "$PROJECT_ROOT/scripts/setup_client.py" --renderer "$RENDERER"

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
