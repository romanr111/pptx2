# План підвищення візуальної якості презентацій — індекс

Короткий індекс. Детальні покрокові інструкції (зміни коду, контракти,
тести, ризики) — у phase-документах:

- **Етап 1** — `VISUAL_QUALITY_PHASE_1_UA.md` — нативні діаграми й таблиці
  (P0 №1);
- **Етап 2** — `VISUAL_QUALITY_PHASE_2_UA.md` — онбординг шаблону + стиль
  зображень (P0 №2–3);
- **Етап 3** — `VISUAL_QUALITY_PHASE_3_UA.md` — дозакрити gate + цикл
  критики (P0 №4, P1 №9);
- **Етап 4** — `VISUAL_QUALITY_PHASE_4_UA.md` — входи, fixtures, шум
  (P1 №5–8, №10–11).

Порядок: Етап 1 → 2 → 3 → 4. Перші два закривають найбільші розриви з
потребами клієнта (data-heavy слайди, змінні шаблони конференцій, узгоджені
анатомічні зображення); решта зміцнює відтворюваність.

## Мета

Стабільне створення професійних, повністю редагованих PowerPoint-презентацій
із мінімумом ручних правок — без растрових скриншотів. Вимоги клієнта:
відповідність шаблону конференції (шрифти, кольори, розташування, діаграми),
єдиний стиль анатомічних зображень, медична точність.

## Принципи відбору

Кожен пункт проходить три тести: (1) реальна цінність для клієнта;
(2) мінімум коду; (3) **агент судить із рендеру, детермінізм — лише де
об'єктивно**. Візуальні питання (узгодженість, шов, вирівнювання, ритм,
near-duplicate) вирішує агент на **montage** деки. Детерміновані перевірки —
тільки для машинно вимірюваного: підрахунок сторінок, sha256 шаблону,
цілісність zip, назва шрифту зі списку, glyph coverage, синхронність skills.
Крихкі числові евристики візуального наміру (дескриптори + пороги +
кластеризація) свідомо не будуємо.

## Вихідний стан (`p0-fixes`, f430ead; має бути змерджено в `main`)

`deck_qa.py` — єдиний delivery gate (build → lint → повний рендер;
`qa_report.json`; exit 1 на error). На деці SIA MED: 0 errors, 6/6 рендер,
`meta.visual_review` на кожному слайді; `tests/test_qa_gates.py` — 72 зелені.
Уже є: provenance sidecars, font-embedding gate, AI-review gate, `lint_deck`
(палітра/type_scale/бюджети), sync `.claude`↔`.agents`. Головні прогалини:
charts досі відхиляються builder-ом; немає публічних self-contained fixtures
(12 production specs — приватні, у `.gitignore`). Обсяг: S — години,
M — 1–2 дні, L — кілька днів.

## Вже виконано (виключено з робіт)

| Первинний пункт | Стан |
| --- | --- |
| P0 «Єдиний delivery gate» | `deck_qa.py` |
| P0 «Повний рендер деки» | `render_all()`; залишок → P0 №4 (page-count, montage) |
| P0 «Цикл візуальної критики» | артефакт + ліміт ітерацій + gate; залишок → P1 №9 |
| P0 «Workflow зображень» | briefs/provenance/licensing/AI-review; залишок → P1 №10 |
| P1 «Drift `.claude`/`.agents`» | `sync_agents.py`; залишок → P1 №11 (CI-перевірка) |

## Обсяг робіт

**P0 — найбільша цінність:**

- **№1** Нативні bar/line/scatter charts + перевірені таблиці — **L**,
  Етап 1. Data-heavy деки; справжня builder-робота (python-pptx), не судження.
- **№2** Онбординг шаблону як одна процедура + freshness gate каталогу
  (sha256) — **M**, Етап 2A.
- **№3** Єдиний стиль анатомічних зображень — **M**, Етап 2B.
  `image_brief.category` + успадкування стилю з styleguide (конструктивно) +
  `style_coherence` у `meta.sequence_review` (агент судить з montage). Без
  детермінованої евристики узгодженості.
- **№4** Дірки gate — **S**, Етап 3A. Page-count hard failure + montage;
  manifest адитивний (найнижча цінність, можна відкласти до P2 №13).

**P1 — якість і надійність:**

- **№5** Обов'язковий outline + контроль джерел — **M**, Етап 4. Формалізує
  наявну конвенцію (`meta.outline` уже є).
- **№6** Deterministic QA — **M**, Етап 4. Чотири об'єктивні перевірки:
  package integrity (error), font substitution, DPI, aspect.
  edge_mismatch/near-dup — на agent-review.
- **№7** Звузити шумний `check_role_alignment` — **S**, Етап 4. Per-slide
  об'єктивний випадок; наскрізне вирівнювання — на montage.
- **№8** Публічні синтетичні fixtures (`fixture_kind` + раннер) — **M**,
  Етап 4.
- **№9** Формат findings — **S**, Етап 3B. `severity` + необов'язковий
  `resolution`; unresolved blocker/major → error; legacy → warn. Без
  модуля/`confidence`/`auto_fixable`.
- **№10** `rejected[]` provenance — **S**, Етап 4. PIL contact sheet
  відкладено.
- **№11** `sync_agents.py --check` + тест — **S**, Етап 4.

**P2 (після P0/P1, без окремих phase-документів):**

- **№12** PowerPoint-specific final QA (osascript: repair dialog, font
  substitution, crops/tables/charts, editability). **Обов'язково для
  chart-слайдів** — LibreOffice-рендер лише проксі.
- **№13** QA manifest + людський sign-off — розширення `manifest.json` з
  P0 №4 (`reviewed_by`/`verdict`/`unresolved[]`; поле `review: null` уже є).

## Залежності

- P0 №4 (manifest) → основа P2 №13; `meta.sequence_review` — власник Етап 2,
  Етап 3 лише розширює формат finding; P1 №8 дає публічний тест для P0 №2.
- Етап 3 не залежить від Етапу 1; від Етапу 2 — лише м'який wiring.
- python-pptx обмежує стилювання діаграм → fallback: таблиця + shapes, ніколи
  не растр. LO-рендер ≠ PowerPoint: фінальна істина для charts/шрифтів — P2 №12.
- Єдиний активний шаблон за `assets/template.pptx`; кілька одночасно — поза
  скоупом.
