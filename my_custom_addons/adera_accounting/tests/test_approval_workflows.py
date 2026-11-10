# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class TestApprovalWorkflows(TransactionCase):

    def setUp(self):
        super().setUp()
        self.doc_partner = self.env['res.partner'].create({
            'name': 'Dr. Tirta Wicaksono, Sp.PD',
            'is_doctor': True,
            'vat': '01.234.567.8-901.000',
        })
        self.service_prod = self.env['product.product'].create({
            'name': 'Konsultasi Spesialis Penyakit Dalam',
            'type': 'service',
            'list_price': 300000.0,
        })
        self.asset_account = self.env['account.account'].search([('code', '=', '121010')], limit=1)
        self.depr_account = self.env['account.account'].search([('code', '=', '122010')], limit=1)
        self.exp_account = self.env['account.account'].search([('code', '=', '510030')], limit=1)
        self.journal = self.env['account.journal'].search([('type', '=', 'general')], limit=1)

    def test_01_physician_remuneration_multi_tier_approval(self):
        """Test Multi-Tier Approval: Draft -> Verified -> Approved -> Paid with Compound GL Entry."""
        batch = self.env['medical.fee.settlement.batch'].create({
            'doctor_id': self.doc_partner.id,
            'period_start': '2026-11-01',
            'period_end': '2026-11-30',
        })
        self.assertEqual(batch.state, 'draft')

        # Add line
        line = self.env['medical.fee.settlement.line'].create({
            'batch_id': batch.id,
            'encounter_date': '2026-11-05',
            'product_id': self.service_prod.id,
            'billing_amount': 300000.0,
            'doctor_fee_amount': 200000.0,
            'encounter_reference': 'ENC-TEST-100',
        })
        batch._compute_financial_totals()
        self.assertEqual(batch.total_gross_fee, 200000.0)
        self.assertEqual(batch.dpp_amount, 100000.0)
        self.assertEqual(batch.total_pph21_withheld, 5000.0) # 5% of 100k
        self.assertEqual(batch.total_net_payable, 195000.0)

        # Tier 1: Submit verification
        batch.action_submit_verification()
        self.assertEqual(batch.state, 'verified')
        self.assertTrue(batch.verified_by_id)

        # Tier 2: Medical Manager verify
        batch.action_medical_manager_verify()
        self.assertEqual(batch.state, 'approved')
        self.assertTrue(batch.approved_by_id)

        # Tier 3: Finance Director approve & execute bank disbursement
        batch.action_finance_approve_and_pay()
        self.assertEqual(batch.state, 'paid')
        self.assertTrue(batch.payment_move_id)
        self.assertEqual(batch.payment_move_id.state, 'posted')

        # Verify GL debit/credit balance
        total_debit = sum(batch.payment_move_id.line_ids.mapped('debit'))
        total_credit = sum(batch.payment_move_id.line_ids.mapped('credit'))
        self.assertAlmostEqual(total_debit, 200000.0)
        self.assertAlmostEqual(total_credit, 200000.0)

        # Check GL accounts: Debit 213010/213020, Credit 212030, Credit 111110
        codes = batch.payment_move_id.line_ids.mapped('account_id.code')
        self.assertIn('212030', codes)
        self.assertIn('111110', codes)

    def test_02_medical_asset_disposal_two_tier(self):
        """Test Two-Tier Medical Asset Disposal & Write-Off GL."""
        asset = self.env['clinic.asset'].create({
            'name': 'Hemodialysis Machine Nipro Surdial-X Test',
            'asset_category': 'medical_device_hd',
            'purchase_date': '2025-01-01',
            'purchase_value': 24000000.0,
            'salvage_value': 0.0,
            'useful_life_months': 24,
            'asset_account_id': self.asset_account.id,
            'depreciation_account_id': self.depr_account.id,
            'expense_account_id': self.exp_account.id,
            'journal_id': self.journal.id,
        })
        asset.compute_depreciation_board()
        asset.action_confirm()

        # Post 6 months depreciation (6 * 1,000,000 = 6,000,000)
        for dl in asset.depreciation_line_ids[:6]:
            dl.action_post_line()

        self.assertEqual(asset.net_book_value, 18000000.0)

        # Create disposal
        disposal = self.env['clinic.asset.disposal'].create({
            'asset_id': asset.id,
            'disposal_date': '2026-11-10',
            'disposal_reason': 'damage_unrepairable',
            'technical_notes': 'Kerusakan hidraulik parah dan tidak layak operasi',
        })
        self.assertEqual(disposal.accumulated_depreciation, 6000000.0)
        self.assertEqual(disposal.net_book_value, 18000000.0)

        # Submit & Approve
        disposal.action_submit_for_approval()
        self.assertEqual(disposal.state, 'to_approve')
        disposal.action_approve_disposal()
        self.assertEqual(disposal.state, 'approved')
        self.assertEqual(asset.state, 'disposed')

        # Check GL move
        self.assertTrue(disposal.disposal_move_id)
        self.assertEqual(disposal.disposal_move_id.state, 'posted')
        debits = sum(disposal.disposal_move_id.line_ids.mapped('debit'))
        credits = sum(disposal.disposal_move_id.line_ids.mapped('credit'))
        self.assertAlmostEqual(debits, 24000000.0)
        self.assertAlmostEqual(credits, 24000000.0)
