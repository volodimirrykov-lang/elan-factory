"""
Regression tests для build_data.py и parsers.
Запуск: python tests/test_build_data.py

Минимальный набор без pytest (чтобы работало на новом компе без доп. деп):
— использует стандартный unittest
— fixtures в tests/fixtures/ (мини-xlsx и ожидаемые snapshots)
"""
import sys, os, json, tempfile, shutil
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import build_data
import parse_raporlar
import parse_kassa_ag

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBuildMonth(unittest.TestCase):
    """Проверка build_data.build_month() с фиктивным snapshot."""

    def setUp(self):
        self.meta = {
            "monthMetadata": {"2026-03": {"label": "Март 2026", "status": "recovery"}},
            "clientMetadata": {
                "fop_kravchenko_ua": {"name": "ФОП", "country": "UA"},
                "usupso": {"name": "USUPSO", "country": "UA"},
                "privates": {"name": "Приваты", "country": "various"},
            },
        }

    def test_revenue_arithmetic(self):
        snap = {
            "period": "2026-03",
            "totals": {"revenue": 100000, "cash_in": 150000, "cash_out": 120000,
                       "export_total": 40000, "founder_injection": 50000},
            "costs": {"cogs_raw": 20000, "opex_personnel_total": 30000,
                      "opex_factory_total": 5000, "opex_services_total": 60000,
                      "customs_duty": 50000},
            "clients": {"fop_kravchenko_ua": 50000, "usupso": 50000},
            "banks": {},
            "inventory": {},
        }
        m = build_data.build_month(snap, self.meta)
        self.assertEqual(m["revenue"], 100000)
        self.assertEqual(m["otherRevenue"], 50000)
        self.assertEqual(m["totalRevenue"], 150000)
        self.assertEqual(m["cogs"]["customs"], 50000)
        # services исключает customs
        self.assertEqual(m["opex"]["services"], 10000)
        # op profit = totalRev - cogs - opex
        expected_cogs = 20000 + 0 + 0 + 0 + 0 + 50000  # raw + customs
        expected_opex = 5000 + 30000 + 10000 + 0
        self.assertEqual(m["opProfit"], 150000 - expected_cogs - expected_opex)

    def test_privates_drop_when_components_present(self):
        """Когда есть LUNESI/CLAB/BILOBROV/USUPSO — агрегат 'privates' должен быть удалён."""
        snap = {
            "period": "2026-03",
            "totals": {"revenue": 100000},
            "costs": {},
            "clients": {
                "privates": 50000,  # aggregate — should be dropped
                "usupso": 25000,
                "fop_kravchenko_ua": 25000,
            },
            "banks": {}, "inventory": {},
        }
        m = build_data.build_month(snap, self.meta)
        keys = {c["key"] for c in m["clients"]}
        self.assertNotIn("privates", keys)
        self.assertIn("usupso", keys)
        self.assertIn("fop_kravchenko_ua", keys)

    def test_privates_kept_when_no_components(self):
        """Когда компонент не найдено — агрегат 'privates' сохраняется."""
        snap = {
            "period": "2026-02",
            "totals": {"revenue": 50000},
            "costs": {},
            "clients": {"privates": 50000},
            "banks": {}, "inventory": {},
        }
        m = build_data.build_month(snap, self.meta)
        keys = {c["key"] for c in m["clients"]}
        self.assertIn("privates", keys)

    def test_zero_revenue_no_div_by_zero(self):
        snap = {
            "period": "2026-02",
            "totals": {"revenue": 0, "founder_injection": 50000},
            "costs": {},
            "clients": {}, "banks": {}, "inventory": {},
        }
        m = build_data.build_month(snap, self.meta)
        self.assertEqual(m["exportShare"], 0)
        # opMargin can be computed — totalRevenue is 50000, not 0
        self.assertEqual(m["opMargin"], 1.0)  # no costs at all


class TestCashPositions(unittest.TestCase):
    def test_eur_equiv_conversion(self):
        snap = {"banks": {
            "bank_emlak_tl":  {"label": "EMLAK BANK TL",  "end": 5110},   # 5110 TL → 100 EUR
            "bank_emlak_eur": {"label": "EMLAK BANK EUR", "end": 1000},   # 1000 EUR as-is
            "bank_emlak_usd": {"label": "EMLAK BANK USD", "end": 1080},   # 1080 USD → 1000 EUR
        }}
        meta = {"fxTlEur": 51.10, "fxEurUsd": 1.08}
        positions = build_data.build_cash_positions(snap, meta)
        by_curr = {p["currency"]: p for p in positions}
        self.assertAlmostEqual(by_curr["TL"]["eurEquiv"], 100.0, places=1)
        self.assertEqual(by_curr["EUR"]["eurEquiv"], 1000.0)
        self.assertAlmostEqual(by_curr["USD"]["eurEquiv"], 1000.0, places=1)


class TestAgKassa(unittest.TestCase):
    def test_ending_from_xlsx_takes_precedence(self):
        ag = {"months": [
            {"month": "2026-03", "in": 100, "out_total": 50, "ending": 999, "sheet": "МАРТ"},
        ]}
        result = build_data.build_ag_kassa(ag, {})
        self.assertEqual(result[0]["ending"], 999)
        self.assertEqual(result[0]["endingSource"], "xlsx")

    def test_ending_computed_when_missing(self):
        ag = {"months": [
            {"month": "2025-12", "in": 100, "out_total": 50, "ending": None, "sheet": "ДЕК"},
            {"month": "2026-01", "in": 200, "out_total": 100, "ending": None, "sheet": "ЯНВ"},
        ]}
        result = build_data.build_ag_kassa(ag, {})
        self.assertEqual(result[0]["ending"], 50)   # 0 + 100 - 50
        self.assertEqual(result[1]["ending"], 150)  # 50 + 200 - 100
        self.assertEqual(result[0]["endingSource"], "computed")


class TestAdjustments(unittest.TestCase):
    """Тесты adjustments layer."""

    def test_add_operation(self):
        snap = {"period": "2099-01", "totals": {"revenue": 100}}
        self._run_with_adj(snap, [{"field": "totals.revenue", "operation": "add", "amount": 50, "reason": "test"}])
        # Note: apply_adjustments читает из filesystem, нужен mock через tempdir

    def _run_with_adj(self, snap, adjustments):
        """Помощник: создаёт временный adjustment файл и применяет."""
        tmp_dir = tempfile.mkdtemp()
        try:
            adj_dir = os.path.join(tmp_dir, "data", "adjustments")
            os.makedirs(adj_dir)
            adj_path = os.path.join(adj_dir, f"{snap['period']}.json")
            with open(adj_path, "w", encoding="utf-8") as f:
                json.dump({"adjustments": adjustments}, f)

            # temporarily override ROOT
            original_root = build_data.ROOT
            build_data.ROOT = tmp_dir
            try:
                result = build_data.apply_adjustments(snap)
            finally:
                build_data.ROOT = original_root
            return result
        finally:
            shutil.rmtree(tmp_dir)

    def test_add(self):
        snap = {"period": "2099-01", "totals": {"revenue": 100}}
        result = self._run_with_adj(snap, [
            {"field": "totals.revenue", "operation": "add", "amount": 50, "reason": "test"}
        ])
        self.assertEqual(result["totals"]["revenue"], 150)

    def test_subtract(self):
        snap = {"period": "2099-01", "totals": {"revenue": 100}}
        result = self._run_with_adj(snap, [
            {"field": "totals.revenue", "operation": "subtract", "amount": 30, "reason": "test"}
        ])
        self.assertEqual(result["totals"]["revenue"], 70)

    def test_set(self):
        snap = {"period": "2099-01", "totals": {"revenue": 100}}
        result = self._run_with_adj(snap, [
            {"field": "totals.revenue", "operation": "set", "amount": 500, "reason": "test"}
        ])
        self.assertEqual(result["totals"]["revenue"], 500)

    def test_missing_reason_raises(self):
        snap = {"period": "2099-01", "totals": {"revenue": 100}}
        with self.assertRaises(ValueError):
            self._run_with_adj(snap, [
                {"field": "totals.revenue", "operation": "add", "amount": 50, "reason": ""}
            ])


class TestValidation(unittest.TestCase):
    def test_clients_sum_matches_revenue(self):
        snap = {
            "period": "2026-03",
            "totals": {"revenue": 100},
            "clients": {"fop_kravchenko_ua": 60, "usupso": 40},
            "banks": {},
        }
        warnings = build_data.validate_snapshot(snap)
        self.assertEqual(warnings, [])

    def test_clients_mismatch_warned(self):
        snap = {
            "period": "2026-03",
            "totals": {"revenue": 100},
            "clients": {"fop_kravchenko_ua": 50},  # 50% shortfall
            "banks": {},
        }
        warnings = build_data.validate_snapshot(snap)
        self.assertTrue(any("clients sum" in w for w in warnings))

    def test_bank_arithmetic_warned(self):
        snap = {
            "period": "2026-03",
            "totals": {"revenue": 0},
            "clients": {},
            "banks": {
                "bad_bank": {"label": "BAD", "start": 100, "in": 50, "out": 20, "end": 999},
            },
        }
        warnings = build_data.validate_snapshot(snap)
        self.assertTrue(any("bank bad_bank" in w for w in warnings))


class TestRealDataIntegrity(unittest.TestCase):
    """Интеграционный тест на реальных snapshot'ах в репо.
    Если они когда-то распарсились корректно, должны всегда оставаться такими."""

    def test_march_snapshot_revenue(self):
        path = os.path.join(ROOT, "data", "snapshots", "2026-03.json")
        if not os.path.exists(path):
            self.skipTest("No march snapshot yet")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # Эти цифры захардкожены в тесте — если парсер сломается, тест упадёт
        self.assertAlmostEqual(data["totals"]["revenue"], 110592.56, delta=0.1)
        self.assertAlmostEqual(data["totals"]["founder_injection"], 92246.34, delta=0.1)
        self.assertEqual(len(data["banks"]), 9)  # 3 банка × 3 валюты
        # клиенты включают и privates-агрегат и компоненты — что мы knowingly хотим
        self.assertGreaterEqual(len(data["clients"]), 10)

    def test_feb_snapshot_revenue(self):
        path = os.path.join(ROOT, "data", "snapshots", "2026-02.json")
        if not os.path.exists(path):
            self.skipTest("No feb snapshot yet")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertAlmostEqual(data["totals"]["revenue"], 3673.55, delta=0.1)
        self.assertAlmostEqual(data["totals"]["founder_injection"], 52931.77, delta=0.1)


class TestDataJsShape(unittest.TestCase):
    """Smoke test: docs/data.js должен быть валидным JSON внутри."""

    def test_data_js_parses(self):
        path = os.path.join(ROOT, "docs", "data.js")
        if not os.path.exists(path):
            self.skipTest("No data.js built yet")
        content = open(path, encoding="utf-8").read()
        start = content.index("{")
        end = content.rstrip().rstrip(";").rfind("}") + 1
        data = json.loads(content[start:end])

        # Ключевые поля, на которые опирается сайт
        self.assertIn("meta", data)
        self.assertIn("lastUpdate", data["meta"])
        self.assertIn("months", data)
        self.assertIn("cashPositions", data)
        for p in data["cashPositions"]:
            self.assertIn("eurEquiv", p)  # index.html runway ломался без этого
        self.assertIn("scenarios", data)
        self.assertIn("loreal_acquisitions", data)
        self.assertIn("valuation", data)
        self.assertIn("userShare7pct", data["valuation"])


if __name__ == "__main__":
    # Verbose output — видно какие тесты прошли
    unittest.main(verbosity=2)
