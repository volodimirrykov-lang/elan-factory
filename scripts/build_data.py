"""
build_data.py — оркестратор: читает всё из data/ и пишет docs/data.js.

Входы:
  data/snapshots/YYYY-MM.json      — из parse_raporlar.py (месячные факты)
  data/snapshots/ag_kassa.json     — из parse_kassa_ag.py
  data/constants.json              — ручные данные (meta, scenarios, loreal, valuation, payroll, capex)

Выход:
  docs/data.js — window.ELAN_DATA = {...}

Usage:
  # 1) парсим raw xlsx → JSON-снапшоты
  python scripts/parse_raporlar.py "_raw/RAPORLAR 2026 MART Kimya (1).xlsx" 2026-03
  python scripts/parse_raporlar.py "_raw/RAPORLAR 2026 ŞUBAT1.xlsx"          2026-02
  python scripts/parse_kassa_ag.py  "_raw/УЧЕТ НАЛИЧНЫХ 2026 АГ.xlsx"
  # 2) собираем data.js
  python scripts/build_data.py
"""
import sys, os, json, glob
from datetime import date
sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_month(snapshot: dict, constants: dict, ag_kassa: list) -> dict:
    """Из snapshot (raporlar) + ag_kassa (other direction income) собираем
    месячный блок той же формы, что был в старом data.js."""
    period = snapshot["period"]
    meta = constants.get("monthMetadata", {}).get(period, {})
    totals = snapshot.get("totals", {})
    costs = snapshot.get("costs", {})

    revenue = totals.get("revenue", 0) or 0
    cash_in = totals.get("cash_in", 0) or 0
    cash_out = totals.get("cash_out", 0) or 0

    # ── COGS ──
    customs = costs.get("customs_duty", 0) or 0
    cogs_raw = costs.get("cogs_raw", 0) or 0
    cogs_packaging = (costs.get("cogs_packaging_jars", 0) or 0) + (costs.get("cogs_packaging_china", 0) or 0)
    cogs_labels = costs.get("cogs_labels", 0) or 0
    cogs_boxes = costs.get("cogs_boxes", 0) or 0
    cogs_shipping = costs.get("cogs_shipping_total", 0) or 0
    cogs_total = cogs_raw + cogs_packaging + cogs_labels + cogs_boxes + cogs_shipping + customs

    # ── OPEX ──
    opex_factory = costs.get("opex_factory_total", 0) or 0
    opex_personnel = costs.get("opex_personnel_total", 0) or 0
    opex_services_raw = costs.get("opex_services_total", 0) or 0
    opex_services = max(0, opex_services_raw - customs)  # customs отделили в COGS
    opex_other = (costs.get("opex_other_total", 0) or 0) + (costs.get("opex_ukr_office", 0) or 0)
    opex_total = opex_factory + opex_personnel + opex_services + opex_other

    capex_through_opex = costs.get("capex_through_opex", 0) or 0
    capex_explicit = meta.get("capex", capex_through_opex)

    # ── Other revenue = "Поступление от учредителей" из RAPORLAR (per user: группа) ──
    other_revenue = totals.get("founder_injection", 0) or 0

    total_revenue = revenue + other_revenue
    op_profit = total_revenue - cogs_total - opex_total
    op_margin = op_profit / total_revenue if total_revenue > 0 else 0

    # ── Clients ──
    # Фикс double-counting: xlsx содержит агрегат "Приваты" + его компоненты (LUNESI UK/RAYE/
    # COSMOPROF, CLAB, BILOBROV, USUPSO) одновременно. Сумма всех клиентов = 169k при revenue 111k.
    # Выкидываем агрегат "privates" если есть хотя бы одна из его компонент.
    PRIVATES_COMPONENTS = {"lunesi_uk", "lunesi_uk_raye", "lunesi_cosmoprof", "clab", "bilobrov", "usupso"}
    raw_clients = snapshot.get("clients") or {}
    has_components = bool(raw_clients.keys() & PRIVATES_COMPONENTS)
    client_map = constants.get("clientMetadata", {})
    clients = []
    for key, amount in raw_clients.items():
        if key == "privates" and has_components:
            continue  # пропускаем агрегат, компоненты сами покажут
        cm = client_map.get(key, {"name": key, "country": "?"})
        clients.append({"name": cm["name"], "country": cm["country"], "amount": round(amount, 2), "key": key})
    clients.sort(key=lambda c: -c["amount"])

    export = totals.get("export_total", 0) or 0
    privates = (snapshot.get("clients") or {}).get("privates", 0) or 0

    return {
        "month": period,
        "label": meta.get("label", period),
        "status": meta.get("status", "normal"),
        "note": meta.get("note", ""),
        "revenue": round(revenue, 2),
        "cashIn": round(cash_in, 2),
        "cashOut": round(cash_out, 2),
        "cogs": {
            "raw_materials": round(cogs_raw, 2),
            "packaging":     round(cogs_packaging, 2),
            "labels":        round(cogs_labels, 2),
            "boxes":         round(cogs_boxes, 2),
            "shipping":      round(cogs_shipping, 2),
            "customs":       round(customs, 2),
            "total":         round(cogs_total, 2),
        },
        "opex": {
            "factory":   round(opex_factory, 2),
            "personnel": round(opex_personnel, 2),
            "services":  round(opex_services, 2),
            "other":     round(opex_other, 2),
            "total":     round(opex_total, 2),
        },
        "capex": round(capex_explicit, 2),
        "otherRevenue": round(other_revenue, 2),
        "totalRevenue": round(total_revenue, 2),
        "opProfit":     round(op_profit, 2),
        "opMargin":     round(op_margin, 4),
        "founderInjection": round(other_revenue, 2),  # legacy alias
        "export":      round(export + privates, 2),
        "exportShare": round((export + privates) / revenue, 4) if revenue > 0 else 0,
        "clients": clients,
    }


def build_ag_kassa(ag_kassa_data: dict, notes: dict) -> list:
    """Ending balance: если xlsx явно содержит "Переходящий остаток на..." — используем его.
    Иначе вычисляем: prev_end + in - out. ⚠️ Для Dec-Feb xlsx не всегда даёт явный маркер,
    вычисленные значения — approximation, не trust для DD."""
    out = []
    prev_end = 0
    for m in ag_kassa_data.get("months", []):
        in_ = m.get("in") or 0
        out_ = m.get("out_total") or 0
        ending_from_xlsx = m.get("ending")
        if ending_from_xlsx is not None:
            end = ending_from_xlsx
            ending_source = "xlsx"
        else:
            end = prev_end + in_ - out_
            ending_source = "computed"
        out.append({
            "month": m["month"],
            "label": m.get("sheet", m["month"]),
            "in":     round(in_, 0),
            "out":    round(out_, 0),
            "ending": round(end, 0),
            "endingSource": ending_source,
            **({"note": notes[m["month"]]} if m["month"] in notes else {}),
        })
        prev_end = end
    return out


def build_cash_positions(snapshot: dict, meta: dict) -> list:
    """Bank positions из последнего снапшота. Пересчёт в EUR через fxTlEur и fxEurUsd.
    Нужно для index.html (runway = totalCashEur / |groupNet|)."""
    fx_tl_eur = meta.get("fxTlEur") or 51.10
    fx_eur_usd = meta.get("fxEurUsd") or 1.08
    out = []
    for key, b in (snapshot.get("banks") or {}).items():
        label = b["label"]
        if " TL" in label: currency = "TL"
        elif "EUR" in label: currency = "EUR"
        elif "USD" in label: currency = "USD"
        else: currency = "?"
        balance = b.get("end") or 0
        if currency == "TL":    eur_equiv = balance / fx_tl_eur
        elif currency == "USD": eur_equiv = balance / fx_eur_usd
        else:                   eur_equiv = balance
        out.append({
            "account":  label,
            "currency": currency,
            "balance":  round(balance, 2),
            "eurEquiv": round(eur_equiv, 2),
        })
    return out


def _round_inv(item: dict) -> dict:
    """Fix 16-decimal floats from openpyxl (e.g. 85779.61538461539 → 85779.62)."""
    if not item:
        return {}
    return {
        "units": round(item.get("units") or 0, 0),
        "value": round(item.get("value") or 0, 2),
    }


def build_inventory(snapshot: dict) -> dict:
    inv = snapshot.get("inventory", {}) or {}
    total = sum((v.get("value") or 0) for v in inv.values())
    return {
        "finishedGoods":    _round_inv(inv.get("finished_goods")),
        "rawMaterials":     _round_inv(inv.get("raw_materials")),
        "packaging_jars":   _round_inv(inv.get("jars")),
        "packaging_boxes":  _round_inv(inv.get("boxes")),
        "labels":           _round_inv(inv.get("labels")),
        "instructions":     _round_inv(inv.get("instructions")),
        "total":            round(total, 2),
    }


def validate(snapshot: dict) -> list:
    """Data quality checks. Возвращает список предупреждений (не fatal)."""
    warnings = []
    period = snapshot.get("period", "?")
    totals = snapshot.get("totals", {})
    clients = snapshot.get("clients") or {}

    # Сумма не-агрегатных клиентов ≈ revenue (допустимое отклонение 2%)
    PRIVATES_COMPONENTS = {"lunesi_uk", "lunesi_uk_raye", "lunesi_cosmoprof", "clab", "bilobrov", "usupso"}
    has_components = bool(clients.keys() & PRIVATES_COMPONENTS)
    skip_keys = {"privates"} if has_components else set()
    clients_sum = sum(v for k, v in clients.items() if k not in skip_keys)
    revenue = totals.get("revenue", 0) or 0
    if revenue > 0:
        delta_pct = abs(clients_sum - revenue) / revenue
        if delta_pct > 0.02:
            warnings.append(f"[{period}] clients sum {clients_sum:.0f} ≠ revenue {revenue:.0f} (Δ {delta_pct*100:.1f}%)")

    # Bank: start + in - out ≈ end (±0.5 EUR допуск на округление)
    for key, b in (snapshot.get("banks") or {}).items():
        s, i, o, e = (b.get("start") or 0), (b.get("in") or 0), (b.get("out") or 0), (b.get("end") or 0)
        if abs((s + i - o) - e) > 0.5:
            warnings.append(f"[{period}] bank {key}: start {s:.0f} + in {i:.0f} - out {o:.0f} ≠ end {e:.0f}")

    return warnings


def main():
    constants = load_json(os.path.join(ROOT, "data", "constants.json"))

    # Все месячные снапшоты
    snap_files = sorted(glob.glob(os.path.join(ROOT, "data", "snapshots", "20??-??.json")))
    snapshots = [load_json(f) for f in snap_files]

    # Data quality checks
    all_warnings = []
    for s in snapshots:
        all_warnings.extend(validate(s))
    if all_warnings:
        print("⚠️  Data quality warnings:")
        for w in all_warnings:
            print(f"   {w}")

    # AG kassa
    ag_path = os.path.join(ROOT, "data", "snapshots", "ag_kassa.json")
    ag_data = load_json(ag_path) if os.path.exists(ag_path) else {"months": []}
    ag_kassa_list = build_ag_kassa(ag_data, constants.get("agKassaNotes", {}))

    # Months
    months = [build_month(s, constants, ag_data.get("months", [])) for s in snapshots]
    months.sort(key=lambda m: m["month"])

    # Последний снапшот → cashPositions + inventory
    latest = snapshots[-1] if snapshots else {}
    cash_positions = build_cash_positions(latest, constants["meta"])
    inventory = build_inventory(latest)

    # Собираем итоговый объект
    out = {
        "meta": {
            **constants["meta"],
            "lastUpdate": date.today().isoformat(),
            "sourceSnapshots": [s["period"] for s in snapshots],
        },
        "months": months,
        "agKassa": ag_kassa_list,
        "cashPositions": cash_positions,
        "payroll": constants.get("payroll_march"),
        "productShipments": constants.get("productShipments"),
        "inventory": inventory,
        "capex": constants.get("capex_summary"),
        "scenarios": constants.get("scenarios"),
        "loreal_acquisitions": constants.get("loreal_acquisitions"),
        "valuation": constants.get("valuation"),
    }

    # Дополним valuation userShare
    share = constants["meta"]["ownerShare"]
    out["valuation"]["userShare7pct"] = {
        "low":  round(out["valuation"]["totalLow"]  * share),
        "high": round(out["valuation"]["totalHigh"] * share),
    }

    # Пишем docs/data.js
    out_path = os.path.join(ROOT, "docs", "data.js")
    header = (
        "// ELAN KIMYA / ELAN FACTORY — unified data (AUTO-GENERATED)\n"
        "// Source: data/snapshots/* (из xlsx) + data/constants.json (ручные данные).\n"
        "// НЕ ПРАВИТЬ ВРУЧНУЮ. Перегенерация: python scripts/build_data.py\n"
        f"// Built: {date.today().isoformat()}\n\n"
        "window.ELAN_DATA = "
    )
    js_body = json.dumps(out, ensure_ascii=False, indent=2)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header + js_body + ";\n")

    print(f"Wrote {out_path} ({len(months)} months, {len(ag_kassa_list)} kassa months)")
    for m in months:
        print(f"  {m['month']} [{m['status']:10s}] rev={m['revenue']:>10.0f}  other={m['otherRevenue']:>10.0f}  opProfit={m['opProfit']:>+10.0f}  margin={m['opMargin']*100:+.1f}%")

    # ── Автогенерация knowledge/04_CURRENT_STATE.md ──
    state_path = os.path.join(ROOT, "knowledge", "04_CURRENT_STATE.md")
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    latest_m = months[-1] if months else None
    lines = [
        "# 04 — Current State (автогенерится)",
        "",
        f"> Последнее обновление: **{out['meta']['lastUpdate']}**.",
        f"> Источник: snapshots {', '.join(out['meta']['sourceSnapshots'])}.",
        f"> Генерируется `scripts/build_data.py`. **Не править руками.**",
        "",
        "## Ключевые метрики",
        "",
        f"- **Цель**: ${out['meta']['targetValuation']/1e6:.0f}M за {out['meta']['targetYears'][0]}-{out['meta']['targetYears'][1]} лет",
        f"- **Текущая оценка**: ${out['valuation']['totalLow']/1e6:.0f}–${out['valuation']['totalHigh']/1e6:.0f}M",
        f"- **Доля Володимира**: {out['meta']['ownerShare']*100:.0f}% (при exit $1B = ${out['meta']['targetValuation']*out['meta']['ownerShare']/1e6:.0f}M)",
        f"- **Персонал**: ~{out['meta']['headcount']} человек",
        "",
    ]
    if latest_m:
        lines += [
            f"## Последний отчёт: {latest_m['label']}",
            "",
            f"| Показатель | EUR |",
            f"|---|---:|",
            f"| Выручка TR завод | {latest_m['revenue']:>12,.0f} |",
            f"| Доход другого направления (ФОП/другое) | {latest_m['otherRevenue']:>12,.0f} |",
            f"| **Total Revenue (группа)** | **{latest_m['totalRevenue']:>12,.0f}** |",
            f"| COGS (сырьё + упаковка + доставка + таможня) | {latest_m['cogs']['total']:>12,.0f} |",
            f"| OPEX (фабрика + персонал + услуги + прочее) | {latest_m['opex']['total']:>12,.0f} |",
            f"| Operating Profit | **{latest_m['opProfit']:>+12,.0f}** |",
            f"| Operating Margin | **{latest_m['opMargin']*100:+.1f}%** |",
            f"| CAPEX через opex | {latest_m['capex']:>12,.0f} |",
            f"| Cash In (ELAN KIMYA) | {latest_m['cashIn']:>12,.0f} |",
            f"| Cash Out (ELAN KIMYA) | {latest_m['cashOut']:>12,.0f} |",
            "",
            "## Топ-5 клиентов",
            "",
            "| # | Клиент | Страна | EUR |",
            "|---:|---|---|---:|",
        ]
        for i, c in enumerate(latest_m['clients'][:5], 1):
            lines.append(f"| {i} | {c['name']} | {c['country']} | {c['amount']:>10,.0f} |")
        lines.append("")

    # Ag kassa recent
    if ag_kassa_list:
        lines += [
            "## Касса АГ (группа — 'другое направление')",
            "",
            "| Месяц | In (EUR) | Out (EUR) | Остаток |",
            "|---|---:|---:|---:|",
        ]
        for k in ag_kassa_list:
            lines.append(f"| {k['label']} | {k['in']:>10,.0f} | {k['out']:>10,.0f} | {k['ending']:>10,.0f} |")
        lines.append("")

    # Inventory
    lines += [
        "## Склад (последний снапшот)",
        "",
        f"- Готовая продукция: **€{inventory.get('finishedGoods', {}).get('value', 0):,.0f}** ({inventory.get('finishedGoods', {}).get('units', 0):,.0f} ед.)",
        f"- Сырьё: €{inventory.get('rawMaterials', {}).get('value', 0):,.0f}",
        f"- Упаковка (банки+коробки+этикетки+инструкции): €{inventory.get('packaging_jars', {}).get('value', 0) + inventory.get('packaging_boxes', {}).get('value', 0) + inventory.get('labels', {}).get('value', 0) + inventory.get('instructions', {}).get('value', 0):,.0f}",
        f"- **Всего: €{inventory.get('total', 0):,.0f}**",
        "",
        "## CAPEX",
        "",
        f"- Бюджет: ${out['capex']['budget']:,}",
        f"- Освоено: ${out['capex']['spent']:,}",
        f"- Остаток бюджета: ${out['capex']['remaining_budget']:,}",
        f"- **Долг китайским поставщикам: ${out['capex']['pending_to_chinese']:,}**",
        "",
    ]

    with open(state_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Wrote {state_path}")


if __name__ == "__main__":
    main()
