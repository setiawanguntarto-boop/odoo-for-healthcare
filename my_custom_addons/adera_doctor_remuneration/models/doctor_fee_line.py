# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class DoctorFeeLine(models.Model):
    _name = 'doctor.fee.line'
    _description = 'Baris Akrual Jasa Medis Dokter'
    _order = 'encounter_date desc, id desc'

    name = fields.Char(string='Referensi Jasa Medis', required=True, copy=False, default='/')
    doctor_id = fields.Many2one('res.partner', string='Dokter Penerima', required=True, domain="[('is_doctor', '=', True)]")
    patient_id = fields.Many2one('res.partner', string='Pasien')
    encounter_reference = fields.Char(string='Referensi Kunjungan EHR / POS')
    encounter_date = fields.Date(string='Tanggal Tindakan', default=fields.Date.context_today, required=True)

    product_id = fields.Many2one('product.product', string='Layanan / Tindakan Medis', required=True)
    billing_amount = fields.Monetary(string='Tarif Tagihan Pasien', currency_field='currency_id', required=True)
    doctor_fee_amount = fields.Monetary(string='Jasa Medis Bruto Dokter', currency_field='currency_id', required=True)
    currency_id = fields.Many2one('res.currency', string='Mata Uang', default=lambda self: self.env.company.currency_id)

    analytic_distribution = fields.Json(string='Analytic Distribution')
    settlement_id = fields.Many2one('doctor.settlement', string='Bilyet / Dokumen Settlement', readonly=True)

    state = fields.Selection([
        ('accrued', 'Telah Diakru (Accrued)'),
        ('in_settlement', 'Dalam Proses Settlement'),
        ('paid', 'Telah Dibayar (Settled)'),
        ('cancelled', 'Dibatalkan'),
    ], string='Status', default='accrued', index=True, required=True)

    accrual_move_id = fields.Many2one('account.move', string='Jurnal Akrual Beban', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('doctor.fee.line') or '/'
        records = super(DoctorFeeLine, self).create(vals_list)
        for rec in records:
            rec._post_accrual_entry()
        return records

    def _post_accrual_entry(self):
        """Membuat jurnal akrual otomatis: Dr Beban Jasa Medis / Cr Utang Jasa Medis."""
        self.ensure_one()
        if self.accrual_move_id:
            return

        # Ambil akun dari kontrak dokter atau default core
        contract = self.env['doctor.contract'].search([
            ('doctor_id', '=', self.doctor_id.id),
            ('active', '=', True)
        ], limit=1)

        rule = contract.rule_ids.filtered(lambda r: r.product_id == self.product_id)[:1] if contract else False

        expense_acc = rule.expense_account_id if rule and rule.expense_account_id else self.env.ref('adera_core.account_510110', raise_if_not_found=False)
        payable_acc = rule.payable_account_id if rule and rule.payable_account_id else self.env.ref('adera_core.account_213010', raise_if_not_found=False)
        misc_journal = self.env.ref('adera_core.journal_misc_clinic', raise_if_not_found=False)

        if not expense_acc or not payable_acc or not misc_journal:
            return

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
                    'analytic_distribution': self.analytic_distribution,
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

