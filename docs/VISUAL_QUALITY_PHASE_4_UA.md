# Етап 4 — входи, fixtures і шум (робоча інструкція)

## Зв'язок із планом

Цей документ — робоча інструкція для «Етапу 4» з
`docs/VISUAL_QUALITY_IMPROVEMENT_PLAN_UA.md`. Він консолідує пункти P1:

- №5 «Обов'язковий narrative outline і контроль джерел» — **M**;
- №6 «Розширити deterministic QA» — **M**;
- №7 «Виправити шумні deck-level heuristics» — **S**;
- №8 «Публічні синтетичні fixtures» — **M**;
- №10 «Contact sheet для кандидатів зображень» — **S**;
- №11 «CI-перевірка синхронізації skill-дерев» — **S**.

Деталі реалізації в майстер-плані для цих пунктів уже досить конкретні,
тому тут вони переважно перевпорядковані в покрокові чеклісти; нове
додано лише там, де майстер-план залишає очевидну прогалину (такі місця
позначені як «зауваження»).

Залежності від попередніх етапів:

- №5 (`layout_ref` в outline) посилається на
  `out/template_visual_catalog.json` і його freshness gate — Етап 2
  (P0 №2);
- chart-фікстура з №8 залежить від editable charts — Етап 1 (P0 №1);
  якщо Етап 1 не завершено, chart-фікстура відкладається, решта №8 не
  блокується;
- сітка montage з Етапу 3 (P0 №4) не є передумовою жодного пункту тут,
  але contact sheet (№10) використовує ту саму PIL-механіку сітки.

## Рекомендований порядок

1. **№7** — S-обсяг, чистий локальний фікс `check_role_alignment`.
   Знімає найгучніше джерело хибних deck-level попереджень *до* того,
   як №6 додасть нові перевірки: нові advisory-сигнали мають лягати на
   тихий базовий рівень, інакше шум знову з'їсть інформативність.
2. **№11** — S-обсяг. Майже всі наступні пункти етапу правлять скрипти
   в `.claude/skills/pptx-deck/scripts/`; режим `--check` +
   обов'язковий тест страхують від розбіжності дерев `.claude/skills`
   і `.agents/skills` протягом усього етапу.
3. **№8** — розблоковує відтворювану перевірку з чистого публічного
   checkout і дає раннер, у який №6 підключає свої негативні fixtures,
   а №5 — showcase-деку з заповненим outline.
4. **№6** — нові детерміновані перевірки; їхні негативні тести
   оформлюються як `intentionally_broken` fixtures у механіці №8.
5. **№10** — незалежний S-обсяг у `asset_resolver.py`; можна виконувати
   паралельно з №6.
6. **№5** — останнім, бо `layout_ref` спирається на
   `template_visual_catalog` з Етапу 2, а заповнення outline для
   production-деки — найбільша процесна (не кодова) зміна етапу.

---

## №7 — виправити шумні deck-level heuristics — **S**

Сьогодні `check_role_alignment` у
`.claude/skills/pptx-deck/scripts/lint_deck.py` збирає всі textbox
одного `role` по всій деці й вимагає однієї координати `x`
(толеранс — 1% ширини слайда). Багатоколонкові та процесні розкладки
дають хибні попередження.

### Кроки

1. `specs/spec.schema.json`, `$defs.element`: додати необов'язкове
   поле `group` (string). Зараз елемент має лише `id`, `type`, `role`,
   `z`, `box`.
2. `lint_deck.py`, `check_role_alignment` — переписати логіку пулу:
   - групувати спочатку за слайдом, потім за `role`, а не однією купою
     по всій деці;
   - кілька елементів одного `role` на одному слайді трактувати як
     колонки: відсортувати `x`, перевірити рівномірність кроку (±2%)
     і збіг першої колонки між слайдами (наявний толеранс `tol`
     залишити), замість вимоги однієї `x` для всіх;
   - елементи зі спільним `group` перевіряти як сітку (рівні кроки,
     спільна базова `x` між слайдами), а не як один стовпчик.
3. Переконатися, що builder і валідатор приймають нове поле `group`
   (спека валідується проти `spec.schema.json` — тому крок 1
   обов'язковий і достатній).
4. Запустити `sync_agents.py` після правок.

### Тести

- Unit-тести в `tests/test_qa_gates.py`:
  - дві колонки з рівним кроком, повторені на кількох слайдах — без
    warn;
  - реальний зсув однієї колонки понад толеранс — warn;
  - явна `group`-сітка з рівними кроками — без warn.
- Перегнати `deck_qa.py` на поточній production-деці: очікуване
  зменшення deck-level попереджень (сьогодні 6) без втрати сигналів
  про реальні зсуви.

### Критерій готовності

Linter знаходить реальні зсуви, але не скаржиться на навмисні колонки,
картки та послідовності.

---

## №11 — перевірка синхронізації skill-дерев — **S**

`.claude/skills/pptx-deck/scripts/sync_agents.py` сьогодні вміє лише
копіювати (`shutil.rmtree` + `copytree`, зачистка `__pycache__`);
режиму порівняння немає.

### Кроки

1. Винести порівняння дерев у функцію (наприклад,
   `trees_differ(src, dst)`), яку можна викликати з тесту на
   `tmp_path`: порівняння набору відносних шляхів і вмісту файлів
   (хеш або `filecmp`), з ігноруванням `__pycache__` (і побічних
   файлів на кшталт `.pyc`, `.DS_Store`).
2. Додати argparse із прапорцем `--check`: без прапорця — наявна
   поведінка копіювання; з `--check` — тільки порівняння, exit 1 і
   список розбіжностей у stdout.
3. Тест у `tests/` (новий `test_sync_agents.py` або секція в
   `test_qa_gates.py`):
   - викликає `sync_agents.py --check` subprocess-ом на реальних
     деревах репозиторію — будь-яка змістовна розбіжність
     `.claude/skills` і `.agents/skills` провалює тестовий прогін;
   - негативний тест на `tmp_path`-копіях дерев зі штучною
     розбіжністю — очікується ненульовий код/`trees_differ() == True`.

Зауваження (план проти коду): у репозиторії поки немає CI-конфігурації
(`.github/workflows/` відсутній), тож «CI-перевірка» на цьому етапі
означає обов'язковий тест у pytest-прогоні; коли CI з'явиться, тест
підхопиться автоматично без додаткової роботи.

### Критерій готовності

Будь-яка змістовна розбіжність `.claude/skills` та `.agents/skills`
завершує тестовий прогін помилкою.

---

## №8 — публічні синтетичні fixtures — **M**

Клієнтські матеріали свідомо не публікуються (12 top-level production
specs — у `.gitignore`), тому з чистого публічного checkout пайплайн
нема на чому відтворювано перевіряти. Наявні
`specs/lint_test_fixtures/broken_example.spec.json` і
`shape_fit_smoketest.spec.json` мають лише `meta.note` і — зауваження
(план проти коду) — **ніде не підключені до тестів**: жоден файл у
`tests/` їх не запускає, тож раннер нижче — повністю нова механіка, а
наявні fixtures — лише зразок стилю.

### Кроки

1. Маркер `meta.fixture_kind` у spec:
   `production` | `regression` | `intentionally_broken`. Для
   `intentionally_broken` — додатково `meta.expected_failures[]` зі
   списком очікуваних check id (наприклад `font_conformance`,
   `text_fit`, `bbox_overlap`), щоб раннер перевіряв діагностику, а не
   лише факт падіння.
2. Позначити наявні fixtures: `broken_example` →
   `intentionally_broken` + expected ids; `shape_fit_smoketest` →
   `regression`.
3. Новий раннер у `tests/` (наприклад, `test_fixtures.py`):
   - збирає всі specs із `fixture_kind`;
   - `production`/`regression` мають проходити build
     (`build_deck.py`) і lint (`lint_render.py`) без errors;
   - кожен `intentionally_broken` мусить падати саме з очікуваними
     check id.
4. Розкладання: негативні та regression — у
   `specs/lint_test_fixtures/`; production-подібні синтетичні — у
   новому `specs/showcase/` з активами в `assets/fixtures/`
   (згенеровані плейсхолдери, ліцензійно чисті).
5. Нові showcase-fixtures: таблиця, chart (після Етапу 1), щільний
   evidence slide, image-led slide, section transition, closing slide.
6. Синтетичний нейтральний «шаблон конференції» (.pptx) — щоб
   онбординг Етапу 2 теж мав публічний тест.
7. Переконатися, що fixtures не посилаються на клієнтські чи
   gitignored шляхи: збірка з чистого checkout — частина перевірки
   (клон у тимчасовий каталог → pytest).

### Тести

- Сам раннер `test_fixtures.py` (позитивні й негативні гілки).
- Smoke з чистого checkout: `git clone` у тимчасовий каталог →
  прогін раннера / `deck_qa.py` на showcase-деці.

### Критерій готовності

Усі публічні fixtures збираються з чистого checkout; негативні
fixtures падають з очікуваною діагностикою.

---

## №6 — розширити deterministic QA — **M**

Вже існують: contrast, glyph coverage, text fit, bbox overlap,
watermark, дублікати, package size, provenance, font embedding, render
structure. Per-slide перевірки живуть у
`.claude/skills/pptx-deck/scripts/lint_render.py` (нові — поруч із
`check_asset_inventory` / `check_asset_duplication`); package
integrity — у build-шляху; font substitution — на рівні рендеру.

### Кроки

1. `check_image_dpi` (`lint_render.py`, warn): для кожного
   image-елемента ефективний DPI = `px_width / (box.cx / 914400)`;
   warn нижче ~110 dpi при еталоні повного слайда 2560 px. Розміри —
   з `out/assets.json` (наявний `check_asset_inventory` вже підсвічує
   неінвентаризовані активи) або напряму через PIL.
2. `check_aspect_distortion` (`lint_render.py`, warn): лише для
   `fit: "stretch"` (режим fit відомий — `add_picture_fitted` у
   `build_deck.py`; `contain`/`cover` спотворень не дають) порівняти
   аспект файлу з аспектом box; warn при відхиленні понад ~2%.
   Зауваження: врахувати media_opt-гілку `_optimize_image`, яка після
   cover-bake повертає effective fit `stretch` для вже обрізаного
   файлу — такий випадок легітимний, перевіряти слід режим зі spec.
3. `check_edge_mismatch` (`lint_render.py`, warn): кольорова відстань
   смуги 4–8 px по периметру зображення до фону слайда — видимі межі
   чи невідповідний фон вставки; узгодити з `seamless_hero.py`
   (оброблені ним hero-зображення мають проходити чисто).
4. `check_package_integrity` (error): `zipfile.testzip()` + повторне
   відкриття python-pptx одразу після `apply_packaging` у
   `build_deck.py` — `native_packaging.py` редагує zip вручну, саме
   там ризик пошкодження пакета.
5. `check_font_substitution` (warn): `pdffonts` (poppler, вже у
   залежностях) по проміжному PDF із `render_all` у `render.py`;
   шрифт поза списком spec — warn. Додати `pdffonts` до
   `check_external_tools` у `deck_qa.py` (зараз там `soffice`,
   `pdftoppm`, `textutil`).
6. Perceptual near-duplicates (warn): dHash на наявних PIL/numpy, без
   нової залежності, поруч із наявною перевіркою в
   `check_asset_duplication`. Зауваження (план проти коду): наявна
   перевірка — per-slide у `lint_render.py` і порівнює виміряні поля
   з `assets.json` (size/mode/alpha/dominant colors), а не байтові
   хеші; «точні дублікати» у майстер-плані слід читати саме так —
   dHash доповнює її перцептивним порівнянням.
7. Усі нові перевірки — advisory warn, окрім package integrity
   (error). Whitespace, hierarchy, balance, visual rhythm, density і
   shape count залишаються advisory.
8. Після впровадження перегнати production-деку через `deck_qa.py` і
   відкалібрувати пороги (~110 dpi, ~2%), щоб не створити нову хвилю
   шуму. Запустити `sync_agents.py`.

### Тести

- Негативні fixtures у `specs/lint_test_fixtures/` на кожну
  перевірку (низький DPI, stretch зі спотворенням, зображення з
  видимими межами, підмінений шрифт), підключені до раннера №8 через
  `intentionally_broken` + expected check id.
- Unit-тести в `tests/test_qa_gates.py` для порогів і країв (contain
  проти stretch, hero після `seamless_hero.py`, near-dup проти
  справді різних зображень).
- Позитивний прогін: поточна production-дека проходить gate без нових
  errors.

### Критерій готовності

(Майстер-план явного критерію для №6 не дає; похідний.) Кожна з шести
перевірок має позитивний і негативний тест; production-дека проходить
gate без нових errors; нові сигнали — advisory, окрім package
integrity.

---

## №10 — contact sheet для кандидатів зображень — **S**

Briefs, provenance, licensing і AI-review gate вже існують;
`asset_resolver.py` — agent-operated (підкоманди `plan` / `import` /
`report`; web/gen-роботу виконує агент). Бракує стандартного артефакту
порівняння кандидатів.

Зауваження (план проти коду): каталог
`out/briefs/<brief_id>/candidates/` з майстер-плану сьогодні **не
існує** — `command_plan` повертає кандидатів лише як JSON-записи
(`local_candidates`, `template_candidates`), а web-кандидатів агент
завантажує в довільне місце. Конвенцію каталогу треба спершу створити
й закріпити у workflow (SKILL.md), інакше contact sheet буде порожнім.

### Кроки

1. Зафіксувати конвенцію: агент складає завантажених/відібраних
   кандидатів у `out/briefs/<brief_id>/candidates/` (оновити SKILL.md
   пайплайна в частині image-briefs workflow).
2. Нова підкоманда `contact-sheet <spec> --brief-id <id>` у `main()`
   `asset_resolver.py`: читає каталог кандидатів, будує PIL-сітку з
   підписами (індекс, розміри, джерело/ім'я файлу) →
   `out/briefs/<brief_id>_contact.png`.
3. Причини вибору/відхилення: `selected_rationale` вже обов'язкове
   поле provenance sidecar (`command_import`, перевіряється
   `provenance_status`); додати `rejected[]` (`candidate`, `reason`)
   у sidecar — повторюваний аргумент `--rejected` для
   `command_import` — і показувати його в `command_report`.
4. Порядок джерел незмінний: user-provided → template → approved
   project assets → web → AI generation лише після невдалого пошуку.
   Contact sheet цей порядок не змінює — лише документує вибір.

### Тести

- `tests/test_asset_resolver.py`: contact sheet із tmp-каталогом
  кандидатів (2–3 згенеровані PIL-плейсхолдери) → PNG створено,
  сітка містить усіх кандидатів; brief без кандидатів → зрозуміла
  помилка, а не порожній файл.
- `import` з `--rejected` → sidecar містить `rejected[]`;
  `report` його відображає.

### Критерій готовності

Кожне зовнішнє зображення має brief, provenance, licensing status,
verification notes і візуально обґрунтований вибір.

---

## №5 — обов'язковий narrative outline і контроль джерел — **M**

Production deck уже містить `meta.outline` (purpose, source_blocks,
вільнотекстовий `layout_reference`) і `meta.unplaced_material` — але
як добровільну конвенцію: контракту в схемі немає, `meta.sources` не
фіксується, і жоден lint не перевіряє покриття. Пункт формалізує
наявну практику, а не вводить її з нуля. `meta` у
`specs/deck.schema.json` сьогодні — вільний об'єкт
(`additionalProperties: true`) без фіксованих полів.

### Кроки

1. Контракт `meta.outline` у `specs/deck.schema.json`:
   - `slides[]`: `stem`, `purpose`, `source_blocks[]`, `layout_ref`
     (посилання на layout/component з
     `out/template_visual_catalog.json` — залежність від Етапу 2);
   - `unplaced[]`: `source`, `reason`;
   - `text_edits[]`: `slide`, `was`, `now`, `why`.
2. `meta.sources[]` (шлях + опис вихідних матеріалів) — щоб покриття
   було перевірюваним, а не декларативним.
3. `check_outline_coverage` у `lint_deck.py` (реєструється в
   `lint_deck()` поруч з іншими deck-перевірками):
   - error — outline відсутній;
   - warn — слайд без `purpose`/`source_blocks`;
   - warn — source з `meta.sources` не згаданий ні в
     `slides[].source_blocks`, ні в `unplaced[]`;
   - advisory warn — `layout_ref`, якого немає в каталозі (доки
     Етап 2 не завершено, перевірка відповідності каталогу
     залишається advisory; обов'язковість самого поля — одразу).
4. Оновити pptx-designer skill: авторство outline — обов'язковий крок
   дизайнера; заповнити `meta.outline` і `meta.sources` для поточної
   production-деки та showcase-деки з №8. Запустити `sync_agents.py`.

### Тести

- Unit-тести в `tests/test_qa_gates.py`: відсутній outline → error;
  повний outline → clean; непокритий source → warn; слайд без
  purpose → warn.
- Showcase-дека з №8 має заповнений outline — раннер №8 перевіряє
  його разом з рештою lint.

### Критерій готовності

Кожен блок вихідного матеріалу використаний або явно позначений як
пропущений із причиною.

---

## Ризики

- **Недолікована евристика №7.** Колонкова логіка, надто поблажлива до
  кроку/першої колонки, може приховати реальні зсуви — негативні
  тести на справжній зсув обов'язкові, а толеранси (±2% кроку, 1%
  ширини) фіксуються в тестах.
- **Нова хвиля шуму від №6.** Шість нових перевірок можуть повторити
  проблему, яку №7 щойно виправив; тому всі, крім package integrity,
  — advisory, а калібрування порогів на production-деці — окремий
  крок, не опція.
- **Ліцензійна чистота fixtures №8.** Синтетичні активи мають бути
  згенерованими плейсхолдерами; випадкове посилання на клієнтський чи
  gitignored шлях ламає головну мету пункту — перевірку з чистого
  checkout (сам checkout-тест це ловить).
- **Порожній contact sheet №10.** Артефакт корисний, лише якщо агент
  реально складає кандидатів у конвенційний каталог — конвенція
  мусить бути закріплена в SKILL.md, а не лише в коді підкоманди.
- **Формальний outline №5.** Lint перевіряє наявність і покриття, але
  не правдивість `purpose` чи доречність `text_edits` — змістовна
  якість залишається на visual/sequence review (Етап 3).
- **Дрейф дерев skills.** Майже кожен пункт етапу править скрипти в
  `.claude/skills`; забутий `sync_agents.py` — розбіжність, яку №11
  саме тому треба зробити першим кроком з тестом у прогоні.
