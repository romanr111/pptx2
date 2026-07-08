#!/usr/bin/env python3
"""Design-reference ingestion: advisory visual facts from a PDF reference.

Organizer-provided PDFs (e.g. Canva exports) are *design references*, not
production templates: they yield palette, typography hints, logos, motifs
and layout ideas for the Decisions layer. The authoritative production
source stays a real .pptx template ingested by inventory.py /
template_style.py — this script's output is a deliberately separate
contract (out/design_reference.json, `"authority": "advisory"`) and must
never be merged into out/template_style.json.

Licensing guard (docs/IMPROVEMENT_PLAN.md §2): raster art inside a
reference export is often stock, not the organizer's property. Every
harvested image gets a provenance sidecar marking its license unverified;
imitating direction (palette/type/motif) is always safe, pixel reuse goes
through the watermark/licensing lint and a recorded judgment call.

Usage:
  reference_style.py <reference.pdf> --event <slug>
      writes out/design_reference.json,
             out/thumbnails/reference/<slug>/page-NN.png,
             assets/reference/<slug>/pNN_xNNN.png (+ .json sidecars)
"""
import argparse
import datetime as _dt
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import pymupdf
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[4]
EMU_PER_PT = 12700
THUMB_WIDTH_PX = 1280
PALETTE_COLORS = 6
MIN_HARVEST_PX = 24  # skip sub-icon-size rasters (rules, textures, bullets)

LICENSE_NOTE = (
    "unverified — extracted from a design-reference export; the organizer's "
    "own brand marks are fair to reuse, generic art is often third-party "
    "stock. Imitate direction freely; gate pixel reuse through the "
    "watermark/licensing lint (docs/IMPROVEMENT_PLAN.md §2)."
)


def _sha256_16(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _strip_subset_prefix(basefont: str) -> str:
    """PDF subset fonts are named like 'ABCDEF+Geologica-Bold'."""
    name = basefont.split("+", 1)[-1]
    return name


def _page_palette(pix: pymupdf.Pixmap, n_colors: int = PALETTE_COLORS):
    """Dominant colors of a rendered page, as [{hex, frac}] sorted by
    coverage. Adaptive-quantized so near-identical shades pool together."""
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    img.thumbnail((256, 256))
    quant = img.quantize(colors=n_colors)
    palette = quant.getpalette()
    counts = Counter(quant.tobytes())  # 'P'-mode bytes = palette indices
    total = sum(counts.values())
    out = []
    for idx, n in counts.most_common(n_colors):
        r, g, b = palette[idx * 3: idx * 3 + 3]
        out.append({"hex": f"{r:02x}{g:02x}{b:02x}", "frac": round(n / total, 4)})
    return out


def _harvest_image(doc, xref: int, smask: int, dest: Path):
    """Extract one embedded raster, preserving alpha via its soft mask.
    Returns (width, height) or None if too small to be worth harvesting."""
    pix = pymupdf.Pixmap(doc, xref)
    if pix.width < MIN_HARVEST_PX or pix.height < MIN_HARVEST_PX:
        return None
    if smask:
        mask = pymupdf.Pixmap(doc, smask)
        try:
            pix = pymupdf.Pixmap(pix, mask)
        except Exception:
            pass  # mismatched mask: keep the opaque base image
    if pix.colorspace and pix.colorspace.n > 3:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    pix.save(dest)
    return pix.width, pix.height


def extract_reference(pdf_path, event, out_json=None, thumbs_dir=None,
                      assets_dir=None):
    """Ingest one PDF design reference. Returns the contract dict and
    writes it to out_json (plus thumbnails and harvested assets)."""
    pdf_path = Path(pdf_path)
    out_json = Path(out_json or PROJECT_ROOT / "out" / "design_reference.json")
    thumbs_dir = Path(thumbs_dir or PROJECT_ROOT / "out" / "thumbnails" / "reference" / event)
    assets_dir = Path(assets_dir or PROJECT_ROOT / "assets" / "reference" / event)
    for d in (out_json.parent, thumbs_dir, assets_dir):
        d.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(pdf_path)
    page0 = doc[0]
    w_pt, h_pt = page0.rect.width, page0.rect.height

    pages, fonts_all, harvested, seen_xrefs = [], set(), [], set()
    overall_counter = Counter()

    for i, page in enumerate(doc, start=1):
        zoom = THUMB_WIDTH_PX / page.rect.width
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        thumb_path = thumbs_dir / f"page-{i:02d}.png"
        pix.save(thumb_path)

        palette = _page_palette(pix)
        for c in palette:
            overall_counter[c["hex"]] += c["frac"]

        page_fonts = sorted({_strip_subset_prefix(f[3]) for f in page.get_fonts()})
        fonts_all.update(page_fonts)

        images = page.get_images(full=True)
        for img in images:
            xref, smask = img[0], img[1]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            dest = assets_dir / f"p{i:02d}_x{xref}.png"
            size = _harvest_image(doc, xref, smask, dest)
            if size is None:
                continue
            data = dest.read_bytes()
            sidecar = {
                "source_pdf": str(pdf_path),
                "page": i,
                "xref": xref,
                "extracted": _dt.date.today().isoformat(),
                "sha256_16": _sha256_16(data),
                "license": LICENSE_NOTE,
            }
            sidecar_path = dest.with_suffix(".json")
            sidecar_path.write_text(json.dumps(sidecar, indent=2))
            harvested.append({
                "path": str(dest),
                "page": i,
                "width": size[0],
                "height": size[1],
                "sha256_16": sidecar["sha256_16"],
                "provenance": str(sidecar_path),
            })

        pages.append({
            "index": i,
            "thumbnail": str(thumb_path),
            "palette": palette,
            "fonts": page_fonts,
            "n_images": len(images),
        })

    result = {
        "contract": "design_reference",
        "authority": "advisory",
        "event": event,
        "source": {
            "path": str(pdf_path),
            "kind": "pdf",
            "sha256_16": _sha256_16(pdf_path.read_bytes()),
        },
        "n_pages": len(doc),
        "page_size": {
            "width_pt": w_pt,
            "height_pt": h_pt,
            "width_emu": round(w_pt * EMU_PER_PT),
            "height_emu": round(h_pt * EMU_PER_PT),
        },
        "pages": pages,
        "fonts_all": sorted(fonts_all),
        "palette_overall": [
            {"hex": h, "weight": round(w, 4)}
            for h, w in overall_counter.most_common(PALETTE_COLORS)
        ],
        "harvested_images": harvested,
        "licensing_note": LICENSE_NOTE,
    }
    doc.close()
    out_json.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf", type=Path, help="path to the reference PDF")
    ap.add_argument("--event", required=True,
                    help="event slug (names the thumbnail/asset subdirs)")
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--thumbs-dir", type=Path, default=None)
    ap.add_argument("--assets-dir", type=Path, default=None)
    args = ap.parse_args()

    result = extract_reference(args.pdf, event=args.event,
                               out_json=args.out_json,
                               thumbs_dir=args.thumbs_dir,
                               assets_dir=args.assets_dir)
    print(f"pages: {result['n_pages']}, fonts: {result['fonts_all']}, "
          f"harvested: {len(result['harvested_images'])} image(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
