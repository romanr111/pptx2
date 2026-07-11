#!/usr/bin/env python3
"""Template-native packaging: post-save surgery on a built .pptx.

Fixes the forensic findings F1/F2/F6: a deck built from python-pptx's
stock scaffold ships a stock "Office" theme and 11 unused stock layouts,
so PowerPoint's color/font pickers show Office defaults instead of the
event brand, and the package carries dead weight.

Two theme sources, decided upstream and frozen into the spec's
`packaging` object (the builder never picks colors — Facts/Decisions/
Execution still holds):

- kind "template": graft the theme part out of the organizer's real
  .pptx (the authoritative path). If that theme references embedded
  media (rare), fall back to patching only its color/font schemes in.
- kind "synthesized": fallback mode for reference-only events — the
  designer maps the reference palette/fonts to theme slots explicitly,
  and those get patched into the stock theme.

`strip_unused_layouts` removes every slide layout no slide references,
plus its rels and content-type override, and prunes the master's
sldLayoutIdLst to match. (Stock scaffold layouts reference no media, so
no media GC is needed here; a future template-derived scaffold would
need one.)
"""
import shutil
import zipfile
from pathlib import Path

from lxml import etree

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_R_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

CLR_SLOTS = ["dk1", "lt1", "dk2", "lt2",
             "accent1", "accent2", "accent3", "accent4", "accent5", "accent6"]


def _read_zip(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def _write_zip(path, entries):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, blob in entries.items():
            z.writestr(name, blob)


def _serialize(root):
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                          standalone=True)


def patch_theme_xml(theme_blob, colors=None, major_font=None,
                    minor_font=None, name=None):
    """Patch clrScheme/fontScheme (and theme name) inside a theme part."""
    root = etree.fromstring(theme_blob)
    if name:
        root.set("name", name)
    scheme = root.find(f".//{{{A_NS}}}clrScheme")
    if colors:
        if name:
            scheme.set("name", name)
        for slot, hexval in colors.items():
            el = scheme.find(f"{{{A_NS}}}{slot}")
            if el is None:
                continue
            for child in list(el):
                el.remove(child)
            srgb = etree.SubElement(el, f"{{{A_NS}}}srgbClr")
            srgb.set("val", hexval.upper())
    font_scheme = root.find(f".//{{{A_NS}}}fontScheme")
    if font_scheme is not None:
        if name:
            font_scheme.set("name", name)
        for tag, fam in ((f"{{{A_NS}}}majorFont", major_font),
                         (f"{{{A_NS}}}minorFont", minor_font)):
            if not fam:
                continue
            group = font_scheme.find(tag)
            latin = group.find(f"{{{A_NS}}}latin")
            latin.set("typeface", fam)
    return _serialize(root)


def extract_template_theme(template_path, theme_index=0):
    """Return the raw XML of themeN.xml from the organizer's template."""
    with zipfile.ZipFile(template_path) as z:
        names = sorted(n for n in z.namelist()
                       if n.startswith("ppt/theme/theme") and n.endswith(".xml"))
        if theme_index >= len(names):
            raise ValueError(f"template has {len(names)} theme(s), "
                             f"index {theme_index} out of range")
        return z.read(names[theme_index])


def _strip_unused_layouts(entries):
    """Remove layouts no slide uses; fix master rels/sldLayoutIdLst/CTs."""
    used_layouts = set()
    for name, blob in entries.items():
        if name.startswith("ppt/slides/_rels/"):
            rels = etree.fromstring(blob)
            for rel in rels.iter(f"{{{PKG_R_NS}}}Relationship"):
                if rel.get("Type").endswith("/slideLayout"):
                    target = rel.get("Target").replace("../", "ppt/")
                    used_layouts.add(target)

    all_layouts = {n for n in entries
                   if n.startswith("ppt/slideLayouts/slideLayout")
                   and n.endswith(".xml")}
    dead = all_layouts - used_layouts
    if not dead:
        return entries

    for name in dead:
        entries.pop(name, None)
        base = name.rsplit("/", 1)[-1]
        entries.pop(f"ppt/slideLayouts/_rels/{base}.rels", None)

    # master rels + sldLayoutIdLst
    for rels_name in [n for n in entries
                      if n.startswith("ppt/slideMasters/_rels/")]:
        rels = etree.fromstring(entries[rels_name])
        removed_ids = set()
        for rel in list(rels):
            if rel.get("Type").endswith("/slideLayout"):
                target = rel.get("Target").replace("../", "ppt/")
                if target in dead:
                    removed_ids.add(rel.get("Id"))
                    rels.remove(rel)
        entries[rels_name] = _serialize(rels)

        master_name = rels_name.replace("/_rels", "").removesuffix(".rels")
        master = etree.fromstring(entries[master_name])
        id_lst = master.find(f"{{{P_NS}}}sldLayoutIdLst")
        if id_lst is not None:
            for lid in list(id_lst):
                if lid.get(f"{{{R_NS}}}id") in removed_ids:
                    id_lst.remove(lid)
        entries[master_name] = _serialize(master)

    cts = etree.fromstring(entries["[Content_Types].xml"])
    for override in list(cts):
        pn = override.get("PartName")
        if pn and pn.lstrip("/") in dead:
            cts.remove(override)
    entries["[Content_Types].xml"] = _serialize(cts)
    return entries


FONT_REL_TYPE = ("http://schemas.openxmlformats.org/officeDocument/2006/"
                 "relationships/font")
FONT_SLOTS = [("regular", "regular"), ("bold", "bold"),
              ("italic", "italic"), ("bold_italic", "boldItalic")]
# CT_Presentation child order up to embeddedFontLst — it must be inserted
# after the last of these that is present
_PRES_PRECEDING = ["sldMasterIdLst", "notesMasterIdLst", "handoutMasterIdLst",
                   "sldIdLst", "sldSz", "notesSz", "smartTags"]


def _embed_fonts(entries, embed_fonts, project_root):
    """PPTX-native font embedding: raw TTF bytes as ppt/fonts/*.fntdata
    parts (PowerPoint's pptx embedding is unobfuscated, unlike Word's
    .odttf), wired through p:embeddedFontLst + embedTrueTypeFonts."""
    cts = etree.fromstring(entries["[Content_Types].xml"])
    if not any(d.get("Extension") == "fntdata"
               for d in cts.iter(f"{{{CT_NS}}}Default")):
        default = etree.SubElement(cts, f"{{{CT_NS}}}Default")
        default.set("Extension", "fntdata")
        default.set("ContentType", "application/x-fontdata")
    entries["[Content_Types].xml"] = _serialize(cts)

    rels = etree.fromstring(entries["ppt/_rels/presentation.xml.rels"])
    next_rid = 1 + max((int(r.get("Id").removeprefix("rId"))
                        for r in rels.iter(f"{{{PKG_R_NS}}}Relationship")
                        if r.get("Id", "").removeprefix("rId").isdigit()),
                       default=0)

    pres = etree.fromstring(entries["ppt/presentation.xml"])
    pres.set("embedTrueTypeFonts", "1")
    lst = etree.Element(f"{{{P_NS}}}embeddedFontLst")
    insert_at = 0
    for i, child in enumerate(pres):
        if etree.QName(child).localname in _PRES_PRECEDING:
            insert_at = i + 1
    pres.insert(insert_at, lst)

    n = 0
    for entry in embed_fonts:
        ef = etree.SubElement(lst, f"{{{P_NS}}}embeddedFont")
        font_el = etree.SubElement(ef, f"{{{P_NS}}}font")
        font_el.set("typeface", entry["family"])
        for key, tag in FONT_SLOTS:
            path = entry.get(key)
            if not path:
                continue
            n += 1
            part_name = f"ppt/fonts/font{n}.fntdata"
            entries[part_name] = (Path(project_root) / path).read_bytes()
            rid = f"rId{next_rid}"
            next_rid += 1
            rel = etree.SubElement(rels, f"{{{PKG_R_NS}}}Relationship")
            rel.set("Id", rid)
            rel.set("Type", FONT_REL_TYPE)
            rel.set("Target", f"fonts/font{n}.fntdata")
            slot = etree.SubElement(ef, f"{{{P_NS}}}{tag}")
            slot.set(f"{{{R_NS}}}id", rid)

    entries["ppt/presentation.xml"] = _serialize(pres)
    entries["ppt/_rels/presentation.xml.rels"] = _serialize(rels)
    return entries


def apply_packaging(pptx_path, packaging, project_root):
    """Rewrite a just-built .pptx in place per the spec's packaging block."""
    pptx_path = Path(pptx_path)
    entries = _read_zip(pptx_path)

    src = packaging.get("theme_source")
    if src:
        if src["kind"] == "template":
            theme_blob = extract_template_theme(
                Path(project_root) / src["path"], src.get("theme_index", 0))
            if b"r:embed" in theme_blob:
                # theme references embedded media we don't carry over;
                # graft only its color/font schemes into the stock theme
                donor = etree.fromstring(theme_blob)
                colors = {}
                scheme = donor.find(f".//{{{A_NS}}}clrScheme")
                for slot in CLR_SLOTS:
                    el = scheme.find(f"{{{A_NS}}}{slot}")
                    child = el[0] if el is not None and len(el) else None
                    if child is not None:
                        val = child.get("val") or child.get("lastClr")
                        if val:
                            colors[slot] = val
                fs = donor.find(f".//{{{A_NS}}}fontScheme")
                major = fs.find(f"{{{A_NS}}}majorFont/{{{A_NS}}}latin").get("typeface")
                minor = fs.find(f"{{{A_NS}}}minorFont/{{{A_NS}}}latin").get("typeface")
                entries["ppt/theme/theme1.xml"] = patch_theme_xml(
                    entries["ppt/theme/theme1.xml"], colors=colors,
                    major_font=major, minor_font=minor,
                    name=donor.get("name"))
            else:
                entries["ppt/theme/theme1.xml"] = theme_blob
        elif src["kind"] == "synthesized":
            entries["ppt/theme/theme1.xml"] = patch_theme_xml(
                entries["ppt/theme/theme1.xml"],
                colors=src["colors"],
                major_font=src.get("major_font"),
                minor_font=src.get("minor_font"),
                name=src.get("name", "Synthesized"))
        else:
            raise ValueError(f"unknown theme_source.kind: {src['kind']}")

    if packaging.get("strip_unused_layouts", True):
        entries = _strip_unused_layouts(entries)

    if packaging.get("embed_fonts"):
        entries = _embed_fonts(entries, packaging["embed_fonts"], project_root)

    tmp = pptx_path.with_suffix(".pptx.tmp")
    _write_zip(tmp, entries)
    shutil.move(tmp, pptx_path)
