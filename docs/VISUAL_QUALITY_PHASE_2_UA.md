# Етап 2 — template fidelity та стиль зображень: робоча інструкція

Детальна інструкція виконання «Етапу 2» з
`docs/VISUAL_QUALITY_IMPROVEMENT_PLAN_UA.md`. Реалізує два пункти
майстер-плану: P0 №2 «Онбординг шаблону конференції як конвеєр» і P0 №3
«Єдиний стиль анатомічних зображень». Усі твердження про поточний код
звірені з гілкою `p0-fixes` (commit `f430ead`) — станом, який план вважає
змердженим у `main` перед початком робіт.

## Зв'язок із планом

- **P0 №2** → Частина A цього документа (кроки 1–6): онбординг шаблону як
  одна відтворювана процедура + freshness gate каталогу в `deck_qa`.
- **P0 №3** → Частина B (кроки 7–12): `image_brief.category`, успадкування
  стилю зі styleguide profile, deck-level перевірка стильової узгодженості,
  `meta.sequence_review`.
- **Спільні артефакти з іншими етапами:**
  - `meta.sequence_review` ділиться з Етапом 3 (P1 №9). **Цей документ
    володіє визначенням контракту**; Етап 3 лише розширює формат окремого
    finding (severity, evidence, confidence, auto_fixable) — тому елементи
    `findings[]` тут свідомо залишаються відкритими для додаткових полів.
  - `meta.outline` з полем `layout_ref` (посилання слайда на layout/component
    з каталогу) належить Етапу 4 (P1 №5). Тут ми його **не специфікуємо** —
    лише фіксуємо, що `layouts_observed[].role` у каталозі стає майбутнім
    ключем для `layout_ref`, і посилаємося на нього в критеріях готовності.
  - Публічний синтетичний «шаблон конференції» (P1 №8, Етап 4) дасть
    онбордингу публічний e2e-тест; до того тести Частини A використовують
    мінімальний `.pptx`, згенерований python-pptx у `tmp_path`.

## Передумови

- Гілка `p0-fixes` змерджена; `tests/` зелені (72 тести в
  `test_qa_gates.py` + решта).
- Наявні facts-артефакти: `out/assets.json`, `out/template_style.json`,
  `out/styleguide_profile.json`, заповнений вручну
  `out/template_visual_catalog.json`, thumbnails у
  `out/thumbnails/template/`.
- Зовнішні інструменти на PATH: `soffice`, `pdftoppm`, `textutil`
  (їх уже перевіряє `check_external_tools` у
  `.claude/skills/pptx-deck/scripts/deck_qa.py`).
- Файли, яких торкається етап:
  - `.claude/skills/pptx-deck/scripts/common.py`
  - `.claude/skills/pptx-deck/scripts/template_style.py`
  - `.claude/skills/pptx-deck/scripts/onboard_template.py` (новий)
  - `.claude/skills/pptx-deck/scripts/deck_qa.py`
  - `.claude/skills/pptx-deck/scripts/asset_resolver.py`
  - `.claude/skills/pptx-deck/scripts/lint_render.py`
  - `.claude/skills/pptx-deck/scripts/lint_deck.py`
  - `specs/spec.schema.json`, `specs/deck.schema.json`
  - `tests/` (новий `test_template_fidelity.py` + доповнення)
  - `out/template_style.json`, `out/template_visual_catalog.json`
    (міграція, крок 5)
- Після змін у `.claude/skills` не забути `sync_agents.py` (дерева
  `.claude/skills` і `.agents/skills` мають лишатися синхронними).

**Розбіжність плану з кодом, зафіксована при підготовці:** майстер-план у
«Залежності та ризики» пише, що активний шаблон — «`template.pptx` у
корені». Насправді `template_style.py` визначає
`DEFAULT_TEMPLATE = PROJECT_ROOT / "assets" / "template.pptx"`, і поточний
каталог записує `"template_file": "assets/template.pptx"`. Далі скрізь
дотримуємося коду: **канонічний шлях активного шаблону —
`assets/template.pptx`**.

## Кроки

### Частина A — онбординг шаблону конференції як конвеєр (P0 №2)

#### Крок 1. `file_sha256` у `common.py`

У `.claude/skills/pptx-deck/scripts/common.py` додати спільний хелпер
хешування файлів. Прецедент уже є двічі: `render.py` має приватний
`_file_hash` (streaming sha256, обрізаний до 16 hex), а
`styleguide_profile.py` пише `source_hash` (sha256 нормалізованого тексту,
теж `[:16]`). Для шаблону дзеркалимо сам підхід «джерело + хеш джерела»,
але, оскільки поле називається `template_sha256`, зберігаємо **повний**
hexdigest байтів файлу:

```python
# common.py (орієнтовно)
import hashlib

def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
```

`render.py` не чіпати — його `_file_hash` живе в кеші рендера і буде
переглянутий Етапом 3 разом із manifest (P0 №4).

#### Крок 2. `template_sha256` у `template_style.py`

Зараз `extract()` у `.claude/skills/pptx-deck/scripts/template_style.py`
записує лише `"template_file": template_path.name` — голе ім'я файлу без
шляху і без хешу (перевірено: у `out/template_style.json` лежить
`"template_file": "template.pptx"`; програмних споживачів цього поля в
скриптах немає, лише документація). Розширити словник `style` у
`extract()`:

```python
# template_style.py, extract() (орієнтовно)
style = {
    "template_file": template_path.name,          # як було, для читабельності
    "template_path": str(template_path.resolve()
                         .relative_to(PROJECT_ROOT)),  # "assets/template.pptx"
    "template_sha256": file_sha256(template_path),
    ...
}
```

`inventory.py` викликає `template_style.extract()` без шляху (використовує
`DEFAULT_TEMPLATE`), тож нове поле з'являється в `out/template_style.json`
автоматично при будь-якому прогоні inventory.

#### Крок 3. Новий скрипт `onboard_template.py`

Створити `.claude/skills/pptx-deck/scripts/onboard_template.py` — одну
команду «новий шаблон → готовий facts layer + скелет каталогу»:

```
onboard_template.py <template.pptx> [--no-thumbnails] [--force] [--stamp]
```

**Звідки береться шлях шаблону і single-template assumption.** Пайплайн
працює з рівно одним активним шаблоном за фіксованим шляхом
`assets/template.pptx` (це `DEFAULT_TEMPLATE` у `template_style.py`;
`inventory.py` взагалі не приймає шлях шаблону — тільки прапорець
`--no-thumbnails`). Тому:

1. Якщо аргумент `<template.pptx>` вказує не на `assets/template.pptx`,
   скрипт **копіює** файл на канонічне місце; попередній
   `assets/template.pptx`, якщо існує і відрізняється, зберігається як
   `assets/template.pptx.bak` (розширення `.bak` безпечне —
   `inventory_images` сканує лише `.png/.jpg/.jpeg`).
2. Кілька одночасних шаблонів — поза скоупом (як і в майстер-плані: тоді
   знадобиться `out/` на кожен шаблон).

**Ланцюжок кроків скрипта** (subprocess-виклики в стилі
`deck_qa.run_build_deck`):

1. Скопіювати шаблон на канонічний шлях (див. вище).
2. Запустити `inventory.py` (з passthrough `--no-thumbnails`) — це пише
   `out/template_style.json` (тепер із `template_sha256`, крок 2),
   `out/assets.json` і `out/thumbnails/template/slide-*.png`.
3. Згенерувати **скелет** `out/template_visual_catalog.json` функцією
   `build_catalog_skeleton(style)` (чиста функція від розпарсеного
   `template_style.json` — тестується без файлової системи).

**Скелет каталогу.** Зберігає рівно той набір ключів, який спостерігається
в поточному `out/template_visual_catalog.json` (`template_file`, `event`,
`n_slides_total`, `note`, `palette_observed`, `color_modes`,
`layouts_observed`, `recurring_assets`, `conformance_notes`), плюс новий
`template_sha256`. Що можна вивести з фактів — заповнюється одразу; решта —
порожні agent-fillable поля, які заповнює людина/агент, дивлячись на
thumbnails (це прямо відповідає `note` поточного каталогу: «Human/LLM-written
from out/thumbnails/template/slide-*.png…»):

```json
{
  "template_file": "assets/template.pptx",
  "template_sha256": "<з out/template_style.json>",
  "event": "",
  "n_slides_total": 31,
  "note": "SKELETON: заповнюється людиною/агентом з out/thumbnails/template/slide-*.png. Описує, що реально зробив дизайнер шаблону, — числові факти в template_style.json цього не передають.",
  "palette_observed": {
    "color_1": "5B49D3",
    "color_2": "131313",
    "note": "seed з explicit_colors_ranked (топ-6); перейменувати ключі на семантичні ролі (brand_*, near_black, ...) і описати вживання"
  },
  "color_modes": [],
  "layouts_observed": [
    {"role": "title",           "example_slides": [], "color_mode": "", "description": ""},
    {"role": "section_divider", "example_slides": [], "color_mode": "", "description": ""},
    {"role": "content",         "example_slides": [], "color_mode": "", "description": ""},
    {"role": "data",            "example_slides": [], "color_mode": "", "description": ""},
    {"role": "closing",         "example_slides": [], "color_mode": "", "description": ""}
  ],
  "recurring_assets": [],
  "conformance_notes": []
}
```

(Орієнтовно.) Деталі виведення:

- `n_slides_total` = `len(style["slide_layout_map"])` (кількість реальних
  слайд-частин шаблону, не layout-визначень — у `template_style.json` поле
  `layouts` містить саме визначення: у поточному шаблоні їх 27 при 31
  записі в `slide_layout_map`). NB: рукописний каталог наразі записує
  `n_slides_total: 30` — людський підрахунок розходиться з фактами на
  одиницю; скелет цю розбіжність усуває, бо бере число з
  `slide_layout_map`.
- `palette_observed` — топ-6 hex з `style["explicit_colors_ranked"]` під
  плейсхолдерними ключами `color_1..color_6`; агент перейменовує на
  семантичні ролі й додає власний `note`.
- `layouts_observed` — обов'язкові exemplar-ролі `title`,
  `section_divider`, `content`, `data`, `closing` (порожні `example_slides`,
  `color_mode`, `description`); агент заповнює їх і додає додаткові ролі за
  потреби (у поточному каталозі їх сім). Це і є «representative layouts» та
  «приклади section/content/data/closing слайдів» з майстер-плану.
- «Recurring components» (маркери, callout-бокси) живуть усередині
  `recurring_assets` — так влаштований поточний каталог (порівняй записи
  «violet diamond bullet marker», «gold rounded callout box»), нового ключа
  не заводимо.

**Захист від перезапису.** Каталог — рукописний артефакт; скелет не має
права мовчки його стерти:

- каталог існує і його `template_sha256` збігається з новим — нічого не
  робити (ідемпотентність);
- каталог існує, але хеш відсутній/інший — без `--force` відмовитися з
  підказкою; з `--force` зберегти старий як
  `out/template_visual_catalog.<старий hash або timestamp>.json` і записати
  скелет;
- `--stamp` — окремий режим для міграції (крок 5): **тільки** дописати
  актуальний `template_sha256` у наявний заповнений каталог, не чіпаючи
  решту полів.

Наприкінці скрипт друкує наступний крок оператору: «заповніть agent-fillable
поля каталогу за out/thumbnails/template/slide-*.png».

#### Крок 4. Freshness gate у `deck_qa.py`

Зараз `out/template_visual_catalog.json` ніде не перевіряється — ні на
наявність, ні на відповідність шаблону (перевірено: жоден скрипт його не
читає, лише SKILL.md). Додати в
`.claude/skills/pptx-deck/scripts/deck_qa.py`:

```python
# deck_qa.py (орієнтовно)
def check_template_freshness(project_root=PROJECT_ROOT):
    """Каталог і facts layer мають описувати САМЕ той шаблон, що лежить
    на диску. Повертає список текстів помилок (порожній = свіжо)."""
    issues = []
    catalog = _load(project_root / "out" / "template_visual_catalog.json")
    if catalog is None:
        return ["out/template_visual_catalog.json відсутній — запустіть "
                "onboard_template.py і заповніть скелет"]
    template = project_root / catalog.get("template_file",
                                          "assets/template.pptx")
    if not template.is_file():
        return [f"шаблон {template} не знайдено"]
    actual = file_sha256(template)
    if not catalog.get("template_sha256"):
        issues.append("каталог без template_sha256 — проженіть "
                      "onboard_template.py --stamp")
    elif catalog["template_sha256"] != actual:
        issues.append("template_visual_catalog.json описує інший шаблон "
                      "(hash mismatch) — переонбордьте шаблон")
    style = _load(project_root / "out" / "template_style.json") or {}
    if style.get("template_sha256") != actual:
        issues.append("out/template_style.json застарів відносно шаблону — "
                      "перезапустіть inventory.py")
    return issues
```

**Точне місце в `main()`.** Поточна послідовність кроків у
`deck_qa.main()`: 0 — `check_external_tools`; 1 — `run_build_deck`; 2 —
per-slide `build_deck.py`; 3 — `run_lint_render` на кожен слайд; 4 —
`run_lint_deck`; 5 — `render_all`; 6 — запис консолідованого звіту.
Freshness gate вставляється **між кроками 0 і 1** (facts layer має бути
актуальним до того, як будь-що збудовано чи злінчено):

```python
# 0b. Template freshness gate
freshness_issues = check_template_freshness()
report["template_freshness"] = {"issues": freshness_issues}
if freshness_issues:
    report["ok"] = False
    report["total_errors"] += len(freshness_issues)
```

Семантика — як у tool checks: `ok=False` + інкремент `total_errors`,
виконання **продовжується** (звіт накопичує все, exit 1 наприкінці — це
поведінка «error» з майстер-плану). Блок `template_freshness` додати і у
фінальний друкований summary-JSON поруч із `tool_issues`.

#### Крок 5. Міграція поточного проєкту

Разом зі змінами коду, в одному PR:

1. Перезапустити `inventory.py` — `out/template_style.json` отримує
   `template_path`/`template_sha256`.
2. `onboard_template.py assets/template.pptx --stamp` — дописати
   `template_sha256` у наявний **заповнений** каталог SIA MED (скелет не
   генерується, рукописний вміст недоторканий).
3. Прогнати `deck_qa.py specs/sia_med/sia_med.deck.json` — gate має
   лишитися зеленим (0 errors). Без цього кроку freshness gate зробить
   червоним будь-який checkout — саме тому міграція не відокремлюється від
   коду.

#### Крок 6. Прив'язка слайдів до каталогу (cross-phase)

Критерій майстер-плану «кожен слайд посилається на template
layout/component або містить пояснення свідомого відхилення» виконується
через `meta.outline` з полем `layout_ref` — це контракт **Етапу 4**
(P1 №5), тут його не специфікуємо. У цьому етапі фіксуємо лише передумову:
`layouts_observed[].role` у каталозі — стабільний ключ, на який
посилатиметься `layout_ref`. Зауваження до стану коду: продакшн-дека
`specs/sia_med/sia_med.deck.json` **уже** містить `meta.outline` з
вільнотекстовим `layout_reference` (напр. «template slide 24 (light
content...)») та `meta.unplaced_material` — Етап 4 формалізує це у ключі
каталогу, а не вводить з нуля (майстер-план у P1 №5 описує стан «outline
відсутній», що застаріло відносно `p0-fixes`).

### Частина B — єдиний стиль анатомічних зображень (P0 №3)

#### Крок 7. Поле `image_brief.category` у контракті briefs

У `specs/spec.schema.json`, `properties.image_briefs.items.properties`
(об'єкт має `additionalProperties: false`, тож без зміни схеми поле не
пройде валідацію), додати:

```json
"category": {
  "enum": ["anatomical", "clinical_photo", "chart", "decor"],
  "description": "Вісь ВІЗУАЛЬНОГО стилю для перевірки узгодженості: порівнюємо лише порівнюване (анатомічні ілюстрації між собою, а не з фото чи декором). Ортогональна до medical_class, який гейтить review."
}
```

Поле в схемі **необов'язкове** (додавання до `required` зламало б наявні
специфікації); обов'язковість забезпечують лінти та резолвер (кроки 8–9).
Співвідношення з наявним `medical_class` (`decorative|conceptual|
anatomical`): `medical_class` відповідає за review-гейтинг медичної
точності, `category` — за стильову кластеризацію; очікувана інваріанта
`medical_class == "anatomical"` ⇒ `category == "anatomical"` перевіряється
лінтом (крок 9), але не схемою.

Те саме поле з'являється в provenance sidecar (пише `command_import`,
крок 8) — так deck-level перевірка бачить категорію і для зображень, чиї
briefs уже прибрані зі спеки.

#### Крок 8. `asset_resolver.py`: enforcement + успадкування стилю

У `.claude/skills/pptx-deck/scripts/asset_resolver.py`:

1. **`command_import`** — точка, де нова робота стає обов'язковою:

   - якщо у brief немає `category` — `SystemExit` з підказкою («додайте
     image_brief.category у спеку і повторіть import»); це не ламає старі
     сайдкари, лише блокує нові імпорти без категорії;
   - у словник `provenance` додати `"category": brief["category"]`.

   Зверни увагу на побічний ефект, який працює на нас: `brief_hash`
   рахується від усього brief, тож додавання `category` до наявного brief
   змінює хеш — старий sidecar автоматично стає `asset_provenance_stale`
   (error у `check_ai_generated_review`), і зображення мусить пройти
   повторний import проти оновленого brief. Це і є механізм міграції.

2. **`command_plan` / `open_brief_plans`** — успадкування стилю. Нова чиста
   функція:

```python
# asset_resolver.py (орієнтовно)
def inherit_styleguide(brief, styleguide):
    """Для anatomical briefs style constraints зі styleguide_profile —
    частина brief, а не побажання: власний style brief-а йде першим,
    дефолти профілю доклеюються."""
    if brief.get("category") != "anatomical" or not styleguide:
        return {}
    defaults = styleguide.get("image_brief_defaults", {})
    joined = lambda *parts: "; ".join(p for p in parts if p)
    return {
        "effective_style": joined(brief.get("style"), defaults.get("style")),
        "effective_negative": joined(brief.get("negative"),
                                     defaults.get("negative")),
        "visual_rules": styleguide.get("visual_rules", {}),
    }
```

   В `open_brief_plans` кожен план-запис отримує `"category"` і, для
   anatomical, результат `inherit_styleguide(...)`;
   `suggested_generation_prompt`/`suggested_search_queries` будуються з
   `effective_style`/`effective_negative` замість сирих полів brief
   (зараз `suggested_prompt` бере дефолти профілю лише як fallback, коли
   у brief порожній `style`, — після зміни для anatomical дефолти
   доклеюються завжди). Джерело даних уже читається:
   `STYLEGUIDE_PROFILE_JSON` → `out/styleguide_profile.json` з полями
   `image_brief_defaults` і `visual_rules` (ключі перевірені).

#### Крок 9. `lint_render.py`: категорія у briefs і сайдкарах

У `.claude/skills/pptx-deck/scripts/lint_render.py`:

1. **`check_image_briefs`** — два advisory-доповнення:

   - brief без `category` → warn, check id `image_brief_category`
     («категорія потрібна для перевірки стильової узгодженості»);
   - `medical_class == "anatomical"` при заданій `category !=
     "anatomical"` → warn про суперечність осей.

2. **`check_ai_generated_review`** — коли і brief, і sidecar мають
   `category`, але значення різні → **error** (check id
   `asset_provenance`, у повідомленні — category mismatch). Випадок «brief
   отримав category після import» окремо ловити не треба: його вже покриває
   наявна перевірка `brief_hash` (`asset_provenance_stale`).

3. **`check_placed_image_provenance`** — для напряму розміщених
   не-template зображень (рукописні сайдкари): sidecar без `category` →
   **warn** (не error — це legacy-міграція; але без категорії deck-level
   перевірка з кроку 10 не побачить анатомічне зображення, про що й каже
   повідомлення). Список обов'язкових error-полів (`source_type`,
   `license`, `selected_rationale`) не розширюємо.

#### Крок 10. `check_image_style_coherence` у `lint_deck.py`

Нова advisory-перевірка в `.claude/skills/pptx-deck/scripts/lint_deck.py`.
Реєструється так само, як решта: виклик у `lint_deck()` після
`check_role_alignment(...)`, із параметром `project_root=PROJECT_ROOT`
(за зразком `check_package_size`) для тестованості. Залежності — лише
наявні PIL/numpy (обидва вже імпортуються сусідніми скриптами; нових
залежностей нуль).

**Збір множини зображень.** Для кожного слайда (`slide_specs` уже є в
`lint_deck()` після `validate_deck`):

- briefs з `category == "anatomical"`, чий `asset` існує на диску
  (заповнений brief);
- image-елементи, чий provenance sidecar (`<asset>.<ext>.json`, локальний
  хелпер на кшталт `_asset_sidecar` з `lint_render.py`) містить
  `"category": "anatomical"`.

Менше двох анатомічних зображень у деці — перевірка мовчить.

**Дескриптор стилю** (орієнтовно):

```python
def style_descriptor(path):
    img = Image.open(path).convert("RGB").resize((128, 128))
    arr = np.asarray(img).astype(np.float64)
    hsv = np.asarray(img.convert("HSV")).astype(np.float64) / 255.0
    h, s = hsv[..., 0], hsv[..., 1]
    colored = s > 0.15                      # ігноруємо біле/сіре тло
    hue_med = float(np.median(h[colored])) if colored.any() else 0.0
    sat_med = float(np.median(s))
    gray = arr.mean(axis=2)
    gx = np.abs(np.diff(gray, axis=1)) > 24
    gy = np.abs(np.diff(gray, axis=0)) > 24
    edge_density = (float(gx.mean()) + float(gy.mean())) / 2  # line-art vs фото
    strip = np.concatenate([arr[:6].reshape(-1, 3), arr[-6:].reshape(-1, 3),
                            arr[:, :6].reshape(-1, 3), arr[:, -6:].reshape(-1, 3)])
    lum = strip @ np.array([0.2126, 0.7152, 0.0722]) / 255.0
    return {"hue": hue_med, "sat": sat_med, "edge": edge_density,
            "border_lum": float(lum.mean()),     # темний vs світлий фон
            "border_uniform": float(lum.std())}  # рівномірність периметра
```

Складові дескриптора і що вони ловлять:

- `hue`/`sat` (медіанні) — кольорова гама: фіолетова 3D-графіка проти
  бежевої ілюстрації з підручника;
- `edge_density` — частка градієнтних пікселів: тонкий line-art дає високу
  щільність контурів при низькій насиченості, фото/3D-рендер — навпаки;
- `border_lum`/`border_uniform` — смуга 6 px по периметру (на зменшеній
  копії ~4–5% сторони): білий рівний фон проти темного канвасу проти
  «брудного» обрізаного фону.

**Відстань і кластеризація** (простий поріг, без нових залежностей):

```python
def descriptor_distance(a, b):
    dh = abs(a["hue"] - b["hue"])
    dh = min(dh, 1.0 - dh) * 2          # hue циклічний, вага 2
    return math.sqrt(dh ** 2
                     + (a["sat"] - b["sat"]) ** 2
                     + (2 * (a["edge"] - b["edge"])) ** 2
                     + (a["border_lum"] - b["border_lum"]) ** 2)

COHERENCE_THR = 0.35   # відкалібрувати так, щоб пари «в одному стилі»
                       # лишалися в одному кластері (див. тести)
```

Кластеризація — жадібне single-linkage об'єднання (union-find): кожне
зображення — власний кластер; для кожної пари з
`descriptor_distance < COHERENCE_THR` кластери зливаються. Якщо в
результаті кластерів більше одного — **одне warn на деку** (check id
`image_style_coherence`) зі складом кластерів (`slide:asset`) і значеннями
дескрипторів у повідомленні, щоб рішення можна було перевірити оком.
Severity — тільки `warn` (advisory, як вимагає майстер-план: обов'язковим
пунктом є review-артефакт з кроку 11, а не автоматична евристика).

Поточна дека SIA MED не має жодного зображення з `category` (усі шість
слайдів кладуть лише template-extracted активи з
`assets/designer_extracted/`, briefs порожні — перевірено), тож перевірка
на ній мовчить і gate лишається зеленим.

#### Крок 11. Контракт `meta.sequence_review` + wiring у `lint_deck`

**Контракт** (на deck spec; цей документ — власник визначення, Етап 3
розширює формат finding):

```json
"sequence_review": {
  "iteration": 1,
  "verdict": "pass | fail | pass_with_notes",
  "findings": [
    {"topic": "style_coherence",
     "note": "усі анатомічні зображення — один 3D-рендер-стиль; фон і гама узгоджені",
     "slides": [3, 4]},
    {"topic": "rhythm", "note": "..."}
  ]
}
```

(Орієнтовно.) Правила: `iteration` — ціле ≥ 1; `findings[]`
**зобов'язаний** містити принаймні один запис з
`topic == "style_coherence"` — стильова узгодженість фіксується в
артефакті явно, навіть коли все гаразд («не мається на увазі», як
формулює майстер-план). Елементи `findings[]` навмисно відкриті для
додаткових полів (severity, evidence, confidence, auto_fixable додасть
Етап 3 / P1 №9).

**Схема.** У `specs/deck.schema.json` `meta` зараз — вільний об'єкт без
фіксованих properties (`additionalProperties: true`, перевірено). Додати
`properties.sequence_review` з наведеною формою (enum для `verdict`,
`minimum: 1` для `iteration`, `findings` — масив об'єктів з обов'язковим
`topic` і `additionalProperties: true`), лишивши `additionalProperties:
true` на самому `meta` — решта meta-полів (outline, token_overrides,
doc_props…) не зачіпаються.

**Wiring.** Нова `check_sequence_review(deck, findings)` у
`lint_deck.py`, викликається в `lint_deck()` поруч з іншими перевірками
(дзеркало per-slide `check_visual_review` з `lint_render.py`, включно з
лімітом ітерацій):

- `meta.sequence_review` відсутній → **warn** (check `sequence_review`) —
  «дека ще не пройшла sequence-level review»;
- `verdict == "fail"` → **error** (check `sequence_review_failed`) з
  перерахуванням issues;
- `iteration > 3` → **error** (check `sequence_review_iterations`) —
  та сама межа `MAX_VISUAL_REVIEW_ITERATIONS`, що й per-slide;
- `findings[]` без запису `topic == "style_coherence"` → **warn**
  (check `sequence_review_style_coherence`).

`deck_qa` підхоплює це без змін: errors від `lint_deck` уже входять у
`total_errors` (крок 4 у `deck_qa.main()`).

#### Крок 12. Міграція деки SIA MED (Частина B)

1. Провести фактичний sequence-level review шестислайдової деки і записати
   `meta.sequence_review` у `specs/sia_med/sia_med.deck.json` (з явним
   `style_coherence`-пунктом).
2. `image_briefs` у поточних слайдах відсутні, тож міграція категорій
   briefs не потрібна; нові briefs пишуться одразу з `category`.
3. Прогнати `deck_qa.py` — очікування: 0 errors; нові warns можливі лише
   advisory (`image_brief_category` на майбутніх briefs без категорії).

## Тести

Стиль — як у `tests/test_qa_gates.py`: прямі виклики check-функцій з
синтетичними спеками, хелпери `_spec`/`_by_check`, PIL-згенеровані
зображення в `tmp_path`, injectable `project_root`. Новий файл
`tests/test_template_fidelity.py` (Частина A + coherence/sequence_review);
доповнення `tests/test_asset_resolver.py` (import/plan).

Частина A:

- `test_template_style_records_sha256` — зібрати мінімальний `.pptx`
  python-pptx-ом у `tmp_path`, викликати
  `template_style.extract(path, with_thumbnails=False)`; у результаті є
  `template_sha256 == common.file_sha256(path)` і repo-relative
  `template_path`.
- `test_catalog_skeleton_preserves_keys` — `build_catalog_skeleton` на
  синтетичному style-словнику повертає рівно набір ключів чинного каталогу
  + `template_sha256`; присутні всі п'ять exemplar-ролей у
  `layouts_observed`; `n_slides_total` виведено зі `slide_layout_map`.
- `test_onboard_refuses_to_clobber_filled_catalog_without_force` — наявний
  каталог з іншим хешем + без `--force` → відмова; з `--force` — старий
  файл збережено поруч.
- `test_freshness_missing_catalog_is_error`,
  `test_freshness_hash_mismatch_is_error`,
  `test_freshness_fresh_is_clean` — `deck_qa.check_template_freshness`
  з `project_root=tmp_path`: відсутній каталог / підмінений байт у
  шаблоні / повний збіг (включно з `template_style.json`).

Частина B:

- `test_import_requires_brief_category` — `command_import` для brief без
  `category` → `SystemExit`.
- `test_import_records_category_in_provenance` — sidecar після import
  містить `category` brief-а.
- `test_anatomical_brief_inherits_styleguide_defaults` — чиста
  `inherit_styleguide`: `effective_style` містить і style brief-а, і
  `image_brief_defaults.style` профілю; `visual_rules` прокинуто; для
  `category: "decor"` — порожній результат.
- `test_brief_without_category_warns`,
  `test_medical_class_category_conflict_warns` —
  `lint_render.check_image_briefs`.
- `test_sidecar_category_mismatch_is_error` —
  `lint_render.check_ai_generated_review` з sidecar `category: "decor"`
  проти brief `category: "anatomical"` (з коректним `brief_hash`, щоб
  ізолювати саме mismatch).
- `test_style_descriptor_separates_lineart_from_photo` — два
  PIL-згенерованих зображення: біле тло + тонкі темні лінії проти
  насиченого кольорового шуму (`np.random.default_rng(0)`, як у
  `_logo_spec` в `test_qa_gates.py`); `edge_density`/`sat` розрізняють їх
  у передбачуваному напрямку.
- `test_style_coherence_uniform_set_is_silent` — два схожих line-art
  зображення (однакова гама/фон) → жодного finding.
- `test_style_coherence_split_set_warns` — line-art + «фото» → рівно один
  warn `image_style_coherence` зі складом обох кластерів у повідомленні.
- `test_style_coherence_single_image_is_silent` — одне анатомічне
  зображення → мовчання.
- `test_sequence_review_missing_is_a_warn`,
  `test_sequence_review_fail_is_an_error`,
  `test_sequence_review_iteration_cap_is_an_error`,
  `test_sequence_review_requires_style_coherence_entry`,
  `test_sequence_review_pass_is_clean` — `lint_deck.check_sequence_review`
  (дзеркало наявних visual_review-тестів у `test_qa_gates.py`).

Інтеграційно: повний `pytest` зелений; `deck_qa.py
specs/sia_med/sia_med.deck.json` після міграції (кроки 5, 12) — `ok:
true`, 0 errors.

## Критерії готовності

Виведені з критеріїв майстер-плану P0 №2 і №3:

1. **Онбординг без зміни коду:** нова конференція = один прогін
   `onboard_template.py <нова.pptx>` → свіжі `out/assets.json`,
   `out/template_style.json` (з `template_sha256`), скелет
   `out/template_visual_catalog.json` і thumbnails; жодного редагування
   Python-коду.
2. **Freshness gate:** відсутній каталог, каталог без хешу або хеш, що не
   збігається з фактичним `assets/template.pptx` (у каталозі чи в
   `template_style.json`), провалює `deck_qa` (`ok=false`, ненульовий
   `total_errors`, блок `template_freshness` у звіті).
3. **Прив'язка слайдів:** кожен слайд посилається на template
   layout/component через `meta.outline` (`layout_ref` за ключами
   `layouts_observed[].role`; формалізація поля — Етап 4) або записує
   обґрунтоване відхилення.
4. **Стильова узгодженість вимірюється:** анатомічні зображення деки
   класифіковані (`category` у briefs і provenance sidecars), а
   `check_image_style_coherence` попереджає, коли їхні дескриптори
   розпадаються на кластери.
5. **Розбіжність стилю неможливо не помітити:** вона або виправлена
   (advisory warn знято), або явно прийнята людиною — `meta.sequence_review`
   присутній, містить `style_coherence`-пункт, `verdict != "fail"`;
   `verdict: "fail"` — це error gate.
6. **Anatomical briefs успадковують style constraints** зі
   `styleguide_profile.json` (`image_brief_defaults` + `visual_rules`) у
   `asset_resolver.py plan`; import без `category` неможливий.
7. Усі наявні тести + нові з розділу «Тести» зелені; дека SIA MED проходить
   gate з 0 errors.

## Ризики

- **Single-template assumption.** Онбординг і gate виходять з одного
  активного шаблону за шляхом `assets/template.pptx`. Кілька одночасних
  шаблонів вимагатимуть `out/` на шаблон — свідомо поза скоупом (як у
  майстер-плані). NB: майстер-план називає шлях «`template.pptx` у корені» —
  це розбіжність з кодом; істина — `assets/template.pptx`.
- **Перезапис активного шаблону.** `onboard_template.py` копіює новий файл
  на канонічне місце; попередній зберігається як `.bak`, а рукописний
  каталог захищений `--force`-семантикою — але оператор усе одно має
  розуміти, що онбординг перемикає весь facts layer на новий шаблон.
- **Червоний gate до міграції.** Freshness gate зробить будь-який наявний
  checkout червоним, поки не виконано кроки 5/12; міграція мусить їхати в
  тому самому PR, що й код.
- **Хибні спрацювання дескриптора.** Шаблон легітимно має два color modes
  (DARK/LIGHT — див. каталог), тож анатомічні зображення на темних і
  світлих слайдах можуть розійтися по `border_lum` навмисно. Тому перевірка
  advisory-only, поріг `COHERENCE_THR` калібрується на тестових парах, а
  фінальне слово — за обов'язковим `style_coherence`-пунктом
  `sequence_review`. Якщо шум високий — наступна ітерація: порівнювати
  кластери в межах одного color mode.
- **Інвалідація сайдкарів через `brief_hash`.** Додавання `category` до
  наявного brief змінює `brief_hash` → старий sidecar дає
  `asset_provenance_stale` (error). Це задумана поведінка (re-review проти
  оновленого brief), але в декі з багатьма заповненими briefs міграція
  вимагатиме серії повторних `asset_resolver.py import` — планувати час.
- **Спільний артефакт з Етапом 3.** `meta.sequence_review.findings[]`
  розширюється Етапом 3 (P1 №9): не закривати елементи findings
  `additionalProperties: false`, інакше Етап 3 зламає схему.
- **Немає публічного шаблону-fixture до Етапу 4** (P1 №8): e2e-тест
  онбордингу працює на синтетичному python-pptx файлі, який не відтворює
  реальний безлад (3 теми в одному шаблоні, змішані шрифти) — частина
  поведінки перевіряється лише на приватному шаблоні локально.
- **Вартість онбордингу.** Крок thumbnails тягне `soffice`+`pdftoppm`
  (повільно, потрібні бінарники); `--no-thumbnails` є, але без thumbnails
  агент не зможе якісно заповнити каталог — це escape hatch для CI, не для
  реального онбордингу.
