---
name: pptx-designer
description: Author a new slide spec under specs/ from the facts layer (out/assets.json, out/template_style.json) and raw slide copy -- the "Decisions" layer of the pptx pipeline. Use when asked to design, draft, or author a slide spec from scratch, as opposed to building/rendering/verifying one that already exists.
---

# pptx-designer

This is the layer `pptx-deck/SKILL.md` calls "Decisions (a human, or a future
designer skill)". Everything here is judgment -- which image, which font
weight, where a box goes, how a long line gets split -- not arithmetic.
Arithmetic (schema validation, XML generation, rendering) belongs to
`pptx-deck`'s scripts and is *never* duplicated here; this skill's only job
is to produce a spec file, then call `pptx-deck`'s scripts to build, lint,
and iterate on it.

## Inputs

- `assets/styleguide.rtf` / `out/styleguide_profile.json` -- if the RTF
  exists, run `styleguide_profile.py` before authoring and read the resulting
  profile as the deck's taste contract. Record the profile name/path in
  `meta.styleguide_profile` and the concrete slide-specific application in
  `meta.styleguide_application`.

- `out/assets.json` -- image classifications, font facts (including the
  Geologica naming-trap flags), `font_roles` (heading/body family + which
  theme they came from), parsed slide-copy text blocks.
- `out/template_style.json` -- theme colors/fonts, per-layout placeholder
  geometry, `logo_candidates`, `inferred_margins_emu`, `consistency_flags`,
  `slide_layout_map` (which layout each real template slide uses),
  `slide_media_map` (which media files each real slide embeds),
  `media_reuse_ranked` (media sorted by how many distinct slides reuse it --
  a high count is a strong signal of a decorative/brand asset, not one-off
  content).
- `out/media_census.png` + `out/media_census/` -- **view the contact sheet
  FIRST; it is the complete template image library (every format, every file,
  including media referenced by no slide), not a ranked or logo-filtered
  subset.** `media_reuse_ranked` and `logo_candidates` are discovery *hints*,
  never filters -- the best hero image is often a one-off (`used 0x`/`used 1x`)
  premium render the ranking buries. Categorize every tile before designing
  (hero candidate / brand mark / decoration / unusable) -- see Loop A.
- `out/template_visual_catalog.json` -- **read this before making any
  color-mode, background, or decorative-asset decision.** It's a cached,
  human/LLM-written description of what the template's own real slides
  actually look like (grouped by distinct layout, plus notes on recurring
  visual assets), because `out/template_style.json` alone only tells you
  numeric facts, not what the template's own designer actually *did* with
  them. If it doesn't exist yet, its `template_fingerprint` doesn't match
  `out/template_style.json.template_fingerprint`, or its `n_slides_total`
  doesn't match the current `out/template_style.json.thumbnails` count, build
  it first and copy the current fingerprint into the catalog:
  1. Use `slide_layout_map` to find the distinct layouts actually in use
     (dedupe by `layouts_index`) -- you don't need to look at every slide,
     only one representative thumbnail per distinct layout.
  2. Use `media_reuse_ranked`'s top entries to find slides where a reused
     asset appears, and look at those thumbnails too.
  3. For each, look at the corresponding path in `template_style.json`'s
     `thumbnails` array (numbered by presentation order and cache-keyed by
     template plus renderer) and write a `layouts_observed` entry
     (color mode, what's on it, any reusable component you notice) and a
     `recurring_assets` entry for anything that shows up on more than one
     slide (note its source media file if `slide_media_map` resolves one --
     see the caveat below if it doesn't). Keep entries as free descriptive
     text, not a rigid vocabulary -- this file is written by judgment, not
     computed.
  This is a one-time cost per template, not per slide -- don't redo it for
  every new spec once it exists and isn't stale.
  Before authoring, confirm its reviewed starter registry is current. Reuse
  `approved_assets` before extracting more template media, and reuse the exact
  `approved_fonts.heading_family` / `body_family` strings within the permitted
  family budget before considering variants. Every approved asset must exist,
  match its SHA-256, and have its declared template provenance sidecar.
  `deck_qa.py --static-only` validates the registry and rejects unapproved or
  known-trap font strings used by the deck.
- `out/design_reference.json` + `out/reference_visual_catalog.json`
  (optional, present when the event supplied a *design reference* — a PDF
  look-and-feel export rather than a real template). **Precedence rule:**
  a real `.pptx` template's facts (`template_style.json`) are
  authoritative and win wherever both exist; reference facts are advisory
  direction — palette, typography hints, motifs, layout ideas. When *only*
  a reference exists (fallback mode), the reference catalog plays the role
  the template catalog normally does: consult it before any color-mode,
  background, or decorative decision, and synthesize layouts from its
  observed pages. **Asset reuse (owner policy, 2026-07-08): materials
  bundled with an organizer-provided template/reference are provided to
  be used — REUSE them.** Harvested photography, decorative art, and
  brand marks are presumed cleared for that event's decks; preferring the
  reference's own imagery over a plain substitute is exactly what makes
  the result feel native (skipping the reference's hero photo out of
  licensing caution measurably degraded a real deliverable once — don't
  repeat that). Two residual gates only: the watermark lint still flags
  visibly-marked stock, and reusing a harvested asset *outside* that
  event's decks needs its own license check. Vector art (logos, icons) is
  not auto-harvested — crop it from a high-zoom page render if needed.
- `specs/spec.schema.json` -- the contract the output spec must validate
  against.

If `out/assets.json`/`out/template_style.json` don't exist or look stale,
run `inventory.py` first (see `pptx-deck/SKILL.md`) -- don't guess at facts
this skill can compute. If the event supplied only a PDF reference, run
`reference_style.py` instead and work in fallback mode as described above.

## Forbidden reads

The point of this skill is to make real design judgment calls from facts +
copy, not to copy a known answer. For any slide where a hand-verified
reference might exist (as it does for the title slide in this project),
**do not read**:

- `output/**` in its entirety -- not just `output/work/geometry.json` /
  `content.json`, but also any built `.pptx` under `output/` (unzipping one
  reveals exact EMU boxes/fonts/sizes -- the full answer key), anything
  under `output/compare/`, and anything under `output/work/` (e.g.
  screenshot-lifted art like `logo_black.png`/`background_title.png` --
  using either is cheating by construction).
- Any existing hand-verified spec for the same slide (e.g.
  `specs/title_slide.spec.json`) or anything under `assets/expected_result/`.
- `.claude/skills/pptx-deck/scripts/geometry_to_spec.py` -- its module-level
  constants (`TITLE_FONT`, `TITLE_TRACKING_PT`, `CAP_RATIO`, etc.) are the
  answer key in code form.
- `.claude/skills/pptx-title-slide/**` -- its SKILL.md's "Tuning knobs"
  section states the exact font/tracking choices for the same fixture.

If you're not sure whether a file is off-limits, treat "does this reveal a
specific pre-computed answer for the slide I'm about to design" as the test,
not "is it literally on this list."

## Output

A new `specs/<name>.spec.json`. **Never overwrite an existing hand-verified
spec.** Use `meta.designer_rationale` (one prose string covering image,
layout, font, and bullet-structure reasoning) and `meta.text_edits` (below)
so every judgment call is visible to whoever reviews the render, not hidden
inside the JSON.

## Judgment calls

These are written against this project's actual facts as a worked example;
apply the same kind of reasoning to different facts on a different template.

**Art direction (do this before the per-slide calls below).** These are the
levers that separate an "ultra-premium editorial" deck from a "clean corporate
template" one -- the difference a styleguide like "Apple Keynote / Nature
Medicine" is actually asking for:

- **Deck rhythm / treatment variety.** Vary dark/light across the deck (e.g.
  dark bookends: cover + closing, light middle). Do NOT stamp one canvas motif
  (a black top band, one accent) on every slide -- that reads as a template,
  not art direction. Consult the template's *full* layout variety (both its
  dark title treatment AND its clean imagery-led content slides), not a single
  motif you locked onto first.
- **Hero imagery per slide (default).** Every content slide carries ONE
  *distinct* premium visual at the styleguide's `visual_ratio_target` (bake it
  seamless to that slide's background with `seamless_hero.py`). Prefer a
  different template render per slide -- reusing the same small accent on every
  slide is monotone and fails the visual-weight gate. A different white-studio
  render, a dark moody bleed, a scattered-element constellation: use the range
  the census reveals.
- **Brand-mark selection.** The census usually holds several mark variants
  (a wide wordmark AND a compact stacked lockup). Pick the *refined* one that
  fits the corner, sized as a mark not a banner, and keep it identical across
  the deck (Loop D).
- **Portrait / hero-element scale.** On a cover, the portrait is a hero
  element -- large, full-height, seamlessly dissolved into the background --
  not a small cutout tucked in a corner.
- **Accent on the right background.** Use the brand/styleguide accent (incl.
  gold) only where it *reads*: bright/gold accents belong on dark backgrounds,
  not on white (gold-on-white fails contrast). If the styleguide calls for a
  gold accent, that is a reason to give the deck dark surfaces where it can land.

**Consult the template's own worked examples before picking a color mode.**
Don't default to a light/plain treatment just because it's safe -- check
`out/template_visual_catalog.json` for the layout closest to your slide's
purpose first. The template's own designer may have used a completely
different treatment (e.g. a dark background with a large decorative photo)
than any specific prior client deck you're aware of, and that's an equally
legitimate reference point, not a deviation to avoid. Concretely, on this
project's template, the *actual* native title-slide example is dark with a
large photographic decorative asset -- a fact invisible to `template_style.json`'s
numeric fields alone (theme colors are just a 12-slot palette; nothing in
the deterministic facts says which slots the template's own designer
actually combined for a *title slide specifically*).

**Reuse cross-slide components you spot in the catalog.** If the catalog
notes a component that recurs across multiple of the template's own slides
(e.g. a consistently-positioned name+credentials card), matching that
arrangement is itself a template-conformance signal -- prefer it over
inventing a new arrangement that's merely "reasonable in isolation."

**Prefer a real recurring template asset over an improvised substitute.**
If `template_visual_catalog.json`'s `recurring_assets` (or a high entry in
`media_reuse_ranked`) names something that fits your slide, extract and use
the real thing via `extract_media.py` rather than approximating it with a
generic `shape` element -- e.g. a real decorative photo beats a flat
gradient standing in for it. Reach for `shape` accents (see below) when
nothing appropriate actually exists in the template's own media, not as a
first choice when it does.

**Don't trust an empty-looking thumbnail, or a "not found" from `slide_media_map`, at face value.**
Thumbnails are rendered from a static export and can show a slide's
*pre-animation* state -- a sparse thumbnail may just mean its content
animates in, not that the layout is genuinely bare. Separately,
`slide_media_map`/`media_reuse_ranked` are regex/rels-based and can miss a
visually obvious asset that's referenced through an indirect or inherited
mechanism (confirmed on this project: a decorative photo clearly visible on
two slides only resolved to a media filename via a *third* slide that
happened to reference it directly). If the catalog's notes describe
something a mapping doesn't corroborate, trust what's actually visible in
the thumbnail and look for the asset via *any* slide that uses it, not just
the one you started from.

**Background + portrait trap.** Check whether your chosen `background_art`
asset already contains a person/photo baked into it before also placing a
separate portrait cutout on top -- doing both produces a double-subject.
Using the composite alone (dropping the separate cutout) can also break an
animation idea that assumes the person isn't visible until their own step.
Make an explicit call (e.g. crop the composite to a non-subject panel and
use the cutout as the only portrait, or use the composite as-is and skip a
separate portrait-entrance step) and record which, and why, in
`meta.designer_rationale`. Don't combine both without noticing the
collision.

**Near-identical portraits.** Two files can be indistinguishable across
every field `assets.json` measures (size, alpha, dominant colors) without
being byte-identical -- don't treat `assets.json`'s equality as proof the
files are the same, and don't use two such files as if they were distinct
images. Pick one by filename semantics (the more literal/specific name for
the actual subject) and say which you picked and why.

**Logo selection from `template_style.json.logo_candidates`.** These are
noisy: a `dark_ink`/`light_ink` classification and an `opaque_frac` number
are not enough to identify which candidate is actually a usable brand
wordmark versus, say, a generic app icon or an unrelated graphic that
happened to pass the extraction heuristics. **Visually inspect** every
candidate before choosing -- extract each with `extract_media.py` (below)
and look at the resulting PNGs, or check the template-thumbnail paths listed
in `out/template_style.json`. Don't pick by `variant`/`opaque_frac` alone.
Also check the ink color actually works on the background you're placing it
against -- a `light_ink` (white) logo is invisible on a light slide;
`extract_media.py --recolor dark|light` can flip it if the shape you want is
otherwise the right one.

**Duplicate/near-duplicate content illustrations.** If several assets are
near-identical `content_illustration`s, prefer one, not all -- using
near-duplicates as if they were different images just multiplies the same
content pointlessly. Which single one (if any) belongs on *this* slide is
a hero/thematic-imagery decision -- see below, don't reflexively exclude
them either.

**Hero/thematic imagery.** A title slide with only a portrait, a logo, and
text is mechanically fine but visually generic -- a well-designed conference
title slide usually signals what the talk is about with at least one
supporting visual, not just a headshot. Actively look for an asset (a
`content_illustration`, part of a `background_art` composite, anything
thematically related to the copy) that could serve that role before
deciding to leave a large region of the canvas empty. Two real constraints
to weigh honestly, not silently work around:
- If the only available candidate is `watermark_suspected: true` (stock art,
  not owned/licensed), don't make it a dominant, clearly-legible centerpiece
  -- that ships someone else's copyright mark in a client-facing deck. Using
  it small/subtle/cropped where the mark isn't legible is a judgment call
  you can make and defend in `meta.designer_rationale`; using it large and
  legible is not. `lint_render.py`'s `check_watermark_usage` will flag any
  use either way -- that's a prompt to double check your call, not
  necessarily to remove it.
- If no candidate actually fits (wrong topic, wrong aspect, all watermarked
  and none croppable tastefully), don't force one in. Instead write a
  structured **image brief** (`image_briefs[]`, see `pptx-deck/SKILL.md`
  and the schema): the box where the image belongs, the expected asset
  path, subject/style constraints locked to the event's palette and mood,
  aspect, negative constraints, and an honest `medical_class` —
  anatomical content will be blocked by lint until a human medical
  sign-off is recorded, and that is the intended behavior, not friction.
  (When `out/styleguide_profile.json` exists, image briefs inherit
  `image_brief_defaults.style` and `image_brief_defaults.negative` unless
  the slide context needs a more specific visual constraint.)
  If the slide should ship without the image for now, add the brief id to
  `meta.acknowledged_briefs` (the composition must then hold up without
  it — judge that by eye, don't leave a visual hole). Keep
  `meta.asset_gaps` for non-image gaps (e.g. a missing organizer logo).
  A plain-but-honest slide beats a cluttered or copyright-risky one, but
  "we don't have the right asset" should be executable, not just visible.


**Asset resolver workflow.** When a spec contains open `image_briefs[]`, run
`asset_resolver.py plan` before accepting the slide as visually complete. The
agent must try sources in this order: local `assets/`, embedded template media,
web image search, then AI generation. For web search, create queries from the
slide message + brief subject/style, collect several candidates, visually reject
watermarked/logo-heavy/low-fit results, double-check the short list against the
brief, then import the best match with resolver provenance. For AI generation,
use the brief's subject/style/aspect/negative constraints only when search is
unsuitable or too generic. Web/generated medical or anatomical fills must include
verification notes in the sidecar; they are allowed with lint warnings and must
be called out to the user before final delivery.

**Delivery: deck_qa.py is the only path.** Never ship a deck without
running `deck_qa.py` - it statically validates every slide first, builds and
renders the assembled deck once, analyzes the actual assembled pages, prepares
QA crops, runs cross-slide/package checks, and consolidates everything into one
`qa_report.json` with exit 1 on any error. The manual sequence of
build + lint steps left gaps in the past (slides never linted,
lint_render run on the wrong file type, errors shipped to delivery).
`deck_qa.py` makes that impossible.

**Image placement: natural proportions, not stretch.** `build_deck.py`
defaults every image to `fit: "stretch"` (fills the exact box, distorting
aspect ratio if the box doesn't match). That's rarely what a real designed
slide does with a portrait or hero image. Prefer `fit: "contain"` with an
explicit `anchor` (e.g. a standing portrait anchored `"bottom"` in a tall
box, so there's natural headroom above the subject instead of their face
jammed into the top edge) so the image keeps its real proportions. Use
`fit: "cover"` (crops to fill without distortion) when you deliberately want
an image to fill a box edge-to-edge, e.g. a background panel. Reach for
`stretch` only when the box was chosen specifically to match the image's own
aspect ratio, not as a default.

**Seamless image integration (MANDATORY for every decorative 3D/photographic
element).** The viewer must *never* see an inserted image's rectangular
boundary, crop box, background edge, or bounding box. Every decorative visual
must look native to the slide -- as though it continues beyond the canvas or
dissolves into the background. A pasted-on rectangle, a hard image border, an
abrupt clip, or a background tone that mismatches the slide (a light-gray
"studio" panel on a white slide, a not-quite-black block on a dark slide)
instantly reads as amateur. This is not lint-checkable -- it is a hard visual-
review gate. Rules:

1. **A "transparent" PNG is NOT automatically seamless -- verify, never assume
   "dissolves for free".** A real alpha channel often does dissolve, but
   template renders frequently carry an **opaque corner-glow/vignette** (baked
   into RGB at high alpha -- inside the box, not "outside the subject") or a
   **semi-transparent AO/shadow haze** over the whole frame; either draws the
   image's rectangular bounding box on a uniform slide. Sampling corners is
   necessary but not sufficient -- confirm each corner is genuinely transparent
   (low alpha AND no coloured glow). When any doubt remains, bake the inner
   edges anyway: `seamless_hero.py --bg none --feather <inner edges>` keeps the
   subject's own alpha and just dissolves the box edges (`--bg black`/`--bg
   white` on an already-alpha source drops the alpha and grunges the subject,
   so use `--bg none` for clean-alpha PNGs). Then overscan the outer edges
   off-slide (below).
2. **A solid-background source (white/gray/black JPG) is never placed as a
   panel as-is.** Its internal edge *will* show. Bake a seamless derivative
   with `pptx-deck`'s `seamless_hero.py`: (a) **match the
   background to the slide** -- whiten a light-desaturated studio background
   to true white on a white slide, or fade to true black on a dark slide,
   using a luminance+saturation mask that whitens/darkens only the background
   and *protects the subject* (colorful spheres, metallic rods, skin); (b)
   **feather every internal edge** with a *directional* alpha ramp (a smooth-
   step gradient over ~12-18% of the width/height, 0->opaque), not a hard
   crop and not uniform whole-image opacity (uniform opacity just washes the
   subject out -- rule 9 of the brief); (c) place the baked PNG with
   `fit: "stretch"` so your feather is preserved exactly (cover/contain would
   re-crop it away).
3. **Overscan the outer edges off-slide** by a few percent: a large object
   should bleed past the slide boundary (`allow_offslide_bleed`), never
   terminate at an arbitrary point *inside* the slide. Only the *internal*
   edge(s) get the feather; the bled edges are clipped by the slide itself
   (which is fine -- an object cropped by the outer boundary is invisible as
   a boundary; an object's own image edge inside the canvas is not).
4. **Preserve the main subject at full clarity** -- fade only near the
   integration edges. Crop the source so shadows/dark corners/foreign objects
   fall in the feathered or bled zone, not in the visible center.
5. **Confirm seamlessness deterministically -- a clean LibreOffice/Docker
   render is NOT proof.** The renderer *masks* an inserted image's bounding-box
   edge, so it can appear only in PowerPoint/Keynote (shipped once: a raw
   transparent helix looked perfect in the LO render but drew a visible box in
   the owner's PowerPoint). Don't trust the assembled render alone -- for every
   `fit:"stretch"` decorative image, sample the baked asset's inner-edge
   rows/columns and confirm they equal the slide surface colour, and set the
   slide surface to the *exact* bake colour (pure `#000000` to match `--bg
   black`, `#FFFFFF` to match `--bg white`) so no tonal rectangle can remain.
   Iterate the threshold and feather width until the transition is invisible.

**Decorative accent shapes.** When a composition has a large plain region
that isn't carrying content (see "Hero/thematic imagery"), and no
appropriate photo/illustration exists to fill it, consider a `type: "shape"`
element (ellipse/rectangle, solid or 2-stop gradient fill) in the theme's
own accent colors (`template_style.json.themes[].colors.accent1/2/3...`) as
a small finishing touch -- a cluster of a few small circles, or a subtle
gradient panel. This is cheap, always available (no missing-asset risk),
and ties the slide to the template's actual palette. Keep it subtle and in
a genuinely empty corner/edge -- a handful of small accents reads as
"branded," the same shapes scattered everywhere or fighting the main content
reads as clutter.

**Layout synthesis.** If the template layout matching your slide type has
few or no usable placeholders, there's nothing to inherit -- you must
synthesize absolute EMU boxes yourself. `inferred_margins_emu` (a median
over the *other* layouts' placeholders) is a starting reference grid, not a
guarantee that it fits your specific composition. Use it plus ordinary
graphic-design judgment (balance, hierarchy, breathing room), and say so in
`meta.designer_rationale`.

**Font selection.** `font_roles` (in `out/assets.json`) names a heading and
body family, but that's a family, not a specific weight or the exact string
a renderer needs. Two things to get right:
1. Pick a specific weight deliberately (e.g. for a large title, a bold-ish
   weight; for body/credential text, a lighter one) and say why.
2. Cross-check the exact string you write into the spec is an **exact** key
   in `assets.json.fonts[].family` -- not just "starts with the right
   name." A font's file can declare a family for XML purposes (its *legacy*
   name, table id 1) that differs from what you'd guess from the family
   name alone, especially when a font ships in several stylistic variants
   (e.g. a plain build, a cursive/alternate build, an auto-axis build) that
   all superficially match the same theme font name -- only one variant
   group is normally the sane default a human would reach for from a font
   menu; the others are for deliberate stylistic use, not a default title
   font. Check `assets.json.font_naming_trap_flags` for any file you're
   considering.
3. Treat `font_roles.heading`/`.body` as a **starting hypothesis to verify by
   eye, not a rule to follow blindly** -- especially on a template whose
   `template_style.json.consistency_flags` already show it doesn't reliably
   follow its own declared theme in practice (this project's template mixes
   3 themes' fonts on its own slides). The theme's declared major font is
   sometimes simply not what looks best as a large headline face, even when
   it's technically "correct." After rendering (see the visual self-review
   step below), if the declared heading font looks thin/awkward/generic at
   title size, it's legitimate to pick a bolder weight from the *body* font
   family instead (still cross-checked against `fonts[].family`) -- record
   why in `meta.designer_rationale`. `check_font_role_alignment`'s warn on
   this is advisory precisely so this deviation stays available.

**Bullet formatting.** Slide-copy text blocks that read as bullets in a
plain-text sense (e.g. dash-prefixed lines) won't necessarily be flagged as
such by any heuristic field in `assets.json` -- that field is unreliable and
under-detects single-line bullets. Trust the actual segmented text blocks
over any boolean flag: each distinct source block that's meant to read as
one bullet point becomes one spec `paragraph` with a `bullet` set; a
block's own wrapped continuation lines become additional entries in that
same paragraph's `lines[]` array, not separate paragraphs (turning them into
separate paragraphs multiplies the bullet mark, which is wrong). Strip the
source's own leading bullet marker and any manual indent from the actual
run text -- the mark and hang come from the spec's `bullet.char` /
`bullet.hang_emu`, not literal characters.

**Text-edit changelog.** Slide text is pre-written and must be preserved,
but you may shorten or split a line to make it fit. Any deviation from the
verbatim source text -- even whitespace -- gets an entry in
`meta.text_edits: [{element_id, original, final, reason}]`, so a human can
diff what changed and approve or reject it. If nothing was edited, omit the
key.

**Line-break discipline: wrap="none" means YOU own every break.** The
builder sets `wrap="none"` on every run (text is joined by explicit
`<a:br>`, never auto-wrapped). This means a line wider than its box in
PowerPoint will overflow in one unbroken line past the box boundary --
LibreOffice masks this by silently auto-wrapping, so an LO render is NOT
proof of correct line breaks. A `lint_render` `text_fit` error (estimated
line width exceeds box.cx) is a **blocker without exceptions**: split the
long text into shorter `lines[]` entries, widen the box, or reduce the
font size until every line fits. Never ship a spec with a `text_fit`
error, and never rely on an LO render screenshot to dismiss one.

**Packaging: the deck must carry the event's theme, not stock Office.**
Every spec should set `packaging.theme_source` (see
`pptx-deck/SKILL.md` and the schema): with a real template, `kind:
"template"` + the correct `theme_index` chosen from
`template_style.json.themes[]` (check the theme *name* and colors — the
first theme is often not the brand one); in fallback mode, `kind:
"synthesized"` with your explicit palette-to-slot mapping (dk1 = darkest
text-bearing tone, lt1 = the paper/background tone, accents = brand
colors by prominence) and the heading/body families as
major_font/minor_font. Also set `meta.doc_props` (title/author/subject)
on every client-facing spec — that's what the file's Properties dialog
shows. Both are Decisions-layer choices; record the mapping rationale.

**Animation.** Only `effect: "fade"` is implemented by `build_deck.py`
today -- use that or nothing. Omit `trigger`/`duration_ms` on animation
steps rather than setting values the builder silently ignores; setting them
would imply a fidelity that doesn't exist.

## Designing a whole deck (outline stage first)

For a multi-slide deck, do NOT jump straight to per-slide specs. Work in
three passes:

1. **Outline** — read all the speaker's materials, then write the slide
   breakdown as part of the deck spec's `meta` (e.g.
   `meta.outline: [{n, purpose, source_blocks, layout_reference}]`): one
   entry per slide with its *purpose* (what this slide must accomplish),
   which source text/images/tables it consumes, and which template/
   reference layout it will adapt. Every source block should be consumed
   or explicitly skipped — unplaced client material is a silent content
   loss, list it in `meta.unplaced_material` if anything is left over.
2. **Tokens** — freeze the deck's design system in `tokens` *before*
   authoring slides: palette roles, a role-keyed type scale, margins,
   budgets. Slides then reference roles that must conform; changing your
   mind mid-deck means updating the token, not slide N in isolation.
3. **Per-slide specs** — author each slide as usual (everything above),
   then `build_deck.py specs/<name>.deck.json` + `lint_deck.py` for the
   cross-slide pass, and review the *whole deck's* renders as a set: do
   consecutive slides read as one system (same grid, same rhythm), do
   section-type slides reuse the same motif treatment, does density stay
   inside the budget?

`lint_deck.py` checks the deck against your own tokens — in fallback
mode (design-reference events) that makes it the primary conformance
check, since `lint_render.py`'s theme warns compare against a template
you're deliberately not using.

## The build/lint/react loop

If `out/styleguide_profile.json` exists, `styleguide_*` findings are visual QA
feedback. The two aesthetic **gates** -- `styleguide_visual_weight` (slide is
not visual-led) and `styleguide_text_budget` (too many lines) -- are NOT
free to dismiss with prose: either fix the slide, or record an explicit
`meta.styleguide_waiver: [{"check": "styleguide_visual_weight", "reason": "..."}]`.
`deck_qa --delivery` **blocks** on any unwaived gate finding and surfaces every
waiver to the user under `delivery.styleguide` -- so "we deliberately shipped
this text-led" is an explicit, reviewable decision, never a buried rationale.
The default is the opposite of text-led: **every content slide carries a
substantial premium hero visual at the styleguide's `visual_ratio_target`.**
Baking a white/black seamless hero from a template render (`seamless_hero.py`)
is the FIRST move, not a fallback; a small repeated accent shape is not a
substitute for a hero.

```
deck_qa.py specs/<name>.deck.json --static-only --output-root output/<run-name>
deck_qa.py specs/<name>.deck.json --renderer docker --output-root output/<run-name>
```

Run static-only after the first complete spec pass and correct every blocker
before the first render. Run full QA once, inspect the pages and generated
crops, and rerun only when rendered content changes. After visual-review
metadata is recorded, use `--delivery`; unchanged content reuses the validated
render cache.

Capped at **3 iterations**. Reaction policy, to avoid ping-ponging on
findings that don't actually indicate a problem:

- `error`-severity findings **must be fixed** before the next iteration.
- `warn`-severity findings are **advisory** -- react only if you agree with
  the warning; otherwise leave your choice as-is and record the
  disagreement in `meta.designer_rationale`. A warn existing is not itself
  a reason to change something.
- **Convergence = zero errors** (warns may remain).

Concretely: `check_font_role_alignment` will warn whenever your chosen
weight doesn't start with the theme's declared family for that role. This
is expected to fire sometimes -- a theme's declared heading font is an
*aspirational* target (see `pptx-deck/SKILL.md`'s framing of template
conformance), not a hard requirement, especially on a template whose own
`consistency_flags` show it doesn't consistently follow its own theme
either. Don't treat every such warn as something to fix; use judgment, and
write down your reasoning either way.

## Mandatory self-verification -- SEVERAL loops across the whole process

Zero lint errors only proves the spec is *mechanically* sound -- text fits,
nothing overlaps, fonts resolve. It says nothing about whether the slide
looks like a finished conference deck. **Passing lint is a prerequisite for
review, not the finish line.**

The failure mode this guards against is real and has shipped: a single
end-of-process review, judged from a downscaled contact sheet, misses small
collisions and seams (a logo laid over spheres, a charcoal render's
rectangle on a black slide, inconsistent logo sizes) -- and self-confirmation
bias ("I already decided it's fine") lets them through. The fix is **not more
deterministic code** (visual questions are the agent's judgment; determinism
is reserved for objectively measurable facts -- see `pptx-deck/SKILL.md`).
The fix is **discipline: verify at several checkpoints, from full-resolution
evidence, against an explicit rubric, and end with an independent pass.**

Run these **five self-verification loops**, each *iterate-to-clean* (same
policy as the build/lint/react loop: fix what's wrong, re-render, re-look;
cap 3 cycles per slide before you stop and reassess the design):

- **Loop A -- Assets understood** (after `inventory.py` + the visual
  catalog). **This is a hard gate: Loop A is not complete until EVERY tile in
  `out/media_census.png` has been viewed at full size and categorized** (hero
  candidate / brand mark / decoration / unusable). Do not let
  `media_reuse_ranked` or `logo_candidates` decide what you look at -- a
  premium hero is often a `used 0x`/`used 1x` render the ranking buries (this
  is exactly how a deck once shipped with a tiny repeated accent while the
  template's own white-studio medical renders sat unused). For every image you
  plan to place, name its **background type**: clean transparent alpha / dark
  *charcoal* render / white *studio* photo. This is where the wrong mental
  model gets caught: "black-on-black is seamless" is FALSE -- most 3D renders
  sit on charcoal (~RGB 32,30,33), not pure black, and show a rectangle on a
  black slide. Mark which assets need `seamless_hero.py`, and with which
  `--bg` (`black` for dark renders, `white` for studio photos, `none` to
  just feather an already-transparent PNG's cut edges).
- **Loop B -- Plan sanity** (after `meta.outline` + `tokens`, before
  building slides). Re-read the brief against the outline: every source block
  placed or explicitly skipped (`meta.unplaced_material`); `tokens` cover
  every colour and font you will actually use; one idea per slide. A cheap
  "does the plan hold together" pass before you spend build effort.
- **Loop C -- Per-slide critique** (after the first assembled-deck render). Look at the
  slide's **full-resolution** render and walk the rubric below element by
  element. Record the verdict in `meta.visual_review` (below).
- **Loop D -- Deck consistency** (after the deck assembles). Look at the
  whole deck as a set: one grid and rhythm; the logo is the **same artwork,
  same size, same corner** on every slide; dark/light treatment is
  consistent; the decorative motif is consistent. This is the pass that
  catches "slide 1's logo is a big wordmark, slide 3's is a small stacked
  mark".
- **Loop E -- Independent fresh-eyes / adversarial pass** (final). Re-examine
  deliberately hostile: "what would a picky client circle?" **Zoom every
  corner** (is the mark on clean background?), **every internal image edge**
  (any visible seam?), **every label that sits over imagery** (still
  legible?). This is the loop that defeats self-confirmation -- treat the
  deck as broken until each crop proves otherwise.

### Evidence rule (this is what actually prevents the misses)

Review only at **full resolution with targeted crops** -- never from one
downscaled contact sheet, which is exactly how the collisions slipped
through. `deck_qa.py` writes full-size per-slide PNGs to
`<output-root>/rendered/<stem>_qa/*.png` and automatically writes logo-corner
and internal image-edge crops plus `qa_crops/manifest.json`. Inspect every
full-size page and every generated crop. Also inspect a composite of any baked
asset on the slide's actual background colour. Crop automation prepares the
evidence only; it does not replace deck-consistency review or the final
adversarial pass, and a montage alone is never sufficient.

### Rubric for Loops C and E (the explicit checklist -- walk it every time)

- **Composition/hierarchy** -- does the eye land on the title first, then
  speaker, then credentials? Is visual weight balanced across the canvas, or
  is one side dense and another dead?
- **Whitespace vs. emptiness** -- deliberate breathing room reads as
  "designed"; a large blank region with nothing happening in it reads as
  "unfinished." If roughly a third or more of the canvas is empty for no
  reason, that's a signal to add something (thematic imagery, an accent
  shape -- see the judgment calls above) or resize the composition.
- **Does it say anything about the topic?** -- logo + portrait + text alone
  is functional but generic. Did you actually consider available thematic
  imagery before leaving the slide plain (see "Hero/thematic imagery")?
- **Typography feel** -- does the title read as a confident headline, or as
  body text that's merely bigger? This is a judgment call a lint check
  cannot make; only looking at the render can.
- **Brand presence** -- does the theme's palette show up anywhere besides
  the logo?
- **Hero visual present** -- does this slide carry a substantial premium
  visual at the styleguide's `visual_ratio_target`, or is it text with a token
  accent? A slide that trips `styleguide_visual_weight` and isn't a deliberate,
  waived full-bleed statement is not done (see the build/lint/react gates).
- **Treatment variety** -- across the deck, is this one motif repeated on
  every slide, or is there dark/light rhythm and a distinct hero per slide?
- **Signature accent used and legible** -- does the styleguide's accent (incl.
  gold) actually appear, on a background where it reads (not gold-on-white)?
- **Mark is the refined lockup, mark-sized** -- not a banner-scale wordmark,
  identical on every slide.
- **Seamless images** -- is any inserted image's rectangular boundary, crop
  box, or background edge visible? Does a photo/render's background tone
  mismatch the slide (a gray panel on white, a not-quite-black block on
  dark)? Every decorative visual must dissolve into or bleed past the canvas
  -- if you can see where the image starts, it fails (see "Seamless image
  integration").
- **Readability & collisions** -- read every label at full size, not
  thumbnail. Text set inside a shape (a circle, a pill, a card) has to fit
  and stay legible -- tiny type crammed into a mechanism circle or a
  diagnostic card fails even when it "fits" geometrically. Labels must not
  collide with or get lost against imagery (a pathway step over a molecular
  render, a caption over a busy photo). These are the failure modes that a
  clean lint pass misses and only a full-size render exposes -- confirm them
  in the exported PNG, never in the spec alone.
- **Logo / corner-mark clearance (check every one, every slide).** A brand
  mark must sit on CLEAN, uniform background -- a black gap in a dark render,
  an empty white margin -- never on top of hero artwork (glossy spheres, a
  photo, a busy render). A logo laid over imagery is almost always a
  *preventable* mistake, not an intentional overlap: when the mark and a
  decorative element both want the same corner, MOVE ONE -- reposition the
  decorative element to another clear area (it usually can go elsewhere), or,
  if the hero must stay full-bleed, re-bake it so it dissolves to the slide
  colour under the mark (`seamless_hero.py` with the mark's edge feathered).
  `lint_render.py`'s `check_logo_clearance` samples what sits behind each
  `role`-logo image and warns when it's busy (high luminance spread) vs. a
  clean panel (low spread) -- treat that warn as a must-fix unless you have
  confirmed by eye that the mark reads cleanly on a uniform area (a white
  wordmark on a pure-black gap is fine; the same mark on lit spheres is not).
  Keep every corner mark the SAME artwork and the SAME size across the deck;
  mixing a horizontal wordmark on one slide and a stacked lockup on the next,
  or different sizes, reads as unfinished.

Record the outcome as a **structured `meta.visual_review` artifact** on each
slide spec, not as prose you'll forget -- `lint_render.py`'s
`check_visual_review` requires it before delivery:

```json
"visual_review": {
  "iteration": 1,
  "verdict": "pass",              // or "pass_with_notes" | "fail"
  "findings": [
    {"element_id": "step_3_label", "issue": "collides with molecule_29"}
  ]
}
```

Anchor every finding to the `element_id` it concerns so the next iteration
knows exactly what to move. A `fail` verdict is a lint error (unresolved
issue); so is an `iteration` above 3 -- that limit is enforced in code, and
hitting it means stop and reassess the slide's design rather than nudging it
a fourth time.

If it doesn't hold up, **keep iterating** -- adjust geometry, fonts, or add
accents, then rebuild and re-render -- exactly like reacting to a lint
error, just judged by eye instead of by script. A spec that lints clean but
looks plain is not done. This step is what actually determines whether the
output is "ready to go," not the JSON report.

Once lint is clean and all five loops hold up (Loop C per slide, Loops D and
E across the deck, or 3 iterations reached), hand the render to a human for
final **design quality and template conformance** sign-off -- not a
pixel-similarity check against any specific reference screenshot. Every real
slide's ideal content differs; the target is *matching the quality bar*
(composition, typography, finish) of a well-designed example, not
reproducing one.

## Tools this skill calls (owned by `pptx-deck`, not duplicated here)

- `inventory.py` -- regenerates the facts layer if stale.
- `extract_media.py <template.pptx> <ppt/media/imageN.png> <out.png>
  [--recolor dark|light]` -- materializes a chosen template-embedded logo
  (or any other template media) as a real on-disk file your spec's `asset`
  field can point at.
- `build_deck.py`, `lint_render.py`, `render.py` -- see `pptx-deck/SKILL.md`.
  `build_deck.py` supports `type: "shape"` elements and real
  `fit`/`anchor` handling for images (not just stretch) -- see its schema
  doc for exact fields; both are referenced above.
