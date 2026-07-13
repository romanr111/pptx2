# План підвищення візуальної якості презентацій

## Мета

Довести систему до стабільного створення професійних, повністю редагованих
PowerPoint-презентацій із мінімальним ручним втручанням — без перетворення
слайдів на растрові скриншоти та без підміни дизайнерського судження кількістю
декору.

Ключові вимоги клієнта: відповідність дизайну конкретного шаблону конференції
(шрифти, кольори, розташування, діаграми), єдиний стиль анатомічних зображень,
медична точність і мінімум ручних правок після генерації.

## Статус документа

Оновлено 2026-07-12 після гілки `p0-fixes` (commit `f430ead`). Первинна версія
плану була складена за аудитом стану `main` до цих виправлень; пункти, які
`p0-fixes` вже реалізувала, перенесено до розділу «Вже виконано» і виключено
з плану робіт. План передбачає, що `p0-fixes` буде змерджено в `main` перед
початком нових робіт.

Оцінка обсягу: **S** — години; **M** — 1–2 дні; **L** — кілька днів.

## Перевірений вихідний стан (на `p0-fixes`, f430ead)

- `deck_qa.py` — єдина команда delivery gate: build → per-slide lint →
  deck lint → повний рендер усіх слайдів; консолідований `qa_report.json`;
  exit 1 за будь-якого error.
- Поточна шестислайдова презентація SIA MED проходить gate: 0 помилок,
  22 slide-level і 6 deck-level попереджень, 6/6 PNG відрендерено,
  `meta.visual_review` присутній на кожному слайді.
- `render_all()` рендерить кожен слайд через PPTX → PDF → `pdftoppm`
  (~2560 px), кешує за хешем файлу; невдалий рендер або відсутній `.pptx`
  провалює QA.
- Visual review — структурований артефакт `meta.visual_review`
  (iteration, verdict, findings); verdict `fail` або iteration > 3 —
  lint error.
- Provenance sidecars обов'язкові для зовнішніх зображень (невалідний або
  неповний sidecar — error); font-embedding — явне рішення з gate;
  AI-згенеровані зображення вимагають зафіксованого review.
- `lint_deck` перевіряє палітру деки (`palette_roles`), `type_scale`,
  бюджети шрифтів/елементів із обґрунтуванням overrides.
- `.claude/skills` і `.agents/skills` синхронізовані (`sync_agents.py`);
  розбіжностей немає.
- `tests/test_qa_gates.py`: 72 тести проходять.
- Charts досі відхиляються builder-ом як reserved; production-візуального
  fixture для таблиць і діаграм немає.
- 12 top-level production specs — приватні клієнтські матеріали, свідомо
  виключені з репозиторію через `.gitignore` («never publish»). Це не
  зламані fixtures; бракує саме публічних self-contained fixtures.

## Вже виконано (виключено з плану робіт)

| Пункт первинного плану | Стан |
| --- | --- |
| P0 №1 «Єдиний delivery gate» | Реалізовано як `deck_qa.py` |
| P0 №2 «Повний рендер деки» | Реалізовано як `render_all()`; залишок — перевірка кількості сторінок і montage/manifest (новий P0 №4) |
| P0 №3 «Цикл візуальної критики» | Інструментальна частина реалізована (структурований артефакт + ліміт ітерацій + gate); залишок — розширений формат findings (новий P1 №9) |
| P0 №4 «Workflow вибору зображень» | Briefs, provenance, licensing і AI-review gate вже існують; резолвер свідомо agent-operated — скрипт не викликає web/gen API. Залишок — contact sheet кандидатів (новий P1 №10) |
| P1 №8 «Drift `.claude`/`.agents`» | Синхронізовано через `sync_agents.py`; залишок — CI-перевірка (новий P1 №11) |

## P0 — найбільша цінність для клієнта

### 1. Нативні діаграми та перевірені таблиці — **L**

**Проблема:** charts відхиляються builder-ом як нереалізовані, а таблиці не
мають production-візуального baseline. Медичні презентації клієнта —
data-heavy; без редагованих діаграм ручна робота не зникає.

**Зміна:** реалізувати мінімальний набір editable charts:

- bar;
- line;
- scatter.

Додати керування insight emphasis, labels, number formats, axes, grids і
legends. Створити self-contained fixtures для таблиці й кожного типу діаграми.

**Деталі реалізації:**

- `chart` уже присутній в enum типів елементів (`specs/spec.schema.json`,
  `$defs.element`); заборона — гілка `el["type"] == "chart"` у валідаторі
  `build_deck.py`. Зняти її і додати `build_chart()` у dispatch
  `add_slide_from_spec` поруч із `build_table`.
- Розширити `$defs.element` payload-контрактом:
  `chart_type` (`bar`|`line`|`scatter`), `categories`, `series`
  (`name`, `values`, `color`), `x_axis`/`y_axis` (`title`,
  `number_format`, `grid`), `legend` (`visible`, `position`),
  `data_labels` (`visible`, `number_format`), `emphasis`
  (`series`, `point`) — акцентна серія/точка кольором з палітри.
- Реалізація: python-pptx `shapes.add_chart` +
  `XL_CHART_TYPE.BAR_CLUSTERED` / `LINE` / `XY_SCATTER`;
  `CategoryChartData` для bar/line, `XyChartData` для scatter
  (окрема гілка — scatter не має categories).
- Кольори серій зобов'язані походити з `tokens.palette_roles`:
  `check_palette_discipline` у `lint_deck.py` має обходити і
  chart-елементи. Шрифти підписів — з `tokens.type_scale`; перевірка
  glyph coverage (кирилиця) стосується і chart-шрифтів.
- Відоме обмеження: LibreOffice рендерить діаграми інакше, ніж
  PowerPoint, а python-pptx покриває не всі стилі. Тому fixtures
  проходять обидва рендери, а PowerPoint-перевірка (P2 №12)
  обов'язкова саме для chart-слайдів.
- Fixtures: `specs/lint_test_fixtures/chart_bar.spec.json`,
  `chart_line.spec.json`, `chart_scatter.spec.json`,
  `table_baseline.spec.json` — самодостатні, без клієнтських матеріалів.

**Критерій готовності:** дані залишаються редагованими, а fixtures проходять
PowerPoint/LibreOffice render та visual QA.

### 2. Онбординг шаблону конференції як конвеєр — **M**

**Проблема:** шаблони змінюються від конференції до конференції — це головна
складність клієнта. Система знає геометрію й тему шаблону, але немає
відтворюваної процедури «новий шаблон → готовий facts layer», і обов'язковий
`out/template_visual_catalog.json` ніде не перевіряється на наявність та
актуальність.

**Зміна:** оформити онбординг нового шаблону як одну процедуру:

1. новий `.pptx` шаблон → `inventory` → `template_style` →
   `template_visual_catalog`;
2. freshness gate: якщо каталог відсутній або старіший за шаблон —
   помилка в `deck_qa`;
3. каталог фіксує representative layouts, recurring components, color
   modes, recurring assets і приклади section/content/data/closing слайдів.

**Деталі реалізації:**

- Сьогодні `inventory.py` → `out/assets.json`, `template_style.py` →
  `out/template_style.json` (`fonts_used_ranked`,
  `explicit_colors_ranked`, `layouts`, `slide_layout_map`,
  `media_reuse_ranked`), а каталог пишеться людиною/агентом без скелета.
- Нова команда `onboard_template.py <template.pptx>`: запускає
  inventory → template_style, генерує скелет каталогу з
  `layouts_observed`/`palette_observed` і порожніми полями для
  агентського заповнення.
- Freshness gate: додати `template_sha256` у
  `template_visual_catalog.json` і `template_style.json` (зараз там
  лише `template_file: "template.pptx"` без хешу; прецедент —
  `styleguide_profile.json` уже має `source_hash`). `deck_qa` звіряє
  хеш із фактичним файлом шаблону: відсутній каталог або невідповідний
  хеш — error.

**Критерій готовності:** новий шаблон онбордиться без зміни коду; кожен слайд
посилається на template layout/component або містить пояснення свідомого
відхилення.

### 3. Єдиний стиль анатомічних зображень — **M**

**Проблема:** клієнт явно вимагає єдиного стилю анатомічних ілюстрацій у межах
презентації. Зараз є `styleguide_profile.json` і review gate для
AI-згенерованих зображень, але жодна перевірка не дивиться на стильову
узгодженість набору зображень деки як цілого.

**Зміна:**

1. додати deck-level перевірку стильової узгодженості зображень
   (advisory warn: рознобій ілюстративних стилів, кольорових гам,
   фонів між анатомічними зображеннями);
2. зробити стильову узгодженість обов'язковим пунктом sequence-level
   visual review (фіксується в артефакті, не мається на увазі);
3. image briefs для анатомічних ілюстрацій успадковують style constraints
   зі styleguide profile.

**Деталі реалізації:**

- Нове поле `image_brief.category`
  (`anatomical` | `clinical_photo` | `chart` | `decor`) у briefs і
  provenance sidecars — перевірка порівнює лише порівнюване.
- `check_image_style_coherence` у `lint_deck.py` (advisory): для кожного
  розміщеного зображення категорії `anatomical` обчислити дескриптор
  наявними PIL/numpy — медіанні hue/saturation, edge density
  (line-art проти фото), рівномірність фону по периметру; warn, якщо
  дескриптори розпадаються на кластери.
- Успадкування стилю: `asset_resolver.py plan` підставляє
  `image_brief_defaults` і `visual_rules` зі
  `styleguide_profile.json` у кожен anatomical brief.
- Sequence-level review: нове `meta.sequence_review` у deck spec —
  аналог per-slide `meta.visual_review` (iteration, verdict, findings)
  з обов'язковим пунктом `style_coherence`; verdict `fail` → error у
  `lint_deck`.

**Критерій готовності:** розбіжність стилю зображень неможливо не помітити —
вона або виправлена, або явно прийнята людиною в review-артефакті.

### 4. Закрити залишкові дірки delivery gate — **S**

**Проблема:** `deck_qa` записує кількість відрендерених PNG, але не порівнює
її з кількістю слайдів деки — тихо втрачена сторінка не провалює gate.
Montage і manifest із хешами артефактів не створюються.

**Зміна:**

1. кількість PNG != кількості слайдів — hard failure;
2. створювати montage всієї деки для людського перегляду;
3. записувати manifest із хешами артефактів delivery-версії.

**Деталі реалізації:**

- У кроці 5 `deck_qa.py` порівняти `len(pngs)` з
  `len(deck["slides"])`; невідповідність → `ok=False` + total_error
  (зараз `n_slides` лише записується у звіт).
- Montage: нова функція в `render.py` (PIL: сітка 3×N, номер слайда під
  кожним кадром) → `output/rendered/<stem>_qa/montage.png`.
- Manifest: `manifest.json` поруч із montage — sha256 деки `.pptx`,
  проміжного PDF і кожного PNG (хеш-функція `_file_hash` уже є в
  `render.py`), версії `soffice`/`pdftoppm`, час, git commit. Це та
  сама структура, яку P2 №13 розширює полями людського sign-off.

**Критерій готовності:** відсутня сторінка — помилка gate; одна команда
залишає montage і manifest поруч із `qa_report.json`.

## P1 — якість і надійність

### 5. Обов'язковий narrative outline і контроль джерел — **M**

**Проблема:** production deck уже містить `meta.outline` (purpose,
source_blocks, вільнотекстовий `layout_reference`) і
`meta.unplaced_material` — але як добровільну конвенцію: контракту в
схемі немає, `meta.sources` не фіксується, і жоден lint не перевіряє
покриття джерел чи повноту полів.

**Зміна:** зробити обов'язковими:

- purpose кожного слайда;
- source blocks;
- layout reference;
- placed/unplaced material;
- пояснення скорочень і текстових змін.

**Деталі реалізації:**

- Контракт `meta.outline` у deck spec (`deck.schema.json`, `meta` зараз
  без фіксованих полів):
  - `slides[]`: `stem`, `purpose`, `source_blocks[]`,
    `layout_ref` (посилання на layout/component з
    `template_visual_catalog.json`);
  - `unplaced[]`: `source`, `reason`;
  - `text_edits[]`: `slide`, `was`, `now`, `why`.
- Нова перевірка `check_outline_coverage` у `lint_deck.py`: error, якщо
  outline відсутній; warn — слайд без `purpose`/`source_blocks` або
  source block, не згаданий ні в slides, ні в unplaced.
- Перелік вихідних матеріалів — нове `meta.sources[]` (шлях + опис),
  щоб покриття було перевірюваним, а не декларативним.

**Критерій готовності:** кожен блок вихідного матеріалу використаний або явно
позначений як пропущений із причиною.

### 6. Розширити deterministic QA — **M**

Вже існують: contrast, glyph coverage, text fit, bbox overlap, watermark,
точні дублікати, package size, provenance, font embedding, render structure.

Додати перевірки (у дужках — механіка):

- effective image DPI (`px_width / (box.cx / 914400)`; warn нижче
  ~110 dpi при еталоні повного слайда 2560 px);
- небажане aspect-ratio distortion (аспект файлу проти аспекту box при
  `fit: "stretch"` — `add_picture_fitted` уже знає режим fit; warn при
  відхиленні понад ~2%);
- видимі межі або невідповідний фон вставленого зображення (кольорова
  відстань смуги 4–8 px по периметру зображення до фону слайда;
  пов'язано з `seamless_hero.py`);
- package/OOXML integrity (`zipfile.testzip()` + повторне відкриття
  python-pptx після `apply_packaging` — `native_packaging.py` редагує
  zip вручну, саме там ризик пошкодження);
- font substitution (`pdffonts` з poppler — уже в залежностях — по
  проміжному PDF із `render_all`; шрифт поза списком spec = warn);
- perceptual near-duplicates (dHash на наявних PIL/numpy, без нової
  залежності, поруч із точними дублікатами в
  `check_asset_duplication`).

Whitespace, hierarchy, balance, visual rhythm, density і shape count повинні
залишатися advisory, а не hard failures.

### 7. Виправити шумні deck-level heuristics — **S**

**Проблема:** `check_role_alignment` збирає всі textbox одного role по всій
деці й вимагає однієї координати `x` — багатоколонкові та процесні розкладки
дають хибні попередження.

**Зміна:** перевіряти alignment у межах семантичної групи або grid pattern,
а не лише за однаковим `role`.

**Деталі реалізації:**

- Додати необов'язкове поле `group` до `$defs.element` (елементи зараз
  мають лише `id`, `type`, `role`, `z`, `box`): елементи однієї групи
  перевіряються як сітка, а не як один стовпчик.
- Без явної групи: кілька елементів одного role на одному слайді
  трактуються як колонки — відсортувати x, перевірити рівномірність
  кроку (±2%) і збіг першої колонки між слайдами, замість вимоги
  однієї x для всіх.

**Критерій готовності:** linter знаходить реальні зсуви, але не скаржиться на
навмисні колонки, картки та послідовності.

### 8. Публічні синтетичні fixtures — **M**

**Проблема:** клієнтські матеріали свідомо не публікуються, тому з чистого
публічного checkout пайплайн нема на чому відтворювано перевіряти. Це
навмисне обмеження, а не дефект — але воно вимагає окремих синтетичних
fixtures.

**Зміна:** створити self-contained fixtures без клієнтських матеріалів і
позначити всі fixtures як:

- `production`;
- `regression`;
- `intentionally_broken`.

Додати fixtures для таблиці, chart, щільного evidence slide, image-led slide,
section transition і closing slide.

**Деталі реалізації:**

- Маркер `meta.fixture_kind` у spec; тестовий раннер у `tests/` збирає
  всі `production`/`regression` fixtures і вимагає, щоб кожен
  `intentionally_broken` падав із очікуваним check id (за зразком
  наявних `broken_example` / `shape_fit_smoketest`).
- Розкладання: негативні та regression — у `specs/lint_test_fixtures/`;
  production-подібні синтетичні — у новому `specs/showcase/` з активами
  в `assets/fixtures/` (згенеровані плейсхолдери, ліцензійно чисті).
- Синтетичний «шаблон конференції» (нейтральний .pptx) — щоб онбординг
  P0 №2 теж мав публічний тест.

**Критерій готовності:** усі публічні fixtures збираються з чистого checkout;
негативні fixtures падають із очікуваною діагностикою.

### 9. Розширений формат visual findings — **S**

**Проблема:** `meta.visual_review` вже структурований (iteration, verdict,
findings), але findings не мають severity, доказів і ознаки автоматизованості;
немає окремого sequence-level review всієї деки.

**Зміна:** кожне finding повинно містити:

- номер слайда;
- елемент або область;
- severity: `blocker`, `major`, `minor` або `observation`;
- видимий доказ;
- рекомендоване виправлення;
- confidence;
- ознаку, чи безпечно автоматизувати виправлення.

Додати sequence-level review (уся дека як послідовність: наскрізна
узгодженість, ритм, переходи). Зберігати before/after montage між ітераціями.

**Деталі реалізації:**

- Розширити `check_visual_review` (`lint_render.py`): нові поля finding
  `severity` (enum), `area`, `evidence` (шлях до crop PNG),
  `recommended_fix`, `confidence` (0–1), `auto_fixable` (bool);
  unresolved `blocker`/`major` → error (зараз error дає лише
  verdict `fail`).
- Sequence-level review living у `meta.sequence_review` deck spec —
  спільний артефакт із P0 №3.
- Між ітераціями зберігати `montage_iter<N>.png` (montage з P0 №4) для
  before/after порівняння.

**Критерій готовності:** немає unresolved blocker/major findings або вони явно
передані на людський review з поясненням ризику.

### 10. Contact sheet для кандидатів зображень — **S**

**Проблема:** briefs, provenance, licensing і AI-review gate вже існують, а
резолвер свідомо agent-operated (скрипт не викликає web/gen API — пошук і
візуальне порівняння виконує агент). Але порівняння кандидатів не має
стандартного артефакту.

**Зміна:** генерувати contact sheet кандидатів для кожного image brief і
фіксувати причини вибору та відхилення. Порядок джерел незмінний:
user-provided → template → approved project assets → web → AI generation
лише після невдалого пошуку.

**Деталі реалізації:**

- Нова підкоманда `asset_resolver.py contact-sheet <brief_id>`:
  кандидати з `out/briefs/<brief_id>/candidates/` → сітка з підписами
  (індекс, розміри, джерело) → `out/briefs/<brief_id>_contact.png`.
- Причини вибору/відхилення — у наявний report-механізм резолвера
  (`selected_rationale` уже обов'язкове поле provenance sidecar);
  додати `rejected[]`: `candidate`, `reason`.

**Критерій готовності:** кожне зовнішнє зображення має brief, provenance,
licensing status, verification notes і візуально обґрунтований вибір.

### 11. CI-перевірка синхронізації skill-дерев — **S**

`sync_agents.py` існує, але вміє лише копіювати. Додати режим
`sync_agents.py --check` (порівняння дерев із ігноруванням `__pycache__`,
exit 1 за розбіжності) і тест у `tests/`, який його викликає — будь-яка
змістовна розбіжність `.claude/skills` та `.agents/skills` завершує
тестовий прогін помилкою.

## P2 — після стабілізації основного циклу

### 12. PowerPoint-specific final QA

Додати фінальну перевірку у desktop або web PowerPoint:

- відкриття без repair dialog;
- відсутність небажаного font substitution;
- коректні crops, tables і charts;
- правильний порядок animations;
- збереження editability після повторного save.

**Деталі реалізації:** на macOS — автоматизація Microsoft PowerPoint через
`osascript` (відкрити, зберегти як копію, закрити); пересохранений файл
проганяється через той самий `deck_qa` — розбіжності проти оригіналу
(structure, рендер) і є сигналом. Обов'язково для chart-слайдів (див. P0 №1).

### 13. QA manifest і людський sign-off

Для кожної delivery-версії зберігати:

- spec hash;
- render hashes;
- lint reports;
- vision findings;
- asset provenance;
- text edits;
- unresolved warnings;
- PowerPoint verification;
- статус фінального reviewer.

**Деталі реалізації:** розширення `manifest.json` з P0 №4 полями
`reviewed_by`, `review_date`, `verdict`, `unresolved[]` — не окремий формат.

## Залежності та ризики

- P0 №4 (manifest) — основа для P2 №13; P0 №3 і P1 №9 ділять
  `meta.sequence_review`; P1 №8 дає публічний тест для P0 №2.
- python-pptx обмежує тонке стилювання діаграм; якщо потрібного вигляду
  не досягти — fallback: редагована таблиця + нативні shapes, але не
  растрове зображення діаграми.
- LibreOffice-рендер — не PowerPoint: для charts і embedded fonts
  фінальна істина — P2 №12; до того LO-рендер вважається достатнім
  проксі для геометрії й палітри.
- Онбординг шаблону припускає, що шлях до активного шаблону
  зафіксований (канонічно — `assets/template.pptx`, це
  `DEFAULT_TEMPLATE` у `template_style.py`); якщо шаблонів стане
  кілька одночасно, знадобиться `out/` на кожен шаблон — поза скоупом
  цього плану.

## Короткий план реалізації

Кожен етап має окрему робочу інструкцію з покроковими змінами,
контрактами, тестами й ризиками:

- Етап 1 — `docs/VISUAL_QUALITY_PHASE_1_UA.md`;
- Етап 2 — `docs/VISUAL_QUALITY_PHASE_2_UA.md`;
- Етап 3 — `docs/VISUAL_QUALITY_PHASE_3_UA.md`;
- Етап 4 — `docs/VISUAL_QUALITY_PHASE_4_UA.md`.

### Етап 1 — розширити професійні можливості (P0 №1)

1. Реалізувати editable bar/line/scatter charts.
2. Додати table/chart fixtures.
3. Прогнати через наявний gate і visual QA.

**Результат:** система підтримує реальні data-heavy медичні презентації.

### Етап 2 — template fidelity та стиль зображень (P0 №2–3)

1. Оформити онбординг шаблону як одну процедуру.
2. Додати freshness gate для template visual catalog.
3. Додати перевірку єдиного стилю анатомічних зображень.

**Результат:** нова конференція = новий шаблон онбордиться відтворювано;
головні вимоги клієнта перевіряються, а не маються на увазі.

### Етап 3 — дозакрити gate і цикл критики (P0 №4, P1 №9)

1. Page-count hard failure, montage, manifest.
2. Розширений формат visual findings і sequence-level review.

**Результат:** gate не має тихих дірок; visual QA повністю відтворюваний.

### Етап 4 — входи, fixtures і шум (P1 №5–8, №10–11)

1. Обов'язковий outline і source coverage.
2. Публічні синтетичні fixtures.
3. Розширений deterministic QA і виправлення шумних heuristics.
4. Contact sheet кандидатів; CI-перевірка синхронізації skills.

**Результат:** дизайн-рішення простежувані, репозиторій відтворюваний з
чистого checkout, попередження знову інформативні.

## Рекомендована послідовність

Найкоротший шлях до відчутного результату для клієнта:

1. charts і table fixtures;
2. онбординг шаблону конференції + freshness gate каталогу;
3. єдиний стиль анатомічних зображень;
4. page-count hard failure + montage/manifest;
5. решта P1 у порядку №5 → №11.

Перші три зміни закривають найбільші розриви між системою і заявленими
потребами клієнта: data-heavy слайди, змінювані шаблони конференцій і
узгоджені анатомічні ілюстрації. Решта зміцнює відтворюваність і зменшує
потребу в ручній роботі.
