# План підвищення візуальної якості презентацій

## Мета

Довести систему до стабільного створення професійних, повністю редагованих
PowerPoint-презентацій із мінімальним ручним втручанням — без перетворення
слайдів на растрові скриншоти та без підміни дизайнерського судження кількістю
декору.

## Перевірений вихідний стан

- Шестислайдова презентація SIA MED успішно збирається і рендериться.
- PPTX містить окремі редаговані об'єкти: 40 auto-shapes, 43 text boxes і
  12 picture objects; повнослайдових растрових скриншотів немає.
- Per-slide lint знаходить 8 помилок і 120 попереджень.
- Deck lint водночас показує 0 помилок і 7 попереджень, бо не агрегує
  результати per-slide lint.
- Із 12 top-level production deck/slide specs лише 2 валідні в поточному
  checkout; 10 посилаються на відсутні assets.
- `render.py` для багатослайдового PPTX створює лише один PNG.
- Charts не реалізовані; production-візуального fixture для таблиць і діаграм
  немає.
- `.claude/skills` і `.agents/skills` мають змістовні розбіжності.

## P0 — блокують професійну видачу

### 1. Єдиний обов'язковий delivery gate

**Проблема:** презентація може успішно зібратися, хоча окремі слайди мають
blocker-level lint errors.

**Зміна:** створити одну команду, яка послідовно виконує:

```text
validate -> build -> render all slides -> slide lint -> deck lint
         -> package validation -> visual review
```

Команда має агрегувати всі результати й завершуватися помилкою за наявності
невиправлених `blocker` або `error` findings.

**Критерій готовності:** поточна SIA MED-презентація падає до виправлення її
8 slide-level errors і проходить після їх усунення.

### 2. Повноцінний рендер усієї презентації

**Проблема:** чинний `render.py` повертає лише один PNG для багатослайдового
PPTX, тому повна візуальна перевірка потребує ручного PDF/page workflow.

**Зміна:** автоматично:

1. конвертувати PPTX у PDF;
2. рендерити кожну сторінку в PNG 2560×1440;
3. перевіряти відповідність кількості PNG кількості слайдів;
4. створювати montage;
5. записувати manifest із хешами артефактів.

**Критерій готовності:** одна команда генерує всі сторінки, montage і manifest;
відсутня сторінка є hard failure.

### 3. Виконуваний цикл візуальної критики

**Проблема:** критерії visual QA описані в designer skill, але не існують як
виконуваний і контрольований процес.

**Зміна:** додати окрему перевірку кожного слайда та всієї послідовності
vision-моделлю. Кожне finding повинно містити:

- номер слайда;
- елемент або область;
- severity: `blocker`, `major`, `minor` або `observation`;
- видимий доказ;
- рекомендоване виправлення;
- confidence;
- ознаку, чи безпечно автоматизувати виправлення.

Цикл:

```text
render -> critique -> update spec -> rebuild -> compare
```

Максимум — три ітерації.

**Критерій готовності:** немає unresolved blocker/major findings або вони явно
передані на людський review з поясненням ризику.

### 4. Реальний workflow пошуку та вибору зображень

**Проблема:** `asset_resolver.py` формує запити й імпортує вже вибраний файл,
але сам не шукає, не генерує та не порівнює кандидатів візуально.

**Зміна:** для кожного image brief:

1. перевірити user-provided, template та approved project assets;
2. отримати кілька web-кандидатів;
3. створити contact sheet;
4. перевірити композицію, роздільну здатність, watermark, сторонній branding,
   стиль, медичну точність і licensing;
5. задокументувати причини вибору та відхилення;
6. використовувати AI generation лише після невдалого пошуку.

**Критерій готовності:** кожне зовнішнє зображення має brief, provenance,
licensing status, verification notes і візуально обґрунтований вибір.

### 5. Нативні діаграми та перевірені таблиці

**Проблема:** charts відхиляються builder-ом як нереалізовані, а таблиці не
мають production-візуального baseline.

**Зміна:** реалізувати мінімальний набір editable charts:

- bar;
- line;
- scatter.

Додати керування insight emphasis, labels, number formats, axes, grids і
legends. Створити реальні fixtures для таблиці й кожного типу діаграми.

**Критерій готовності:** дані залишаються редагованими, а fixtures проходять
PowerPoint/LibreOffice render та visual QA.

## P1 — найбільше покращення якості та надійності

### 6. Обов'язковий narrative outline і контроль джерел

**Проблема:** designer skill вимагає outline, але production deck не містить
`meta.outline` або обліку невикористаних матеріалів.

**Зміна:** зробити обов'язковими:

- purpose кожного слайда;
- source blocks;
- layout reference;
- placed/unplaced material;
- пояснення скорочень і текстових змін.

**Критерій готовності:** кожен блок вихідного матеріалу використаний або явно
позначений як пропущений із причиною.

### 7. Контроль template fidelity

**Проблема:** обов'язковий `template_visual_catalog.json` відсутній. Система
знає геометрію й тему шаблону, але не гарантує використання його реальної
візуальної мови.

**Зміна:** автоматично перевіряти наявність і актуальність каталогу, який
фіксує:

- representative layouts;
- recurring components;
- color modes;
- recurring assets;
- приклади section, content, data та closing slides.

**Критерій готовності:** кожен слайд посилається на template layout/component
або містить пояснення свідомого відхилення.

### 8. Усунути drift між `.claude` та `.agents`

**Проблема:** skill-дерева відрізняються у builder, linter, designer guidance
і наявності `seamless_hero.py`.

**Зміна:** залишити `.claude/skills` джерелом правди, додати механічну
синхронізацію та CI-перевірку через `diff -qr`.

**Критерій готовності:** будь-яка змістовна розбіжність skill-дерев завершує
перевірку помилкою.

### 9. Посилити deterministic QA

Додати перевірки:

- effective image DPI;
- небажане aspect-ratio distortion;
- видимі межі або невідповідний фон вставленого зображення;
- package/OOXML integrity;
- font substitution;
- відсутні font embeds;
- невидимі логотипи;
- дублікати й perceptual near-duplicates;
- кількість rendered pages;
- відповідність тексту між spec і PPTX.

Whitespace, hierarchy, balance, visual rhythm, density і shape count повинні
залишатися advisory, а не hard failures.

### 10. Виправити шумні deck-level heuristics

**Проблема:** повторювані елементи колонок і процесів помилково перевіряються
як такі, що повинні мати одну координату `x`.

**Зміна:** перевіряти alignment у межах семантичної групи або grid pattern,
а не лише за однаковим `role`.

**Критерій готовності:** linter знаходить реальні зсуви, але не скаржиться на
навмисні колонки, картки та послідовності.

### 11. Відновити та розширити fixtures

**Проблема:** 10 із 12 top-level production specs не відтворюються з чистого
checkout через відсутні assets.

**Зміна:** повернути дозволені assets або замінити їх автономними тестовими
ресурсами. Позначити fixtures як:

- `production`;
- `regression`;
- `intentionally_broken`.

Додати fixtures для таблиці, chart, щільного evidence slide, image-led slide,
section transition і closing slide.

**Критерій готовності:** усі production fixtures збираються з чистого checkout;
негативні fixtures падають із очікуваною діагностикою.

## P2 — після стабілізації основного циклу

### 12. PowerPoint-specific final QA

Додати фінальну перевірку у desktop або web PowerPoint:

- відкриття без repair dialog;
- відсутність небажаного font substitution;
- коректні crops, tables і charts;
- правильний порядок animations;
- збереження editability після повторного save.

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

## Короткий план реалізації

### Етап 1 — зробити дефекти неможливими для видачі

1. Реалізувати повний deck renderer.
2. Додати єдину release-команду.
3. Агрегувати slide-lint і deck-lint.
4. Додати package validation.
5. Використати поточну SIA MED-презентацію як regression fixture.

**Результат:** система більше не видає deck із механічними blocker errors.

### Етап 2 — замкнути візуальний цикл

1. Ввести структурований формат vision findings.
2. Додати per-slide і sequence review.
3. Реалізувати максимум три ітерації.
4. Зберігати before/after montage та unresolved findings.

**Результат:** visual QA стає відтворюваним процесом, а не рекомендацією.

### Етап 3 — покращити вхідні рішення

1. Зробити outline і source coverage обов'язковими.
2. Додати freshness gate для template visual catalog.
3. Реалізувати contact-sheet workflow для assets.
4. Синхронізувати `.claude` та `.agents`.

**Результат:** дизайн-рішення стають простежуваними й стабільнішими між
запусками.

### Етап 4 — розширити професійні можливості

1. Реалізувати charts.
2. Додати production table/chart fixtures.
3. Посилити image/font/package checks.
4. Додати PowerPoint-specific sign-off.

**Результат:** система підтримує реальні data-heavy презентації та фінальну
перевірку у цільовому редакторі.

## Рекомендована послідовність

Найкоротший шлях до відчутного результату:

1. delivery gate;
2. повний deck render;
3. vision-review loop;
4. asset-selection workflow;
5. charts і production fixtures.

Перші три зміни перетворюють наявні правила з рекомендацій на відтворювану
систему контролю якості. Решта розширює покриття й зменшує потребу в ручній
роботі.
