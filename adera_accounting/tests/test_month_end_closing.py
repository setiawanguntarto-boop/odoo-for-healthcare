# -*- coding: utf-8 -*-
from datetime import date
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "adera_accounting", "adera_dashboard")
class TestMonthEndClosing(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Account = cls.env["account.account"]
        cls.Journal = cls.env["account.journal"]
        cls.Analytic = cls.env["account.analytic.account"]

        cls.acc_111130 = cls.Account.search([("code", "=", "111130")], limit=1)
        cls.acc_112020 = cls.Account.search([("code", "=", "112020")], limit=1)
        cls.acc_112990 = cls.Account.search([("code", "=", "112990")], limit=1)
        cls.acc_320010 = cls.Account.search([("code", "=", "320010")], limit=1)
        cls.acc_320020 = cls.Account.search([("code", "=", "320020")], limit=1)
        cls.acc_410010 = cls.Account.search([("code", "=", "410010")], limit=1)
        cls.acc_410110 = cls.Account.search([("code", "=", "410110")], limit=1)
        cls.acc_610010 = cls.Account.search([("code", "=", "610010")], limit=1)

        cls.j_mandiri = cls.Journal.search([("code", "=", "BMDRI")], limit=1)
        cls.j_misc = cls.Journal.search([("code", "in", ["MISCL", "MISC"])], limit=1) or cls.Journal.search([("type", "=", "general")], limit=1)

    def test_01_bpjs_reconciliation(self):
        """FPK Rp 50jt (48jt approved, 1.5jt dispute, 500k rejected) posts bank inflow and 112990 write-off."""
        batch = self.env["clinic.bpjs.reconciliation.batch"].create({
            "service_unit": "hemodialysis",
            "bank_journal_id": self.j_mandiri.id,
            "total_claimed_amount": 50000000.0,
            "total_approved_amount": 48000000.0,
            "total_disputed_amount": 1500000.0,
            "total_rejected_amount": 500000.0,
        })
        batch.action_verify()
        self.assertEqual(batch.state, "verified")

        batch.action_reconcile()
        self.assertEqual(batch.state, "reconciled")
        self.assertTrue(batch.settlement_move_id)
        self.assertTrue(batch.writeoff_move_id)

        dr_bank = sum(batch.settlement_move_id.line_ids.filtered(lambda l: l.account_id == self.acc_111130).mapped("debit"))
        cr_bpjs_settle = sum(batch.settlement_move_id.line_ids.filtered(lambda l: l.account_id == self.acc_112020).mapped("credit"))
        self.assertAlmostEqual(dr_bank, 48000000.0, places=2)
        self.assertAlmostEqual(cr_bpjs_settle, 48000000.0, places=2)

        dr_112990 = sum(batch.writeoff_move_id.line_ids.filtered(lambda l: l.account_id == self.acc_112990).mapped("debit"))
        cr_bpjs_wo = sum(batch.writeoff_move_id.line_ids.filtered(lambda l: l.account_id == self.acc_112020).mapped("credit"))
        self.assertAlmostEqual(dr_112990, 500000.0, places=2)
        self.assertAlmostEqual(cr_bpjs_wo, 500000.0, places=2)

    def test_02_segmented_pnl_and_inter_entity_elimination(self):
        """Consolidated Net Profit equals sum of segments and inter-entity clearing nets to Rp 0.00."""
        aa_prat = self.Analytic.search([("code", "=", "ACC-PRATAMA")], limit=1)
        aa_hd = self.Analytic.search([("code", "=", "ACC-HD")], limit=1)
        aa_hold = self.Analytic.search([("code", "=", "ACC-HOLDING")], limit=1)

        # Post test entries across segments
        m = self.env["account.move"].create({
            "journal_id": self.j_misc.id,
            "date": date.today(),
            "move_type": "entry",
            "line_ids": [
                (0, 0, {"name": "Kas Masuk Pratama", "account_id": self.acc_111130.id, "debit": 20000000.0, "credit": 0.0}),
                (0, 0, {"name": "Rev Pratama", "account_id": self.acc_410010.id, "debit": 0.0, "credit": 20000000.0, "analytic_distribution": {str(aa_prat.id): 100.0}}),
                (0, 0, {"name": "Kas Masuk HD", "account_id": self.acc_111130.id, "debit": 30000000.0, "credit": 0.0}),
                (0, 0, {"name": "Rev HD", "account_id": self.acc_410110.id, "debit": 0.0, "credit": 30000000.0, "analytic_distribution": {str(aa_hd.id): 100.0}}),
                (0, 0, {"name": "Beban Holding", "account_id": self.acc_610010.id, "debit": 10000000.0, "credit": 0.0, "analytic_distribution": {str(aa_hold.id): 100.0}}),
                (0, 0, {"name": "Kas Keluar Holding", "account_id": self.acc_111130.id, "debit": 0.0, "credit": 10000000.0}),
            ],
        })
        m.action_post()

        pnl_data = self.env["clinic.segmented.pnl.report"].get_segmented_pnl_data(
            date.today().replace(day=1), date.today()
        )
        sum_segments = (
            pnl_data["ACC-PRATAMA"]["net_profit"]
            + pnl_data["ACC-HD"]["net_profit"]
            + pnl_data["ACC-HOLDING"]["net_profit"]
            + pnl_data["UNSEGMENTED"]["net_profit"]
        )
        self.assertAlmostEqual(pnl_data["CONSOLIDATED"]["net_profit"], sum_segments, places=2)
        self.assertAlmostEqual(pnl_data["inter_entity_net"], 0.0, places=2)

    def test_03_sinking_fund_allocation(self):
        """Net profit Rp 100,000,000 triggers exact Rp 10,000,000 reserve transfer 320010 -> 320020."""
        alloc = self.env["clinic.sinking.fund.allocation"].create({
            "date": date.today(),
            "net_profit": 100000000.0,
            "reserve_rate": 10.0,
            "transfer_liquidity": False,
        })
        self.assertAlmostEqual(alloc.reserve_amount, 10000000.0, places=2)

        alloc.action_post_allocation()
        self.assertEqual(alloc.state, "posted")
        self.assertTrue(alloc.move_id)

        dr_320010 = sum(alloc.move_id.line_ids.filtered(lambda l: l.account_id == self.acc_320010).mapped("debit"))
        cr_320020 = sum(alloc.move_id.line_ids.filtered(lambda l: l.account_id == self.acc_320020).mapped("credit"))
        self.assertAlmostEqual(dr_320010, 10000000.0, places=2)
        self.assertAlmostEqual(cr_320020, 10000000.0, places=2)

    def test_04_general_ledger_single_unaffected_earnings_and_dashboard(self):
        """Verify single equity_unaffected account (320010), indirect cash flow, and dashboard KPIs."""
        unaffected = self.Account.search([("account_type", "=", "equity_unaffected")])
        self.assertEqual(len(unaffected), 1)
        self.assertEqual(unaffected.code, "320010")

        cf = self.env["clinic.indirect.cash.flow.report"].create({
            "date_from": date.today().replace(day=1),
            "date_to": date.today(),
        })
        self.assertIsNotNone(cf.net_operating_cash_flow)

        metrics = self.env["clinic.dashboard.kpi"].get_dashboard_metrics(
            date_from=date.today().replace(day=1).strftime("%Y-%m-%d"),
            date_to=date.today().strftime("%Y-%m-%d"),
        )
        self.assertIn("bank_treasury_breakdown", metrics)
        self.assertIn("sinking_fund_reserve", metrics["compliance_flags"])

