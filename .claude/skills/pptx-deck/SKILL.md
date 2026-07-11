---
name: pptx-deck
description: Spec-driven .pptx pipeline — validate/build a slide spec into a real deck, render it, and inventory template/asset facts. Use when asked to build a deck from a slide spec, inventory assets/template for a new deck, or extend the pptx generation pipeline beyond the title-slide spike.
---

# pptx-deck

Generic engine for the larger goal (see `assets/client_goal.rtf`): turning a
doctor's materials into a presentation that conforms to a conference
template. Every slide is split into three layers:

1. **Facts** (this skill's `inventory.py`, deterministic) — what assets
   exist, what the template dictates.
2. **Decisions** (a human, or a future designer skill) — frozen into a
   **slide spec** JSON file validated against `specs/spec.schema.json`.
3. **Execution** (this skill's `build_deck.py` + `render.py`, deterministic)
   — spec in, `.pptx` + PNGs out. The builder never makes a layout or style
   decision; it only executes what the spec says.

The only things ever hardcoded here are the spec schema and the builder
primitives — never a particular slide's layout, fonts, or positions.

## Scripts

All under `scripts/`, run with the project venv (`.venv/bin/python`, set up
by `.claude/skills/pptx-title-slide/scripts/setup_env.sh`):

- **`styleguide_profile.py`** — converts `assets/styleguide.rtf` into
  `out/styleguide_profile.json`, a compact design-phase taste contract used by
  `pptx-designer`, `asset_resolver.py`, and `lint_render.py`.
- **`inventory.py`** — walks `assets/` and the template `.pptx`, writes
  `out/assets.json` (per-image classification + watermark flag, per-font
  name-table families/weights + role guess, per-text-file parsed blocks) and
  `out/template_style.json` (theme fonts/colors, per-layout placeholder
  geometry, media/logo inventory, margins, animation exemplars, slide
  thumbnails, plus — since the thumbnails were being rendered but never
  actually used — `slide_layout_map` (which layout definition each real
  template slide uses), `slide_media_map` (which media files each real
  slide's own XML embeds), and `media_reuse_ranked` (media ranked by how
  many distinct slides reuse it — a cheap, deterministic signal for
  "decorative/brand asset" vs. "one-off content", though not exhaustive:
  some assets are only traceable via *a* slide that references them
  directly, not every slide that visually shows them — see
  `out/template_visual_catalog.json`'s caveats). Read this before authoring
  a spec by hand or designing a new slide type.
- **`out/template_visual_catalog.json`** — a cached, human/LLM-written
  description of what the template's own real slides actually look like
  (grouped by distinct layout via `slide_layout_map`, plus notes on
  recurring visual assets via `media_reuse_ranked`), because the facts
  above are all numeric/structural and say nothing about what the
  template's own designer actually *did* with them — e.g. which color mode
  a given layout uses, or that a decorative asset visible on several slides
  can only be extracted via one specific slide's media reference. Built
  once per template by following the bootstrap procedure documented in
  `pptx-designer/SKILL.md`'s Inputs section (not by a deterministic
  script — it requires actually looking at the thumbnails), and reused
  cheaply after that; stale if its `n_slides_total` no longer matches
  `template_style.json.thumbnails`'s count.
- **`reference_style.py <reference.pdf> --event <slug>`** — the *design
  reference* ingestion path: organizer-provided PDFs (e.g. Canva exports)
  are look-and-feel references, **not** production templates. Writes
  `out/design_reference.json` (a deliberately separate, self-identifying
  contract with `"authority": "advisory"` — never merge it into
  `out/template_style.json`): page geometry in EMU, per-page dominant
  palette + font names, thumbnails to `out/thumbnails/reference/<slug>/`,
  and harvested raster images to `assets/reference/<slug>/` each with a
  provenance sidecar. Per owner policy (2026-07-08), assets bundled with
  provided materials are presumed cleared for that event's decks and
  should be reused (see `docs/IMPROVEMENT_PLAN.md` §2 — the watermark
  lint still applies, and reuse outside the event needs its own check).
  Vector art (logos, icons, rules) is *not* harvested — only embedded
  rasters; check the thumbnails.
  Where a real `.pptx` template exists, its facts always win; reference
  facts only inform the Decisions layer. Like the template path, a
  human/LLM-written `out/reference_visual_catalog.json` (built by looking
  at the thumbnails) captures what the reference's designer actually did —
  layouts, motifs, color roles — and goes stale when its `n_pages_total`
  no longer matches the PDF.
- **`build_deck.py <spec.json> [--states] [--check-only] [--out PATH]`** —
  validates a spec (JSON Schema + cross-checks: duplicate ids, missing
  assets, off-slide boxes without `allow_offslide_bleed`, animation targets
  that don't exist) and builds it. `--states` also writes one static
  snapshot deck per animation step to `output/states/<spec-stem>/state{k}.pptx`
  (state k = every element whose earliest entrance step is <= k).
- **`render.py`** — `render(pptx_path, outdir) -> png_path`, headless
  LibreOffice render at 2560x1440. Imported by `verify_reference.py` and
  `lint_render.py`.
- **`lint_render.py <spec.json> [--out PATH]`** — deterministic critique of a
  spec with no reference screenshot to compare against (assumes
  `build_deck.py <spec> --states` already ran): font-family conformance
  against `assets.json.fonts[].family` (the naming-trap catcher), glyph
  coverage, a render-free text-fit estimate (box vs. estimated line width/
  height), bounding-box overlap, plus warn-only nudges (font-role/color
  alignment with the resolved theme, contrast, **watermark usage** —
  flags any `watermark_suspected` asset so unlicensed stock art can't ship
  silently, asset duplication, a render-based line-count confirmation).
  JSON report + 0/1 exit, same severity split as a designer would react to:
  fix `error`s, weigh `warn`s. This catches everything *mechanically*
  checkable; it cannot judge whether a slide actually looks good — that's
  the `pptx-designer` skill's mandatory visual-self-review step, not
  something this script attempts.
- **`native_packaging.py`** (imported by `build_deck.py`, not a CLI) —
  post-save package surgery driven by the spec's optional `packaging`
  object: swaps the built deck's theme part so PowerPoint's color/font
  pickers show the *event's* brand instead of stock Office, and strips
  every slide layout no slide references (plus rels and content-type
  overrides). Two theme sources, both frozen upstream as decisions:
  `{"kind": "template", "path": ..., "theme_index": N}` grafts the theme
  out of the organizer's real .pptx (pick the index from
  `template_style.json.themes[]` — templates can carry several); 
  `{"kind": "synthesized", "colors": {dk1..accent6}, "major_font",
  "minor_font", "name"}` is the fallback for reference-only events, where
  the designer maps the reference palette to slots explicitly. The builder
  also stamps docProps from `meta.doc_props` (title/author/subject +
  spec-hash provenance, real dates, correct slide count and 16:9 format)
  on every build — decks never ship python-pptx's stock boilerplate.
  Two more packaging levers: `embed_fonts` (per-family TTF slots →
  `ppt/fonts/*.fntdata` + `embeddedFontLst`, so the deck renders as
  designed on machines without the fonts; `lint_render`'s
  `check_embed_font_licenses` warns when no license file sits beside an
  embedded font) and `media_optimization` (opt-in: bakes cover-crops into
  pixels and downscales to `dpi_budget` before embedding — forensic F5;
  originals never touched, derivatives cached in `output/media_cache/`).
  `max_package_mb` sets a size budget that `lint_deck.py` checks against
  the built file.
- **`extract_media.py <template.pptx> <ppt/media/imageN.png> <out.png>
  [--recolor dark|light]`** — pulls one template-embedded media file (e.g. a
  `logo_candidates` entry, which is only known by its in-archive path) onto
  disk so a spec can reference it as an `asset`; `--recolor` flips its ink
  color (fills RGB, keeps alpha) for use against a different background.
- **`verify_reference.py`** — the title-slide regression fixture: renders
  `output/states/title_slide/state{1,2,3}.pptx` and compares each against
  `assets/expected_result/1st_slide{n}.jpg` (per-region RMSE + structural
  text-line check). Exit 0 = pass. This is fixture-specific by design (it
  knows this slide's regions); a second reference-checked slide would need
  its own check or a generalized version — not worth abstracting from one
  example.
- **`geometry_to_spec.py`** — one-off converter that freezes
  `output/work/geometry.json` + `content.json` (produced by the
  `pptx-title-slide` skill's screenshot measurement) into
  `specs/title_slide.spec.json`. This is how the title-slide spike's numbers
  entered the spec-driven pipeline; it is not how a new slide gets authored.
- **`imaging.py`** — shared pixel-analysis helpers (`line_bands`, `new_ink`,
  `dilate`, `bbox_of`, `alpha_bbox`) used by both `extract_assets.py`
  (pptx-title-slide skill) and `verify_reference.py`, so the two never drift.

- **`lint_deck.py <name.deck.json>`** — cross-slide lint against the deck
  spec's own `tokens` (the designer's frozen design system): font-family
  budget (error), `type_scale` conformance by element role (error),
  palette discipline (warn), content margins for textboxes/tables (warn),
  per-slide density budget (warn — restraint is countable; the reference
  slide this pipeline grew from had exactly 7 shapes), and same-role
  grid alignment across slides (warn). Because the tokens are the
  standard, this is also the correct conformance source in fallback mode,
  where `lint_render.py`'s template-theme warns don't apply.

## Deck specs

`specs/deck.schema.json` is the deck contract: ordered `slides` (paths to
member slide specs), shared `slide` geometry every member must match,
deck-level `packaging` + `meta.doc_props` (these supersede per-slide
ones), and `tokens` — palette roles, a role-keyed type scale, margins,
and budgets. `build_deck.py specs/<name>.deck.json` validates every
member and assembles them into one .pptx (`--states` is per-slide dev
tooling and doesn't apply at deck level). `specs/dental.deck.json` is the
worked example.

## Spec files

`specs/spec.schema.json` is the versioned contract. A slide spec has:

- `slide`: width/height in EMU.
- `background`: optional full-bleed image + box.
- `elements[]`: z-ordered `image`, `textbox`, `shape`, or `table` shapes
  (`chart` is still schema-reserved and rejected with a clear error rather
  than silently ignored). `table` elements carry `table.columns_emu`,
  row-major `table.rows` (row 0 = header when `header: true`), and a
  mandatory `table.style` (font/size/colors/fills/borders) — the builder
  kills PowerPoint's theme banding so the spec's explicit styling is the
  only styling. Each element has an `id`
  (referenced by animations), and an optional free-text `role` (e.g.
  `title`, `credentials`, `logo`) for future cross-slide consistency checks.
  `textbox` elements carry `paragraphs[]` of `lines[]` (runs joined by
  explicit `<a:br>`, never left to auto-wrap), each with font/size/color/
  tracking/bold, plus optional exact line spacing, space-before, and a dash
  bullet with hanging indent. `image` elements support `fit: "stretch"`
  (default, exact box, distorts aspect if needed) | `"contain"` (natural
  aspect ratio, letterboxed within the box, placed per `anchor`) | `"cover"`
  (fills the box exactly via center-crop, no distortion) — `contain`/`cover`
  actually read the image's real pixel size at build time, `stretch` doesn't
  need to. `shape` elements (`shape_type: "ellipse"|"rectangle"|
  "rounded_rectangle"`, solid or 2-stop-gradient `fill`, optional `line`
  outline) need no image asset at all — for decorative accents/panels in
  the template's own theme colors.
- `image_briefs[]`: structured wanted-but-missing images. Each brief carries a
box, expected `asset` path (conventionally `assets/generated/<name>.png`),
subject, style, aspect, negative constraints, and `medical_class`
(`decorative` | `conceptual` | `anatomical`). Fill = put an image at the
asset path and rebuild. Open unacknowledged briefs render as loud placeholder
panels and `lint_render.py` errors; `meta.acknowledged_briefs` records a
reviewable "ship without it" decision.

Use `asset_resolver.py` for the agent-operated fill workflow:

```bash
.venv/bin/python .claude/skills/pptx-deck/scripts/asset_resolver.py plan specs/<name>.spec.json
.venv/bin/python .claude/skills/pptx-deck/scripts/styleguide_profile.py assets/styleguide.rtf
.venv/bin/python .claude/skills/pptx-deck/scripts/asset_resolver.py import specs/<name>.spec.json \
  --brief-id <id> --source <selected-image> --source-type local|template|web|generated \
  --rationale "why this image fits" --verification "what was checked"
.venv/bin/python .claude/skills/pptx-deck/scripts/asset_resolver.py report specs/<name>.spec.json
```

Resolver order is local `assets/`, embedded template media, web search, then AI
generation. Web/generated fills without provenance sidecars (`asset.ext.json`)
lint as **error**. Verified medical/anatomical web/generated fills lint as
**warn** so the user sees the accuracy caveat, not as a hard block.

- `animations[]`: ordered steps, each `{step, targets, effect, duration_ms}`.
  Only `effect: "fade"` is implemented today (backlog: wipe/fly/appear —
  `build_deck.py` will reject other effects with a clear message rather than
  emit wrong XML).
- `meta`: free-text designer intent, ignored by the builder.

`specs/title_slide.spec.json` is the first (and so far only) spec, migrated
from the title-slide spike. It is the regression fixture for `build_deck.py`
itself: `build_deck.py specs/title_slide.spec.json --states` followed by
`verify_reference.py` must keep reproducing the numbers documented in
`.claude/skills/pptx-title-slide/SKILL.md`.

## How to run (title-slide fixture, end to end)

```bash
.venv/bin/python .claude/skills/pptx-title-slide/scripts/extract_assets.py
.venv/bin/python .claude/skills/pptx-deck/scripts/geometry_to_spec.py
.venv/bin/python .claude/skills/pptx-deck/scripts/build_deck.py specs/title_slide.spec.json --states
.venv/bin/python .claude/skills/pptx-deck/scripts/verify_reference.py
```

## How to run (inventory, for a new slide/deck)

```bash
.venv/bin/python .claude/skills/pptx-deck/scripts/inventory.py
# -> out/assets.json, out/template_style.json, out/thumbnails/
```

## How to run (lint a spec with no reference screenshot)

```bash
.venv/bin/python .claude/skills/pptx-deck/scripts/build_deck.py specs/<name>.spec.json --states
.venv/bin/python .claude/skills/pptx-deck/scripts/lint_render.py specs/<name>.spec.json
```

## Known gaps (by design, not yet in scope)

- Authoring a spec from `out/assets.json` + `out/template_style.json` + slide
  copy is the `pptx-designer` skill's job, not this skill's — it makes the
  judgment calls (image/font/layout choices), then calls `build_deck.py` +
  `lint_render.py` here to build and critique what it wrote.
- `table`/`chart` element types are schema-reserved, not implemented.
- Only entrance animations (`fade`) are implemented; the visible-set model
  in `build_deck.py` (`visible_ids_for_state`) will need extending once
  exit/emphasis effects exist, so it doesn't silently mis-render state
  snapshots.
