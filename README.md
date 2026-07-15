# pptx2

pptx2 turns approved presentation materials into editable PowerPoint decks that match an organization's template. It gives teams a repeatable, quality-gated way to create polished decks faster while keeping client content private.

## First-time client setup

On macOS, install the Docker CLI, start a Docker-compatible daemon once
(Docker Desktop, Colima, or OrbStack), and install Poppler:

```bash
brew install poppler
brew install docker
```

Start your preferred Docker-compatible daemon before setup. For example,
Docker Desktop's engine can be started with `docker desktop start`, while
Colima uses `colima start`. Every pipeline operation after that uses the
`docker` CLI; it does not drive a GUI renderer.

Then, from a clean pptx2 checkout, run the setup script with the actual client
template. It creates the virtual environment, installs Python dependencies,
synchronizes the Codex-facing skill mirror, proves Docker is usable, pulls the
pinned LibreOffice image when needed, and runs the template preflight.

```bash
python3 scripts/setup_client.py \
  --template path/to/template.pptx \
  --output-root output/<client-run>
```

`textutil` is included with macOS. The script intentionally reports a missing
system prerequisite instead of installing it silently. It also refuses an
incomplete checkout, such as one missing either schema file. For local
development only, use `--renderer host` after installing LibreOffice.

## Delivery workflow

Use the Docker renderer for delivery. It runs the pinned LibreOffice image with no network, a read-only input mount, and an output-only writable mount. Host LibreOffice is available only as an explicit development fallback.

Before any deck design, prove the local environment with the actual template:

```bash
.venv/bin/python .claude/skills/pptx-deck/scripts/preflight.py \
  --template path/to/template.pptx --renderer docker \
  --output-root output/<run-name>
```

Inventory uses the same explicit template path and keeps deterministic facts in `out/`:

```bash
.venv/bin/python .claude/skills/pptx-deck/scripts/inventory.py \
  --template path/to/template.pptx
```

Before client handoff, run delivery QA. `--output-root` contains the assembled deck, one authoritative full-deck render set, automatic QA crops, media cache, and its default `qa_report.json`. For direct builds, `build_deck.py --out` remains the explicit primary deck-file override; in `deck_qa.py`, `--out` overrides only the report file.

```bash
.venv/bin/python .claude/skills/pptx-deck/scripts/deck_qa.py \
  specs/<name>.deck.json --delivery --renderer docker \
  --output-root output/<run-name>
```

Use `deck_qa.py ... --static-only` after the first spec pass. It writes a complete report and stops before build/render when any blocking static error exists. A full run builds the assembled deck once, renders it once, lints the actual assembled pages, and writes `qa_crops/manifest.json`. During a run, progress is flushed and `qa_report.partial.json` is updated atomically; `qa_report.json` appears only after a complete QA result. Delivery QA fails unless all slides render, deterministic lints are clean, and each slide records a visual review with iteration 1-3 and verdict `pass` or `pass_with_notes`.
