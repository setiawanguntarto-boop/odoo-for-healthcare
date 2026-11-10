# -*- coding: utf-8 -*-
from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_prepaid_treatment_package = fields.Boolean(
        string='Merupakan Paket Prepaid / Voucher Perawatan',
        default=False,
        help='Jika dicentang, pendapatan penjualan otomatis dikreditkan ke Pendapatan Diterima Dimuka (Akun 214010).'
    )
    package_sessions_count = fields.Integer(
        string='Jumlah Sesi Tindakan Termasuk',
        default=1,
        help='Misal 5 sesi cuci darah HD atau 3 paket scalling gigi.'
    )
    redemption_revenue_account_id = fields.Many2one(
        'account.account',
        string='Akun Pendapatan Riil Saat Ditebus (Redeemed)',
        domain="[('account_type', '=', 'income')]",
        help='Akun pendapatan yang dikredit saat sesi perawatan riil dilakukan ke pasien (misal 410110).'
    )

