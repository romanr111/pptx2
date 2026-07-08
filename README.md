# pptx2

A spec-driven pipeline, built as Claude Code skills, for turning raw source
material (template + assets + copy) into a template-conformant `.pptx` deck.

The client's own template, photos, and slide copy used to develop and
self-test this pipeline are intentionally **not** included in this repo
(see `.gitignore`) — this repo is the reusable process, not one client's
output.

## Architecture

Every slide is split into three layers:

1. **Facts** (`pptx-deck/scripts/inventory.py`, `template_style.py`,
   deterministic) — what assets exist, what the template's own theme/layouts/
   media dictate. No guessing.
2. **Decisions** (`pptx-designer` skill, LLM judgment) — reads the facts,
   makes layout/color/font/asset choices, and freezes them into a **slide
   spec** JSON validated against `specs/spec.schema.json`.
3. **Execution** (`pptx-deck/scripts/build_deck.py`, `render.py`,
   deterministic) — spec in, `.pptx` + PNGs out. The builder never makes a
   layout or style decision; it only executes what the spec says.

A deterministic linter (`lint_render.py`) checks a spec/render for schema
conformance, font-naming-trap and glyph-coverage issues, text-fit overflow,
bounding-box overlap, contrast, watermark usage, and asset duplication
before the designer's own mandatory visual self-review.

## Layout

```
.claude/skills/
  pptx-deck/       # Facts + Execution: inventory, build, render, lint
  pptx-designer/    # Decisions: the design-judgment skill (SKILL.md)
  pptx-title-slide/ # original single-slide spike this pipeline grew from
specs/
  spec.schema.json  # the versioned slide-spec JSON Schema contract
  lint_test_fixtures/  # synthetic specs used to test the linter itself
```

## Using it on your own deck

1. Put your conference template at `assets/template.pptx` (or pass a path
   explicitly) and your own images/fonts/copy under `assets/`.
2. Run `inventory.py` to produce `out/assets.json` + `out/template_style.json`.
3. Have the `pptx-designer` skill author a spec under `specs/`, validating
   and iterating via `build_deck.py` + `lint_render.py` as documented in
   `.claude/skills/pptx-deck/SKILL.md` and `.claude/skills/pptx-designer/SKILL.md`.
4. Build the final deck: `build_deck.py specs/<name>.spec.json --states`.

See the `SKILL.md` file in each skill directory for the full, current
contract and workflow — they're the source of truth, not this README.
