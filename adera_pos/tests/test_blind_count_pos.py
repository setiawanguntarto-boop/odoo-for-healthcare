# -*- coding: utf-8 -*-
"""
Unit Test Suite for POS Blind-Count Closing Protocol & Cash Variance Governance
Klinik ADERA ERP (Odoo 19 CE)
"""

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError
from odoo import fields


class TestPosBlindCountGovernance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company

        # 1. Accounts
        cls.Account = cls.env['account.account']
        cls.cash_account = cls.Account.search([('code', 'in', ['111010', '111110'])], limit=1)
        cls.loss_account = cls.Account.search([('code', '=', '619990')], limit=1)
        if not cls.loss_account:
            cls.loss_account = cls.Account.create({
                'name': 'Beban Selisih Rekonsiliasi Kas Kasir',
                'code': '619990',
                'account_type': 'expense',
            })

        # 2. POS Config - Create a dedicated test config to avoid conflicts with active sessions
        journal = cls.env['account.journal'].search([('type', '=', 'cash')], limit=1)
        if not journal:
            journal = cls.env['account.journal'].search([('type', '=', 'general')], limit=1)
        cls.pos_config = cls.env['pos.config'].create({
            'name': 'Test POS Blind Count Config',
            'journal_id': journal.id,
        })

        # 3. Users: Cashier & Manager
        cls.group_pos_user = cls.env.ref('point_of_sale.group_pos_user')
        cls.group_pos_manager = cls.env.ref('point_of_sale.group_pos_manager')

        cls.cashier_user = cls.env['res.users'].create({
            'name': 'Kasir Pratama Test',
            'login': 'kasir_test_adera',
            'email': 'kasir@adera.test',
            'group_ids': [(6, 0, [cls.group_pos_user.id])],
        })

        cls.manager_user = cls.env['res.users'].create({
            'name': 'Supervisor Kasir Test',
            'login': 'spv_test_adera',
            'email': 'spv@adera.test',
            'group_ids': [(6, 0, [cls.group_pos_manager.id])],
        })

    def test_01_blind_count_variance_calculation(self):
        """Test blind count calculation and variance within acceptable tolerance (Rp 15,000)."""
        session = self.env['pos.session'].create({
            'user_id': self.cashier_user.id,
            'config_id': self.pos_config.id,
        })
        session.is_blind_count_mode = True
        session.cash_register_balance_end = 500000.0  # System expected: Rp 500.000
        session.blind_count_physical_total = 485000.0  # Physical count: Rp 485.000 (Shortage of Rp 15.000)

        # Variance must compute to -15,000.0
        self.assertEqual(session.cash_variance_amount, -15000.0)
        self.assertTrue(abs(session.cash_variance_amount) <= session.variance_tolerance_limit)

    def test_02_automated_cash_variance_journal_entry(self):
        """Test intentional shortage of Rp 15,000 automatically posts to Account 619990."""
        session = self.env['pos.session'].create({
            'user_id': self.cashier_user.id,
            'config_id': self.pos_config.id,
        })
        session.cash_register_balance_end = 1000000.0
        session.blind_count_physical_total = 985000.0  # Rp 15,000 shortage
        session.discrepancy_reason = "Uang kembalian koin tidak tersedia"

        # Trigger variance posting
        move = session._post_cashier_variance_entry()
        self.assertTrue(move, "Move should be generated and posted")
        self.assertEqual(move.state, 'posted')

        # Check line accounts
        debit_line = move.line_ids.filtered(lambda l: l.debit > 0)
        credit_line = move.line_ids.filtered(lambda l: l.credit > 0)

        self.assertEqual(debit_line.account_id.code, '619990', "Debit line must be Account 619990 (Beban Selisih)")
        self.assertEqual(debit_line.debit, 15000.0)
        self.assertEqual(credit_line.credit, 15000.0)

    def test_03_major_discrepancy_requires_supervisor_override(self):
        """Test major cash shortage (> Rp 50,000) blocks session closure without supervisor PIN/approval."""
        session = self.env['pos.session'].create({
            'user_id': self.cashier_user.id,
            'config_id': self.pos_config.id,
        })
        session.cash_register_balance_end = 2000000.0
        session.blind_count_physical_total = 1800000.0  # Rp 200,000 shortage! (Exceeds Rp 50,000)

        # 1. Standard Cashier cannot approve variance
        with self.assertRaises(UserError):
            session.with_user(self.cashier_user).action_supervisor_approve_variance(
                reason="Selisih kasir besar belum diverifikasi"
            )

        # 2. Session close without approval raises ValidationError
        with self.assertRaises(ValidationError):
            session.action_pos_session_close()

        # 3. Manager approves variance with Berita Acara
        session.with_user(self.manager_user).action_supervisor_approve_variance(
            reason="Investigasi: Terjadi salah input refund pasien, diotorisasi supervisor"
        )
        self.assertEqual(session.supervisor_override_user_id.id, self.manager_user.id)
        self.assertTrue(session.supervisor_override_date)
