# -*- coding: utf-8 -*-
from odoo import models, fields


class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    payment_type_category = fields.Selection([
        ('cash', 'Cash (Fisik Kas Kasir)'),
        ('electronic', 'Electronic (QRIS / EDC / Transfer)'),
        ('insurance_claim', 'Klaim Asuransi / BPJS (AR Open Item)'),
        ('voucher_deposit', 'Tebus Voucher / Deposit Pasien (Deferred Revenue)'),
    ], string='Kategori Pembayaran Klinik', default='electronic')

    third_party_partner_id = fields.Many2one(
        'res.partner',
        string='Default Debitur / Penjamin Klaim',
        help='Misal BPJS Kesehatan, AdMedika, Inhealth saat pembayaran menggunakan metode klaim piutang.'
    )

