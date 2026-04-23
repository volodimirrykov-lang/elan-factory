# 02 — Архитектура данных

## Level 0 (сейчас, 2026-04-23)

```
_raw/                          ← gitignored, локально на компе
  ├── RAPORLAR YYYY MONTH.xlsx       ← от бухгалтера, основной источник
  ├── УЧЕТ НАЛИЧНЫХ АГ.xlsx           ← личная касса АГ Кравченко, 5 monthly sheets
  ├── Зарплата MONTH.xlsx             ← payroll (помесячно)
  └── Расходы на стройку.xlsx         ← CAPEX tracker (накопительно)

data/                          ← в git — audit trail
  ├── constants.json           ← ручные (meta, scenarios, loreal, valuation, payroll, capex)
  └── snapshots/
      ├── YYYY-MM.json         ← авто из parse_raporlar.py
      └── ag_kassa.json        ← авто из parse_kassa_ag.py

scripts/                       ← в git
  ├── parse_raporlar.py        ← xlsx ИТОГ sheet → YYYY-MM.json
  ├── parse_kassa_ag.py        ← 5 monthly sheets → ag_kassa.json
  └── build_data.py            ← snapshots/* + constants.json → docs/data.js

docs/                          ← в git — GitHub Pages source
  ├── data.js                  ← BUILD ARTIFACT (не править руками)
  ├── *.html                   ← сайт, потребляет window.ELAN_DATA
  └── *.css / *.js             ← темы, графики
```

### Как работает парсер RAPORLAR

Лист `ИТОГ İCMAL` стабилен месяц к месяцу. Парсер **label-driven**:

- **Колонки A-E**: банковские позиции + итоги (`ПОСТУПЛЕНИЯ`/`ОПЛАТЫ`/`ПРОДАЖИ`/`ЭКСПОРТ` + клиенты)
- **Колонки G-H**: разбивка расходов (сырьё, доставка, фабрика, персонал, услуги, прочее) + "Поступление от учредителей"

Ищем по тексту в col A или col G — устойчив к сдвигу строк. State-машина чтобы не считать клиентов из блока "Дебеторская задолженность" дважды.

### Как работает парсер кассы АГ

Лист на месяц. Ищем "Всего:" маркеры и соседние числовые ячейки **до первой пустой колонки-разделителя** (gap-stop). Структура отличается от месяца к месяцу — поэтому не row-based, а label + scan.

## Level 1 (план, 1 день работы)

```
Google Sheets                    (как v7padel_db)
  ├── elan_db (raw)
  │    ├── raporlar_monthly      ← long-format: period | source_file | category | subcategory | amount
  │    ├── ag_kassa_monthly
  │    ├── payroll_monthly
  │    └── capex_tracker
  └── elan_cache (aggregates)
       ├── monthly_pnl           ← собирается из raw
       ├── client_revenue
       └── dashboard_kpis

Python ETL (gspread)
  ├── scripts/sync_to_sheets.py  ← читает data/snapshots/*.json + пишет в Sheets
  └── Cron (Windows TS или GitHub Actions ежемесячно)

Сайт
  └── data.js читает из GVIZ CSV API (как V7)
```

**Что даст Level 1:**
- Доступ к данным через Google Sheets (легче показать инвесторам, бухгалтерам)
- Исторический long-format (легко агрегировать за любые периоды)
- ETL на cron — не надо думать когда обновлять
- Data export для аудиторов — просто share Sheets

## Level 2 (план, 1-2 недели)

**Консолидация 4 юрлиц + profitable analytics.**

```
external-sources/
  ├── 1С API (TR-юрлицо)         ← если 1С поддерживает OData/REST
  ├── ФОП Украина (bank export)
  ├── ELAN BEAUTY PL (KPiR / JPK)
  └── ELAN COSMETICS UAE (accounting)

DuckDB (локально или на GH Actions)
  ├── raw_transactions (long-format, все 4 юрлица)
  ├── intercompany (линк-таблица: ФОП → TR suppliers)
  ├── fx_rates (monthly close)
  └── consolidated_pnl

scripts/
  ├── consolidate.py             ← из raw → consolidated
  ├── validate.py                ← data quality тесты
  └── generate_data_room.py      ← для DD
```

**Что даст Level 2:**
- DD-ready financials (P&L, BS, CF за 3 года консолидированно)
- Intercompany elimination
- Related vs external revenue (для DD-ready metric)
- Unit economics по SKU/бренду
- Готовые отчёты для инвесторов (L Catterton, Advent, Carlyle)

## Принципы

1. **xlsx — source of truth, но локально** (чувствительные числа не в git)
2. **JSON-снапшот = audit trail** (коммитится, можно откатить)
3. **data.js — build artifact** (не править руками, только regenerate)
4. **Label-driven парсинг** (устойчивость к сдвигам строк/колонок)
5. **State-машина** там где нужно отделить блоки (клиенты vs задолженность)
6. **Gap-stop** при скане соседних ячеек (вместо fixed window — стоп на первой пустой ячейке)

## Чего НЕТ и будет в Level 1+

- ❌ Исторический P&L за 12 месяцев (есть только Feb + Mar 2026 + Jun 2025 benchmark)
- ❌ Balance sheet
- ❌ COGS per SKU (только per бренд)
- ❌ Утилизация производства (загрузка реакторов, выработка/день)
- ❌ Marketing метрики
- ❌ Связка 4 юрлиц в единой модели
- ❌ Отдельный учёт бренда ELAN (запуск в мае 2026)
- ❌ FX-политика (monthly close rate)
- ❌ Health-check / sensor на поломку парсеров при изменении формата xlsx

## Как менять что-то в системе

| Что меняется | Куда смотреть | Что обновить |
|---|---|---|
| Бухгалтер прислал новый xlsx | `_raw/` | `parse_raporlar.py` → `parse_kassa_ag.py` → `build_data.py` |
| Формат xlsx поменялся (новые колонки/строки) | `scripts/parse_*.py` | Добавить новый label или сдвиг колонок |
| Нужен новый показатель на сайте | `docs/data.js` через `build_data.py` | Добавить field в `build_month()` + рендер в `docs/*.html` |
| Новый сценарий exit | `data/constants.json` → `scenarios` | Потом `python scripts/build_data.py` |
| Новая сделка L'Oréal | `data/constants.json` → `loreal_acquisitions` | Потом rebuild |
| Новый KPI цель | `knowledge/00_GOAL.md` + `constants.json` → `meta.targetValuation` etc | |

## Тесты и валидация (нужны в Level 1)

Сейчас — None. Запускаешь и смотришь глазами. Что нужно добавить:

1. `scripts/validate.py`:
   - Сумма клиентов ≈ revenue (tolerance 1%)
   - COGS + OPEX < cash_out (иначе что-то не в отчёте)
   - Кассовый баланс (start + in - out = end) — arithmetic check
   - Client keys match constants.clientMetadata (нет осиротевших)
   - Month gap check — если пропустили месяц, предупреждение
2. Health-check: если парсер не нашёл ни одной ожидаемой строки — alert
