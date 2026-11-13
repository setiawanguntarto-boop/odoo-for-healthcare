# -*- coding: utf-8 -*-
from odoo import models, fields, api, tools, exceptions, _


class ClinicApprovalInbox(models.Model):
    _name = 'clinic.approval.inbox'
    _description = 'Unified Clinical Approval Inbox'
    _auto = False
    _order = 'priority desc, date desc'

    name = fields.Char(string='Nomor Dokumen', readonly=True)
    document_type = fields.Selection([
        ('doctor_fee_batch', 'Remunerasi Dokter Bulanan'),
        ('asset_disposal', 'Pelepasan / Afkir Aset Medis'),
        ('pharmacy_scrap', 'Pemusnahan Farmasi & Spoilage'),
        ('pos_shortage', 'Selisih Kasir di Atas Toleransi'),
    ], string='Jenis Dokumen', readonly=True)

    res_model = fields.Char(string='Model Asal', readonly=True)
    res_id = fields.Integer(string='ID Dokumen Asal', readonly=True)

    originator_id = fields.Many2one('res.users', string='Diajukan Oleh', readonly=True)
    date = fields.Datetime(string='Tanggal Pengajuan', readonly=True)

    analytic_account_id = fields.Many2one('account.analytic.account', string='Unit Bisnis / Cabang', readonly=True)
    amount_total = fields.Monetary(string='Nilai Finansial / Risiko', currency_field='currency_id', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Mata Uang', readonly=True)

    current_state = fields.Char(string='Status Dokumen', readonly=True)
    required_role = fields.Selection([
        ('medical_manager', 'Manajer Pelayanan Medis'),
        ('finance_director', 'Direktur Keuangan'),
        ('clinic_director', 'Direktur Utama'),
        ('pharmacy_head', 'Apoteker Penanggung Jawab'),
    ], string='Wewenang Otorisasi', readonly=True)

    priority = fields.Selection([
        ('0', 'Rendah'),
        ('1', 'Normal'),
        ('2', 'Tinggi'),
        ('3', 'Kritis / Segera'),
    ], string='Prioritas', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW clinic_approval_inbox AS (
                -- 1. Doctor Remuneration Batches awaiting verification or disbursement
                SELECT 
                    (1000000 + b.id) AS id,
                    b.name AS name,
                    'doctor_fee_batch' AS document_type,
                    'medical.fee.settlement.batch' AS res_model,
                    b.id AS res_id,
                    b.create_uid AS originator_id,
                    b.create_date AS date,
                    NULL::integer AS analytic_account_id,
                    COALESCE(b.total_net_payable, 0.0) AS amount_total,
                    (SELECT currency_id FROM res_company LIMIT 1) AS currency_id,
                    b.state AS current_state,
                    CASE 
                        WHEN b.state = 'draft' THEN 'medical_manager'
                        ELSE 'finance_director'
                    END AS required_role,
                    '3' AS priority
                FROM medical_fee_settlement_batch b
                WHERE b.state IN ('draft', 'verified')

                UNION ALL

                -- 2. Medical Asset Disposal
                SELECT 
                    (2000000 + a.id) AS id,
                    a.name AS name,
                    'asset_disposal' AS document_type,
                    'clinic.asset.disposal' AS res_model,
                    a.id AS res_id,
                    a.create_uid AS originator_id,
                    a.create_date AS date,
                    NULL::integer AS analytic_account_id,
                    COALESCE(a.net_book_value, 0.0) AS amount_total,
                    (SELECT currency_id FROM res_company LIMIT 1) AS currency_id,
                    a.state AS current_state,
                    'clinic_director' AS required_role,
                    '1' AS priority
                FROM clinic_asset_disposal a
                WHERE a.state = 'confirmed'

                UNION ALL

                -- 3. Pharmacy & Spoilage Scrap
                SELECT 
                    (3000000 + s.id) AS id,
                    COALESCE(s.scrap_reason, 'Pemusnahan Obat/BMHP #' || s.id) AS name,
                    'pharmacy_scrap' AS document_type,
                    'stock.scrap.clinic' AS res_model,
                    s.id AS res_id,
                    s.create_uid AS originator_id,
                    s.create_date AS date,
                    s.analytic_account_id AS analytic_account_id,
                    COALESCE(s.total_spoilage_cost, 0.0) AS amount_total,
                    (SELECT currency_id FROM res_company LIMIT 1) AS currency_id,
                    s.state AS current_state,
                    'pharmacy_head' AS required_role,
                    '2' AS priority
                FROM stock_scrap_clinic s
                WHERE s.state IN ('draft', 'pending_approval')

                UNION ALL

                -- 4. POS Cash Shortage / Overage Exceeding Variance Tolerance
                SELECT 
                    (4000000 + p.id) AS id,
                    ('Sesi Kasir: ' || p.name) AS name,
                    'pos_shortage' AS document_type,
                    'pos.session' AS res_model,
                    p.id AS res_id,
                    p.create_uid AS originator_id,
                    p.create_date AS date,
                    NULL::integer AS analytic_account_id,
                    ABS(COALESCE(p.cash_variance_amount, 0.0)) AS amount_total,
                    (SELECT currency_id FROM res_company LIMIT 1) AS currency_id,
                    p.state AS current_state,
                    'finance_director' AS required_role,
                    '3' AS priority
                FROM pos_session p
                WHERE p.state = 'closing_control'
                  AND ABS(COALESCE(p.cash_variance_amount, 0.0)) > COALESCE(p.variance_tolerance_limit, 50000.0)
                  AND p.supervisor_override_user_id IS NULL
            )
        """)

    def action_open_target_document(self):
        """Navigate directly to the underlying document form view."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.res_model,
            'res_id': self.res_id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_inline_approve(self):
        """Execute approval directly from the unified inbox list view."""
        self.ensure_one()
        record = self.env[self.res_model].browse(self.res_id)
        if not record.exists():
            raise exceptions.UserError(_("Dokumen asal sudah tidak ditemukan."))

        res = None
        if self.res_model == 'medical.fee.settlement.batch':
            if record.state == 'draft':
                res = record.action_medical_manager_verify()
            elif record.state == 'verified':
                res = record.action_finance_approve_and_pay()
        elif self.res_model == 'clinic.asset.disposal':
            res = record.action_approve_disposal()
        elif self.res_model == 'stock.scrap.clinic':
            if hasattr(record, 'action_confirm_spoilage_manager'):
                res = record.action_confirm_spoilage_manager()
            elif hasattr(record, 'action_confirm_spoilage'):
                res = record.action_confirm_spoilage()
            elif hasattr(record, 'action_confirm_scrap'):
                res = record.action_confirm_scrap()
        elif self.res_model == 'pos.session':
            if hasattr(record, 'action_supervisor_approve_variance'):
                record.action_supervisor_approve_variance()
                res = True

        # Complete pending To-Do activities
        activities = self.env['mail.activity'].search([
            ('res_model', '=', self.res_model),
            ('res_id', '=', self.res_id),
        ])
        if activities:
            activities.action_feedback(feedback=_("Disetujui melalui Pusat Otorisasi oleh %s.") % self.env.user.name)

        return res or True

    def action_open_reject_wizard(self):
        """Trigger rejection popup wizard requiring mandatory feedback."""
        self.ensure_one()
        return {
            'name': _('Tolak Dokumen & Kirim Catatan Revisi'),
            'type': 'ir.actions.act_window',
            'res_model': 'clinic.approval.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_inbox_id': self.id,
                'default_res_model': self.res_model,
                'default_res_id': self.res_id,
                'default_document_name': self.name,
            }
        }

