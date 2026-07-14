"""QA-gate checks added by the p0-fixes branch: the visual_review artifact,
the (deck-aware) font-embedding decision, placed-image provenance,
inventory coverage, deck-token-aware color conformance, and lint_deck's
token-override justifications.

These are contract tests in the spirit of test_schema_builder_coverage: a
check that exists but is never exercised can silently rot.
"""
import json

import lint_deck
import lint_render


def _spec(elements=None, meta=None, packaging=None):
    spec = {
        "spec_version": 1,
        "slide": {"width_emu": 12192000, "height_emu": 6858000},
        "elements": elements if elements is not None else [],
    }
    if meta is not None:
        spec["meta"] = meta
    if packaging is not None:
        spec["packaging"] = packaging
    return spec


def _textbox(font="Geologica", color="112233"):
    return {"id": "t", "type": "textbox",
            "box": {"x": 0, "y": 0, "cx": 1000000, "cy": 500000},
            "paragraphs": [{"lines": [{"text": "x", "font": font,
                                       "size_pt": 12, "color": color}]}]}


def _by_check(findings):
    return {f["check"]: f["severity"] for f in findings}


# --------------------------------------------------------- visual_review --

def test_visual_review_missing_is_a_warn():
    findings = []
    lint_render.check_visual_review(_spec(), findings)
    assert _by_check(findings) == {"visual_review": "warn"}


def test_visual_review_pass_is_clean():
    findings = []
    meta = {"visual_review": {"iteration": 1, "verdict": "pass", "findings": []}}
    lint_render.check_visual_review(_spec(meta=meta), findings)
    assert findings == []


def test_visual_review_fail_and_iteration_cap_are_errors():
    findings = []
    meta = {"visual_review": {"iteration": 4, "verdict": "fail",
                              "findings": [{"element_id": "t", "issue": "clips"}]}}
    lint_render.check_visual_review(_spec(meta=meta), findings)
    sev = _by_check(findings)
    assert sev["visual_review_iterations"] == "error"
    assert sev["visual_review_failed"] == "error"


# --------------------------------------------- font_embedding_decision --

LOOKUP = {"Geologica": "assets/fonts/geologica.ttf"}


def test_font_embedding_unembedded_non_system_font_warns():
    findings = []
    lint_render.check_font_embedding_decision(
        _spec(elements=[_textbox()]), LOOKUP, findings)
    assert _by_check(findings) == {"font_embedding_decision": "warn"}


def test_font_embedding_spec_level_embed_silences():
    findings = []
    spec = _spec(elements=[_textbox()],
                 packaging={"embed_fonts": [{"family": "Geologica"}]})
    lint_render.check_font_embedding_decision(spec, LOOKUP, findings)
    assert findings == []


def test_font_embedding_deck_level_embed_silences():
    """embed_fonts lives at DECK level for deck members — the deck's
    packaging must count, or every member slide warns forever."""
    findings = []
    deck = {"packaging": {"embed_fonts": [{"family": "Geologica"}]}}
    lint_render.check_font_embedding_decision(
        _spec(elements=[_textbox()]), LOOKUP, findings, deck=deck)
    assert findings == []


def test_font_embedding_deck_opt_out_silences():
    findings = []
    deck = {"meta": {"font_embedding_opt_out": "venue machines have the fonts"}}
    lint_render.check_font_embedding_decision(
        _spec(elements=[_textbox()]), LOOKUP, findings, deck=deck)
    assert findings == []


def test_font_embedding_system_font_is_silent():
    findings = []
    lint_render.check_font_embedding_decision(
        _spec(elements=[_textbox(font="Arial")]), LOOKUP, findings)
    assert findings == []


# ---------------------------------------------- placed_image_provenance --

def _image(asset, role=None):
    el = {"id": "img", "type": "image", "asset": asset,
          "box": {"x": 0, "y": 0, "cx": 1000000, "cy": 1000000}}
    if role:
        el["role"] = role
    return el


def test_placed_image_without_sidecar_is_an_error(tmp_path):
    from PIL import Image
    target = tmp_path / "assets" / "photos" / "pic.png"
    target.parent.mkdir(parents=True)
    Image.new("RGB", (10, 10)).save(target)
    findings = []
    lint_render.check_placed_image_provenance(
        _spec(elements=[_image("assets/photos/pic.png")]), findings,
        project_root=tmp_path)
    assert _by_check(findings) == {"placed_image_provenance": "error"}


def test_placed_image_with_sidecar_is_clean(tmp_path):
    from PIL import Image
    target = tmp_path / "assets" / "photos" / "pic.png"
    target.parent.mkdir(parents=True)
    Image.new("RGB", (10, 10)).save(target)
    (tmp_path / "assets" / "photos" / "pic.png.json").write_text(json.dumps(
        {"source_type": "local", "license": "client-provided",
         "selected_rationale": "speaker's own photo"}))
    findings = []
    lint_render.check_placed_image_provenance(
        _spec(elements=[_image("assets/photos/pic.png")]), findings,
        project_root=tmp_path)
    assert findings == []


def test_template_extracted_and_pipeline_assets_are_exempt(tmp_path):
    findings = []
    spec = _spec(elements=[
        _image("assets/designer_extracted/molecule.jpg"),
        _image("some/pic.png", role="template-molecular-visual"),
        _image("logo.png", role="event-logo"),
        _image("output/work/logo_black.png", role="logo"),  # spike fixture
    ])
    lint_render.check_placed_image_provenance(spec, findings,
                                              project_root=tmp_path)
    assert findings == []


def test_role_substring_does_not_exempt(tmp_path):
    """'untemplated' must not slip through a substring match."""
    from PIL import Image
    target = tmp_path / "x.png"
    Image.new("RGB", (10, 10)).save(target)
    findings = []
    lint_render.check_placed_image_provenance(
        _spec(elements=[_image("x.png", role="untemplated")]), findings,
        project_root=tmp_path)
    assert _by_check(findings) == {"placed_image_provenance": "error"}


def test_placed_image_invalid_json_sidecar_is_an_error(tmp_path):
    """A broken .json is truthy internally ({'_invalid_json': True}) — it must
    not silence the gate."""
    from PIL import Image
    target = tmp_path / "assets" / "photos" / "pic.png"
    target.parent.mkdir(parents=True)
    Image.new("RGB", (10, 10)).save(target)
    (tmp_path / "assets" / "photos" / "pic.png.json").write_text("{not valid json")
    findings = []
    lint_render.check_placed_image_provenance(
        _spec(elements=[_image("assets/photos/pic.png")]), findings,
        project_root=tmp_path)
    assert _by_check(findings) == {"placed_image_provenance": "error"}


def test_placed_image_partial_sidecar_is_an_error(tmp_path):
    """A sidecar that exists but omits the promised source/license/rationale
    fields must not pass just by being present."""
    from PIL import Image
    target = tmp_path / "assets" / "photos" / "pic.png"
    target.parent.mkdir(parents=True)
    Image.new("RGB", (10, 10)).save(target)
    (tmp_path / "assets" / "photos" / "pic.png.json").write_text(
        json.dumps({"note": "looks fine"}))
    findings = []
    lint_render.check_placed_image_provenance(
        _spec(elements=[_image("assets/photos/pic.png")]), findings,
        project_root=tmp_path)
    assert _by_check(findings) == {"placed_image_provenance": "error"}


# -------------------------------------------------------- logo_clearance --

def _logo_spec(tmp_path, hero_fill, hero_size=(60, 60)):
    """A hero image (filled with `hero_fill`) plus a logo overlapping it."""
    from PIL import Image
    import numpy as np
    hero = tmp_path / "hero.png"
    if hero_fill == "noise":
        Image.fromarray((np.random.default_rng(0).random((*hero_size, 3)) * 255)
                        .astype("uint8")).save(hero)
    else:
        Image.new("RGB", hero_size, hero_fill).save(hero)
    Image.new("RGB", (10, 10)).save(tmp_path / "logo.png")
    return _spec(elements=[
        {"id": "hero", "type": "image", "asset": "hero.png", "z": 1,
         "box": {"x": 8000000, "y": 0, "cx": 4000000, "cy": 6858000}},
        {"id": "brand", "type": "image", "role": "event-logo", "asset": "logo.png",
         "z": 5, "box": {"x": 9000000, "y": 200000, "cx": 900000, "cy": 1100000}},
    ])


def test_logo_over_busy_imagery_warns(tmp_path):
    """The exact miss that shipped once: a brand mark placed on top of a
    glossy render instead of clean background."""
    findings = []
    lint_render.check_logo_clearance(
        _logo_spec(tmp_path, "noise"), findings, project_root=tmp_path)
    assert _by_check(findings) == {"logo_clearance": "warn"}


def test_logo_over_clean_panel_is_silent(tmp_path):
    """A logo over a uniform dark panel (a black molecule gap) is fine and
    must not warn — that is the 'some overlaps are OK' case."""
    findings = []
    lint_render.check_logo_clearance(
        _logo_spec(tmp_path, (0, 0, 0)), findings, project_root=tmp_path)
    assert findings == []


def test_logo_with_no_overlap_is_silent(tmp_path):
    from PIL import Image
    Image.new("RGB", (60, 60), (0, 0, 0)).save(tmp_path / "hero.png")
    Image.new("RGB", (10, 10)).save(tmp_path / "logo.png")
    spec = _spec(elements=[
        {"id": "hero", "type": "image", "asset": "hero.png", "z": 1,
         "box": {"x": 8000000, "y": 3000000, "cx": 4000000, "cy": 3858000}},
        {"id": "brand", "type": "image", "role": "event-logo", "asset": "logo.png",
         "z": 5, "box": {"x": 900000, "y": 200000, "cx": 900000, "cy": 1100000}},
    ])
    findings = []
    lint_render.check_logo_clearance(spec, findings, project_root=tmp_path)
    assert findings == []


# ----------------------------------------------------- embed_font_license --

def test_deck_level_embedded_font_without_license_warns(tmp_path):
    """Deck packaging supersedes per-slide packaging at build time, so a
    deck-level embedded font with no license beside it (e.g. HeliosCond) must
    still trip the redistribution warning."""
    font = tmp_path / "assets" / "fonts" / "helioscond" / "HeliosCond.ttf"
    font.parent.mkdir(parents=True)
    font.write_bytes(b"\x00\x01\x00\x00")
    deck = {"packaging": {"embed_fonts": [
        {"family": "HeliosCond",
         "regular": "assets/fonts/helioscond/HeliosCond.ttf"}]}}
    findings = []
    lint_render.check_embed_font_licenses(
        _spec(), findings, project_root=tmp_path, deck=deck)
    assert _by_check(findings) == {"embed_font_license": "warn"}


def test_deck_level_embedded_font_with_license_is_clean(tmp_path):
    font = tmp_path / "assets" / "fonts" / "geologica" / "Geologica.ttf"
    font.parent.mkdir(parents=True)
    font.write_bytes(b"\x00\x01\x00\x00")
    (font.parent / "OFL.txt").write_text("SIL Open Font License")
    deck = {"packaging": {"embed_fonts": [
        {"family": "Geologica",
         "regular": "assets/fonts/geologica/Geologica.ttf"}]}}
    findings = []
    lint_render.check_embed_font_licenses(
        _spec(), findings, project_root=tmp_path, deck=deck)
    assert findings == []


# --------------------------------------------------- asset inventory --

def test_uninventoried_placed_asset_warns():
    assets_json = {"images": [{"file": "assets/images/known.png"}]}
    findings = []
    spec = _spec(elements=[_image("assets/images/known.png"),
                           {**_image("assets/other/unknown.png"), "id": "img2"}])
    lint_render.check_asset_inventory(spec, assets_json, findings)
    assert [f["element_id"] for f in findings] == ["img2"]
    assert _by_check(findings) == {"asset_not_in_inventory": "warn"}


# ------------------------------------------- deck-aware color conformance --

def test_color_conformance_uses_deck_palette_when_given():
    deck = {"tokens": {"palette_roles": {"accent": "5E4AE3"}}}
    findings = []
    lint_render.check_color_conformance(
        _spec(elements=[_textbox(color="5E4AE3")]), {}, {}, findings, deck=deck)
    assert findings == []

    findings = []
    lint_render.check_color_conformance(
        _spec(elements=[_textbox(color="FF0000")]), {}, {}, findings, deck=deck)
    assert len(findings) == 1
    assert "deck palette_roles" in findings[0]["message"]


def test_color_conformance_falls_back_to_template_theme():
    assets_json = {"font_roles": {"theme_used": "T"}}
    template_style = {"themes": [{"name": "T", "colors": {"accent1": "FF0000"}}],
                      "explicit_colors_ranked": []}
    findings = []
    lint_render.check_color_conformance(
        _spec(elements=[_textbox(color="FF0000")]), assets_json,
        template_style, findings)
    assert findings == []


# ------------------------------------------------ lint_deck token_override --

def test_raised_budgets_without_justification_warn():
    deck = {"slide": {"width_emu": 12192000, "height_emu": 6858000},
            "tokens": {"max_font_families": 3, "max_elements_per_slide": 24}}
    findings = []
    lint_deck.check_font_budget(deck, [], [], findings)
    lint_deck.check_type_scale(deck, [], [], findings)
    lint_deck.check_density(deck, [], [], findings)
    overrides = [f for f in findings if f["check"] == "token_override"]
    assert len(overrides) == 3  # font budget, missing type_scale, density
    assert all(f["severity"] == "warn" for f in overrides)


def test_justified_budgets_do_not_warn():
    deck = {"slide": {"width_emu": 12192000, "height_emu": 6858000},
            "tokens": {"max_font_families": 3, "max_elements_per_slide": 24},
            "meta": {"token_overrides": [
                {"key": "max_font_families", "reason": "display+text+mono"},
                {"key": "max_elements_per_slide", "reason": "diagnostic cards"},
                {"key": "type_scale", "reason": "single-slide sizes vary by design"},
            ]}}
    findings = []
    lint_deck.check_font_budget(deck, [], [], findings)
    lint_deck.check_type_scale(deck, [], [], findings)
    lint_deck.check_density(deck, [], [], findings)
    assert [f for f in findings if f["check"] == "token_override"] == []
