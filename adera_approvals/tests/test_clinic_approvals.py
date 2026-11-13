# -*- coding: utf-8 -*-
"""
Unit Test Suite for Unified Approval Hub & Activity Notifications
Klinik ADERA ERP (Odoo 19 CE)
"""

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError
from odoo import fields


class TestClinicApprovalsHub(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company

        # 1. Groups & Users
        cls.group_director = cls.env.ref('adera_core.group_clinic_director')
        cls.group_medical = cls.env.ref('adera_doctor_remuneration.group_medical_manager')
        cls.group_pharmacy = cls.env.ref('adera_approvals.group_pharmacy_head')

        cls.user_director = cls.env['res.users'].create({
            'name': 'Direktur Eksekutif Test',
            'login': 'director_test_adera',
            'email': 'director@adera.test',
            'group_ids': [(6, 0, [cls.group_director.id])],
        })

        cls.user_medical = cls.env['res.users'].create({
            'name': 'Manajer Medis Test',
            'login': 'medical_test_adera',
            'email': 'medmanager@adera.test',
            'group_ids': [(6, 0, [cls.group_medical.id])],
        })

    def test_01_approval_inbox_sql_view_aggregation(self):
        """Test aggregation of doctor remuneration batches and scrap records in clinic.approval.inbox."""
        # Create a doctor partner
        doctor = self.env['res.partner'].create({
            'name': 'dr. Approval Test, Sp.PD',
            'is_doctor': True,
            'doctor_type': 'general',
        })

        # Create doctor batch in draft
        batch = self.env['medical.fee.settlement.batch'].create({
            'name': 'BATCH/TEST/2026/001',
            'doctor_id': doctor.id,
            'period_start': fields.Date.today(),
            'period_end': fields.Date.today(),
            'total_net_payable': 4500000.0,
            'state': 'draft',
        })

        # Check view aggregation
        inbox_item = self.env['clinic.approval.inbox'].search([
            ('res_model', '=', 'medical.fee.settlement.batch'),
            ('res_id', '=', batch.id),
        ])
        self.assertTrue(inbox_item.exists(), "Doctor fee batch should appear in unified approval inbox.")
        self.assertEqual(inbox_item.required_role, 'medical_manager')
        self.assertEqual(inbox_item.priority, '3')
        self.assertEqual(inbox_item.amount_total, 4500000.0)

    def test_02_approval_rejection_wizard_with_mandatory_notes(self):
        """Test rejection wizard validation and chatter comment logging."""
        doctor = self.env['res.partner'].create({
            'name': 'dr. Rejection Test',
            'is_doctor': True,
        })
        batch = self.env['medical.fee.settlement.batch'].create({
            'name': 'BATCH/REJECT/2026/001',
            'doctor_id': doctor.id,
            'period_start': fields.Date.today(),
            'period_end': fields.Date.today(),
            'state': 'verified',
        })

        # Wizard validation with empty reason
        wizard = self.env['clinic.approval.reject.wizard'].create({
            'res_model': 'medical.fee.settlement.batch',
            'res_id': batch.id,
            'document_name': batch.name,
            'rejection_reason': '   ',
        })
        with self.assertRaises(ValidationError):
            wizard.action_confirm_rejection()

        # Wizard rejection with valid notes
        wizard.write({
            'rejection_reason': 'Nominal jasa tindakan hemodialisis tanggal 10 belum diverifikasi dengan log mesin.',
        })
        wizard.action_confirm_rejection()

        batch.invalidate_recordset()
        self.assertEqual(batch.state, 'draft', "Batch status should be rolled back to draft.")
        self.assertIn("Nominal jasa tindakan", batch.cancellation_reason)

    def test_03_notification_activity_bell_integration(self):
        """Test automatic To-Do mail.activity generation for authorized managers."""
        doctor = self.env['res.partner'].create({
            'name': 'dr. Activity Test',
            'is_doctor': True,
        })
        batch = self.env['medical.fee.settlement.batch'].create({
            'name': 'BATCH/ACT/2026/001',
            'doctor_id': doctor.id,
            'period_start': fields.Date.today(),
            'period_end': fields.Date.today(),
            'total_net_payable': 3500000.0,
            'state': 'draft',
        })

        # Trigger notification
        batch._notify_approvers_activity(
            summary="Otorisasi Remunerasi Dokter: BATCH/ACT/2026/001",
            note="Harap verifikasi tagihan jasa medis",
            target_group_xmlid='adera_doctor_remuneration.group_medical_manager',
        )

        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'medical.fee.settlement.batch'),
            ('res_id', '=', batch.id),
        ])
        self.assertTrue(len(activities) > 0, "To-Do activity should be created for notification bell.")
        self.assertEqual(activities[0].activity_type_id.category, 'default')

        # Test completion
        batch._complete_approval_activities()
        remaining_activities = self.env['mail.activity'].search([
            ('res_model', '=', 'medical.fee.settlement.batch'),
            ('res_id', '=', batch.id),
        ])
        self.assertEqual(len(remaining_activities), 0, "Activities should be marked done after completion.")
