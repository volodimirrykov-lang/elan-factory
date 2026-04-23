"""
build_data.py — оркестратор: читает всё из data/ и пишет docs/data.js + knowledge/04_CURRENT_STATE.md.

Входы:
  data/snapshots/YYYY-MM.json           — из parse_raporlar.py (месячные факты, копия xlsx)
  data/snapshots/ag_kassa.json          — из parse_kassa_ag.py
  data/adjustments/YYYY-MM.json         — ручные корректировки поверх snapshot'ов
  data/ops/meta.json                    — technical constants (entity, FX, period metadata)
  data/ops/payroll.json                 — payroll snapshot (manual)
  data/ops/capex.json                   — CAPEX snapshot (manual)
  data/ops/product_shipments.json       — unit economics (manual)
  data/business/valuation.json          — текущая + целевая оценка, components
  data/business/scenarios.json          — сценарии exit + L'Oréal paths
  data/business/comparables.json        — реальные сделки L'Oréal

Выход:
  docs/data.js                          — window.ELAN_DATA = {...}
  knowledge/04_CURRENT_STATE.md         — автогенерация текущего состояния

Usage:  python scripts/build_data.py
"""
import sys, os, json, glob, copy
from datetime import date
sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_json(path, optional=False):
    if optional and not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────
# Adjustments layer — ручные корректировки поверх snapshot'ов
# ─────────────────────────────────────────────────────────────────────────

def apply_adjustments(snapshot: dict) -> dict:
    """Применяет data/adjustments/<period>.json к snapshot. Возвращает новый объект."""
    period = snapshot.get("period")
    adj_path = os.path.join(ROOT, "data", "adjustments", f"{period}.json")
    if not os.path.exists(adj_path):
        return snapshot
    adj_data = load_json(adj_path)
    result = copy.deepcopy(snapshot)
    adjustments_applied = []

    for adj in adj_data.get("adjustments", []):
        field = adj["field"]
        op = adj["operation"]
        amount = adj["amount"]
        reason = adj.get("reason", "").strip()
        if not reason:
            raise ValueError(f"Adjustment без reason: {adj}")

        # dot-path navigation
        parts = field.split(".")
        obj = result
        for p in parts[:-1]:
            obj = obj.setdefault(p, {})
        leaf = parts[-1]
        current = obj.get(leaf, 0) or 0

        if op == "add":        obj[leaf] = current + amount
        elif op == "subtract": obj[leaf] = current - amount
        elif op == "set":      obj[leaf] = amount
        elif op == "multiply": obj[leaf] = current * amount
        else:
            raise ValueError(f"Unknown operation: {op}")

        adjustments_applied.append(f"{field} {op} {amount} ({reason})")

    result["_adjustments_applied"] = adjustments_applied
    return result


# ─────────────────────────────────────────────────────────────────────────
# Построение месячного блока
# ─────────────────────────────────────────────────────────────────────────

def build_month(snapshot: dict, meta: dict) -> dict:
    period = snapshot["period"]
    month_meta = meta.get("monthMetadata", {}).get(period, {})
    totals = snapshot.get("totals", {})
    costs = snapshot.get("costs", {})

    revenue = totals.get("revenue", 0) or 0
    cash_in = totals.get("cash_in", 0) or 0
    cash_out = totals.get("cash_out", 0) or 0

    # COGS
    customs = costs.get("customs_duty", 0) or 0
    cogs_raw = costs.get("cogs_raw", 0) or 0
    cogs_packaging = (costs.get("cogs_packaging_jars", 0) or 0) + (costs.get("cogs_packaging_china", 0) or 0)
    cogs_labels = costs.get("cogs_labels", 0) or 0
    cogs_boxes = costs.get("cogs_boxes", 0) or 0
    cogs_shipping = costs.get("cogs_shipping_total", 0) or 0
    cogs_total = cogs_raw + cogs_packaging + cogs_labels + cogs_boxes + cogs_shipping + customs

    # OPEX
    opex_factory = costs.get("opex_factory_total", 0) or 0
    opex_personnel = costs.get("opex_personnel_total", 0) or 0
    opex_services_raw = costs.get("opex_services_total", 0) or 0
    opex_services = max(0, opex_services_raw - customs)
    opex_other = (costs.get("opex_other_total", 0) or 0) + (costs.get("opex_ukr_office", 0) or 0)
    opex_total = opex_factory + opex_personnel + opex_services + opex_other

    capex_through_opex = costs.get("capex_through_opex", 0) or 0
    capex_explicit = month_meta.get("capex", capex_through_opex)

    other_revenue = totals.get("founder_injection", 0) or 0
    total_revenue = revenue + other_revenue
    op_profit = total_revenue - cogs_total - opex_total
    op_margin = op_profit / total_revenue if total_revenue > 0 else 0

    # Clients: drop агрегат "privates" если есть компоненты
    PRIVATES_COMPONENTS = {"lunesi_uk", "lunesi_uk_raye", "lunesi_cosmoprof", "clab", "bilobrov", "usupso"}
    raw_clients = snapshot.get("clients") or {}
    has_components = bool(raw_clients.keys() & PRIVATES_COMPONENTS)
    client_map = meta.get("clientMetadata", {})
    clients = []
    for key, amount in raw_clients.items():
        if key == "privates" and has_components:
            continue
        cm = client_map.get(key, {"name": key, "country": "?"})
        clients.append({"name": cm["name"], "country": cm["country"], "amount": round(amount, 2), "key": key})
    clients.sort(key=lambda c: -c["amount"])

    export = totals.get("export_total", 0) or 0
    privates = raw_clients.get("privates", 0) or 0

    return {
        "month": period,
        "label": month_meta.get("label", period),
        "status": month_meta.get("status", "normal"),
        "note": month_meta.get("note", ""),
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
        "founderInjection": round(other_revenue, 2),
        "export":      round(export + privates, 2),
        "exportShare": round((export + privates) / revenue, 4) if revenue > 0 else 0,
        "clients": clients,
    }


def build_ag_kassa(ag_kassa_data: dict, notes: dict) -> list:
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


# ─────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────

def validate_snapshot(snapshot: dict) -> list:
    warnings = []
    period = snapshot.get("period", "?")
    totals = snapshot.get("totals", {})
    clients = snapshot.get("clients") or {}

    PRIVATES_COMPONENTS = {"lunesi_uk", "lunesi_uk_raye", "lunesi_cosmoprof", "clab", "bilobrov", "usupso"}
    has_components = bool(clients.keys() & PRIVATES_COMPONENTS)
    skip_keys = {"privates"} if has_components else set()
    clients_sum = sum(v for k, v in clients.items() if k not in skip_keys)
    revenue = totals.get("revenue", 0) or 0
    if revenue > 0:
        delta_pct = abs(clients_sum - revenue) / revenue
        if delta_pct > 0.02:
            warnings.append(f"[{period}] clients sum {clients_sum:.0f} ≠ revenue {revenue:.0f} (Δ {delta_pct*100:.1f}%)")

    for key, b in (snapshot.get("banks") or {}).items():
        s = b.get("start") or 0
        i = b.get("in") or 0
        o = b.get("out") or 0
        e = b.get("end") or 0
        if abs((s + i - o) - e) > 0.5:
            warnings.append(f"[{period}] bank {key}: start {s:.0f} + in {i:.0f} - out {o:.0f} ≠ end {e:.0f}")

    return warnings


def validate_against_schema(data: dict, schema_path: str) -> list:
    """JSON Schema validation для docs/data.js структуры. Если jsonschema не установлен —
    пропускаем (warning)."""
    try:
        import jsonschema
    except ImportError:
        return ["⚠️  jsonschema не установлен — schema validation пропущена. `pip install jsonschema`"]
    if not os.path.exists(schema_path):
        return [f"⚠️  Schema {schema_path} не найден"]
    schema = load_json(schema_path)
    validator = jsonschema.Draft7Validator(schema)
    errors = []
    for err in validator.iter_errors(data):
        path = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"schema [{path}]: {err.message}")
    return errors


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────

def generate_current_state_md(out_path: str, data: dict, inventory: dict, ag_kassa: list):
    latest_m = data["months"][-1] if data["months"] else None
    meta = data["meta"]
    lines = [
        "# 04 — Current State (автогенерится)",
        "",
        f"> Последнее обновление: **{meta['lastUpdate']}**.",
        f"> Источник: snapshots {', '.join(meta['sourceSnapshots'])}.",
        f"> Генерируется `scripts/build_data.py`. **Не править руками.**",
        "",
        "## Ключевые метрики",
        "",
        f"- **Цель**: ${meta['targetValuation']/1e6:.0f}M за {meta['targetYears'][0]}-{meta['targetYears'][1]} лет",
        f"- **Текущая оценка**: ${data['valuation']['totalLow']/1e6:.0f}–${data['valuation']['totalHigh']/1e6:.0f}M",
        f"- **Доля Володимира**: {meta['ownerShare']*100:.0f}% (при exit $1B = ${meta['targetValuation']*meta['ownerShare']/1e6:.0f}M)",
        f"- **Персонал**: ~{meta['headcount']} человек",
        "",
    ]
    if latest_m:
        lines += [
            f"## Последний отчёт: {latest_m['label']}",
            "",
            "| Показатель | EUR |",
            "|---|---:|",
            f"| Выручка TR завод | {latest_m['revenue']:>12,.0f} |",
            f"| Доход другого направления (ФОП/другое) | {latest_m['otherRevenue']:>12,.0f} |",
            f"| **Total Revenue (группа)** | **{latest_m['totalRevenue']:>12,.0f}** |",
            f"| COGS | {latest_m['cogs']['total']:>12,.0f} |",
            f"| OPEX | {latest_m['opex']['total']:>12,.0f} |",
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

        related_keys = {"fop_kravchenko_ua", "elan_cosmetics_uae", "elan_beauty_pl", "elan_kozmetik_tr"}
        related_total = sum(c['amount'] for c in latest_m['clients'] if c['key'] in related_keys)
        external_total = latest_m['revenue'] - related_total
        lines += [
            "## Related-party vs External (из TR-стороны)",
            "",
            f"- Related: **€{related_total:,.0f}** ({related_total/latest_m['revenue']*100:.1f}% выручки)",
            f"- External: €{external_total:,.0f}",
            f"- Target для DD: related <30%",
            "",
        ]

    if ag_kassa:
        lines += [
            "## Касса АГ (группа — 'другое направление')",
            "",
            "| Месяц | In (EUR) | Out (EUR) | Остаток | Источник ending |",
            "|---|---:|---:|---:|---|",
        ]
        for k in ag_kassa:
            lines.append(f"| {k['label']} | {k['in']:>10,.0f} | {k['out']:>10,.0f} | {k['ending']:>10,.0f} | {k['endingSource']} |")
        lines.append("")

    lines += [
        "## Склад (последний снапшот)",
        "",
        f"- Готовая продукция: **€{inventory.get('finishedGoods', {}).get('value', 0):,.0f}** ({inventory.get('finishedGoods', {}).get('units', 0):,.0f} ед.)",
        f"- Сырьё: €{inventory.get('rawMaterials', {}).get('value', 0):,.0f}",
        f"- Упаковка: €{inventory.get('packaging_jars', {}).get('value', 0) + inventory.get('packaging_boxes', {}).get('value', 0) + inventory.get('labels', {}).get('value', 0) + inventory.get('instructions', {}).get('value', 0):,.0f}",
        f"- **Всего: €{inventory.get('total', 0):,.0f}**",
        "",
        "## CAPEX",
        "",
        f"- Бюджет: ${data['capex']['budget']:,}",
        f"- Освоено: ${data['capex']['spent']:,}",
        f"- Остаток бюджета: ${data['capex']['remaining_budget']:,}",
        f"- **Долг китайским поставщикам: ${data['capex']['pending_to_chinese']:,}**",
        "",
    ]

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    # ── Load split config files ──
    meta_cfg       = load_json(os.path.join(ROOT, "data", "ops", "meta.json"))
    payroll_cfg    = load_json(os.path.join(ROOT, "data", "ops", "payroll.json"),             optional=True)
    capex_cfg      = load_json(os.path.join(ROOT, "data", "ops", "capex.json"),                optional=True)
    shipments_cfg  = load_json(os.path.join(ROOT, "data", "ops", "product_shipments.json"),    optional=True)
    valuation_cfg  = load_json(os.path.join(ROOT, "data", "business", "valuation.json"))
    scenarios_cfg  = load_json(os.path.join(ROOT, "data", "business", "scenarios.json"))
    comparables_cfg = load_json(os.path.join(ROOT, "data", "business", "comparables.json"))

    # ── Snapshots ──
    snap_files = sorted(glob.glob(os.path.join(ROOT, "data", "snapshots", "20??-??.json")))
    snapshots = [load_json(f) for f in snap_files]

    # ── Apply adjustments ──
    snapshots = [apply_adjustments(s) for s in snapshots]

    # ── Validate snapshots (data quality) ──
    all_warnings = []
    for s in snapshots:
        all_warnings.extend(validate_snapshot(s))
    if all_warnings:
        print("⚠️  Data quality warnings:")
        for w in all_warnings:
            print(f"   {w}")

    # ── AG kassa ──
    ag_path = os.path.join(ROOT, "data", "snapshots", "ag_kassa.json")
    ag_data = load_json(ag_path, optional=True)
    ag_kassa_list = build_ag_kassa(ag_data, meta_cfg.get("agKassaNotes", {}))

    # ── Months ──
    months = [build_month(s, meta_cfg) for s in snapshots]
    months.sort(key=lambda m: m["month"])

    # ── Latest snapshot → cashPositions + inventory ──
    latest = snapshots[-1] if snapshots else {}
    cash_positions = build_cash_positions(latest, meta_cfg)
    inventory = build_inventory(latest)

    # ── Assemble ──
    out = {
        "meta": {
            "entity":           meta_cfg["entity"],
            "country":          meta_cfg["country"],
            "headcount":        meta_cfg["headcount"],
            "ownerShare":       meta_cfg["ownerShare"],
            "currentValuation": valuation_cfg["currentValuation"],
            "targetValuation":  valuation_cfg["targetValuation"],
            "targetYears":      valuation_cfg["targetYears"],
            "brandLaunch":      meta_cfg["brandLaunch"],
            "fxEurUsd":         meta_cfg["fxEurUsd"],
            "fxTlEur":          meta_cfg["fxTlEur"],
            "lastUpdate":       date.today().isoformat(),
            "sourceSnapshots":  [s["period"] for s in snapshots],
        },
        "months": months,
        "agKassa": ag_kassa_list,
        "cashPositions": cash_positions,
        "payroll": payroll_cfg or None,
        "productShipments": (shipments_cfg or {}).get("productShipments"),
        "inventory": inventory,
        "capex": capex_cfg or None,
        "scenarios": scenarios_cfg["scenarios"],
        "loreal_acquisitions": comparables_cfg["loreal_acquisitions"],
        "valuation": valuation_cfg["valuation"],
    }

    # Add user share to valuation
    share = meta_cfg["ownerShare"]
    out["valuation"]["userShare7pct"] = {
        "low":  round(out["valuation"]["totalLow"]  * share),
        "high": round(out["valuation"]["totalHigh"] * share),
    }

    # ── Schema validation ──
    schema_path = os.path.join(ROOT, "schemas", "data_js.schema.json")
    schema_errors = validate_against_schema(out, schema_path)
    # Warnings (prefixed with ⚠️) — not blocking
    blocking = [e for e in schema_errors if not e.startswith("⚠️")]
    warnings_only = [e for e in schema_errors if e.startswith("⚠️")]
    for w in warnings_only:
        print(w)
    if blocking:
        print("❌ Schema validation failures (docs/data.js shape):")
        for e in blocking:
            print(f"   {e}")
        print("⛔ Aborting — fix schema mismatch before publishing.")
        sys.exit(1)

    # ── Write data.js ──
    out_path = os.path.join(ROOT, "docs", "data.js")
    header = (
        "// ELAN KIMYA / ELAN FACTORY — unified data (AUTO-GENERATED)\n"
        "// Source: data/snapshots/* (xlsx) + data/ops/* + data/business/* (manual).\n"
        "// НЕ ПРАВИТЬ ВРУЧНУЮ. Перегенерация: python scripts/build_data.py\n"
        f"// Built: {date.today().isoformat()}\n\n"
        "window.ELAN_DATA = "
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(header + json.dumps(out, ensure_ascii=False, indent=2) + ";\n")

    print(f"✅ Wrote {out_path} ({len(months)} months, {len(ag_kassa_list)} kassa months)")
    for m in months:
        adjs = m.get("_adjustments_applied", []) if isinstance(m, dict) else []
        print(f"   {m['month']} [{m['status']:10s}] rev={m['revenue']:>10.0f}  other={m['otherRevenue']:>10.0f}  opProfit={m['opProfit']:>+10.0f}  margin={m['opMargin']*100:+.1f}%")

    # ── Auto-gen knowledge/04_CURRENT_STATE.md ──
    state_path = os.path.join(ROOT, "knowledge", "04_CURRENT_STATE.md")
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    generate_current_state_md(state_path, out, inventory, ag_kassa_list)
    print(f"✅ Wrote {state_path}")

    # ── Auto-gen knowledge/SNAPSHOT_HISTORY.md (changelog снапшотов) ──
    history_path = os.path.join(ROOT, "knowledge", "SNAPSHOT_HISTORY.md")
    history_lines = [
        "# Snapshot History (автогенерится)",
        "",
        "> История всех обработанных снапшотов + краткое состояние месяца.",
        "> Автогенерация. Не править руками.",
        "",
        "| Период | Revenue EUR | Op Profit | Op Margin | Источник | Adjustments |",
        "|---|---:|---:|---:|---|---|",
    ]
    for s in snapshots:
        m = next((mm for mm in months if mm["month"] == s["period"]), None)
        if not m: continue
        adjs = s.get("_adjustments_applied", [])
        adj_str = f"{len(adjs)} корректировок" if adjs else "—"
        history_lines.append(
            f"| {m['label']} | {m['revenue']:>10,.0f} | {m['opProfit']:>+10,.0f} | {m['opMargin']*100:+.1f}% | {s.get('source_file', '?')} | {adj_str} |"
        )
    history_lines += ["", f"*Последнее обновление: {date.today().isoformat()}*"]
    with open(history_path, "w", encoding="utf-8") as f:
        f.write("\n".join(history_lines))
    print(f"✅ Wrote {history_path}")


if __name__ == "__main__":
    main()
