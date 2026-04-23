# ELAN Factory — Entry point для ИИ

> **Первый раз в проекте?** Прочти в порядке: `knowledge/04_CURRENT_STATE.md` → `knowledge/05_BACKLOG.md` → `knowledge/00_GOAL.md`. Получишь 80% контекста за 5 минут.

## Что это за проект

Завод косметики **ELAN KİMYA A.Ş.** в Турции. CMO/private label модель: производим косметику под чужими брендами (LUNESI, USUPSO, C-LAB, BILOBROV и др.) + запускаем свой бренд ELAN с мая 2026. ~40 человек, ~110 000 EUR выручки/месяц (в марте 2026). Часть группы из 4 юрлиц: Турция (производство), UA (ФОП Кравченко), PL (ELAN BEAUTY), UAE (ELAN COSMETICS).

Собственники: Анна Кравченко (АГ) + Гузенко (ТГ). **Доля пользователя (Володимир): 7%.**

- **Цель**: продать группу с брендом за **$1B через 5-7 лет** (2030-2032). Anchor — реальные сделки L'Oréal: **Medik8** (€1B, свой lab + manufacturing) — самый прямой fit.
- **Текущая оценка**: $7–12M.
- **Позиционирование**: brand-with-manufacturing, не pure CMO (без бренда потолок $50M).
- **Язык**: все ответы и документы на **русском**. Код/комменты можно на англ.

## Карта документации

| Файл | Зачем |
|---|---|
| `knowledge/00_GOAL.md` | Цель $1B, сценарии exit, L'Oréal comparables |
| `knowledge/01_GROUP.md` | 4 юрлица (TR/UA/PL/UAE), как связаны, related-party |
| `knowledge/02_DATA_ARCHITECTURE.md` | Level 0 сейчас, план Level 1/2 |
| `knowledge/03_PRINCIPLES.md` | Как работаем: правила, привычки, анти-паттерны |
| `knowledge/04_CURRENT_STATE.md` | **Авто-генерится** — live числа из snapshots |
| `knowledge/05_BACKLOG.md` | Что делать дальше (priority list, max 5 в NOW) |
| `knowledge/06_ACCOUNTING.md` | Кто ведёт, где какие данные, сверка, FX-политика |
| `knowledge/07_ANTI_PATTERNS.md` | Что НЕ делать (конкретные факапы) |

## Стек в одну строку

GitHub Pages ([elan-groupe.github.io/elan-factory](https://elan-groupe.github.io/elan-factory/)) + static HTML/JS + Chart.js + Python парсеры (openpyxl) + xlsx от бухгалтера как источник истины.

## Архитектура данных (Level 0)

```
_raw/                          ← gitignored (xlsx приватные)
data/constants.json            ← ручные (meta, scenarios, loreal, valuation, payroll, capex)
data/snapshots/YYYY-MM.json    ← авто из parse_raporlar.py (в git — audit trail)
data/snapshots/ag_kassa.json   ← авто из parse_kassa_ag.py
scripts/build_data.py          ← всё → docs/data.js
docs/data.js                   ← BUILD ARTIFACT, не править руками
docs/*.html                    ← сайт, потребляет window.ELAN_DATA
```

Подробнее: `knowledge/02_DATA_ARCHITECTURE.md`.

### Workflow нового месяца от бухгалтера

```bash
# 1. Кладёшь xlsx в _raw/
# 2. Парсишь
python scripts/parse_raporlar.py "_raw/RAPORLAR 2026 АПРЕЛЬ.xlsx" 2026-04
python scripts/parse_kassa_ag.py  "_raw/УЧЕТ НАЛИЧНЫХ 2026 АГ.xlsx"
# 3. Собираешь сайт
python scripts/build_data.py
# 4. Коммит + push → GitHub Pages
git add data/ docs/data.js
git commit -m "data: снапшот 2026-04"
git push
```

## Критические правила

1. **Никаких "доля 7%" в UI** — было и убрали. Эта цифра только для внутренних расчётов (`ownerShare` в `constants.json`).
2. **Никакой ручной правки `docs/data.js`** — он build artifact. Правишь либо `data/constants.json`, либо xlsx в `_raw/` → прогоняешь скрипты.
3. **xlsx НЕ коммитятся** (в `.gitignore`). JSON-снапшоты коммитятся — они не содержат детализации транзакций, только агрегаты.
4. **Ссылки в ответах пользователю — markdown-кликабельные**, никогда голым текстом.
5. **После push — `curl` проверить что задеплоилось**, только потом говорить "готово".
6. **Mobile-first** — любой UI сразу адаптировать под телефон.
7. **Критические решения — ADR в `knowledge/09_DECISIONS.md`** (когда появится).
8. **Связанные стороны (related-party) в отдельной колонке** в любых отчётах. Invest на DD увидит 60% related как red flag.

## Основные собственники и роли

- **Володимир Рыков** — совладелец 7%, технолог/аналитик. Первичный заказчик дашборда.
- **Анна Кравченко (АГ)** — основной собственник, управляет группой, её личная касса проводит "другое направление" ($80-100k/мес).
- **Гузенко (ТГ)** — второй собственник, основной капитал. Декабрь 2025: транш 263k EUR.
- **Виталий Обухов** — экспорт/ВЭД, главный sales driver (премия +1.5% с экспорта).
- **Osman Aksu** — Production manager.
- **Larysa Ivanina / Hidayet Şahin / Tamara Vorobeva / Olena Petik** — R&D / QC / технологи.

## Где крутится сайт

- Репо: [github.com/elan-groupe/elan-factory](https://github.com/elan-groupe/elan-factory)
- Live: [elan-groupe.github.io/elan-factory](https://elan-groupe.github.io/elan-factory/)
- Локально: `C:\Users\User\Завод\` (на Windows у Володимира)
- Деплой: push в `main` → Pages пересобирает из `docs/`

## Что не входит в этот repo

- **Сырые xlsx** (в `_raw/`, gitignored, приватные). Передаются через Telegram.
- **1С и турецкая бух. программа** — у бухгалтеров, не автоматизировано.
- **Memory Claude** (предпочтения Володимира, локальные заметки) — в `~/.claude/projects/.../memory/`, локально.
