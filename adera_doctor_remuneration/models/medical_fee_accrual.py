# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class MedicalFeeAccrual(models.Model):
    _name = 'medical.fee.accrual'
    _description = 'Akrual Jasa Medis Dokter per Tindakan'
    _order = 'encounter_date desc, id desc'

    name = fields.Char(string='Referensi Akrual', required=True, copy=False, default='/')
    doctor_id = fields.Many2one('res.partner', string='Dokter Penerima', required=True, domain="[('is_doctor', '=', True)]")
    patient_id = fields.Many2one('res.partner', string='Pasien')
    encounter_reference = fields.Char(string='Referensi Kunjungan EHR / POS', index=True)
    encounter_date = fields.Date(string='Tanggal Tindakan', default=fields.Date.context_today, required=True)

    product_id = fields.Many2one('product.product', string='Layanan / Tindakan Medis', required=True)
    billing_amount = fields.Monetary(string='Tarif Tagihan Pasien', currency_field='currency_id', required=True)
    doctor_fee_amount = fields.Monetary(string='Jasa Medis Bruto Dokter', currency_field='currency_id', required=True)
    currency_id = fields.Many2one('res.currency', string='Mata Uang', default=lambda self: self.env.company.currency_id)

    analytic_distribution = fields.Json(string='Analytic Distribution')
    settlement_id = fields.Many2one('doctor.settlement', string='Bilyet Settlement Bulanan', readonly=True)

    state = fields.Selection([
        ('accrued', 'Telah Diakru (Accrued)'),
        ('in_settlement', 'Dalam Proses Settlement'),
        ('disbursed', 'Telah Dibayar (Disbursed)'),
        ('cancelled', 'Dibatalkan'),
    ], string='Status', default='accrued', index=True, required=True)

    accrual_move_id = fields.Many2one('account.move', string='Jurnal Memorial Akrual', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('medical.fee.accrual') or '/'
        records = super(MedicalFeeAccrual, self).create(vals_list)
        for rec in records:
            rec._post_accrual_entry()
        return records

    def _post_accrual_entry(self):
        """Membuat jurnal akrual otomatis: Dr 510110/510120 / Cr 213010/213020."""
        self.ensure_one()
        if self.accrual_move_id:
            return

        rule = self.env['medical.fee.rule'].search([
            ('product_id', '=', self.product_id.id),
            ('doctor_type', '=', self.doctor_id.doctor_type),
        ], limit=1)

        # Check encounter unit if available
        is_hd = self.doctor_id.doctor_type == 'specialist_hd'
        if self.encounter_reference:
            encounter = self.env['clinic.encounter'].search([
                ('external_encounter_id', '=', self.encounter_reference)
            ], limit=1)
            if encounter:
                is_hd = encounter.clinic_unit == 'hd'

        if rule:
            expense_acc = rule.expense_account_id
            payable_acc = rule.payable_account_id
        else:
            # Fallback berdasarkan unit / doctor_type
            if is_hd:
                expense_acc = self.env.ref('adera_core.account_510120', raise_if_not_found=False)
                payable_acc = self.env.ref('adera_core.account_213020', raise_if_not_found=False)
            else:
                expense_acc = self.env.ref('adera_core.account_510110', raise_if_not_found=False)
                payable_acc = self.env.ref('adera_core.account_213010', raise_if_not_found=False)

        misc_journal = self.env.ref('adera_core.journal_misc_clinic', raise_if_not_found=False)
        if not expense_acc or not payable_acc or not misc_journal:
            return

        # Fallback analytic distribution jika belum diset
        dist = self.analytic_distribution
        if not dist:
            if is_hd:
                hd_analytic = self.env.ref('adera_core.analytic_account_hd_treat', raise_if_not_found=False)
                if hd_analytic:
                    dist = {str(hd_analytic.id): 100.0}
            else:
                prat_analytic = self.env.ref('adera_core.analytic_account_prat_umum', raise_if_not_found=False)
                if prat_analytic:
                    dist = {str(prat_analytic.id): 100.0}

        move_vals = {
            'journal_id': misc_journal.id,
            'date': self.encounter_date,
            'ref': f"Akrual Jasa Medis: {self.doctor_id.name} ({self.encounter_reference or self.name})",
            'move_type': 'entry',
            'line_ids': [
                (0, 0, {
                    'name': f"Beban Jasa Medis: {self.product_id.name} - {self.doctor_id.name}",
                    'account_id': expense_acc.id,
                    'debit': self.doctor_fee_amount,
                    'credit': 0.0,
                    'analytic_distribution': dist,
                }),
                (0, 0, {
                    'name': f"Utang Jasa Medis: {self.doctor_id.name}",
                    'account_id': payable_acc.id,
                    'partner_id': self.doctor_id.id,
                    'debit': 0.0,
                    'credit': self.doctor_fee_amount,
                }),
            ]
        }
        move = self.env['account.move'].create(move_vals)
        move.action_post()
        self.accrual_move_id = move.id

