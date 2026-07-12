Repo root: /Users/roman/Documents/Development/pptx2
Branch: p0-fixes (worktree: /Users/roman/Documents/Development/pptx2-p0-fixes)
Base branch: main (origin/main)
Merge status: p0-fixes created from main at 272500b, not yet pushed.

Ownership:
- Current task: P0 improvements — 5 items all implemented on p0-fixes branch.
  1. Fixed 6 text_fit errors in slides 01/02/06 (line splits + box size adjustments). Added wrap="none" blocker rule to pptx-designer SKILL.md.
  2. Created deck_qa.py orchestrator: build_deck → per-slide build → lint_render(each slide) → lint_deck → consolidated qa_report.json. Exit 1 on any error.
  3. Fixed inventory blind zone: inventory_images() now scans all assets/ except fonts/; lint_render warns on placed images absent from inventory (asset_not_in_inventory check).
  4. Resolved .agents/ drift: created sync_agents.py to copy .claude/skills → .agents/skills; .agents/ now git-tracked (no longer a silent stale copy).
  5. Added requirements.txt (python-pptx, Pillow, numpy, jsonschema, fonttools, lxml, pymupdf, pytest); setup_env.sh now installs from requirements.txt and checks soffice/pdftoppm/textutil; deck_qa.py checks all three binaries.

Conflicts:
- None.

Cleanup:
- .venv, assets, out, output in the worktree are symlinks to the main worktree (git-ignored).
- specs/sia_med_conference/ and specs/sia_med_conference.deck.json are real copies (not symlinks) in the worktree.

Working:
- None.

Done recent:
- 2026-07-11 P0 fixes: all 5 items implemented. deck_qa.py reports ok=true, 0 errors on all 6 slides, 0 deck lint errors, 0 tool issues. 51 tests pass.

Receipts:
- Headroom proxy OK at session start.
- CodeGraph unavailable: no justfile; used grep/glob fallback.
- `.venv/bin/python -m py_compile` passed for deck_qa.py, sync_agents.py, inventory.py, lint_render.py.
- `.venv/bin/python -m pytest -q tests/ --disable-warnings` passed: 51 passed, 5 warnings.
- `.venv/bin/python .claude/skills/pptx-deck/scripts/deck_qa.py specs/sia_med_conference.deck.json --out output/qa_report.json` — ok: true, total_errors: 0, all 6 slides 0 errors, deck_lint_errors: 0, tool_issues: [].