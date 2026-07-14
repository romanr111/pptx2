# pptx2

## Start here

- Read the relevant `SKILL.md` before authoring a deck, changing the pipeline,
  or using a presentation workflow. Skills own detailed procedures and commands.
- `.claude/skills/` is authoritative. `.agents/skills/` is the Codex-facing
  mirror: never edit it directly.
- After changing source skills, run
  `python3 .claude/skills/pptx-deck/scripts/sync_agents.py`, then
  `diff -qr --exclude='__pycache__' .claude/skills .agents/skills`.

## Non-negotiable boundaries

- Keep **facts** (deterministic inventory), **decisions** (the slide spec), and
  **execution** (build, render, QA) separate. Do not hard-code a client's
  design decisions into generic scripts.
- Treat `assets/` as local client material. Never commit or expose templates,
  imagery, fonts, copy, or derived deliverables.
- Generated `out/` and `output/` artifacts are ignored and stateful. Keep
  them out of source edits.

## Deck workflow

1. Inventory the template and assets before design decisions.
2. Record layout, typography, color, and asset choices in a validated spec.
3. Build, lint, inspect the render, and complete visual review before delivery.

## Quality and validation

- Lint errors and a failing visual-review verdict block delivery. Warnings need
  explicit assessment but are not automatic blockers.
- Preserve deterministic checks. Add focused tests for pipeline or quality-gate
  changes, then run the full suite: `.venv/bin/python -m pytest -q`.
- Use `.venv/bin/python`. The full local pipeline needs `soffice`, `pdftoppm`,
  and macOS `textutil`.
