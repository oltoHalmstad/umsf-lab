# umsf-incident-ai-agent

**Програмний проєкт обробки даних агентом штучного інтелекту з прийняттям рішень згідно з отриманими даними:
логістика рятування людей і логістика ліквідації наслідків удару.**

Версія 1.0.0 · Python ≥ 3.10 · ядро — лише стандартна бібліотека · ліцензія MIT

---

## Abstract (English)

`umsf-incident-ai-agent` is research software that implements the decision-support layer of the
architecture described in Torstensson, Prokopovych-Tkachenko, Adilzhanova, Tykhonenko, Beketova and
Sydybayeva (2026), *Evidence-Aware Multisensor Monitoring for Critical Infrastructure Incident Support*.
An agent observes a multisensor incident dataset (personnel wearables, stationary building-state nodes,
gateway, operator, responder and authoritative external reports), assesses it with coverage-aware
physiological rules (Eq. 1–5) and a source-qualified zone incident state S_z = (M, H, P, F, U)
(Eq. 6–7), and plans two logistics tracks: **rescue logistics** (personnel accounting and an exact
lexicographic team–task assignment, Eq. 8–9) and **consequence-liquidation logistics** (exact
service-continuity allocation, Eq. 10–11, and a resource-constrained recovery schedule with hard
prerequisites). All arithmetic, eligibility, alerts and plans are deterministic. Every output is a
*proposal* packaged for the authorising role of Table 9 and recorded in a hash-chained audit log
together with approvals or rejections and their reasons. An optional Claude language-model layer only
writes a Ukrainian situation briefing from minimised, read-only aggregates; its text is post-checked and
falls back to a deterministic briefing whenever it is unavailable or makes an unsupported claim. The
package reproduces the paper's Table 10 and Section 4.9 / Table 16 / Fig. 14 results exactly
(`umsf-agent reproduce-paper`, 44/44 checks) and ships a self-contained synthetic two-site
post-impact scenario. It has not been validated against real rescue operations.

---

## 1. Призначення

Агент призначений для **підтримки рішень** відповідальних осіб на об'єкті критичної інфраструктури після
можливого удару:

* **рятувальна логістика** — звірка обліку персоналу (очікуваний список, свіже спостереження, прямий
  запит допомоги, підтвердження рятувальниками, нез'ясоване місцеперебування), формування завдань
  (SOS / запит допомоги, невраховані особи з останнім підтвердженим місцем, перевірка можливих ознак
  присутності в зонах з ознаками удару чи газу), точний розподіл рятувальних ланок за рівняннями (8)–(9);
* **логістика ліквідації наслідків** — точний розподіл обмеженої залишкової потужності між сервісами
  (рівняння 10–11) з обов'язковими сервісами безпеки життя як жорсткими обмеженнями, та кандидатний
  графік відновлювальних робіт (обстеження конструкцій, перевірка газової небезпеки, розчищення уламків,
  тимчасова схема живлення, відновлення зв'язку/водопостачання) з жорсткими передумовами.

## 2. Принцип проєктування (обов'язковий)

| Принцип | Як реалізовано |
|---|---|
| Арифметика, допустимість, сповіщення і плани **детерміновані** | `physio_rules`, `incident_state`, `rescue`, `assignment`, `continuity`, `recovery` — без випадковості й без мовної моделі |
| Мовна модель лише **підсумовує мінімізовані агрегати і пояснює плани** | `llm.py`: п'ять інструментів лише для читання, псевдоніми, без сирої фізіології; пост-перевірка тексту; детермінований резервний варіант |
| ШІ **не ставить діагнозів**, не призначає категорій медичного сортування, не обирає маршрутів входу до будівель, **не керує обладнанням** | немає таких функцій; дії керування (перезапуск виробництва, комутація живлення, вентиляція, розблокування) виключаються з графіка і лише перелічуються |
| Кожен план — **ПРОПОЗИЦІЯ**, що потребує затвердження роллю з Таблиці 9 | `decision_packages.json`, команди `approve` / `reject` з обов'язковою причиною, перевірка ролі |
| Затвердження/відхилення і причини — в **журналі аудиту** | `audit.jsonl`: append-only, ланцюжок SHA-256, SHA-256 вхідних даних, версії, метод розв'язувача, статус |
| Відсутні дані → **невідомо**, ніколи не «норма» | null-значення не замінюються; недостатнє покриття → «недостатньо даних для групового висновку» |
| Жодного висновку про жертви з тиші; акустика/PIR — лише **можливі ознаки присутності** | втрата зв'язку → прогалина спостереження з останнім відомим станом; завдання «перевірка ознаки», а не «потерпілий» |
| Атрибуція удару лише від `authoritative_external_alert` | `possible_impact_local` завжди позначено як НЕПІДТВЕРДЖЕНЕ; повідомлення з інших джерел відхиляються як атрибуція |

## 3. Швидкий старт

```bash
# без встановлення
export PYTHONPATH=src
python -m umsf_agent reproduce-paper            # Таблиця 10 і розділ 4.9; ненульовий код при розбіжності
python -m umsf_agent demo --out demo_out        # синтетичний сценарій + повторне відтворення (офлайн)

# або встановлення
pip install .            # ядро без залежностей
pip install .[llm]       # необов'язково: офіційний SDK anthropic
umsf-agent --help
```

Основні команди:

| Команда | Дія |
|---|---|
| `umsf-agent run --data DIR --out OUT [--as-of T] [--llm] [--interactive] [--auto-approve-for-simulation]` | оцінка і планування в один момент часу (типово — кінець даних) |
| `umsf-agent replay --data DIR --out OUT [--step 60]` | покрокове відтворення (типово кожні 60 с часу сценарію) з виявленням змін: нова пропозиція лише коли змінився її зміст |
| `umsf-agent approve/reject --out OUT --package ID --role ROLE --by NAME --reason TEXT` | рішення людини з причиною до журналу аудиту (роль перевіряється за Таблицею 9) |
| `umsf-agent demo --out DIR [--llm]` | генерує синтетичний сценарій і виконує повний цикл офлайн |
| `umsf-agent reproduce-paper [--json F]` | перевірки Таблиці 10, розділу 4.3, примітки Study A і розділу 4.9 (+ дані Рис. 14) |
| `umsf-agent verify-audit --audit OUT/audit.jsonl` | перевірка цілісності ланцюжка аудиту |
| `umsf-agent generate-scenario --out DIR [--variant post_impact\|no_backup_power]` | лише вхідні синтетичні дані |

Прапорець `--auto-approve-for-simulation` створює **імітовані** затвердження (actor
`SIMULATION-AUTO-APPROVE`), явно позначені в усіх виходах; це ніколи не є рішенням людини.

### Дані P1 (`umsf-incident-dataset`)

Завантажувач толерантний і нормалізує формат P1 (обгортка `sites` у `roster.json`, `t0`/`duration_s`,
рядкові рівні подій, агрегований `personnel_accounting.details`, `asset_status.details`,
`capacity_lower_bound`, `weight`/`prerequisites`, `eta_min`, `available_from_min`,
`incident_associations`):

```bash
umsf-agent replay --data ../umsf-incident-dataset/data/incident --out p1_out
# з імітованими рішеннями штабу щодо доступу та ЗІЗ (не з даних сенсорів):
umsf-agent replay --data ../umsf-incident-dataset/data/incident \
    --policy examples/p1_incident_command_input.json --out p1_out_cmd
```

Без рішень штабу доступ до зон невідомий → завдання не призначаються автоматично, а ескалюються
(і не покидаються). Для набору P1 результат безперервності Q = 93,75 % збігається з очікуваним P1
значенням при нижній межі 6 одиниць.

### Необов'язковий шар Claude

`--llm` викликає офіційний SDK `anthropic` (імпорт лише за потреби): `client = anthropic.Anthropic()`,
`client.beta.messages.create(model=…, max_tokens=16000, betas=["server-side-fallback-2026-07-01"],
fallbacks="default", output_config={"effort": "medium"}, system=…, tools=[…], messages=[…])` з ручним
циклом інструментів, обробкою `refusal` і `pause_turn` та окремим перехопленням `RateLimitError`,
`APIStatusError`, `APIConnectionError`. Модель задається `UMSF_LLM_MODEL` (типово `claude-opus-5-5`).
Текст позначається «AI-generated summary — verify against deterministic outputs» і відхиляється, якщо
містить заборонені твердження (напр. «ракетний удар підтверджено», «загиб…», «безпечно для входу») або
числа, яких немає у виходах інструментів. Без SDK, облікових даних чи мережі використовується
детермінована довідка (`briefing.md`).

## 4. Цикл агента

```
observe (ingest) → assess (physio_rules + incident_state)
   → plan (rescue + assignment, continuity, recovery)
   → propose (пакети рішень, Таблиця 9) → чекати рішення людини → log (audit.jsonl)
   ↺ replay: кожні 60 с часу сценарію; нова пропозиція лише при зміні змісту
```

Детальніше: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## 5. Відповідність модулів рівнянням і таблицям статті

| Модуль | Зміст | Джерело у статті |
|---|---|---|
| `ingest.py` | ідентичність (site, device, boot, sequence), ідемпотентність, карантин конфліктів, null замість «норми», список як знаменник, нормалізація P1 | розд. 3.3.4, 3.3.8; PROTOCOL §0, §5 |
| `physio_rules.py` | робастний z (медіана, 1,4826·MAD, ε_k, некалібрований стан), зважений обмежений бал, стійкий прапорець (недоступний ≠ 0), груповий шлюз з урахуванням покриття, цілочислове переформулювання, перевірка порогів щодо списку, чотири стани + терміновий шлях | рівн. (1)–(5); розд. 3.6.4; розд. 4.3; Таблиця 10 |
| `incident_state.py` | S_z = (M, H, P, F, U) як типізовані записи; клас джерела, час, невизначеність, вік, якість, походження, версії/заміщення; свіжість; прогалини при втраті зв'язку; атрибуція лише з уповноваженого джерела; пакети інциденту; T_report, T_action (точка / інтервал / некваліфіковано) | рівн. (6)–(7); розд. 3.8.1–3.8.3; Таблиця 8 |
| `rescue.py`, `assignment.py` | облік персоналу; завдання; e_rj (компетенції, ЗІЗ у газових зонах), a_j (невідомо → 0 → ескалація); δ_rj — кваліфікована оцінка; точний лексикографічний розв'язок (Угорський алгоритм з цілочисловими вагами; доведено проти перебору) | рівн. (8)–(9); розд. 3.9.1; Таблиця 9 |
| `continuity.py` | y_j ≤ y_ℓ, g_j, обов'язкові L, кілька ресурсів (кВт, кВт·год за горизонт, зв'язок, персонал) з обґрунтованими нижніми межами (невідомо → 0); повний перебір n ≤ 20, гілки й межі понад; INFEASIBLE без послаблення; Q | рівн. (10)–(11); розд. 3.9.2, 4.9; Таблиця 16; Рис. 14 |
| `recovery.py` | завдання ліквідації наслідків, жорсткі передумови, CPM, послідовна схема генерації розкладу з правилом пріоритету, заблоковані завдання, виключення керування обладнанням, зв'язок з результатом безперервності | Таблиця 9 («Recovery scheduling»), розд. 3.9.2 |
| `agent.py`, `audit.py` | оркестратор, пакети рішень, авторизація, журнал аудиту з ланцюжком хешів, перепланування з виявленням змін | розд. 3.7.1, 3.9; Таблиця 9; Рис. 9 |
| `llm.py` | необов'язковий підсумок мовною моделлю | розд. 3.3.8 (межа LLM) |
| `report.py` | детермінована довідка українською, пакети JSON, звіт Markdown, статична HTML-панель (вбудований SVG) | Рис. 4 (структура інтерфейсу) |
| `scenario.py` | синтетичний сценарій (2 майданчики, 6 зон, 12 працівників) | — (СИНТЕТИЧНІ дані) |
| `paper.py` | відтворення Таблиці 10 і розділу 4.9 | розд. 4.1, 4.3, 4.4, 4.9 |

Рівняння з поясненнями: [docs/DECISION_MODEL.md](docs/DECISION_MODEL.md).

## 6. Повноваження щодо рішень (Таблиця 9)

| Домен рішення | Вихід системи | Уповноважена роль | Межа |
|---|---|---|---|
| Термінова допомога персоналу | запит, вік, останній підтверджений контекст, стан підтвердження | координатор рятувальних робіт / надзвичайних ситуацій | без групових порогів як передумови |
| Розподіл рятувальних завдань | призначення, непризначені термінові завдання, активні обмеження | координатор рятувальних робіт / штаб реагування | коефіцієнти — не ймовірності виживання; маршрути не обираються |
| Облік персоналу | враховані, невраховані, нерозв'язані записи | уповноважена група координації інциденту | без висновків про жертви лише з сенсорів |
| Стан конструкцій і доступу | результат обстеження з джерелом або явне «невідомо» | кваліфікований експерт і штаб реагування | без автоматичного «допуску» до будівлі |
| Збереження життєво важливих сервісів | допустимий розподіл потужності з залежностями та обмеженнями | відповідальний оператор інфраструктури | обов'язкові сервіси безпеки — обмеження |
| Графік ліквідації наслідків | кандидатні завдання, сумісні з ресурсами, і невирішені передумови | уповноважене керівництво відновленням | керування промисловим обладнанням поза межами сервісу |
| Фізіологічне групове попередження | n, N, покриття, m, частка, причина | фахівець з гігієни праці / відповідальний з безпеки | запит на розслідування, не діагноз |

## 7. Вхідні та вихідні дані

* Вхід: каталог з `roster.json`, `physio.jsonl`, `station.jsonl`, `events.jsonl`, `assets.json`,
  `teams.json`, `manifest.json`; необов'язково `policy.json` (рішення штабу). Формат:
  [docs/INPUT_FORMAT.md](docs/INPUT_FORMAT.md).
* Вихід (`--out`): `decision_packages.json`, `briefing.md` (детермінована довідка українською),
  `ai_briefing.md` (лише з `--llm`), `report.md`, `dashboard.html` (один файл, без зовнішніх залежностей),
  `incident_packets.json`, `result.json`, `timeline.json` (replay), `audit.jsonl`.

Приклади в `examples/`:

* `examples/scenario_post_impact/` — основний синтетичний сценарій (вхід);
* `examples/scenario_no_backup_power/` — варіант без підтвердженого резервного живлення (безперервність
  INFEASIBLE, обмеження безпеки життя не послаблюються);
* `examples/demo_run/` — результат `replay` основного сценарію з двома продемонстрованими рішеннями
  через CLI (затвердження і відхилення з причинами; виконавець — синтетичний демонстраційний оператор);
* `examples/paper_reproduction.json` — перевірки й дані Рис. 14;
* `examples/p1_incident_command_input.json` — імітовані рішення штабу для набору P1.

## 8. Відтворення результатів статті

```
$ umsf-agent reproduce-paper
[PASS] Table 10 case A: … 12 / 10, 4, 83.3 %, 40.0 % → Possible group event
[PASS] Table 10 case B: … 12 / 4, 3, 33.3 %, 75.0 % → Insufficient group evidence; individual review
[PASS] Table 10 case C: … 12 / 10, 1, 83.3 %, 10.0 % + SOS → Urgent individual assistance; no group trigger
[PASS] Study A: six-person zone, n_min 5 → effective minimum coverage 83.3 %
[PASS] Sec 4.9: B < 3 infeasible; 3 ≤ B < 6 → (1,1,0,0), Q = 68.75 %; 6 ≤ B < 10 → (1,1,1,0), Q = 93.75 %; B ≥ 10 → Q = 100 %
…
44/44 checks passed
```

Тести: `python -m unittest discover -s tests -t tests` (116 тестів, з них 6 запускаються лише за наявності сусіднього набору P1; точність розв'язувачів доведено
порівнянням з повним перебором на випадкових малих екземплярах).

## 9. Обмеження

* Програма **не валідована на реальних рятувальних операціях** і не є медичним виробом чи
  сертифікованою системою безпеки; це підтримка рішень, а не їх прийняття.
* Коефіцієнти h_j, p_j, w_j — це **значення політики штабу, а не ймовірності виживання**; Q — зважене
  покриття сервісів, а не частка врятованих людей чи відновленого об'єкта.
* Порогові значення фізіологічних правил — параметри розробки, а не клінічні пороги; групове
  попередження — запит на розслідування, а не діагноз.
* δ_rj — кваліфікована оцінка за матрицею відстаней або `eta_min`, а не перевірений маршрут.
* Графік відновлення — евристичний кандидат (CPM + послідовна схема генерації), не оптимум; тривалості —
  припущення планування.
* Модель безперервності бінарна: без комутації, пускових струмів, мережевих потоків.
* Усі дані в репозиторії **синтетичні**; синтетичні значення ЧСС — поля інтерфейсу.
* Журнал аудиту з ланцюжком хешів виявляє зміни, але не є цифровим підписом.

Етичні засади: [docs/SAFETY_AND_ETHICS.md](docs/SAFETY_AND_ETHICS.md).

## 10. Цитування та ліцензія

Див. `CITATION.cff` і `.zenodo.json`. Ліцензія MIT (`LICENSE`).

> Torstensson O., Prokopovych-Tkachenko D., Adilzhanova S., Tykhonenko M., Beketova G., Sydybayeva M.
> (2026). *umsf-incident-ai-agent: evidence-aware AI decision-support agent for rescue and
> consequence-liquidation logistics* (версія 1.0.0) [Програмне забезпечення]. Zenodo.
