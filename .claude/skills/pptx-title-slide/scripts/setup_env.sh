#!/bin/bash
# Sets up the Python environment and fonts needed by the pptx-title-slide skill.
# Idempotent: safe to re-run.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
VENV="$PROJECT_ROOT/.venv"

if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet python-pptx Pillow numpy jsonschema fonttools

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
"$VENV/bin/python" -c "import pptx, PIL, numpy, jsonschema, fontTools; print('python-pptx', pptx.__version__, '| Pillow', PIL.__version__, '| numpy', numpy.__version__, '| jsonschema', jsonschema.__version__, '| fonttools', fontTools.version)"
