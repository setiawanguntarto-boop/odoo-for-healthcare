# -*- coding: utf-8 -*-
from odoo import models, fields


class MedicalFeeRule(models.Model):
    _name = 'medical.fee.rule'
    _description = 'Aturan Pembagian Jasa Medis Dokter per Layanan'

    name = fields.Char(string='Nama Skema Remunerasi', required=True)
    doctor_type = fields.Selection([
        ('general', 'Dokter Umum / Gigi (Poli Pratama)'),
        ('specialist_hd', 'Dokter Spesialis HD'),
        ('nurse_hd', 'Perawat Mahir HD'),
    ], string='Kategori Dokter', required=True, default='general')

    product_id = fields.Many2one(
        'product.product',
        string='Layanan / Tindakan Medis',
        required=True,
        domain="[('type', '=', 'service')]"
    )
    doctor_share_type = fields.Selection([
        ('percentage', 'Persentase (%)'),
        ('fixed_amount', 'Nominal Tetap (Rp)'),
    ], string='Tipe Bagi Hasil', default='percentage', required=True)

    doctor_share_rate = fields.Float(string='Porsi Dokter (%)', default=70.0)
    fixed_amount = fields.Monetary(string='Nominal Jasa Medis (Rp)', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Mata Uang', default=lambda self: self.env.company.currency_id)

    expense_account_id = fields.Many2one(
        'account.account',
        string='Akun Beban Jasa Medis (P&L)',
        required=True,
        domain="[('account_type', '=', 'expense_direct_cost')]"
    )
    payable_account_id = fields.Many2one(
        'account.account',
        string='Akun Utang Jasa Medis (Neraca/Akrual)',
        required=True,
        domain="[('account_type', '=', 'liability_current')]"
    )

