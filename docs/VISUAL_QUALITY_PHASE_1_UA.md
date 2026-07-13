# Етап 1 — розширити професійні можливості: нативні діаграми та перевірені таблиці

## Зв'язок із планом

Це робоча інструкція для «Етап 1 — розширити професійні можливості» з
`docs/VISUAL_QUALITY_IMPROVEMENT_PLAN_UA.md`. Вона реалізує пункт
P0 №1 (обсяг **L**): мінімальний набір editable charts (bar, line,
scatter) з керуванням emphasis, labels, number formats, axes, grids і
legends; self-contained fixtures для таблиці й кожного типу діаграми;
прогін через наявний gate `deck_qa.py` без змін самого gate.

Кодова база — гілка `p0-fixes` (commit `f430ead`), яку план вважає
змердженою в `main`. Усі шляхи — відносно кореня репозиторію; скрипти
конвеєра живуть у `.claude/skills/pptx-deck/scripts/`.

Зв'язки з рештою плану (розділ «Залежності та ризики»):

- LibreOffice-рендер — лише проксі для геометрії й палітри; фінальна
  істина для charts — PowerPoint-перевірка P2 №12, обов'язкова саме
  для chart-слайдів;
- fixtures цього етапу — перші представники публічної системи fixtures
  P1 №8; маркер `meta.fixture_kind` можна проставити вже зараз, але
  контракт тестового раннера — скоуп P1 №8;
- fallback-правило: якщо python-pptx не дає потрібного вигляду —
  редагована таблиця + нативні shapes, **ніколи** не растрове
  зображення діаграми.

## Передумови

1. `p0-fixes` змерджено в `main`; чисте робоче дерево.
2. `.venv` за `requirements.txt`. Ескізи нижче перевірені на
   python-pptx **1.0.2** (поточна версія в `.venv`); залежність у
   `requirements.txt` не зафіксована за версією — див. «Ризики».
3. `soffice`, `pdftoppm`, `textutil` на PATH —
   `.claude/skills/pptx-deck/scripts/deck_qa.py`
   (`check_external_tools`) і так це перевіряє.
4. Facts layer на місці: `out/assets.json` і `out/template_style.json`
   (`lint_render.py` читає їх безумовно). Родина `Geologica Roman`
   (OFL, повне покриття кирилиці) присутня в `out/assets.json`
   `fonts[].family` — fixtures використовують саме її.
5. Каталог `specs/lint_test_fixtures/` існує на `f430ead`
   (`broken_example.spec.json`, `shape_fit_smoketest.spec.json`) —
   нові fixtures лягають поруч.

## Кроки

### 1. Payload-контракт `chart` у `specs/spec.schema.json`

`chart` уже присутній в enum `$defs.element.properties.type`. У блоці
`$defs.element.allOf` зараз стоїть placeholder-гілка «Reserved for a
later phase» з декоративним `data: { "type": "object" }` — замінити її
цілком на робочий контракт (payload під ключем `chart`, за зразком
`table`: увесь стиль — рішення верхнього рівня, builder не вигадує ні
кольорів, ні шрифтів):

```json
{
  "if": { "properties": { "type": { "const": "chart" } } },
  "then": {
    "required": ["chart"],
    "properties": {
      "chart": {
        "type": "object",
        "description": "Native editable chart. Уся стилістика — упстрім-рішення: builder не вигадує кольорів і шрифтів.",
        "required": ["chart_type", "series", "labels"],
        "additionalProperties": false,
        "properties": {
          "chart_type": { "enum": ["bar", "line", "scatter"] },
          "categories": {
            "type": "array",
            "minItems": 1,
            "items": { "type": "string" },
            "description": "Обов'язкові для bar/line, заборонені для scatter (перехресна перевірка у validate_spec)."
          },
          "series": {
            "type": "array",
            "minItems": 1,
            "items": {
              "type": "object",
              "required": ["name", "values", "color"],
              "additionalProperties": false,
              "properties": {
                "name": { "type": "string" },
                "values": {
                  "type": "array",
                  "minItems": 1,
                  "items": {
                    "oneOf": [
                      { "type": "number" },
                      {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 2,
                        "items": { "type": "number" }
                      }
                    ]
                  },
                  "description": "bar/line: числа, вирівняні з categories; scatter: пари [x, y]."
                },
                "color": {
                  "type": "string",
                  "pattern": "^[0-9A-Fa-f]{6}$"
                }
              }
            }
          },
          "labels": {
            "type": "object",
            "description": "Єдина типографіка всіх підписів діаграми: tick labels, заголовки осей, легенда, data labels.",
            "required": ["font", "size_pt", "color"],
            "additionalProperties": false,
            "properties": {
              "font": { "type": "string" },
              "size_pt": { "type": "number", "exclusiveMinimum": 0 },
              "color": { "type": "string", "pattern": "^[0-9A-Fa-f]{6}$" }
            }
          },
          "x_axis": { "$ref": "#/$defs/chart_axis" },
          "y_axis": { "$ref": "#/$defs/chart_axis" },
          "legend": {
            "type": "object",
            "additionalProperties": false,
            "properties": {
              "visible": { "type": "boolean", "default": false },
              "position": {
                "enum": ["bottom", "top", "left", "right"],
                "default": "bottom"
              }
            }
          },
          "data_labels": {
            "type": "object",
            "additionalProperties": false,
            "properties": {
              "visible": { "type": "boolean", "default": false },
              "number_format": { "type": "string" }
            }
          },
          "emphasis": {
            "type": "object",
            "description": "Insight emphasis: акцентна серія (і опційно одна її точка) кольором з палітри деки.",
            "required": ["series", "color"],
            "additionalProperties": false,
            "properties": {
              "series": { "type": "integer", "minimum": 0 },
              "point": { "type": "integer", "minimum": 0 },
              "color": { "type": "string", "pattern": "^[0-9A-Fa-f]{6}$" }
            }
          }
        }
      }
    }
  }
}
```

І нове означення осі в `$defs`:

```json
"chart_axis": {
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "title": { "type": "string" },
    "number_format": {
      "type": "string",
      "description": "Excel-формат чисел tick labels, напр. \"0\", \"0.0\", \"0%\"."
    },
    "grid": { "type": "boolean", "default": false }
  }
}
```

Конвенції контракту (зафіксувати в description, як зроблено для
`table.style`):

- `x_axis` описує **вісь категорій** (bar/line) або X-вісь значень
  (scatter); `y_axis` — вісь значень. Для `chart_type: "bar"`
  (горизонтальні смуги, див. крок 3) вісь категорій рендериться
  вертикально — це свідома конвенція контракту, не помилка;
- `emphasis.color` обов'язковий: у плані поле перелічене як
  `{series, point}`, але конвеєр ніде не дозволяє builder-у вигадувати
  кольори, тож акцентний колір має бути явно заморожений у spec, а
  lint (крок 5) перевіряє його належність до `tokens.palette_roles`.

### 2. `validate_spec`: зняти заборону, додати перехресні перевірки

У `.claude/skills/pptx-deck/scripts/build_deck.py`, функція
`validate_spec`, зараз стоїть гілка:

```python
if el["type"] == "chart":
    errors.append(f"element '{el['id']}': type 'chart' is reserved, "
                   f"not implemented by build_deck.py yet")
```

Замінити її на перевірки, які схема сама виразити не може (за зразком
наявної перевірки довжини рядків таблиці там само):

- `bar`/`line`: `categories` обов'язкові; довжина `values` кожної
  серії дорівнює `len(categories)`; кожне значення — число, не пара;
- `scatter`: `categories` заборонені; кожне значення — пара `[x, y]`;
- `emphasis.series` < кількості серій; `emphasis.point` (якщо задано)
  < кількості значень акцентної серії.

Орієнтовний ескіз:

```python
if el["type"] == "chart":
    c = el["chart"]
    is_pair = lambda v: isinstance(v, list)
    if c["chart_type"] == "scatter":
        if "categories" in c:
            errors.append(f"element '{el['id']}': scatter chart "
                           f"must not declare categories")
        for si, s in enumerate(c["series"]):
            if not all(is_pair(v) for v in s["values"]):
                errors.append(f"element '{el['id']}': scatter series "
                               f"{si} values must be [x, y] pairs")
    else:
        if "categories" not in c:
            errors.append(f"element '{el['id']}': "
                           f"{c['chart_type']} chart requires categories")
        else:
            n = len(c["categories"])
            for si, s in enumerate(c["series"]):
                if any(is_pair(v) for v in s["values"]):
                    errors.append(f"element '{el['id']}': series {si} "
                                   f"values must be numbers, not pairs")
                elif len(s["values"]) != n:
                    errors.append(f"element '{el['id']}': series {si} "
                                   f"has {len(s['values'])} values, "
                                   f"expected {n} (categories)")
    emph = c.get("emphasis")
    if emph:
        if emph["series"] >= len(c["series"]):
            errors.append(f"element '{el['id']}': emphasis.series "
                           f"{emph['series']} out of range")
        elif (emph.get("point") is not None and emph["point"]
              >= len(c["series"][emph["series"]]["values"])):
            errors.append(f"element '{el['id']}': emphasis.point "
                           f"{emph['point']} out of range")
```

`else`-гілку з `SpecError` в `add_slide_from_spec` не чіпати — вона
залишається пасткою для майбутніх нереалізованих типів.

### 3. `build_chart()` і dispatch в `add_slide_from_spec`

Там само в `build_deck.py`:

1. Імпорти: `from pptx.chart.data import CategoryChartData,
   XyChartData` та `from pptx.enum.chart import XL_CHART_TYPE,
   XL_LEGEND_POSITION`.
2. Мапи типів (поруч із наявною `SHAPE_TYPE_MAP`):

```python
CHART_TYPE_MAP = {
    "bar": XL_CHART_TYPE.BAR_CLUSTERED,
    "line": XL_CHART_TYPE.LINE,
    "scatter": XL_CHART_TYPE.XY_SCATTER,
}
LEGEND_POSITION_MAP = {
    "bottom": XL_LEGEND_POSITION.BOTTOM,
    "top": XL_LEGEND_POSITION.TOP,
    "left": XL_LEGEND_POSITION.LEFT,
    "right": XL_LEGEND_POSITION.RIGHT,
}
```

3. `build_chart(slide, el)` поруч із `build_table`. Ключова розвилка —
   дані: `CategoryChartData` для bar/line, `XyChartData` для scatter
   (scatter не має categories, точки додаються парами). Орієнтовний
   ескіз (перевірено на python-pptx 1.0.2 — `shapes.add_chart`
   створює справжню chart part `ppt/charts/chartN.xml`):

```python
def build_chart(slide, el):
    """Native editable chart, повністю стилізований зі spec."""
    c = el["chart"]
    if c["chart_type"] == "scatter":
        data = XyChartData()
        for s in c["series"]:
            ser = data.add_series(s["name"])
            for x, y in s["values"]:
                ser.add_data_point(x, y)
    else:
        data = CategoryChartData()
        data.categories = c["categories"]
        for s in c["series"]:
            data.add_series(s["name"], s["values"])
    gf = slide.shapes.add_chart(
        CHART_TYPE_MAP[c["chart_type"]], *emu_box(el["box"]), data)
    _style_chart(gf.chart, c)  # крок 4
    return gf
```

4. Dispatch в `add_slide_from_spec` — нова гілка поруч із
   `build_table`:

```python
elif el["type"] == "chart":
    shp = build_chart(slide, el)
```

   `add_chart` повертає `GraphicFrame` — як і `add_table` — тож
   `shp.shape_id` для карти анімацій працює без змін; chart-елемент
   автоматично може бути ціллю `fade`.

### 4. Стилювання діаграми (`_style_chart`)

Все з payload-контракту кроку 1 має спостережно потрапляти в XML —
інакше тест покриття схеми (див. «Тести») його зловить. Орієнтовний
ескіз; API-виклики перевірені на python-pptx 1.0.2:

```python
def _apply_chart_font(font, labels):
    font.name = labels["font"]
    font.size = Pt(labels["size_pt"])
    font.color.rgb = RGBColor.from_string(labels["color"])


def _set_series_color(ser, chart_type, color_hex):
    color = RGBColor.from_string(color_hex)
    if chart_type == "line":
        ser.format.line.color.rgb = color
    elif chart_type == "scatter":
        ser.marker.format.fill.solid()
        ser.marker.format.fill.fore_color.rgb = color
    else:  # bar
        ser.format.fill.solid()
        ser.format.fill.fore_color.rgb = color


def _style_chart(chart, c):
    labels = c["labels"]
    plot = chart.plots[0]
    for si, s in enumerate(c["series"]):
        _set_series_color(plot.series[si], c["chart_type"], s["color"])
        if c["chart_type"] == "line":
            plot.series[si].smooth = False
    emph = c.get("emphasis")
    if emph:
        ser = plot.series[emph["series"]]
        if emph.get("point") is None:
            _set_series_color(ser, c["chart_type"], emph["color"])
        else:
            pt = ser.points[emph["point"]]
            pt.format.fill.solid()  # bar; line/scatter — pt.marker
            pt.format.fill.fore_color.rgb = \
                RGBColor.from_string(emph["color"])
    # осі: category_axis = вісь категорій (bar/line) або X-вісь
    # (scatter: python-pptx 1.0.2 повертає ValueAxis, не кидає);
    # value_axis = вісь значень
    for axis, ax_spec in ((chart.category_axis, c.get("x_axis")),
                          (chart.value_axis, c.get("y_axis"))):
        if ax_spec is None:
            continue
        axis.has_major_gridlines = ax_spec.get("grid", False)
        if ax_spec.get("title"):
            axis.has_title = True
            axis.axis_title.text_frame.text = ax_spec["title"]
            _apply_chart_font(axis.axis_title.text_frame
                              .paragraphs[0].runs[0].font, labels)
        if ax_spec.get("number_format"):
            axis.tick_labels.number_format = ax_spec["number_format"]
            axis.tick_labels.number_format_is_linked = False
        _apply_chart_font(axis.tick_labels.font, labels)
    leg = c.get("legend", {})
    chart.has_legend = leg.get("visible", False)
    if chart.has_legend:
        chart.legend.position = \
            LEGEND_POSITION_MAP[leg.get("position", "bottom")]
        chart.legend.include_in_layout = False
        _apply_chart_font(chart.legend.font, labels)
    dl = c.get("data_labels", {})
    if dl.get("visible"):
        plot.has_data_labels = True
        if dl.get("number_format"):
            plot.data_labels.number_format = dl["number_format"]
            plot.data_labels.number_format_is_linked = False
        _apply_chart_font(plot.data_labels.font, labels)
```

Зауваги:

- точковий emphasis для line/scatter має йти через
  `point.marker.format.fill` (маркер точки), для bar — через
  `point.format.fill` (у package це `<c:dPt>`); винести цю розвилку в
  helper поруч із `_set_series_color`;
- `XL_CHART_TYPE.BAR_CLUSTERED` — **горизонтальні** смуги. Якщо під
  час верстки fixtures з'ясується, що потрібні вертикальні колонки —
  це `COLUMN_CLUSTERED`; розширення enum (`column`) робити окремим
  свідомим рішенням, не мовчазною заміною мапи.

### 5. `lint_deck.py`: палітра, бюджет шрифтів і type_scale бачать charts

У `.claude/skills/pptx-deck/scripts/lint_deck.py` обхідники сьогодні
знають лише `textbox`, `shape`, `table`:

1. `_slide_fonts` — додати гілку для chart-елементів:
   `fonts.add(el["chart"]["labels"]["font"])`. Через це
   `check_font_budget` рахує chart-шрифти автоматично.
2. `_slide_colors` — додати кольори діаграми, після чого
   `check_palette_discipline` (яка працює на `_slide_colors` проти
   `tokens.palette_roles`) покриває charts без власних змін:

```python
if el["type"] == "chart":
    c = el["chart"]
    colors.add(c["labels"]["color"].upper())
    for s in c["series"]:
        colors.add(s["color"].upper())
    if c.get("emphasis"):
        colors.add(c["emphasis"]["color"].upper())
```

3. `check_type_scale` — зараз перевіряє лише textbox, чий `role` є
   ключем `tokens.type_scale`. Додати гілку: для chart-елемента з
   `role` у scale порівнювати `chart.labels.font` і
   `chart.labels.size_pt` з токеном (error при розбіжності; поле
   `bold` токена до chart-підписів не застосовується — у контракті
   його немає). Конвенція для дек: окремий ключ `chart_label` у
   `type_scale`, а chart-елементи отримують `"role": "chart_label"`.
4. `check_margins` — розширити кортеж контент-типів
   `("textbox", "table")` до `("textbox", "table", "chart")`:
   діаграма — контент, а не декор, і не має висіти в полях.

Без змін (працюють автоматично, бо оперують `box`/кількістю
елементів): `check_density`, `check_role_alignment` (textbox-only за
задумом), а в `lint_render.py` — `check_bbox_overlap`.

### 6. `lint_render.py`: conformance, glyph coverage, embedding бачать charts

У `.claude/skills/pptx-deck/scripts/lint_render.py` сьогодні:

- `check_font_conformance` — лише runs/bullets textbox-ів;
- `check_glyph_coverage` — лише runs textbox-ів;
- `check_font_embedding_decision` — runs/bullets + `table.style.font`;
- `check_text_fit`, `check_render_structure` — textbox-only
  (для charts свідомо не розширюються — див. «Ризики»).

Зміни:

1. Спільний helper видимого тексту діаграми (все рендериться шрифтом
   `chart.labels.font`):

```python
def _chart_texts(el):
    c = el["chart"]
    texts = [s["name"] for s in c["series"]]
    texts += c.get("categories", [])
    for ax in ("x_axis", "y_axis"):
        if c.get(ax, {}).get("title"):
            texts.append(c[ax]["title"])
    return c["labels"]["font"], texts
```

2. `check_font_conformance`: для кожного chart-елемента — якщо
   `labels.font` не є точним ключем `assets.json fonts[].family`,
   додати `(el["id"], font)` до `failed` і зафіксувати error (та сама
   «пастка іменування», що й для textbox: `Geologica SemiBold` ≠
   `Geologica Roman SemiBold`).
3. `check_glyph_coverage`: для chart-елементів проганяти всі рядки з
   `_chart_texts` через cmap шрифту `labels.font` (той самий
   `TTFont(...).getBestCmap()` і кеш). Кириличні категорії, назви
   серій і заголовки осей — головний споживач цієї перевірки. Числа
   data labels перевіряти не треба — цифри покриває будь-який шрифт.
4. `check_font_embedding_decision`: додати `labels.font` chart-ів до
   `used_fonts` (симетрично до вже врахованого `table.style.font`).
5. Суміжна дірка, яку оголює кириличний `table_baseline`:
   `check_font_conformance`/`check_glyph_coverage` сьогодні не бачать
   і `table.style.font` / текст клітинок. «Перевірені таблиці» з
   P0 №1 — привід закрити її тут же тим самим прийомом (шрифт стилю +
   усі рядки `table.rows`). Дешево, але після зміни обов'язково
   прогнати наявну production-деку (крок 8, регрес).

`deck_qa.py` змін не потребує: він уже ланцюжить build → per-slide
`lint_render --deck` → `lint_deck` → `render_all` і провалюється на
будь-якому error — нові findings підхоплюються автоматично.

### 7. Fixtures: чотири слайди + fixture-дека

Створити в `specs/lint_test_fixtures/` (усі дані — синтетичні,
медично-правдоподібні, без клієнтських матеріалів; шрифт —
`Geologica Roman`, кольори — лише з палітри fixture-деки):

1. **`chart_bar.spec.json`** — «Відповідь на лікування за методами
   (синтетичні дані, n=200)». Один chart-елемент
   (`role: "chart_label"`) + заголовок-textbox (`role: "title"`).
   Категорії: «Шинотерапія», «Фізіотерапія», «Комбінована терапія»,
   «Контроль»; серія «Пацієнти зі зниженням болю ≥50 %, %» зі
   значеннями `[42, 38, 67, 18]`, колір `5B49D3`; emphasis
   `{series: 0, point: 2, color: "EFD12A"}` (комбінована терапія —
   інсайт слайда); `y_axis` `{title: "Пацієнти, %",
   number_format: "0", grid: true}`; data_labels
   `{visible: true, number_format: "0"}`; легенда вимкнена. Приклад
   каркаса:

```json
{
  "spec_version": 1,
  "meta": {
    "note": "Synthetic chart fixture - no client material.",
    "fixture_kind": "regression"
  },
  "slide": { "width_emu": 12192000, "height_emu": 6858000 },
  "elements": [
    {
      "id": "title", "type": "textbox", "role": "title", "z": 1,
      "box": { "x": 838200, "y": 520700,
               "cx": 10515600, "cy": 800000 },
      "paragraphs": [ { "lines": [ {
        "text": "Відповідь на лікування за методами (n=200)",
        "font": "Geologica Roman", "size_pt": 28,
        "color": "131313", "bold": true } ] } ]
    },
    {
      "id": "response_chart", "type": "chart",
      "role": "chart_label", "z": 1,
      "box": { "x": 838200, "y": 1600000,
               "cx": 10515600, "cy": 4600000 },
      "chart": {
        "chart_type": "bar",
        "categories": ["Шинотерапія", "Фізіотерапія",
                        "Комбінована терапія", "Контроль"],
        "series": [ {
          "name": "Пацієнти зі зниженням болю ≥50 %, %",
          "values": [42, 38, 67, 18],
          "color": "5B49D3" } ],
        "labels": { "font": "Geologica Roman", "size_pt": 12,
                     "color": "131313" },
        "x_axis": { "title": "Метод лікування" },
        "y_axis": { "title": "Пацієнти, %",
                     "number_format": "0", "grid": true },
        "legend": { "visible": false },
        "data_labels": { "visible": true, "number_format": "0" },
        "emphasis": { "series": 0, "point": 2, "color": "EFD12A" }
      }
    }
  ],
  "animations": []
}
```

2. **`chart_line.spec.json`** — «Динаміка інтенсивності болю (VAS),
   12 тижнів». Категорії: тижні `["0", "2", "4", "8", "12"]`; серії:
   «Комбінована терапія» `[7.8, 6.1, 4.6, 3.2, 2.1]` (колір
   `5B49D3`), «Контрольна група» `[7.6, 7.2, 6.8, 6.5, 6.1]` (колір
   `5A5A63`); emphasis `{series: 0, color: "74A71B"}`; легенда
   `{visible: true, position: "bottom"}`; `x_axis`
   `{title: "Тиждень спостереження"}`, `y_axis` `{title: "VAS,
   балів", number_format: "0.0", grid: true}`.
3. **`chart_scatter.spec.json`** — «Амплітуда відкривання рота проти
   інтенсивності болю». Без categories; одна серія «Пацієнти (n=11)»
   (колір `5B49D3`) з парами
   `[[24, 8.5], [28, 7.9], [31, 7.2], [33, 6.8], [36, 5.9],
   [38, 5.1], [41, 4.4], [43, 3.6], [46, 2.9], [49, 2.2],
   [52, 1.8]]` (правдоподібна негативна кореляція); `x_axis`
   `{title: "Відкривання рота, мм", number_format: "0"}`, `y_axis`
   `{title: "VAS, балів", number_format: "0.0", grid: true}`.
4. **`table_baseline.spec.json`** — production-візуальний baseline
   таблиці: «Методи оцінки дисфункції СНЩС». Колонки: Метод / Що
   оцінює / Тривалість; рядки: «Клінічний огляд — Амплітуда й
   траєкторія рухів — 15 хв», «МРТ СНЩС — Положення диска, м'які
   тканини — 30 хв», «КПКТ — Кісткові структури — 10 хв»,
   «Аксіографія — Траєкторії рухів щелепи — 20 хв». `table.style`:
   `font: "Geologica Roman"`, `size_pt: 14`, `text_color: "131313"`,
   `header_fill: "5B49D3"`, `header_color: "FFFFFF"`,
   `alt_row_fill: "EFEFF4"` — і `EFEFF4` додати роллю в палітру деки
   (нижче), інакше palette warn; `border_color: "5A5A63"`.
5. **`chart_fixtures.deck.json`** — fixture-дека, що збирає всі
   чотири слайди й дає токени, проти яких token-aware лінти судять
   charts (`deck_qa` завжди передає `--deck`):

```json
{
  "deck_version": 1,
  "slide": { "width_emu": 12192000, "height_emu": 6858000 },
  "meta": {
    "doc_props": {
      "title": "Chart and table fixtures",
      "author": "pptx2 pipeline",
      "subject": "Synthetic QA fixtures"
    },
    "fixture_kind": "regression",
    "font_embedding_opt_out": "public fixture: Geologica is OFL and auto-installed by ensure_fonts_installed; package is not a client deliverable"
  },
  "tokens": {
    "palette_roles": {
      "paper": "FFFFFF",
      "ink": "131313",
      "violet": "5B49D3",
      "green": "74A71B",
      "gold": "EFD12A",
      "muted": "5A5A63",
      "row_tint": "EFEFF4"
    },
    "type_scale": {
      "title": { "font": "Geologica Roman", "size_pt": 28,
                  "bold": true },
      "chart_label": { "font": "Geologica Roman", "size_pt": 12 }
    }
  },
  "slides": [
    "specs/lint_test_fixtures/chart_bar.spec.json",
    "specs/lint_test_fixtures/chart_line.spec.json",
    "specs/lint_test_fixtures/chart_scatter.spec.json",
    "specs/lint_test_fixtures/table_baseline.spec.json"
  ]
}
```

`meta.visual_review` до fixtures **не** вписувати наперед — його
фіксують після реального перегляду рендерів на кроці 8 (відсутній
review — лише warn, gate не провалюється, але критерій готовності
вимагає записаного вердикту).

### 8. Прогін через gate і перевірка редагованості

З кореня репозиторію:

```bash
# 1. Схема + перехресні перевірки кожного fixture
.venv/bin/python .claude/skills/pptx-deck/scripts/build_deck.py \
    specs/lint_test_fixtures/chart_bar.spec.json --check-only
# ... те саме для chart_line / chart_scatter / table_baseline

# 2. Повний gate: build → per-slide lint → deck lint → render_all
.venv/bin/python .claude/skills/pptx-deck/scripts/deck_qa.py \
    specs/lint_test_fixtures/chart_fixtures.deck.json \
    --out output/chart_fixtures_qa.json
```

Очікування: exit 0, `total_errors: 0`, 4 PNG у
`output/rendered/chart_fixtures_qa/` (LibreOffice → PDF → `pdftoppm`,
як у `render.py` `render_all`). Переглянути PNG очима і зафіксувати
`meta.visual_review` (iteration, verdict, findings) на кожному
fixture-слайді.

Перевірка редагованості (chart — нативна chart part, не растр):

```bash
unzip -l output/chart_fixtures.pptx | grep "ppt/charts/"
# очікування: chart1.xml..chart3.xml (+ _rels), жодного нового
# ppt/media/* для chart-слайдів

.venv/bin/python - <<'EOF'
from pptx import Presentation
prs = Presentation("output/chart_fixtures.pptx")
for i, slide in enumerate(prs.slides, 1):
    for sh in slide.shapes:
        if sh.has_chart:
            ser = sh.chart.plots[0].series[0]
            print(i, sh.chart.chart_type, list(ser.values)[:4])
EOF
```

Ручна перевірка в desktop/web PowerPoint (доки P2 №12 не
автоматизовано, для chart-слайдів вона обов'язкова): файл
відкривається без repair dialog; правий клік на діаграмі → «Edit
Data» відкриває таблицю даних; кольори/осі/легенда відповідають spec.

Регрес: наявна production-дека мусить і далі проходити gate без нових
errors (особливо після розширення лінтів на table-шрифти в кроці 6):

```bash
.venv/bin/python .claude/skills/pptx-deck/scripts/deck_qa.py \
    specs/sia_med/sia_med.deck.json
```

### 9. Документація і синхронізація skill-дерев

1. `.claude/skills/pptx-deck/SKILL.md` двічі стверджує, що `chart`
   schema-reserved і відхиляється (опис `elements[]` та розділ
   обмежень) — оновити обидва місця описом реалізованого контракту й
   fallback-правила.
2. Після всіх правок синхронізувати дерева:

```bash
.venv/bin/python .claude/skills/pptx-deck/scripts/sync_agents.py
```

   (скрипт замінює `.agents/skills` свіжою копією `.claude/skills` —
   без цього дерева розійдуться, що план окремо забороняє).

## Тести

Стиль — `tests/test_qa_gates.py`: маленькі синтетичні spec-словники,
прямі виклики check-функцій, `_by_check`-зведення; для package-рівня —
стиль `tests/test_schema_builder_coverage.py` (зібрати, зберегти,
шукати очікувані вузли в XML). `tests/conftest.py` вже додає каталог
скриптів у `sys.path`.

Новий файл `tests/test_charts.py`:

1. `test_valid_bar_chart_spec_validates` — `build_deck.validate_spec`
   повертає `[]` для валідного chart-spec (charts не потребують
   активів, `project_root=tmp_path` достатньо).
2. `test_scatter_with_categories_is_rejected`,
   `test_bar_series_length_mismatch_is_rejected`,
   `test_bar_pair_values_are_rejected`,
   `test_emphasis_indices_out_of_range_are_rejected` — негативні
   гілки кроку 2, кожна з характерним фрагментом повідомлення.
3. `test_built_chart_is_native_chart_part` — зібрати через
   `build_deck.build`, зберегти в tmp, `zipfile`: існує
   `ppt/charts/chart1.xml`, у ньому `<c:barChart>`; для chart-слайда
   не додано жодної `ppt/media/*` картинки (антирастр-інваріант
   fallback-правила).
4. `test_series_color_emphasis_and_formats_reach_chart_xml` — у
   chart XML присутні `srgbClr val` кольору серії, `<c:dPt>` для
   точкового emphasis, `formatCode` числового формату,
   `majorGridlines`; є `<c:lineChart>`/`<c:scatterChart>` для
   відповідних типів, а scatter не містить `<c:cat>`.
5. `test_palette_discipline_traverses_chart_colors` — off-palette
   колір серії дає warn `palette_discipline`, on-palette — чисто
   (виклик `lint_deck.check_palette_discipline` з deck-токенами).
6. `test_font_budget_counts_chart_label_font` — chart-шрифт
   враховується `lint_deck.check_font_budget`.
7. `test_type_scale_covers_chart_labels` — розбіжність
   `chart.labels` з токеном `chart_label` → error `type_scale`.
8. `test_font_conformance_covers_chart_label_font` — `labels.font`
   поза lookup → error `font_conformance` (порожній lookup, файли не
   потрібні).
9. `test_glyph_coverage_covers_chart_text` — субсетнути наявний у
   репозиторії Geologica TTF до latin-only через fontTools у
   `tmp_path`, вказати lookup на нього: кириличні категорії → error
   `glyph_coverage`; повний шрифт → чисто.
10. `test_font_embedding_decision_counts_chart_fonts` — chart-шрифт
    без embed/opt-out → warn `font_embedding_decision`.
11. `test_fixture_specs_validate` — параметризовано по всіх чотирьох
    fixtures + fixture-деці: `validate_spec`/`validate_deck` чисті з
    реального checkout.

Правки наявних тестів:

- `tests/test_schema_builder_coverage.py`:
  - з `test_unimplemented_fields_reject_loudly` **прибрати**
    chart-мутацію (елемент списку з needle `"reserved"`) — інакше
    suite падає одразу після кроку 2;
  - додати chart-елемент до `maximal_spec` і тест
    `test_chart_fields(built)` — філософія suite: кожне поле схеми
    або спостережно виконується, або голосно відхиляється.

## Критерії готовності

Виведено з критерію P0 №1 («дані залишаються редагованими, а fixtures
проходять PowerPoint/LibreOffice render та visual QA»):

1. Усі чотири fixtures і fixture-дека валідуються та збираються з
   чистого checkout без помилок.
2. Діаграми в package — нативні chart parts
   (`ppt/charts/chartN.xml`); жодного растрового сурогату діаграми
   ніде в конвеєрі; PowerPoint відкриває файл без repair, «Edit Data»
   працює, повторне збереження не ламає діаграму (ручна перевірка до
   появи P2 №12).
3. `deck_qa.py` на `chart_fixtures.deck.json`: exit 0, PNG на кожен
   слайд, консолідований звіт без errors.
4. Лінти доказово бачать charts: контрольні негативні прогони
   (off-palette колір серії; labels поза `type_scale`; шрифт без
   кирилиці) дають очікувані findings — закріплено тестами.
5. `meta.visual_review` зафіксовано на кожному fixture-слайді після
   реального перегляду LibreOffice-рендерів.
6. Повний тестовий прогін зелений: нові тести + оновлений
   `test_schema_builder_coverage.py` + решта наявних.
7. Production-дека `specs/sia_med/sia_med.deck.json` проходить gate
   без нових errors (регрес розширених лінтів).
8. `.claude/skills` і `.agents/skills` синхронізовані
   (`sync_agents.py`), SKILL.md більше не називає `chart` reserved.

## Ризики

- **LibreOffice ≠ PowerPoint.** LO рендерить діаграми інакше
  (метрики шрифтів осей, авто-масштаб, відступи легенди), тож
  LO-рендер — лише проксі геометрії й палітри; розбіжності вигляду в
  LO не «фіксити» наосліп. Фінальна істина для chart-слайдів —
  PowerPoint-перевірка P2 №12; до її появи — ручний прогін з кроку 8.
- **python-pptx покриває не всі стилі** (немає керування major unit,
  gap width, trendlines, secondary axis; `bar` — лише горизонтальні
  смуги BAR_CLUSTERED). Якщо потрібного вигляду не досягти — fallback
  за планом: редагована таблиця + нативні shapes, ніколи не растр.
- **Версійна чутливість API.** Поведінку перевірено на python-pptx
  1.0.2; зокрема `chart.category_axis` для XY-діаграми повертає
  `ValueAxis` (не кидає виняток). `requirements.txt` не пінить
  версію — закріпити цей контракт тестами (пп. 3–4 «Тестів»), щоб
  апгрейд бібліотеки падав голосно.
- **Deterministic-оцінки тексту не покривають charts.**
  `check_text_fit` і `check_render_structure` лишаються
  textbox-only: довгу назву категорії може обрізати без
  попередження. Компенсація — обов'язковий visual review
  chart-слайдів; розширення оцінок на chart-підписи — кандидат у
  P1 №6, не цей етап.
- **Розширення лінтів на table-шрифти (крок 6.5) може підняти нові
  findings на наявних деках.** Тому регрес-прогін production-деки —
  окремий критерій готовності; несподівані errors розбирати, а не
  глушити.
- **Emphasis і палітра.** Контракт вимагає явний `emphasis.color`;
  дисципліну «акцент — з палітри деки» тримає
  `check_palette_discipline` (warn). Якщо практика покаже, що warn
  занадто м'який для акцентів, посилення до error — свідоме рішення
  пізніше, не зараз.
