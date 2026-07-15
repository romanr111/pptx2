#!/usr/bin/env python3
"""Extract a style guide + logo/animation/consistency facts from the
conference template .pptx.

Writes out/template_style.json. Called by inventory.py, or standalone:
  template_style.py [template.pptx]
"""
import io
import json
import re
import statistics
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np
from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.util import Emu

from common import PROJECT_ROOT
from render import (_file_hash, _renderer_cache_key, conversion_command,
                    resolve_renderer)
DEFAULT_TEMPLATE = PROJECT_ROOT / "assets" / "template.pptx"
OUT = PROJECT_ROOT / "out"
THUMB_DIR = OUT / "thumbnails" / "template"

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"


def _color_val(el):
    if el is None:
        return None
    srgb = el.find(A + "srgbClr")
    if srgb is not None:
        return srgb.get("val").upper()
    sysc = el.find(A + "sysClr")
    if sysc is not None:
        return sysc.get("lastClr", "").upper() or None
    return None


def parse_theme(xml_bytes, filename):
    root = etree.fromstring(xml_bytes)
    scheme = root.find(f".//{A}clrScheme")
    colors = {}
    if scheme is not None:
        for slot in scheme:
            tag = etree.QName(slot).localname
            colors[tag] = _color_val(slot)
    font_scheme = root.find(f".//{A}fontScheme")
    major = minor = None
    if font_scheme is not None:
        maj_el = font_scheme.find(f"{A}majorFont/{A}latin")
        min_el = font_scheme.find(f"{A}minorFont/{A}latin")
        major = maj_el.get("typeface") if maj_el is not None else None
        minor = min_el.get("typeface") if min_el is not None else None
    return {
        "file": filename,
        "name": scheme.get("name") if scheme is not None else None,
        "colors": colors,
        "major_font": major,
        "minor_font": minor,
    }


def zip_read(z, name):
    try:
        return z.read(name)
    except KeyError:
        return None


def rels_targets(z, part_name):
    """Resolve every relationship target for a part, keyed by rId."""
    d = part_name.rsplit("/", 1)
    folder = d[0] if len(d) > 1 else ""
    base = d[-1]
    rels_path = f"{folder}/_rels/{base}.rels" if folder else f"_rels/{base}.rels"
    data = zip_read(z, rels_path)
    if not data:
        return {}
    root = etree.fromstring(data)
    out = {}
    for rel in root:
        target = rel.get("Target")
        # normalize "../media/imageN.png" relative to the part's folder
        if target.startswith("../"):
            parts = folder.split("/")
            t = target
            while t.startswith("../"):
                parts = parts[:-1]
                t = t[3:]
            target = "/".join(parts + [t]) if parts else t
        elif not target.startswith("/"):
            target = f"{folder}/{target}" if folder else target
        out[rel.get("Id")] = target
    return out


def extract_themes(z, names):
    themes = []
    for n in sorted(x for x in names if re.match(r"ppt/theme/theme\d+\.xml$", x)):
        themes.append(parse_theme(z.read(n), n))
    # who references each theme?
    used_by = {t["file"]: [] for t in themes}
    for n in names:
        if re.match(r"ppt/slideMasters/slideMaster\d+\.xml$", n):
            for rid, target in rels_targets(z, n).items():
                if target in used_by:
                    used_by[target].append(n)
    for n in names:
        if n == "ppt/presentation.xml":
            for rid, target in rels_targets(z, n).items():
                if target in used_by and n not in used_by[target]:
                    used_by[target].append(f"{n} (presentation default)")
    for t in themes:
        t["referenced_by"] = used_by.get(t["file"], [])
    return themes


def extract_layout_geometry(prs):
    layouts_out = []
    for mi, master in enumerate(prs.slide_masters):
        for li in range(len(master.slide_layouts)):
            layout = master.slide_layouts[li]
            placeholders = []
            for shp in layout.placeholders:
                pf = shp.placeholder_format
                placeholders.append({
                    "idx": pf.idx,
                    "type": str(pf.type),
                    "name": shp.name,
                    "box_emu": None if shp.left is None else
                        {"x": shp.left, "y": shp.top, "cx": shp.width, "cy": shp.height},
                })
            bg_media = []
            sw, sh = prs.slide_width, prs.slide_height
            for shp in layout.shapes:
                if shp.shape_type is not None and str(shp.shape_type) == "PICTURE (13)":
                    if (shp.left in (0, None) and shp.top in (0, None)
                            and shp.width and shp.width >= sw * 0.9
                            and shp.height and shp.height >= sh * 0.9):
                        try:
                            bg_media.append(shp.image.filename or f"part:{shp.image.sha1}")
                        except Exception:
                            bg_media.append("(embedded, name unresolved)")
            layouts_out.append({
                "master_index": mi,
                "layout_file": str(layout.part.partname).lstrip("/"),
                "name": layout.name,
                "placeholder_count": len(placeholders),
                "placeholders": placeholders,
                "non_placeholder_shape_count": len(layout.shapes) - len(placeholders),
                "background_media": bg_media,
            })
    return layouts_out


def infer_margins(layouts_out):
    lefts, tops, rights, bottoms = [], [], [], []
    sw, sh = 12192000, 6858000
    for l in layouts_out:
        for ph in l["placeholders"]:
            b = ph["box_emu"]
            if not b:
                continue
            lefts.append(b["x"])
            tops.append(b["y"])
            rights.append(sw - (b["x"] + b["cx"]))
            bottoms.append(sh - (b["y"] + b["cy"]))
    if not lefts:
        return None
    return {
        "left_emu": round(statistics.median(lefts)),
        "top_emu": round(statistics.median(tops)),
        "right_emu": round(statistics.median(rights)),
        "bottom_emu": round(statistics.median(bottoms)),
        "n_placeholders_sampled": len(lefts),
    }


def map_slides_to_layouts(z, names, layouts_out):
    """Which of layouts_out (master/layout definitions) each real slide
    actually uses -- template_style.json's `layouts` list is layout
    *definitions* (there happen to be 30, same count as real slides, purely
    coincidentally), this is the join key that was previously missing.
    """
    # build (master_file, layout_file) -> layouts_out index once
    layout_index = {}
    for li, l in enumerate(layouts_out):
        layout_index[(l["master_index"], l["layout_file"])] = li

    out = {}
    for n in sorted(x for x in names if re.match(r"ppt/slides/slide\d+\.xml$", x)):
        targets = rels_targets(z, n)
        layout_file = next((t for t in targets.values()
                             if re.match(r"ppt/slideLayouts/slideLayout\d+\.xml$", t)), None)
        if layout_file is None:
            out[n] = None
            continue
        master_file = next((t for t in rels_targets(z, layout_file).values()
                             if re.match(r"ppt/slideMasters/slideMaster\d+\.xml$", t)), None)
        master_index = None
        if master_file is not None:
            m = re.search(r"slideMaster(\d+)\.xml$", master_file)
            if m:
                master_index = int(m.group(1)) - 1
        li = layout_index.get((master_index, layout_file))
        out[n] = {"layout_file": layout_file, "layouts_index": li}
    return out


def map_slides_to_media(z, names):
    """Which ppt/media/imageN.png files each slide's own XML actually
    embeds (<a:blip r:embed="rIdN">, resolved via that slide's .rels) --
    lets media_reuse_ranked below tell decorative/brand assets (used on
    many slides) apart from one-off slide content (used on one).
    """
    out = {}
    for n in sorted(x for x in names if re.match(r"ppt/slides/slide\d+\.xml$", x)):
        xml = z.read(n).decode("utf-8", errors="ignore")
        rids = re.findall(r'<a:blip[^>]*r:embed="(rId\d+)"', xml)
        targets = rels_targets(z, n)
        media = sorted({targets[r] for r in rids if r in targets
                         and re.match(r"ppt/media/image\d+\.", targets[r])})
        out[n] = media
    return out


def rank_media_reuse(slide_media_map):
    counter = Counter()
    for media in slide_media_map.values():
        counter.update(media)
    return [{"media": m, "n_slides": n} for m, n in counter.most_common()]


def rank_slide_usage(z, names):
    """Frequency-rank explicit colors and fonts actually used across the real
    slides (not the theme definitions) -- what the deck's authors reached
    for in practice, which may drift from the nominal theme.
    """
    color_counter, font_counter = Counter(), Counter()
    slide_names = sorted(n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n))
    per_slide_fonts = {}
    for n in slide_names:
        xml = z.read(n).decode("utf-8", errors="ignore")
        colors = re.findall(r'<a:srgbClr val="([0-9A-Fa-f]{6})"', xml)
        fonts = re.findall(r'typeface="([^"]+)"', xml)
        color_counter.update(c.upper() for c in colors)
        font_counter.update(f for f in fonts if f)
        per_slide_fonts[n] = sorted(set(f for f in fonts if f))
    return color_counter, font_counter, per_slide_fonts


def flag_font_mixing(per_slide_fonts, themes):
    """A slide is flagged if it uses typefaces whose *core* families belong
    to more than one theme -- a concrete, deterministic signal of template
    inconsistency (not a verdict; that's a later, human/LLM judgment call).
    """
    theme_cores = {}
    for t in themes:
        core = {f for f in (t["major_font"], t["minor_font"]) if f}
        if core:
            theme_cores[t["name"] or t["file"]] = core

    def core_family(typeface):
        # "Montserrat Black" -> "Montserrat", "Geologica Roman SemiBold" -> "Geologica"
        for theme_name, core in theme_cores.items():
            for c in core:
                if typeface == c or typeface.startswith(c.split()[0]):
                    return theme_name
        return None

    flags = []
    for slide, fonts in per_slide_fonts.items():
        touched_themes = {core_family(f) for f in fonts if f != "Arial"}
        touched_themes.discard(None)
        if len(touched_themes) > 1:
            flags.append({
                "slide": slide,
                "fonts": fonts,
                "themes_mixed": sorted(touched_themes),
            })
    return flags


def classify_logo_media(z, names):
    """Media images that look like logos: has alpha, ink is (near-)monochrome,
    modest size. Returns dark/light variant + a coarse ink-column fingerprint
    (downsampled column ink density) that can distinguish kerning/width
    between variants without a full pixel diff.
    """
    logos = []
    for n in sorted(x for x in names if re.match(r"ppt/media/image\d+\.(png)$", x)):
        try:
            img = Image.open(io.BytesIO(z.read(n))).convert("RGBA")
        except Exception:
            continue
        arr = np.asarray(img)
        alpha = arr[..., 3]
        if alpha.max() == 0:
            continue
        opaque_frac = (alpha > 128).mean()
        if opaque_frac > 0.92 or opaque_frac < 0.01:
            continue  # not a cutout (full rectangle photo, or empty)
        ink = arr[..., :3][alpha > 128]
        if ink.size == 0:
            continue
        mean_ink = ink.mean()
        w, h = img.size
        if max(w, h) > 3000:
            continue  # too big to plausibly be a logo mark
        variant = "dark_ink" if mean_ink < 128 else "light_ink"
        mask = alpha > 128
        col_ink = mask.sum(axis=0).astype(np.float64)
        buckets = np.array_split(col_ink, 24)
        fingerprint = [round(float(b.sum()) / max(1, h * len(b)), 3) for b in buckets]
        logos.append({
            "media": n, "size": [w, h], "aspect": round(w / h, 3),
            "opaque_frac": round(float(opaque_frac), 3),
            "variant": variant, "ink_column_fingerprint": fingerprint,
        })
    return logos


def extract_animation_exemplars(z, names):
    exemplars = []
    for n in sorted(x for x in names if re.match(r"ppt/slides/slide\d+\.xml$", x)):
        xml = z.read(n)
        if b"<p:timing>" not in xml:
            continue
        root = etree.fromstring(xml)
        timing = root.find(f".//{P}timing")
        steps = []
        for par in timing.iter(f"{P}cTn"):
            preset_id = par.get("presetID")
            if preset_id is None:
                continue
            node_type = par.get("nodeType")
            preset_class = par.get("presetClass")
            spid = None
            # walk down to find the first spTgt within this cTn's subtree
            spTgt = par.getparent().find(f".//{P}spTgt")
            if spTgt is not None:
                spid = spTgt.get("spid")
            anim_effect = par.getparent().find(f".//{P}animEffect")
            filt = anim_effect.get("filter") if anim_effect is not None else None
            steps.append({
                "node_type": node_type, "preset_class": preset_class,
                "preset_id": preset_id, "filter": filt, "target_shape_id": spid,
            })
        if steps:
            exemplars.append({"slide": n, "steps": steps})
    return exemplars


def render_thumbnails(template_path, renderer=None):
    """Render template thumbnails with the delivery renderer by default."""
    renderer = resolve_renderer(renderer)
    cache_key = (f"{template_path.stem}_{_file_hash(template_path)}_"
                 f"{_renderer_cache_key(renderer)}")
    thumbnail_dir = THUMB_DIR / cache_key
    thumbnail_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir = OUT / "thumbnails" / "_tmp_pdf" / cache_key
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_dir / (template_path.stem + ".pdf")
    if not pdf_path.exists():
        subprocess.run(
            conversion_command(template_path, pdf_dir, "pdf", renderer=renderer),
            check=True, capture_output=True, timeout=300)
    existing = sorted(thumbnail_dir.glob("slide-*.png"))
    if not existing:
        subprocess.run(
            ["pdftoppm", "-png", "-r", "80", str(pdf_path), str(thumbnail_dir / "slide")],
            check=True, capture_output=True, timeout=300)
        existing = sorted(thumbnail_dir.glob("slide-*.png"))
    return [str(p.relative_to(PROJECT_ROOT)) for p in existing]


MEDIA_CENSUS_DIR = OUT / "media_census"
MEDIA_CENSUS_SHEET = OUT / "media_census.png"
_MEDIA_RE = re.compile(r"ppt/media/[^/]+\.(png|jpg|jpeg|gif|bmp|tif|tiff|webp)$", re.I)


def _checker(size, sq=16):
    """A light checkerboard so transparent-alpha tiles read on the sheet."""
    yy, xx = np.mgrid[0:size, 0:size]
    mask = ((xx // sq + yy // sq) % 2).astype(bool)
    base = np.empty((size, size, 4), dtype=np.uint8)
    base[...] = (206, 206, 210, 255)
    base[mask] = (172, 172, 176, 255)
    return Image.fromarray(base, "RGBA")


def _write_media_contact_sheet(tiles, sheet_path, cols=4, cell=256, cap=48, pad=14):
    """One labeled grid of every template image (basename, WxH, reuse count)."""
    from PIL import ImageDraw, ImageFont
    if not tiles:
        return
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    checker = _checker(cell)
    rows = (len(tiles) + cols - 1) // cols
    cw, ch = cell + pad, cell + cap + pad
    sheet = Image.new("RGB", (cols * cw + pad, rows * ch + pad), (44, 44, 48))
    draw = ImageDraw.Draw(sheet)
    for i, (base, entry, im) in enumerate(tiles):
        r, c = divmod(i, cols)
        x0, y0 = pad + c * cw, pad + r * ch
        thumb = im.copy()
        thumb.thumbnail((cell, cell))
        tilebg = checker.copy()
        tilebg.alpha_composite(thumb, ((cell - thumb.width) // 2,
                                       (cell - thumb.height) // 2))
        sheet.paste(tilebg.convert("RGB"), (x0, y0))
        size = entry.get("size")
        caption = (f"{base}\n{size[0]}x{size[1]}  used {entry['n_slides_used']}x"
                   if size else f"{base}\n(unreadable)")
        if font is not None:
            draw.multiline_text((x0 + 1, y0 + cell + 4), caption,
                                fill=(236, 236, 240), font=font, spacing=3)
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(sheet_path)


def dump_media_census(z, names, slide_media_map, out_dir=MEDIA_CENSUS_DIR,
                      sheet_path=MEDIA_CENSUS_SHEET):
    """Extract EVERY embedded template image and build one labeled contact
    sheet, so the designer surveys the full media library instead of a
    ranked/logo-filtered subset. (classify_logo_media only looks at
    `image\\d+.png`; that filter once hid the template's premium white-studio
    `.jpg` renders.) Writes out/media_census/<name> + out/media_census.png and
    returns a per-file census list. media_reuse_ranked is a discovery hint,
    never a filter -- one-off content is often the best hero.
    """
    out_dir, sheet_path = Path(out_dir), Path(sheet_path)
    used_on = {}
    for slide, media in slide_media_map.items():
        for m in media:
            used_on.setdefault(m, []).append(slide.split("/")[-1])

    out_dir.mkdir(parents=True, exist_ok=True)
    census, tiles = [], []
    for n in sorted(x for x in names if _MEDIA_RE.match(x)):
        data = zip_read(z, n)
        if data is None:
            continue
        base = n.split("/")[-1]
        (out_dir / base).write_bytes(data)
        entry = {
            "media": n,
            "file": f"out/media_census/{base}",
            "ext": base.rsplit(".", 1)[-1].lower(),
            "n_slides_used": len(used_on.get(n, [])),
            "used_on_slides": sorted(used_on.get(n, [])),
            "size": None, "mode": None, "has_alpha": None,
        }
        try:
            with Image.open(io.BytesIO(data)) as im:
                entry["size"] = list(im.size)
                entry["mode"] = im.mode
                entry["has_alpha"] = (im.mode in ("RGBA", "LA")
                                      or "transparency" in im.info)
                # Downscale to the tile size BEFORE holding it: template media
                # can be enormous (15124x8538 here), and keeping full-res RGBA
                # copies of every image at once would blow memory.
                thumb = im.convert("RGBA")
                thumb.thumbnail((256, 256))
                tiles.append((base, entry, thumb))
        except Exception:
            pass
        census.append(entry)

    _write_media_contact_sheet(tiles, sheet_path)
    return census


def extract(template_path=DEFAULT_TEMPLATE, with_thumbnails=True, renderer=None):
    prs = Presentation(str(template_path))
    layouts = extract_layout_geometry(prs)
    margins = infer_margins(layouts)
    with zipfile.ZipFile(template_path) as z:
        names = z.namelist()
        themes = extract_themes(z, names)
        color_usage, font_usage, per_slide_fonts = rank_slide_usage(z, names)
        font_mix_flags = flag_font_mixing(per_slide_fonts, themes)
        logos = classify_logo_media(z, names)
        animation_exemplars = extract_animation_exemplars(z, names)
        slide_media_map = map_slides_to_media(z, names)
        media_reuse_ranked = rank_media_reuse(slide_media_map)
        slide_layout_map = map_slides_to_layouts(z, names, layouts)
        # Full media census (all formats, not the logo/reuse-ranked subset) so
        # the designer surveys every template image, not a filtered slice.
        media_census = dump_media_census(z, names, slide_media_map)

    style = {
        "template_file": template_path.name,
        "template_fingerprint": _file_hash(template_path),
        "slide_size_emu": {"width": prs.slide_width, "height": prs.slide_height},
        "themes": themes,
        "consistency_flags": (
            ([f"{len(themes)} distinct themes present across masters/notes: "
              f"{[t['name'] for t in themes]}"] if len(themes) > 1 else [])
            + [f"slide {f['slide']} mixes fonts from multiple themes "
               f"({', '.join(f['themes_mixed'])}): {f['fonts']}"
               for f in font_mix_flags]
        ),
        "explicit_colors_ranked": [
            {"hex": c, "count": n} for c, n in color_usage.most_common(20)
        ],
        "fonts_used_ranked": [
            {"typeface": f, "count": n} for f, n in font_usage.most_common(20)
        ],
        "layouts": layouts,
        "inferred_margins_emu": margins,
        "logo_candidates": logos,
        "animation_exemplars": animation_exemplars,
        "slide_layout_map": slide_layout_map,
        "slide_media_map": slide_media_map,
        "media_reuse_ranked": media_reuse_ranked,
        "media_census": media_census,
        "media_census_sheet": "out/media_census.png",
    }
    if with_thumbnails:
        style["thumbnails"] = render_thumbnails(template_path, renderer=renderer)
    return style


def main():
    template_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TEMPLATE
    style = extract(template_path)
    OUT.mkdir(exist_ok=True)
    out_path = OUT / "template_style.json"
    out_path.write_text(json.dumps(style, ensure_ascii=False, indent=2))
    print("wrote", out_path)


if __name__ == "__main__":
    sys.exit(main())
