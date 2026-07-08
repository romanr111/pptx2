# Improvement Plan — Speaker-Ready Decks

**Implementation status (2026-07-08): M1, M2, M3 (charts excepted), M4,
M5-A, and M6 are implemented and verified — 39 tests green, dental proof
deck built end-to-end (`specs/dental.deck.json` → `output/dental.pptx`).
Remaining: M5-B (blocked on image-API provider choice), chart element
type, PowerPoint fidelity check on a machine that has it, HeliosCond
license verification. Deviation from plan: the "full SAMED deck" M3
acceptance was not buildable — `assets/slides_text.rtf` contains only the
title-slide copy, so the two-slide dental deck serves as the deck-level
proof until more client material arrives.**

*2026-07-08, rev. 2. Sources: the forensic reconstruction of the SIA MED
SUMMIT title-slide build (external analysis of this pipeline's ancestor
session), `assets/client_goal.rtf`, the current skill/scripts state, and
owner decisions recorded in §2/§3.*

*Rev. 2 corrections: (a) the PDFs on hand are **design references**, not
production templates — the production template source remains a real
`.pptx` deck when the organizer provides one; (b) the plan is reframed
around the business deliverable (a speaker-ready deck), not around builder
mechanics; (c) organizer-material reuse (logos, motifs, section styles) is
promoted to a first-class goal with a licensing guard.*

## 1. The product goal — what "done" means

The deliverable is not a technically valid `.pptx`. It is a
**speaker-ready deck**: a presentation the speaker can walk on stage with
the same day, looking as if a professional presentation designer / art
director produced it for that specific event. Everything below exists to
close one or more of these criteria:

| # | Speaker-ready criterion | Closed by |
|---|---|---|
| R1 | **Art-director quality**: confident hierarchy, deliberate whitespace, restraint, one consistent visual system from title to closing slide | M3 + designer skill's visual review |
| R2 | **Native to the event**: the organizer's theme, logo, recurring motifs and section styles are reused so the deck feels commissioned by the event, while staying customized to the speaker and topic | M1 + M2 + existing designer reuse rules |
| R3 | **Faithful to the speaker**: their copy, images, tables and data; medical accuracy preserved; every text edit logged for approval | existing `meta.text_edits` + M3 tables/charts |
| R4 | **Presents correctly anywhere**: fonts embedded, rendering verified, animations work, correct aspect ratio on the conference machine | M4 + existing states/render QA |
| R5 | **No silent gaps**: every wanted-but-missing visual is either generated and reviewed, or its absence is an explicit signed-off decision | M5 |
| R6 | **Professional file**: metadata names the speaker and event (no tool boilerplate), size sane for email/upload | M2 + M6 |

A milestone is only done when its acceptance criteria are phrased — and
checked — in these terms, not in "the script exits 0" terms.

## 2. Source-material model

Three kinds of input, with **different authority** (owner clarification,
2026-07-08):

1. **Production template — a real `.pptx` from the organizer.
   Authoritative.** Supplies package-level facts: theme XML, masters,
   layouts, placeholder geometry, embedded media. This is the core
   assumption of the pipeline and stays so; when a `.pptx` exists, the
   final deck is built *inside a minimal derivative of it* (M2). The SAMED
   template (`assets/Шаблон SIA MED SUMMIT 2026 new.pptx`) is the worked
   example.
2. **Design references — PDFs, images, example decks. Advisory.** The six
   Canva-style PDF exports at `/Users/roman/Downloads/templates/`
   (1440×810, 16:9) are this kind. They yield *visual direction only*:
   palette, typography hints, logos, recurring graphic elements, slide
   motifs, section styles, layout ideas. Reference facts feed the
   **Decisions layer**; they never redefine the production package, and
   production facts win wherever both exist.
3. **Speaker materials** — copy, clinical images, tables/data
   (`assets/slides_text.rtf`, `assets/images/`). Content source of truth;
   preserved, never invented.

**Fallback mode**: when an event supplies only a reference (no `.pptx`),
the pipeline synthesizes the production package (theme + layouts) *from*
reference facts — explicitly marked as synthesized in the spec/docProps,
and **rebased onto the real template if one arrives later** (re-run
template ingestion; the spec's decisions largely survive, the packaging
changes).

**Asset reuse from provided materials (owner ruling, 2026-07-08)**:
assets bundled with an organizer-provided template or reference are
*provided to be used* — photography, decorative art, and brand marks are
presumed cleared for that event's decks, and the pipeline should reuse
them by default (that reuse is precisely what makes a deck feel native;
an earlier, more conservative reading of this guard cost a real
deliverable its hero image). Residual gates: the watermark lint still
flags visibly-marked stock, and reusing a harvested asset *outside* the
event it was provided for needs its own license check.

## 3. Owner decisions on record

- **Image generation staged**: structured briefs first (provider-
  independent, works today); a pluggable generation-API adapter later,
  once a provider/key is chosen.
- **Medical imagery policy**: AI-generated anatomical/clinical images
  allowed, but each one lints as **error** until human sign-off is
  recorded in the spec; decorative/conceptual generation gets a warn-level
  reminder. The gate stays error-severity.
- **First milestone**: prove the pipeline serves a *second visual
  identity* (from the Downloads references) before deepening features.
- **Standing constraint** (memory `feedback_process_over_reference_matching`):
  everything must generalize; nothing tuned to the SAMED fixture or judged
  by matching its reference screenshots.

## 4. What the forensic reconstruction teaches

Each confirmed finding from the ancestor session, checked against the
current repo. These aren't abstract tech debt — each open one visibly
cheapens a client deliverable (the R-criterion it violates is noted):

| # | Forensic finding (section) | Status in pptx2 today | Violates | Action |
|---|---|---|---|---|
| F1 | Deck built from python-pptx's stock scaffold: stock "Office" theme, 11 unused stock layouts, docProps frozen at "Steve Canny"/2013/"4:3"/"0 slides" (§2, §4) | **Still true.** `build_deck.py` calls `Presentation()`; docProps never set. Every deliverable carries wrong, unprofessional metadata and stock baggage | R2, R6 | M2 |
| F2 | Brand colors/fonts hard-coded on runs; the deck's *actual* theme is the unused stock one (§5, §6) | **Still true.** A built deck's PowerPoint color/font pickers show Office defaults, not the event brand | R2 | M2 |
| F3 | No font embedding → silent fallback to a default sans on any machine without HeliosCond/Geologica (§4, §6) | **Still true.** No embedding code anywhere | R4 | M4 |
| F4 | `set_bullet(color_hex=...)` dead parameter — `buClr` never written; bullets render in an uncontrolled default color (§3, confirmed bug) | **Carried over.** `apply_bullet` writes `buFont`/`buChar` only; the schema has no bullet color field at all | R1 | M2 (quick win) |
| F5 | Crops metadata-only; full 2496×1664 pixels shipped for a cropped view; images never recompressed (§5) | **Still true.** `fit:"cover"` uses `crop_*` metadata; no media optimization pass | R6 | M6 |
| F6 | Naive template trimming saved 0.024%; from-scratch rebuild saved 90.2% (§5) | **Validated** — the pipeline rebuilds. But a pure rebuild discards the template's package identity; M2's minimal derivative gets both: small *and* native | R2, R6 | M2 |
| F7 | Rendering verified only in LibreOffice; real PowerPoint fidelity unknown (§2, §10) | **Still true**, and no PowerPoint is installed on this machine | R4 | M4 |
| F8 | No provenance — the forensic effort was needed at all because nothing recorded intent (§1, §8, §9) | **Mostly solved** by the spec-driven repo + `meta.designer_rationale`; the built .pptx itself still carries none | R6 | M2 |
| F9 | Relative-path fragility (§3) | **Solved** — scripts anchor on `PROJECT_ROOT` | — | — |
| F10 | What made the slide *good* (§6): exactly 7 top-level shapes, generous negative space, one accent per text tier — restraint is countable | Exists only as per-slide prose in `pptx-designer/SKILL.md`; nothing enforces it *across* a deck | R1 | M3 |

Meta-lesson from F4: a field can exist in the contract and silently do
nothing. M2 includes a schema↔builder coverage test so the dead-parameter
class of bug can't recur.

## 5. Milestones

### M1 — Design-reference ingestion + second-identity proof *(first, per owner — R2)*

**Business value**: an event that sends only a look-and-feel PDF still
gets a deck native to its identity, and the pipeline proves it serves
*any* event, not just SAMED.

1. **New reference-facts contract**, `out/design_reference.json` —
   deliberately separate from `out/template_style.json`, which stays
   `.pptx`-only production facts:
   - per-page thumbnails, dominant palette, font names, extracted images
     (logos, recurring graphics) into `assets/reference/<event>/` with
     provenance sidecars;
   - tooling: PyMuPDF (rasterizes pages, extracts images/fonts/colors in
     one dependency; AGPL is fine for internal tooling — alternative:
     `pypdf` + poppler). Note: macOS `sips` only rasterizes page 1 of a
     PDF, so it is not sufficient;
   - a reference **visual catalog** (built by eye, like the template one):
     motifs, section styles, layout ideas per page group.
2. **Designer-skill extension**: read reference facts for styling
   decisions; document the precedence rule (production `.pptx` facts win
   where both exist); apply the §2 licensing guard to any harvested
   raster asset.
3. **Generalization proof**: using
   `Brown and Beige Minimalist Dental Clinic Presentation.pdf` (client is
   a dentist — thematically closest; alternate: `Blue and Gray Modern
   Medical Presentation.pdf`) as the design reference in **fallback mode**
   (no `.pptx` exists for it), design a title slide + 1–2 content slides
   from real client copy through the normal build/lint/visual-review loop.
   No reference screenshots to match — by design.

**Acceptance**: zero SAMED-specific edits needed; `template_style.json`
contract untouched; harvested brand elements (logo, palette, at least one
motif) demonstrably present in the designed slides; every gap found
becomes a named backlog item, not an inline hack.

### M2 — Template-native packaging + professional package hygiene *(R2, R6; fixes F1, F2, F4, F6, F8)*

**Business value**: the deck opens as if the organizer's own designers
made it — their theme in PowerPoint's pickers, metadata naming the speaker
and the event, zero tool boilerplate.

1. **Minimal template derivative** instead of `Presentation()` when a
   `.pptx` template exists (the authoritative path): real theme, one
   master, only the layout(s) used; stock Office layouts gone.
2. **Fallback path** (reference-only events): synthesize `theme1.xml`
   from M1's reference facts, marked as synthesized.
3. **docProps**: speaker + talk title + event, correct slide count and
   format, provenance (generator, spec hash, build date).
4. **Bullet color** (quick win, can land during M1): `bullet.color` in
   schema + `<a:buClr>` in builder.
5. **Schema↔builder coverage test**: every schema field either observably
   honored or loudly rejected.
6. Optional: theme-slot color references in specs (`{"theme":"accent1"}`)
   so decks stay brand-editable in PowerPoint.

**Acceptance**: opening a built deck shows the event theme in the
color/font pickers; docProps present the speaker and event; no stock
layouts; file size in today's ballpark.

### M3 — Multi-slide decks + enforceable art-direction system *(R1, R3)*

**Business value**: this is the actual product — a complete talk,
consistent from title to closing slide, that a speaker can present the
same day. The review question changes from "is this file valid?" to
"would I present this?"

1. **Deck spec**: ordered slide specs + shared **style tokens** (type
   scale, palette roles, margin grid, spacing rhythm) that slides
   reference instead of repeating raw values.
2. **Builder**: assemble N slides into one .pptx (today: one per file).
3. **Cross-slide lint** — the measurable half of art direction:
   consistent title geometry, grid-alignment tolerance, type-scale
   conformance, ≤ 2 font families, palette-role discipline, per-slide
   density budget (F10: restraint is countable), and **motif/section-style
   consistency** — recurring organizer elements applied uniformly to
   section dividers and repeated slide types.
4. **Designer workflow extension**: an *outline stage* first (speaker
   materials → slide breakdown, each slide with a stated purpose), then
   per-slide specs, then a whole-deck visual review in addition to
   per-slide review.
5. **Tables + charts**: implement the schema-reserved types, styled from
   the theme — the client's materials explicitly include tables and data.

**Acceptance**: a complete SAMED deck built from `assets/slides_text.rtf`
as one .pptx; cross-slide lint clean; whole-deck visual review documented
against the R1 criteria.

### M4 — Font embedding + external fidelity check *(R4; fixes F3, mitigates F7)*

**Business value**: the deck looks as designed on the conference laptop,
not only on the build machine.

1. Embed fonts via OOXML `<p:embeddedFontLst>` + `fntdata` parts
   (python-pptx has no API — raw package post-process step).
2. **License gate**: Geologica is OFL (license file already in
   `assets/fonts/`); HeliosCond's license is unverified. Inventory records
   license evidence; lint warns on embedding unknown-license fonts.
3. **Fidelity**: no PowerPoint on this machine, so LibreOffice stays the
   only automated renderer (F7 stands). Mitigation: embedding removes the
   biggest substitution risk, plus a delivery-checklist step — verify once
   per template family in real PowerPoint (desktop or free PowerPoint web).

### M5 — AI image gap-filling *(R5, staged per owner decision)*

**Business value**: no slide ships with an awkward hole, a stolen stock
image, or an unvetted medical visual — the AI decides *where* an image
would help, and humans stay in control of *what* ships.

**Stage A — structured briefs (now, no new dependencies):**
- Replace free-text `meta.asset_gaps` with structured `image_briefs[]`:
  target element/box, subject, style constraints derived from the event's
  palette and mood, aspect ratio, negative constraints ("no text, no
  watermark"), `medical_class: decorative | conceptual | anatomical`,
  rationale. The *decision* that an image is nice-but-missing is the
  designer skill's existing "Hero/thematic imagery" judgment, now with
  machine-readable output.
- Builder renders a labeled placeholder panel for an unfilled brief; lint
  makes an open brief an **error** unless explicitly acknowledged.
- Filling a brief = drop the file at the path the brief names and rebuild.

**Stage B — generation adapter (once a provider/key is chosen):**
- `generate_image(brief) -> path` behind a small interface; outputs in
  `assets/generated/` with provenance sidecars (prompt, model, date, brief
  hash); inventory tags them `ai_generated: true`.

**Review policy (owner decision, enforced by lint):**
- `ai_generated` + `medical_class: anatomical` → **error** until sign-off
  recorded (`meta.image_reviews: [{asset, reviewed_by, date}]`).
- `decorative`/`conceptual` → warn-level review reminder.
- Existing watermark-usage checks stay, and extend to reference-harvested
  assets (§2 licensing guard).

### M6 — Media optimization *(R6; fixes F5)*

Build-time pass: bake `srcRect` crops into pixels, downscale to a
render-DPI budget, recompress photos (JPEG where alpha isn't needed) —
originals in `assets/` untouched. Deck-size budget check in lint.

## 6. Sequencing and effort

| Order | Milestone | Effort | Rationale |
|---|---|---|---|
| 1 | M1 Reference ingestion + second identity | M | Owner-selected; de-risks "every conference looks different" before anything is deepened |
| 2 | M2 Template-native packaging | M | Every deliverable benefits; fixes 4 forensic findings; F4 + docProps quick wins can land during M1 |
| 3 | M3 Multi-slide + art-direction system | L | The client's product is a deck, not a slide; biggest single piece |
| 4 | M5-A Image briefs | S | Cheap (schema + lint + skill guidance); unblocks the client's workflow immediately |
| 5 | M4 Font embedding + fidelity | M | Fiddly OOXML work; matters most at delivery time |
| 6 | M6 Media optimization | S | Polish; do once decks are real |
| — | M5-B Generation API | M | Blocked on provider/key decision |

## 7. Risks and open items

- **Reference-only events produce weaker packages** (no theme/layout XML
  to inherit) — fallback decks are synthesized and marked as such; rebase
  onto the real `.pptx` when the organizer supplies one.
- **Reference-harvest licensing**: Canva-export raster art is usually
  stock, not organizer property — direction (palette/type/motif) is safe
  to imitate, pixel reuse goes through the watermark/licensing lint and a
  recorded judgment call.
- **HeliosCond license** unknown → embedding gated until verified.
- **PowerPoint fidelity** not automatable locally; standing manual
  checklist step (per template family, not per deck).
- **Image-generation provider** unchosen → M5-B blocked; M5-A is
  deliberately provider-independent.
- **Medical accuracy** of generated anatomical imagery is accepted *with*
  the mandatory-review gate — the gate stays error-severity, never
  softened to a warn.
