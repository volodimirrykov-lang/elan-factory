# Adjustments

Ручные корректировки, применяемые поверх snapshot'ов после парсинга xlsx. Нужны когда:

- Бухгалтер забыл отразить одноразовую статью
- Нужен intercompany elimination (например ФОП UA купил у TR — убираем double counting в consolidated view)
- Reclass: «эта статья должна быть COGS, а не OPEX»
- Округления для DD-ready отчёта

## Формат

`data/adjustments/YYYY-MM.json`:

```json
{
  "period": "2026-04",
  "adjustments": [
    {
      "field": "costs.opex_personnel_total",
      "operation": "add",
      "amount": 1500,
      "reason": "Бухгалтер забыл включить бонус за Q1 (договорённость от 2026-04-15)",
      "applied_by": "Володимир",
      "applied_at": "2026-05-02"
    },
    {
      "field": "totals.revenue",
      "operation": "subtract",
      "amount": 25000,
      "reason": "Intercompany: ФОП UA → TR (eliminate для consolidated)",
      "applied_by": "Володимир",
      "applied_at": "2026-05-02"
    },
    {
      "field": "clients.fop_kravchenko_ua",
      "operation": "set",
      "amount": 0,
      "reason": "Related-party: полностью elim в group view"
    }
  ]
}
```

## Операции

- `add` — `current + amount`
- `subtract` — `current - amount`
- `set` — `amount` (перезапись)
- `multiply` — `current * amount` (для % корректировок)

## Поля обязательные

- `field` — dot-path (e.g. `costs.opex_personnel_total`, `clients.usupso`, `totals.revenue`)
- `operation` — одна из add/subtract/set/multiply
- `amount` — число
- `reason` — **обязательно**, для audit trail (на DD спросят "почему")

## Правила

1. **Adjustments применяются ПОСЛЕ парсинга**, перед генерацией data.js.
2. **Оригинальный snapshot не меняется** — он остаётся точной копией xlsx.
3. **Каждая корректировка должна иметь reason**. Без reason — не принимается (build_data.py упадёт).
4. **Commit с adjustment → коммит-сообщение содержит период и причину.**
5. **Для DD-экспорта adjustments тоже экспортируются** как отдельный attachment (аудитору нужно).
