#!/usr/bin/env python3
"""Agent-operated resolver for spec image_briefs.

This script does not call web search or image-generation APIs. It gives the
agent a deterministic planning/import/report surface around the existing
image_briefs contract, while the agent performs web/image tool work.
"""

import argparse
import datetime as dt
import hashlib
import json
import math
import shutil
from pathlib import Path

from PIL import Image

from common import PROJECT_ROOT
OUT = PROJECT_ROOT / "out"
ASSETS_JSON = OUT / "assets.json"
TEMPLATE_STYLE_JSON = OUT / "template_style.json"
STYLEGUIDE_PROFILE_JSON = OUT / "styleguide_profile.json"
PROVENANCE_SUFFIX = ".json"
EXTERNAL_SOURCE_TYPES = {"web", "generated"}
SOURCE_TYPES = {"local", "template", "web", "generated"}


def load_json(path: Path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text())


def write_json(data, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def brief_hash(brief):
    payload = json.dumps(brief, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def provenance_path(asset_path: Path) -> Path:
    return asset_path.with_suffix(asset_path.suffix + PROVENANCE_SUFFIX)


def parse_aspect(value, box=None):
    if isinstance(value, str) and ":" in value:
        left, right = value.split(":", 1)
        try:
            return float(left) / float(right)
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    if box and box.get("cy"):
        return box["cx"] / box["cy"]
    return None


def image_aspect(path: Path):
    with Image.open(path) as img:
        w, h = img.size
    return w / h if h else None


def aspect_score(candidate_aspect, target_aspect):
    if not candidate_aspect or not target_aspect:
        return 0.0
    distance = abs(math.log(candidate_aspect / target_aspect))
    return max(0.0, 1.0 - min(distance, 1.0))


def subject_tokens(text):
    raw = "".join(ch.lower() if ch.isalnum() else " " for ch in text or "")
    return {tok for tok in raw.split() if len(tok) >= 4}


def candidate_score(brief, candidate):
    target_aspect = parse_aspect(brief.get("aspect"), brief.get("box"))
    candidate_aspect = candidate.get("aspect")
    score = 0.65 * aspect_score(candidate_aspect, target_aspect)

    classification = candidate.get("classification") or candidate.get("kind") or ""
    med = brief.get("medical_class")
    if med == "decorative" and classification in {"background_art", "content_illustration", "photo"}:
        score += 0.18
    elif med in {"conceptual", "anatomical"} and classification in {"content_illustration", "background_art"}:
        score += 0.18
    elif classification:
        score += 0.06

    name_tokens = subject_tokens(candidate.get("asset") or candidate.get("file") or candidate.get("media"))
    overlap = len(subject_tokens(brief.get("subject")) & name_tokens)
    score += min(0.12, overlap * 0.04)
    if candidate.get("watermark_suspected"):
        score -= 0.25
    return round(max(0.0, min(1.0, score)), 3)


def local_candidates(brief, assets_json, limit=5):
    candidates = []
    for img in assets_json.get("images", []):
        asset = img.get("file") or img.get("asset")
        if not asset:
            continue
        candidate = {
            "asset": asset,
            "classification": img.get("classification"),
            "aspect": img.get("aspect"),
            "watermark_suspected": img.get("watermark_suspected", False),
        }
        candidate["score"] = candidate_score(brief, candidate)
        candidates.append(candidate)
    return sorted(candidates, key=lambda c: c["score"], reverse=True)[:limit]


def template_candidates(brief, template_style, limit=5):
    candidates = []
    for item in template_style.get("logo_candidates", []):
        candidate = {
            "media": item.get("media"),
            "classification": "logo",
            "aspect": item.get("aspect"),
            "size": item.get("size"),
            "variant": item.get("variant"),
        }
        candidate["score"] = candidate_score(brief, candidate)
        candidates.append(candidate)
    for item in template_style.get("media_reuse_ranked", []):
        candidate = {
            "media": item.get("media"),
            "classification": "template_media",
            "n_slides": item.get("n_slides"),
        }
        candidate["score"] = candidate_score(brief, candidate)
        candidates.append(candidate)
    return sorted(candidates, key=lambda c: c["score"], reverse=True)[:limit]


def styleguide_summary(styleguide):
    if not styleguide:
        return {"exists": False}
    return {
        "exists": True,
        "style_name": styleguide.get("style_name"),
        "source": styleguide.get("source"),
        "image_style": styleguide.get("image_brief_defaults", {}).get("style"),
        "negative": styleguide.get("image_brief_defaults", {}).get("negative"),
    }


def suggested_queries(brief, spec, styleguide=None):
    subject = brief.get("subject", "").strip()
    style = brief.get("style", "").strip()
    profile_style = (styleguide or {}).get("image_brief_defaults", {}).get("style", "")
    title = spec.get("meta", {}).get("doc_props", {}).get("title", "")
    base = " ".join(part for part in [subject, title] if part).strip()
    if not base:
        base = subject or "medical presentation visual"
    suffix = "medical conference presentation image no watermark"
    if brief.get("medical_class") == "anatomical":
        suffix = "medical anatomical illustration accurate no labels no watermark"
    queries = [f"{base} {suffix}"]
    if style:
        queries.append(f"{base} {style} no text no watermark")
    if profile_style:
        queries.append(f"{base} {profile_style} no text no watermark")
    return list(dict.fromkeys(queries))[:3]


def suggested_prompt(brief, styleguide=None):
    defaults = (styleguide or {}).get("image_brief_defaults", {})
    parts = [
        brief.get("subject", "").strip(),
        brief.get("style", "").strip() or defaults.get("style", ""),
        f"aspect ratio {brief.get('aspect')}",
        brief.get("negative") or defaults.get("negative") or "no text, no watermarks, no logos",
    ]
    return "; ".join(part for part in parts if part)


def open_brief_plans(spec, project_root=PROJECT_ROOT):
    assets_json = load_json(ASSETS_JSON, {})
    template_style = load_json(TEMPLATE_STYLE_JSON, {})
    styleguide = load_json(STYLEGUIDE_PROFILE_JSON, {})
    plans = []
    for brief in spec.get("image_briefs", []):
        asset_path = project_root / brief["asset"]
        if asset_path.is_file():
            continue
        plans.append({
            "id": brief["id"],
            "asset": brief["asset"],
            "brief_hash": brief_hash(brief),
            "subject": brief.get("subject"),
            "medical_class": brief.get("medical_class"),
            "aspect": brief.get("aspect"),
            "box": brief.get("box"),
            "local_candidates": local_candidates(brief, assets_json),
            "template_candidates": template_candidates(brief, template_style),
            "styleguide_context": styleguide_summary(styleguide),
            "suggested_search_queries": suggested_queries(brief, spec, styleguide),
            "suggested_generation_prompt": suggested_prompt(brief, styleguide),
        })
    return plans


def command_plan(args):
    spec_path = Path(args.spec)
    spec = load_json(spec_path, {})
    result = {
        "spec": str(spec_path),
        "resolver_order": ["local", "template", "web", "generated"],
        "styleguide_profile": styleguide_summary(load_json(STYLEGUIDE_PROFILE_JSON, {})),
        "open_briefs": open_brief_plans(spec),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def command_import(args):
    spec_path = Path(args.spec)
    spec = load_json(spec_path, {})
    briefs = {b["id"]: b for b in spec.get("image_briefs", [])}
    if args.brief_id not in briefs:
        raise SystemExit(f"unknown brief id: {args.brief_id}")
    if args.source_type not in SOURCE_TYPES:
        raise SystemExit(f"source_type must be one of {sorted(SOURCE_TYPES)}")

    brief = briefs[args.brief_id]
    source = Path(args.source)
    if not source.is_file():
        raise SystemExit(f"source file not found: {source}")
    target = PROJECT_ROOT / brief["asset"]
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        shutil.copyfile(source, target)

    warnings = args.warning or []
    provenance = {
        "brief_id": brief["id"],
        "brief_hash": brief_hash(brief),
        "asset": brief["asset"],
        "source_type": args.source_type,
        "source_path": str(source),
        "source_url": args.source_url,
        "generation_prompt": args.prompt,
        "selected_rationale": args.rationale,
        "verification_notes": args.verification,
        "warnings": warnings,
        "medical_class": brief.get("medical_class"),
        "subject": brief.get("subject"),
        "aspect": brief.get("aspect"),
        "ai_generated": args.source_type == "generated",
        "imported_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "tool": "asset_resolver.py",
    }
    write_json(provenance, provenance_path(target))
    print(json.dumps({
        "imported": brief["id"],
        "asset": str(target.relative_to(PROJECT_ROOT)),
        "provenance": str(provenance_path(target).relative_to(PROJECT_ROOT)),
    }, ensure_ascii=False, indent=2))


def provenance_status(asset_path: Path):
    sidecar = provenance_path(asset_path)
    if not sidecar.is_file():
        return {"exists": False}
    data = load_json(sidecar, {})
    required = ["brief_id", "brief_hash", "source_type", "selected_rationale"]
    missing = [key for key in required if not data.get(key)]
    if data.get("source_type") in EXTERNAL_SOURCE_TYPES and not data.get("verification_notes"):
        missing.append("verification_notes")
    return {"exists": True, "path": str(sidecar.relative_to(PROJECT_ROOT)), "missing": missing, "data": data}


def command_report(args):
    spec_path = Path(args.spec)
    spec = load_json(spec_path, {})
    acknowledged = set(spec.get("meta", {}).get("acknowledged_briefs", []))
    rows = []
    for brief in spec.get("image_briefs", []):
        asset_path = PROJECT_ROOT / brief["asset"]
        filled = asset_path.is_file()
        row = {
            "id": brief["id"],
            "asset": brief["asset"],
            "filled": filled,
            "acknowledged_missing": brief["id"] in acknowledged,
        }
        if filled:
            row["provenance"] = provenance_status(asset_path)
        rows.append(row)
    print(json.dumps({"spec": str(spec_path), "briefs": rows}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="List open image briefs and candidate sources.")
    p_plan.add_argument("spec")
    p_plan.set_defaults(func=command_plan)

    p_import = sub.add_parser("import", help="Import a selected asset and write provenance.")
    p_import.add_argument("spec")
    p_import.add_argument("--brief-id", required=True)
    p_import.add_argument("--source", required=True)
    p_import.add_argument("--source-type", required=True, choices=sorted(SOURCE_TYPES))
    p_import.add_argument("--source-url")
    p_import.add_argument("--prompt")
    p_import.add_argument("--rationale", required=True)
    p_import.add_argument("--verification", required=True)
    p_import.add_argument("--warning", action="append")
    p_import.set_defaults(func=command_import)

    p_report = sub.add_parser("report", help="Report fill/provenance status for image briefs.")
    p_report.add_argument("spec")
    p_report.set_defaults(func=command_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
