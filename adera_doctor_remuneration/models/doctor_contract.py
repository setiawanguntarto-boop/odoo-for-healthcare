# -*- coding: utf-8 -*-
from odoo import models, fields


class DoctorContract(models.Model):
    _name = 'doctor.contract'
    _description = 'Perjanjian Kerjasama & Skema Bagi Hasil Dokter'

    name = fields.Char(string='Nomor Kontrak / SK', required=True)
    doctor_id = fields.Many2one('res.partner', string='Dokter', required=True, domain="[('is_doctor', '=', True)]")
    active = fields.Boolean(default=True)
    date_start = fields.Date(string='Tanggal Mulai Berlaku', required=True, default=fields.Date.context_today)
    date_end = fields.Date(string='Tanggal Berakhir')

    # Fee Split Rules
    rule_ids = fields.One2many('doctor.contract.rule', 'contract_id', string='Aturan Bagi Hasil per Layanan')


class DoctorContractRule(models.Model):
    _name = 'doctor.contract.rule'
    _description = 'Aturan Bagi Hasil per Tindakan / Produk'

    contract_id = fields.Many2one('doctor.contract', string='Kontrak', ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Layanan / Tindakan Medis', required=True)
    split_type = fields.Selection([
        ('percentage', 'Persentase (%)'),
        ('fixed', 'Nominal Tetap (Rp)'),
    ], string='Tipe Bagi Hasil', default='percentage', required=True)

    split_percentage = fields.Float(string='Porsi Dokter (%)', default=70.0)
    fixed_amount = fields.Monetary(string='Nominal Jasa Medis (Rp)', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Mata Uang', default=lambda self: self.env.company.currency_id)

    expense_account_id = fields.Many2one(
        'account.account',
        string='Akun Beban Jasa Medis',
        required=True,
        domain="[('account_type', '=', 'expense_direct_cost')]"
    )
    payable_account_id = fields.Many2one(
        'account.account',
        string='Akun Utang Jasa Medis (Akrual)',
        required=True,
        domain="[('account_type', '=', 'liability_current')]"
    )

