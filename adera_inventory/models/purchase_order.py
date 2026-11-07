# -*- coding: utf-8 -*-
from odoo import models, fields


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # Dual-Vendor Handling: Distributor Penjual (partner_id) vs Pabrikan / Prinsipal (manufacturer_id)
    manufacturer_id = fields.Many2one(
        'res.partner',
        string='Pabrikan Asal (Manufacturer / Principal)',
        help='Pabrikan asli pembuat obat/BHP (contoh: Fresenius, Kalbe Farma, Dexa Medica), '
             'sedangkan Partner PO adalah PBF / Distributor Penjual (contoh: PT Enseval, PT Anugrah Argon).'
    )
    distributor_license_no = fields.Char(
        string='No. Izin PBF Distributor',
        related='partner_id.ref',
        readonly=True,
    )

