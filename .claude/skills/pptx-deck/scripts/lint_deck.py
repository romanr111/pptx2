#!/usr/bin/env python3
"""Cross-slide deck lint: the measurable half of "looks art-directed".

Per-slide checks live in lint_render.py; this checks what only exists
*between* slides — one type system, one palette, one grid, restraint —
against the deck spec's own tokens (the designer's frozen design system,
so this is also the conformance source in fallback mode, where the
template theme isn't the standard).

Severities follow the pipeline's convention: fix errors, weigh warns.

Usage: lint_deck.py <name.deck.json> [--out report.json]
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_deck import PROJECT_ROOT, validate_deck  # noqa: E402
from common import resolve_output_root  # noqa: E402


def finding(severity, check, where, message):
    return {"severity": severity, "check": check, "where": where,
            "message": message}


def _has_override_justification(deck, key):
    """Check if meta.token_overrides has an entry for this key with a reason."""
    for entry in deck.get("meta", {}).get("token_overrides", []):
        if entry.get("key") == key and entry.get("reason"):
            return True
    return False


def _iter_runs(spec):
    for el in spec["elements"]:
        if el["type"] == "textbox":
            for para in el["paragraphs"]:
                for run in para["lines"]:
                    yield el, para, run


def _slide_fonts(spec):
    fonts = set()
    for el, para, run in _iter_runs(spec):
        fonts.add(run["font"])
        if para.get("bullet"):
            fonts.add(para["bullet"]["font"])
    for el in spec["elements"]:
        if el["type"] == "table":
            fonts.add(el["table"]["style"]["font"])
    return fonts


def _slide_colors(spec):
    colors = set()
    for el, para, run in _iter_runs(spec):
        colors.add(run["color"].upper())
        if para.get("bullet", {}) and para["bullet"].get("color"):
            colors.add(para["bullet"]["color"].upper())
    for el in spec["elements"]:
        if el["type"] == "shape":
            colors.add(el["fill"]["color"].upper())
            if el["fill"].get("color2"):
                colors.add(el["fill"]["color2"].upper())
            if el.get("line"):
                colors.add(el["line"]["color"].upper())
        if el["type"] == "table":
            st = el["table"]["style"]
            for k in ("text_color", "header_fill", "header_color",
                      "row_fill", "alt_row_fill", "border_color"):
                if st.get(k):
                    colors.add(st[k].upper())
    return colors


def check_font_budget(deck, slides, names, findings):
    budget = deck.get("tokens", {}).get("max_font_families", 2)
    used = {}
    for name, spec in zip(names, slides):
        for f in _slide_fonts(spec):
            used.setdefault(f, name)
    if len(used) > budget:
        findings.append(finding(
            "error", "font_budget", "deck",
            f"{len(used)} font families used ({sorted(used)}), deck budget "
            f"is {budget} — one type system, not a specimen sheet"))
    # Warn when the budget was raised above the default of 2 without a
    # recorded justification in meta.token_overrides.
    if budget > 2 and not _has_override_justification(deck, "max_font_families"):
        findings.append(finding(
            "warn", "token_override", "deck",
            f"max_font_families raised to {budget} (default 2) without "
            f"justification in meta.token_overrides — three+ families risk "
            f"reading as unfocused"))


def check_type_scale(deck, slides, names, findings):
    scale = deck.get("tokens", {}).get("type_scale", {})
    if not scale:
        if not _has_override_justification(deck, "type_scale"):
            findings.append(finding(
                "warn", "token_override", "deck",
                "no tokens.type_scale set — role-keyed size/font conformance "
                "cannot be checked; record a justification in "
                "meta.token_overrides or add a type_scale"))
        return
    for name, spec in zip(names, slides):
        for el in spec["elements"]:
            if el["type"] != "textbox" or el.get("role") not in scale:
                continue
            token = scale[el["role"]]
            first = el["paragraphs"][0]["lines"][0]
            if first["font"] != token["font"] or first["size_pt"] != token["size_pt"]:
                findings.append(finding(
                    "error", "type_scale", f"{name}:{el['id']}",
                    f"role '{el['role']}' opens with {first['font']} "
                    f"{first['size_pt']}pt, token demands {token['font']} "
                    f"{token['size_pt']}pt"))
            elif token.get("bold") is not None and first.get("bold", False) != token["bold"]:
                findings.append(finding(
                    "warn", "type_scale", f"{name}:{el['id']}",
                    f"role '{el['role']}' bold={first.get('bold', False)} "
                    f"differs from token bold={token['bold']}"))


def check_palette_discipline(deck, slides, names, findings):
    roles = deck.get("tokens", {}).get("palette_roles", {})
    if not roles:
        return
    allowed = {v.upper() for v in roles.values()}
    for name, spec in zip(names, slides):
        stray = _slide_colors(spec) - allowed
        for color in sorted(stray):
            findings.append(finding(
                "warn", "palette_discipline", name,
                f"color {color} is not one of the deck's palette_roles — "
                f"off-palette one-offs erode the brand read"))


def check_margins(deck, slides, names, findings):
    margins = deck.get("tokens", {}).get("margins_emu", {})
    if not margins:
        return
    sw = deck["slide"]["width_emu"]
    sh = deck["slide"]["height_emu"]
    for name, spec in zip(names, slides):
        for el in spec["elements"]:
            if el["type"] not in ("textbox", "table"):
                continue  # shapes/images may bleed by design
            b = el["box"]
            if margins.get("left") and b["x"] < margins["left"]:
                findings.append(finding(
                    "warn", "margins", f"{name}:{el['id']}",
                    f"starts at x={b['x']}, inside the {margins['left']} left margin"))
            if margins.get("right") and b["x"] + b["cx"] > sw - margins["right"]:
                findings.append(finding(
                    "warn", "margins", f"{name}:{el['id']}",
                    f"ends at x={b['x'] + b['cx']}, inside the right margin"))
            if margins.get("top") and b["y"] < margins["top"]:
                findings.append(finding(
                    "warn", "margins", f"{name}:{el['id']}",
                    f"starts at y={b['y']}, inside the {margins['top']} top margin"))
            if margins.get("bottom") and b["y"] + b["cy"] > sh - margins["bottom"]:
                findings.append(finding(
                    "warn", "margins", f"{name}:{el['id']}",
                    f"ends at y={b['y'] + b['cy']}, inside the bottom margin"))


def check_density(deck, slides, names, findings):
    budget = deck.get("tokens", {}).get("max_elements_per_slide", 9)
    for name, spec in zip(names, slides):
        n = len(spec["elements"])
        if n > budget:
            findings.append(finding(
                "warn", "density", name,
                f"{n} elements against a budget of {budget} — restraint is "
                f"what reads as 'designed'"))
    # Warn when the budget was raised above the default of 9 without a
    # recorded justification.
    if budget > 9 and not _has_override_justification(deck, "max_elements_per_slide"):
        findings.append(finding(
            "warn", "token_override", "deck",
            f"max_elements_per_slide raised to {budget} (default 9) without "
            f"justification in meta.token_overrides — high density risks "
            f"reading as cluttered"))


def check_package_size(deck, deck_path, findings, project_root=PROJECT_ROOT,
                       output_root=None):
    budget_mb = deck.get("packaging", {}).get("max_package_mb")
    if not budget_mb:
        return
    stem = Path(deck_path).stem.replace(".deck", "")
    built = resolve_output_root(
        output_root, default_root=Path(project_root) / "output") / f"{stem}.pptx"
    if not built.is_file():
        findings.append(finding(
            "warn", "package_size", "deck",
            f"skipped: {built} not found — run build_deck.py first"))
        return
    size_mb = built.stat().st_size / (1024 * 1024)
    if size_mb > budget_mb:
        findings.append(finding(
            "warn", "package_size", "deck",
            f"built package is {size_mb:.1f} MB against a "
            f"{budget_mb} MB budget — consider packaging.media_optimization"))


def check_role_alignment(deck, slides, names, findings):
    """Same-role textboxes should sit on the same vertical grid line."""
    tol = round(deck["slide"]["width_emu"] * 0.01)
    by_role = defaultdict(list)
    for name, spec in zip(names, slides):
        for el in spec["elements"]:
            if el["type"] == "textbox" and el.get("role"):
                by_role[el["role"]].append((name, el["id"], el["box"]["x"]))
    for role, hits in by_role.items():
        if len(hits) < 2:
            continue
        xs = [x for _, _, x in hits]
        if max(xs) - min(xs) > tol:
            detail = ", ".join(f"{n}:{i}@x={x}" for n, i, x in hits)
            findings.append(finding(
                "warn", "role_alignment", role,
                f"role '{role}' is not on one grid line across slides ({detail})"))


def lint_deck(deck_path, project_root=PROJECT_ROOT, static_only=False,
              package_only=False, output_root=None):
    if static_only and package_only:
        raise ValueError("static_only and package_only are mutually exclusive")
    deck = json.loads(Path(deck_path).read_text())
    if package_only:
        findings = []
        check_package_size(
            deck, deck_path, findings, project_root, output_root=output_root)
        return {"deck": str(deck_path), "n_errors": 0,
                "n_warns": len(findings), "findings": findings}
    errors, slide_specs = validate_deck(deck, project_root)
    findings = [finding("error", "deck_valid", "deck", e) for e in errors]
    if not errors:
        names = [Path(p).stem.replace(".spec", "") for p in deck["slides"]]
        check_font_budget(deck, slide_specs, names, findings)
        check_type_scale(deck, slide_specs, names, findings)
        check_palette_discipline(deck, slide_specs, names, findings)
        check_margins(deck, slide_specs, names, findings)
        check_density(deck, slide_specs, names, findings)
        check_role_alignment(deck, slide_specs, names, findings)
        if not static_only:
            check_package_size(
                deck, deck_path, findings, project_root,
                output_root=output_root)
    n_err = sum(1 for f in findings if f["severity"] == "error")
    return {"deck": str(deck_path), "n_errors": n_err,
            "n_warns": len(findings) - n_err, "findings": findings}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("deck", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--output-root", type=Path, default=None)
    stage = ap.add_mutually_exclusive_group()
    stage.add_argument("--static-only", action="store_true")
    stage.add_argument("--package-only", action="store_true")
    args = ap.parse_args()
    report = lint_deck(
        args.deck, static_only=args.static_only,
        package_only=args.package_only, output_root=args.output_root)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 1 if report["n_errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
