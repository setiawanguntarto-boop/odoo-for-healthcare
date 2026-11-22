# -*- coding: utf-8 -*-
from datetime import date
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged("post_install", "-at_install", "adera_accounting")
class TestTreasuryPipeline(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Account = cls.env["account.account"]
        cls.Journal = cls.env["account.journal"]
        cls.MoveLine = cls.env["account.move.line"]

        cls.acc_111010 = cls.Account.search([("code", "=", "111010")], limit=1)
        cls.acc_111020 = cls.Account.search([("code", "=", "111020")], limit=1)
        cls.acc_111120 = cls.Account.search([("code", "=", "111120")], limit=1)
        cls.acc_111220 = cls.Account.search([("code", "=", "111220")], limit=1)
        cls.acc_610090 = cls.Account.search([("code", "=", "610090")], limit=1)
        cls.acc_999999 = cls.Account.search([("code", "=", "999999")], limit=1)

        cls.j_kksr = cls.Journal.search([("code", "=", "KKSR")], limit=1)
        cls.j_kkcil = cls.Journal.search([("code", "=", "KKCIL")], limit=1)
        cls.j_bri569 = cls.Journal.search([("code", "=", "BR569")], limit=1)
        cls.j_gopay = cls.Journal.search([("code", "=", "GOPAY")], limit=1)

    def test_01_zero_clearing_balance(self):
        """Account 999999 must balance strictly to Rp 0.00."""
        self.assertTrue(self.acc_999999, "Account 999999 must exist")
        posted_lines = self.MoveLine.search([
            ("account_id", "=", self.acc_999999.id),
            ("parent_state", "=", "posted"),
        ])
        net_balance = sum(posted_lines.mapped("balance"))
        self.assertAlmostEqual(net_balance, 0.0, places=2)

    def test_02_cash_deposit_execution(self):
        """Confirming & posting a Rp 15,000,000 cash deposit debits 111120 and credits 111010."""
        deposit = self.env["clinic.cash.deposit"].create({
            "date": date.today(),
            "source_journal_id": self.j_kksr.id,
            "destination_bank_id": self.j_bri569.id,
            "amount": 15000000.0,
        })
        deposit.action_confirm()
        self.assertEqual(deposit.state, "confirmed")

        deposit.action_post()
        self.assertEqual(deposit.state, "posted")
        self.assertTrue(deposit.move_id)

        dr_bank = sum(deposit.move_id.line_ids.filtered(lambda l: l.account_id == self.acc_111120).mapped("debit"))
        cr_vault = sum(deposit.move_id.line_ids.filtered(lambda l: l.account_id == self.acc_111010).mapped("credit"))
        self.assertAlmostEqual(dr_bank, 15000000.0, places=2)
        self.assertAlmostEqual(cr_vault, 15000000.0, places=2)

    def test_03_petty_cash_replenishment_ceiling(self):
        """Replenishment exceeding Rp 2,000,000 fails without override; valid tranche posts Dr 111020 / Cr 111120."""
        over_limit = self.env["clinic.petty.cash.replenishment"].create({
            "date": date.today(),
            "petty_cash_journal_id": self.j_kkcil.id,
            "funding_journal_id": self.j_bri569.id,
            "requested_amount": 2500000.0,
            "director_override": False,
        })
        with self.assertRaises(ValidationError):
            over_limit.action_request_replenishment()

        valid_req = self.env["clinic.petty.cash.replenishment"].create({
            "date": date.today(),
            "petty_cash_journal_id": self.j_kkcil.id,
            "funding_journal_id": self.j_bri569.id,
            "requested_amount": 1500000.0,
        })
        valid_req.action_request_replenishment()
        self.assertEqual(valid_req.state, "confirmed")

        valid_req.action_disburse_tranche()
        self.assertEqual(valid_req.state, "posted")
        dr_petty = sum(valid_req.move_id.line_ids.filtered(lambda l: l.account_id == self.acc_111020).mapped("debit"))
        cr_bank = sum(valid_req.move_id.line_ids.filtered(lambda l: l.account_id == self.acc_111120).mapped("credit"))
        self.assertAlmostEqual(dr_petty, 1500000.0, places=2)
        self.assertAlmostEqual(cr_bank, 1500000.0, places=2)

    def test_04_pg_mdr_reconciliation(self):
        """Rp 1,000,000 QRIS settlement with 0.7% (Rp 7,000) MDR posts Rp 993,000 to Bank and Rp 7,000 to 610090."""
        reconcile = self.env["clinic.pg.settlement.reconcile"].create({
            "date": date.today(),
            "pg_journal_id": self.j_gopay.id,
            "bank_journal_id": self.j_bri569.id,
            "gross_amount": 1000000.0,
            "mdr_rate": 0.7,
        })
        self.assertAlmostEqual(reconcile.mdr_amount, 7000.0, places=2)
        self.assertAlmostEqual(reconcile.net_bank_amount, 993000.0, places=2)

        reconcile.action_reconcile_pg_settlement()
        self.assertEqual(reconcile.state, "posted")
        move = reconcile.move_id

        dr_bank = sum(move.line_ids.filtered(lambda l: l.account_id == self.acc_111120).mapped("debit"))
        dr_mdr = sum(move.line_ids.filtered(lambda l: l.account_id == self.acc_610090).mapped("debit"))
        cr_clearing = sum(move.line_ids.filtered(lambda l: l.account_id == self.acc_111220).mapped("credit"))
        self.assertAlmostEqual(dr_bank, 993000.0, places=2)
        self.assertAlmostEqual(dr_mdr, 7000.0, places=2)
        self.assertAlmostEqual(cr_clearing, 1000000.0, places=2)

