# Етап 3 — дозакрити gate і цикл критики

Робоча інструкція до «Етап 3» майстер-плану
(`docs/VISUAL_QUALITY_IMPROVEMENT_PLAN_UA.md`). Реалізує два пункти:

- **P0 №4 «Закрити залишкові дірки delivery gate»** — page-count hard
  failure, montage всієї деки, manifest із хешами артефактів (обсяг S);
- **P1 №9 «Розширений формат visual findings»** — severity, evidence,
  confidence, auto_fixable у findings; gate на unresolved blocker/major;
  wiring sequence-level review у `lint_deck`; before/after montage між
  ітераціями (обсяг S).

## Зв'язок із планом

- Кодова база: гілка `p0-fixes` (commit `f430ead`), змерджена в `main` —
  та сама передумова, що й у розділі «Статус документа» майстер-плану.
- Із «Залежності та ризики»: manifest цього етапу — основа для
  P2 №13 «QA manifest і людський sign-off», тому структура manifest
  проєктується адитивно (див. Крок 3); контракт `meta.sequence_review`
  спільний для P0 №3 і P1 №9 — **власник контракту — Етап 2**
  (`docs/VISUAL_QUALITY_PHASE_2_UA.md`), тут лише wiring його findings
  у `lint_deck` (Крок 8).
- Етап 3 не залежить від Етапу 1 (charts) і може виконуватися
  паралельно; від Етапу 2 залежить лише Крок 8, і той деградує м'яко
  (відсутній `meta.sequence_review` → warn), тому етапи можна мерджити
  в будь-якому порядку.

## Передумови

Перевірений стан коду, на який спираються кроки нижче:

- `deck_qa.py` (`.claude/skills/pptx-deck/scripts/deck_qa.py`), крок 5:
  викликає `render_all(deck_pptx, render_dir)` з
  `render_dir = output/rendered/<stem>_qa/`, записує
  `report["render"]["n_slides"] = len(pngs)` — і **ніде не порівнює** це
  число з `len(deck["slides"])`. Тихо втрачена сторінка не провалює
  gate. Exit-code: `1 if not report["ok"] else 0`.
- Deck spec парситься лише всередині `spec_paths_from_deck` (крок 2);
  якщо парсинг падає, у `report["slides"]` пишеться один запис
  `"deck spec is not valid: ..."`, `ok=False`, а крок 5 усе одно
  рендерить `output/<stem>.pptx`, якщо той лишився від попереднього
  запуску.
- `render.py`: `render_all` кешує за `_file_hash` у файлі
  `<outdir>/.render_cache_<hash>.json` (`{"hash", "pptx", "pngs"}`);
  проміжний PDF (`<outdir>/<stem>.pdf`) залишається на диску після
  рендера; при повторному рендері видаляються лише сторінки за глобом
  `<stem>_page*.png` — сторонні файли в каталозі не чіпає.
  `_file_hash` рахує sha256, але **повертає лише перші 16 hex-символів**
  (`hexdigest()[:16]`).
- `lint_render.py`: `finding(severity, check, element_id, message)`;
  `check_visual_review` вимагає `meta.visual_review = {iteration,
  verdict, findings[{element_id, issue}]}`; помилку дають лише
  `verdict == "fail"` та `iteration > MAX_VISUAL_REVIEW_ITERATIONS`
  (= 3). Значення `verdict` **не валідується** — невідомий verdict
  проходить мовчки (docstring обіцяє `pass | fail | pass_with_notes`).
- `lint_deck.py`: `finding(severity, check, where, message)`; звіт
  `{deck, n_errors, n_warns, findings}`; exit 1 при `n_errors > 0`;
  усі перевірки викликаються з `lint_deck()` після `validate_deck`.
- `specs/deck.schema.json`: `meta` має `additionalProperties: true` —
  нові поля (`sequence_review`) не потребують зміни схеми.
- `imaging.py` вже дає PIL/numpy-хелпери; нові залежності не потрібні.
- `tests/test_qa_gates.py` — стиль тестів: прямі виклики check-функцій,
  `tmp_path`/`project_root=` для ізоляції, хелпер `_by_check`.

Розбіжності майстер-плану з кодом, враховані нижче:

1. План каже «хеш-функція `_file_hash` уже є в `render.py`» — так, але
   вона віддає скорочений 16-символьний префікс. Для manifest потрібен
   повний sha256 (Крок 3 розширює `_file_hash` параметром `full`).
2. У P1 №9 finding повинно містити «номер слайда». Для per-slide
   `meta.visual_review` слайд відомий із самого spec-файла; окреме поле
   `slide` потрібне лише в sequence-level findings (Крок 8).

## Кроки

### Частина A — дірки delivery gate (P0 №4)

#### Крок 1. Page-count hard failure у `deck_qa.py`

Файл: `.claude/skills/pptx-deck/scripts/deck_qa.py`, функція `main`.

1. Розпарсити deck spec **один раз** на початку `main()` (сьогодні його
   читає лише `spec_paths_from_deck`): `try/except` навколо
   `json.loads(deck_path.read_text())`; на помилці зберегти поточну
   поведінку кроку 2 (запис `"deck spec is not valid"`, `ok=False`,
   `total_errors += 1`) і зафіксувати `expected_slides = None`.
   `spec_paths_from_deck` перевести на вже розпарсений об'єкт, щоб не
   читати файл двічі.
2. У кроці 5 після успішного `render_all` додати порівняння:

   ```python
   # орієнтовний ескіз
   report["render"]["expected_slides"] = expected_slides  # int | None
   if expected_slides is not None:
       report["render"]["page_count_ok"] = len(pngs) == expected_slides
       if not report["render"]["page_count_ok"]:
           report["render"]["page_count_error"] = (
               f"rendered {len(pngs)} page(s), deck declares "
               f"{expected_slides} slide(s)")
           report["ok"] = False
           report["total_errors"] += 1
   else:
       report["render"]["page_count_ok"] = None
   ```

3. Поведінка при непарсабельному deck spec: порівняння **пропускається**
   (`page_count_ok: null`) — gate уже червоний через помилку парсингу,
   а `output/<stem>.pptx` міг лишитися від попереднього запуску, тож
   будь-яке число сторінок звідти нічого не доводить. `null` явно
   відрізняє «не змогли перевірити» від «перевірили, збіглося».
4. Поле `n_slides` (фактична кількість PNG) лишити як є — його вже
   читають; нові поля `expected_slides` / `page_count_ok` /
   `page_count_error` — додаткові. Додати `expected_slides` і
   `page_count_ok` у підсумковий `print(...)`-JSON поруч із наявним
   `render.n_slides`.

#### Крок 2. Montage у `render.py`

Файл: `.claude/skills/pptx-deck/scripts/render.py`, нова функція.

1. Сигнатура (орієнтовно):

   ```python
   MONTAGE_COLS = 3
   MONTAGE_TILE_W = 640          # px, ширина кадру до даунскейлу
   MONTAGE_BUDGET_PX = 20_000_000  # стеля сумарних пікселів montage

   def build_montage(pngs: list[Path], out_path: Path,
                     cols: int = MONTAGE_COLS,
                     tile_w: int = MONTAGE_TILE_W) -> Path: ...
   ```

2. Реалізація лише на PIL (уже в залежностях): сітка `cols` колонок ×
   `ceil(n / cols)` рядів; кожен кадр даунскейлиться до `tile_w` зі
   збереженням аспекту (`Image.resize(..., Image.LANCZOS)`); під кожним
   кадром — підписна смуга (~40 px) із номером слайда (`slide 1`,
   `slide 2`, ...), шрифт — `ImageFont.load_default()` (у Pillow ≥ 10
   можна `load_default(size=...)`), щоб не залежати від OS-шрифтів;
   світлий фон, невеликий gutter між кадрами.
3. Нумерація — 1-based за порядком сторінок. Порядок брати не з
   лексикографічного індексу списку, а парсити номер сторінки з імені
   `<stem>_page-<N>.png` (`pdftoppm` доповнює номери нулями, але
   покладатися на це не варто — див. Ризики).
4. Піксельний бюджет: якщо `n * tile_w * tile_h_estimate` перевищує
   `MONTAGE_BUDGET_PX`, пропорційно зменшити `tile_w`
   (`tile_w = int(tile_w * sqrt(budget / estimate))`) — montage має
   відкриватися будь-яким переглядачем, це огляд для людини, а не
   джерело пікселів (ним лишаються повнорозмірні page-PNG).
5. Вихід: `output/rendered/<stem>_qa/montage.png`. Викликається з
   `deck_qa.py` після успішного `render_all` (Крок 5). Сам `render_all`
   не чіпаємо — одна функція, одна відповідальність.

#### Крок 3. Manifest у `deck_qa.py`

1. У `render.py` розширити хеш-функцію, зберігши поведінку кешу:

   ```python
   def _file_hash(path: Path, full: bool = False) -> str:
       ...
       return h.hexdigest() if full else h.hexdigest()[:16]
   ```

   Кеш (`.render_cache_<hash>.json`) і далі використовує 16-символьний
   префікс — наявні кеш-файли лишаються валідними; manifest бере повний
   digest (`full=True`).
2. Новий хелпер у `deck_qa.py` (орієнтовна сигнатура):

   ```python
   def write_qa_manifest(render_dir, deck_spec_path, deck_pptx,
                         pdf_path, pngs, montage_path,
                         qa_report_path) -> Path: ...
   ```

   Пише `output/rendered/<stem>_qa/manifest.json`. Шлях до PDF відомий:
   `render_all` залишає його як `render_dir / f"{deck_pptx.stem}.pdf"`.
3. Вміст manifest (орієнтовний ескіз; шляхи — repo-root-relative):

   ```json
   {
     "schema": "deck_qa_manifest/1",
     "created_utc": "2026-07-13T10:00:00+00:00",
     "deck_spec": "specs/sia_med.deck.json",
     "deck_pptx": {"path": "output/sia_med.pptx", "sha256": "..."},
     "pdf": {"path": "output/rendered/sia_med_qa/sia_med.pdf",
             "sha256": "..."},
     "pages": [
       {"n": 1, "path": "output/rendered/sia_med_qa/sia_med_page-1.png",
        "sha256": "..."}
     ],
     "montage": {"path": "output/rendered/sia_med_qa/montage.png",
                 "sha256": "..."},
     "tools": {"soffice": "LibreOffice 26.2.4.2 ...",
               "pdftoppm": "pdftoppm version 26.07.0"},
     "git_commit": "f430ead...",
     "qa_report": "qa_report.json",
     "review": null
   }
   ```

4. Як отримати версії інструментів:
   - `soffice --version` → перший непорожній рядок stdout;
   - `pdftoppm -v` → poppler друкує банер версії в **stderr**
     (перевірено: `pdftoppm version 26.07.0`); брати перший непорожній
     рядок stderr, fallback — stdout; **не** вимагати `returncode == 0`
     (старіші poppler-утиліти повертали ненульовий код на `-v`).
   - Обидва виклики в `try/except` → при невдачі `null`, без падіння.
5. Git commit: `subprocess.run(["git", "rev-parse", "HEAD"],
   cwd=PROJECT_ROOT, capture_output=True, text=True)`; будь-яка невдача
   (не git-репозиторій, git відсутній) → `null`, без падіння.
6. UTC-час: `datetime.now(timezone.utc).isoformat()`.
7. Адитивність під P2 №13: поле `review: null` зарезервоване одразу —
   P2 №13 заповнює його об'єктом `{reviewed_by, review_date, verdict,
   unresolved[]}` без зміни жодного наявного ключа; `schema` дає
   версіонування, якщо колись знадобиться незворотна зміна. Manifest
   фіксує факт QA-прогону, а не вердикт — авторитетом pass/fail
   залишається `qa_report.json` (і згодом — sign-off у `review`).
8. `qa_report` — repo-root-relative шлях до файлу з `--out`, якщо той
   заданий, інакше `null`.

#### Крок 4. Взаємодія з кешем `render_all` — рішення

`render_all` на cache hit повертає PNG без ре-рендеру. **Обране
рішення:** `deck_qa` безумовно (пере)записує `montage.png` і
`manifest.json` після кожного успішного `render_all` — і на cache hit
теж. Обґрунтування:

- manifest несе факти конкретного прогону (timestamp, версії
  інструментів, git commit) — їх не можна «взяти з кешу»;
- montage будується з даунскейлених кадрів — це секунди, кешувати нема
  чого;
- кеш `render.py` лишається з єдиною відповідальністю (повторне
  використання PNG); альтернатива «внести montage/manifest у cache
  entry» відхилена — вона зв'язала б рендер-кеш із QA-артефактами і все
  одно не розв'язала б проблему timestamp.

Наслідок: `.render_cache_<hash>.json` не змінюється; montage/manifest у
ньому не перелічуються.

#### Крок 5. Wiring у кроці 5 `deck_qa.py`

Після успішного `render_all`, у порядку:

1. page-count перевірка (Крок 1);
2. `build_montage(...)` → `report["render"]["montage"]`;
3. копія `montage_iter<N>.png` (Крок 9, частина B);
4. `write_qa_manifest(...)` → `report["render"]["manifest"]`.

Виняток у montage/manifest — це `ok=False` + `total_errors += 1`
(окремий `try/except` із власним повідомленням у
`report["render"]["error"]`), **не** мовчазний warn: критерій P0 №4 —
«одна команда залишає montage і manifest поруч із `qa_report.json`»,
тож gate, який не зміг їх створити, зобов'язаний упасти голосно.
Додати `montage`/`manifest` у підсумковий `print(...)`-JSON.

### Частина B — розширений формат visual findings (P1 №9)

#### Крок 6. Спільний модуль контракту `review_contract.py`

Новий файл `.claude/skills/pptx-deck/scripts/review_contract.py` —
єдине місце, де живе розширений формат finding; його імпортують і
`lint_render.py`, і `lint_deck.py` (без важких залежностей — тільки
stdlib).

1. Розширена форма finding (орієнтовний ескіз):

   ```json
   {
     "element_id": "headline",
     "area": "element:headline",
     "issue": "заголовок наїжджає на молекулу",
     "severity": "major",
     "evidence": "output/rendered/sia_med_qa/crops/iter2_headline.png",
     "recommended_fix": "зсунути headline на 20 px ліворуч",
     "confidence": 0.85,
     "auto_fixable": false,
     "resolution": {"action": "fixed", "iteration": 3,
                    "note": "box зсунуто, ре-рендер чистий"}
   }
   ```

   - `severity`: `blocker | major | minor | observation`;
   - `area`: id елемента (`element:<id>`) або вільний опис регіону
     (`region:top-left`), коли дефект не прив'язаний до елемента;
     `element_id` лишається для сумісності й адресації;
   - `evidence`: repo-root-relative шлях до crop-PNG (конвенція:
     `output/rendered/<stem>_qa/crops/iter<N>_<area>.png`; crops ріже
     агент-рецензент із повнорозмірних page-PNG);
   - `confidence`: число 0–1; `auto_fixable`: bool;
   - `resolution` — необов'язковий об'єкт; його присутність із
     непорожнім `action` означає «resolved». Спеціальне значення
     `action: "deferred_to_human"` (обов'язково з `reason`) — явна
     передача людині: gate не блокує, але лишає warn.
2. API модуля (орієнтовно):

   ```python
   SEVERITIES = {"blocker", "major", "minor", "observation"}
   GATE_SEVERITIES = {"blocker", "major"}
   VERDICTS = {"pass", "fail", "pass_with_notes"}

   def is_legacy(f) -> bool: ...      # {element_id, issue} без severity
   def is_resolved(f) -> bool: ...
   def validate_review(review, project_root) -> list[dict]:
       """[{level: 'error'|'warn', code, where, message}] —
       нейтральні issues; кожен linter мапить їх у свій finding()."""
   ```

3. Правила `validate_review` (виконуються для обох рівнів review):
   - legacy-форма finding (`{element_id, issue}` без `severity`) →
     **один warn** на review (`code: visual_review_findings_legacy`),
     ніколи не error — зворотна сумісність із поточним контрактом
     `check_visual_review`;
   - невідомий `severity` → warn; `confidence` не число або поза
     [0, 1] → warn; `auto_fixable` не bool → warn;
   - `evidence` заданий, але файл відсутній (перевірка через
     `project_root / evidence`) → warn; blocker/major без `evidence`
     → warn (докази вимагаються, але їх відсутність не маскує головний
     сигнал — unresolved-помилку нижче);
   - **unresolved blocker/major → error**
     (`code: visual_review_unresolved`). Визначення «unresolved»:
     `severity ∈ {blocker, major}` і (немає валідного `resolution`
     **або** `verdict == "fail"`). `deferred_to_human` із `reason` —
     resolved для gate + окремий warn;
   - `verdict` поза `VERDICTS` → warn — закриває сьогоднішню діру,
     коли невідомий verdict проходить мовчки.

#### Крок 7. Розширити `check_visual_review` у `lint_render.py`

Файл: `.claude/skills/pptx-deck/scripts/lint_render.py`.

1. Поточну поведінку зберегти без змін: відсутній
   `meta.visual_review` → warn; невалідна `iteration` → warn;
   `iteration > MAX_VISUAL_REVIEW_ITERATIONS` → error
   (`visual_review_iterations`); `verdict == "fail"` → error
   (`visual_review_failed`).
2. Додати виклик `review_contract.validate_review(review,
   PROJECT_ROOT)` і змапити нейтральні issues у
   `finding(level, code, element_id_or_"meta", message)`. Для
   testability пропустити `project_root` параметром із дефолтом
   `PROJECT_ROOT`, за зразком `check_placed_image_provenance`.
3. Оновити docstring `check_visual_review` новим контрактом (він —
   де-факто документація формату для агента-рецензента).
4. Семантика gate після зміни: сьогодні error дає лише
   `verdict == "fail"`; тепер додатково — будь-який unresolved
   blocker/major finding, навіть коли verdict уже `pass` чи
   `pass_with_notes` (внутрішньо суперечливий review не має проходити).

#### Крок 8. Wiring `meta.sequence_review` у `lint_deck.py`

Контракт `meta.sequence_review` (обов'язковий пункт `style_coherence`,
семантика iteration, коли відсутність стає error) **належить Етапу 2**
— див. `docs/VISUAL_QUALITY_PHASE_2_UA.md` (P0 №3). Тут — лише
підключення його findings до спільного розширеного формату:

1. `check_sequence_review(deck, findings, project_root=PROJECT_ROOT)`
   у `.claude/skills/pptx-deck/scripts/lint_deck.py`, виклик — із
   `lint_deck()` після успішного `validate_deck`, поруч із рештою
   перевірок. Цю функцію вводить Етап 2 (Крок 11); якщо він уже
   виконаний — розширити наявну, не дублювати; якщо ні — створити тут
   із м'якою деградацією нижче.
2. Поведінка:
   - `meta.sequence_review` відсутній → warn («sequence-level review
     не записано») — ескалацію до error, якщо така буде, вирішує
     Етап 2;
   - присутній → та сама `review_contract.validate_review`;
     `verdict == "fail"` → error; unresolved blocker/major → error;
     мапінг у `finding(severity, check, where, message)` з
     `where = "deck"` або `"deck:<stem>"` за першим елементом
     `slides[]` finding-а.
3. Sequence-level findings додатково несуть поле `slides[]` (номери
   або stem-и слайдів; порожній список — наскрізний дефект) — за
   контрактом Етапу 2; саме тут матеріалізується вимога майстер-плану
   «номер слайда». У per-slide `meta.visual_review` слайд відомий із
   самого spec-файла, окреме поле не потрібне.
4. Зміни схеми не потрібні: `meta` у `specs/deck.schema.json` має
   `additionalProperties: true` (перевірено).

#### Крок 9. Before/after montage між ітераціями

Файл: `.claude/skills/pptx-deck/scripts/deck_qa.py`, крок 5 (після
`build_montage`, до manifest).

1. Обчислити `N` = максимум серед: `meta.visual_review.iteration` усіх
   слайд-spec (вони вже парсяться для lint-кроків) та
   `meta.sequence_review.iteration` deck spec. Якщо жодного review ще
   немає — копію не робити (є лише `montage.png`).
2. Скопіювати `montage.png` → `montage_iter<N>.png` у тому самому
   `output/rendered/<stem>_qa/`. Повторний прогін із тим самим `N`
   перезаписує файл (ідемпотентність); файли попередніх ітерацій не
   чіпаються — саме вони і є "before".
3. Retention: тримати всі `montage_iter*.png` — їх максимум
   `MAX_VISUAL_REVIEW_ITERATIONS` (+1 на випадок over-limit-прогону),
   бо `iteration > 3` і так дає error. Cleanup — вручну на початку
   нового delivery-циклу. `render_all` їх не зачепить: його прибирання
   старих сторінок глобить лише `<stem>_page*.png` (перевірено).
4. Опційно (адитивно): перелічити наявні копії в manifest полем
   `montage_iterations: [{iteration, path, sha256}]`.

## Тести

Додавати в `tests/test_qa_gates.py` (стиль: прямий виклик функції,
`tmp_path` + параметр `project_root=`, хелпер `_by_check`) або в
сусідній `tests/test_qa_artifacts.py`, якщо файл розростеться.

Частина A:

1. `build_montage`: 7 синтетичних PNG (PIL, різні розміри/кольори) →
   файл існує; ширина = 3 колонки; 3 ряди; сумарні пікселі ≤ бюджету;
   1 PNG → монтаж із одного кадру не падає.
2. Порядок кадрів: файли `x_page-2.png`, `x_page-10.png`,
   `x_page-1.png` → підписи йдуть 1, 2, 10 (числовий парсинг, не
   лексикографія).
3. `_file_hash`: дефолт — 16 символів (сумісність кешу), `full=True` —
   64; обидва — префікс/повний того самого digest.
4. `write_qa_manifest` на tmp-файлах: усі ключі присутні; sha256 у
   `pages[]`/`deck_pptx`/`pdf` мають довжину 64; `review is None`;
   `schema == "deck_qa_manifest/1"`.
5. Толерантність manifest: monkeypatch `subprocess.run`, що кидає
   виняток → `tools.*` і `git_commit` стають `null`, функція не падає.
6. Page-count: винести порівняння в чисту функцію (наприклад,
   `page_count_finding(expected, actual)` у `deck_qa.py`) і покрити:
   збіг → `None`; розбіжність → error-повідомлення з обома числами;
   `expected is None` → `None` (перевірка пропущена).
7. Cache hit: із наявним `.render_cache_<hash>.json` `render_all`
   повертає кешовані PNG, а хелпери montage/manifest, викликані після
   нього, все одно (пере)записують файли зі свіжим `created_utc`.

Частина B:

8. Розширений finding `minor` без resolution, verdict `pass` → без
   error (лише можливі warn за відсутній evidence).
9. `blocker` без `resolution` → error `visual_review_unresolved`;
   те саме при verdict `pass_with_notes` (вердикт не маскує).
10. `blocker` із `resolution.action = "fixed"` → чисто.
11. `major` із `resolution.action = "deferred_to_human"` + `reason` →
    warn, без error (явна передача людині — критерій P1 №9).
12. Legacy-форма `{element_id, issue}` → warn
    `visual_review_findings_legacy`, без error; наявні три
    visual_review-тести (`test_visual_review_missing_is_a_warn` та
    ін.) проходять без змін — це і є перевірка зворотної сумісності.
13. Валідація полів: невідомий `severity` → warn; `confidence: 1.5` →
    warn; `auto_fixable: "yes"` → warn; невідомий `verdict` → warn.
14. `evidence` вказує на неіснуючий файл (`project_root=tmp_path`) →
    warn; існуючий crop-PNG → чисто.
15. `lint_deck.check_sequence_review`: відсутній → warn; verdict
    `fail` → error; unresolved blocker → error; blocker із resolution
    → чисто; `where` містить stem слайда, коли finding має непорожній
    `slides[]`.
16. `montage_iter<N>`: хелпер вибору `N` — максимум по слайдах і
    deck; без жодного review → копія не створюється.

Прогін: `pytest tests/` — усі наявні 72 тести лишаються зеленими;
поточна шестислайдова production-дека проходить `deck_qa.py` без нових
errors (її `meta.visual_review` — legacy-форма → лише warn).

## Критерії готовності

Похідні від P0 №4 і P1 №9 майстер-плану:

- відсутня або зайва сторінка рендера — помилка gate (`ok=False`,
  exit 1), із явними полями `expected_slides` / `page_count_ok` у
  `qa_report.json`; при непарсабельному deck spec —
  `page_count_ok: null` при вже червоному gate;
- одна команда (`deck_qa.py`) залишає `montage.png` і `manifest.json`
  поруч із `qa_report.json` — і на cache hit теж; manifest містить
  повні sha256 деки `.pptx`, PDF і кожного page-PNG, версії
  `soffice`/`pdftoppm`, UTC-час, git commit, і зарезервоване
  `review: null` під P2 №13;
- немає unresolved blocker/major findings — або вони явно передані на
  людський review (`deferred_to_human` + `reason`) із зафіксованим
  ризиком; legacy-форма findings дає warn, а не error;
- sequence-level review, коли він записаний за контрактом Етапу 2,
  проходить ту саму валідацію формату в `lint_deck`; verdict `fail`
  чи unresolved blocker/major на рівні деки — error;
- між ітераціями review зберігаються `montage_iter<N>.png` для
  before/after порівняння;
- усі нові й наявні тести зелені; production-дека проходить gate без
  ручних правок.

## Ризики

- **Порядок сторінок.** `pdftoppm` доповнює номери сторінок нулями,
  тож `sorted(glob(...))` у `render_all` сьогодні стабільний; але
  montage не повинен успадковувати цю крихкість — підписи беруть номер
  із імені файлу числовим парсингом (Крок 2.3).
- **Недетермінованість manifest.** `created_utc`, версії інструментів
  і git commit змінюються між прогонами — тести не повинні порівнювати
  manifest байт-у-байт, лише ключі та інваріанти.
- **Пожорсткішання gate.** Щойно команда почне проставляти `severity`,
  раніше «зелені» деки можуть почервоніти через unresolved major.
  Міграція м'яка за построєнням: legacy-форма лишається warn, тож
  наявні spec-и не ламаються; нові правила вмикаються природно з
  наступною ітерацією review.
- **Зловживання `deferred_to_human`.** Ескіз навмисно вимагає `reason`
  і лишає warn; фінальний запобіжник — P2 №13, де людський sign-off
  фіксується в тому самому manifest (`review`), і unresolved-список
  стає видимим у delivery-артефакті.
- **Pillow-шрифт підписів.** `ImageFont.load_default(size=...)`
  потребує Pillow ≥ 10; на старіших версіях fallback — дрібний
  бітмап-шрифт без масштабування. Прийнятно: підписи — орієнтир, не
  типографіка.
- **Великі деки.** Піксельний бюджет montage зменшує кадри; для
  40+ слайдів кадри стануть дрібними. Це свідомий компроміс: montage —
  огляд для людини, джерелом пікселів (і `evidence`-crops) лишаються
  повнорозмірні page-PNG.
- **LibreOffice-рендер — не PowerPoint** (успадковано з майстер-плану):
  page-count і montage доводять цілісність LO-проксі; розбіжності з
  PowerPoint закриває P2 №12, не цей етап.
