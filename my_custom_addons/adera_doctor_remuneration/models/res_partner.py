# -*- coding: utf-8 -*-
from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_doctor = fields.Boolean(string='Merupakan Dokter / Tenaga Ahli Medis', default=False)
    doctor_type = fields.Selection([
        ('general', 'Dokter Umum / Gigi (Poli Pratama)'),
        ('specialist_hd', 'Dokter Spesialis Penyakit Dalam (Sp.PD-KGH / HD)'),
        ('nurse_hd', 'Perawat Mahir HD / Paramedis Dialisis'),
    ], string='Kategori Tenaga Medis', default='general')

    sip_number = fields.Char(string='Nomor SIP / STR', index=True)
    npwp_nik = fields.Char(string='NPWP / NIK (16 Digit)', help='Wajib 16 digit sesuai ketentuan NIK jadi NPWP.')
    has_npwp = fields.Boolean(string='Memiliki NPWP / NIK Valid', default=True)

    pph21_method = fields.Selection([
        ('berkesinambungan', 'Tenaga Ahli Berkesinambungan (Pasal 17 Progressive)'),
        ('flat', 'Tarif Efektif Rata-Rata (TER) / Flat Rate'),
    ], string='Metode Pemotongan PPh 21', default='berkesinambungan', required=True)

    ytd_gross_fee = fields.Monetary(
        string='Akumulasi Bruto Tahunan (YTD)',
        currency_field='currency_id',
        default=0.0,
        help='Total bruto fee yang diterima dalam tahun pajak berjalan.'
    )
    ytd_dpp_cumulative = fields.Monetary(
        string='Akumulasi DPP Tahunan (50% YTD)',
        currency_field='currency_id',
        default=0.0,
        help='Akumulasi DPP progresif Pasal 17.'
    )
