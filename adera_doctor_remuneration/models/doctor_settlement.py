# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class DoctorSettlement(models.Model):
    _name = 'doctor.settlement'
    _description = 'Rekapitulasi Remunerasi & Bukti Potong PPh 21 Dokter'
    _order = 'date_settlement desc, id desc'

    name = fields.Char(string='Nomor Rekap Settlement', required=True, copy=False, default='/')
    doctor_id = fields.Many2one('res.partner', string='Dokter', required=True, domain="[('is_doctor', '=', True)]")
    date_settlement = fields.Date(string='Tanggal Pembayaran', required=True, default=fields.Date.context_today)
    date_from = fields.Date(string='Periode Dari', required=True)
    date_to = fields.Date(string='Periode Sampai', required=True)

    fee_line_ids = fields.One2many('medical.fee.accrual', 'settlement_id', string='Rincian Tindakan Pelayanan')

    total_gross_fee = fields.Monetary(
        string='Total Jasa Medis Bruto',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )
    dpp_amount = fields.Monetary(
        string='Dasar Pengenaan Pajak (DPP = 50% Bruto)',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )
    pph21_amount = fields.Monetary(
        string='Potongan PPh 21 Tenaga Ahli (Pasal 17)',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )
    net_fee_payable = fields.Monetary(
        string='Jasa Medis Bersih (Take Home Pay)',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )

    currency_id = fields.Many2one('res.currency', string='Mata Uang', default=lambda self: self.env.company.currency_id)
    payment_move_id = fields.Many2one('account.move', string='Jurnal Pembayaran Bank', readonly=True)
    bank_journal_id = fields.Many2one(
        'account.journal',
        string='Rekening Bank Pengirim',
        domain="[('type', '=', 'bank')]",
        required=True,
    )

    state = fields.Selection([
        ('draft', 'Draft (Draf)'),
        ('calculated', 'Dihitung (Calculated)'),
        ('approved', 'Disetujui Direksi'),
        ('paid', 'Dibayar & Bukti Potong Terbit'),
        ('cancelled', 'Dibatalkan'),
    ], string='Status', default='draft', required=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('doctor.settlement') or '/'
        return super(DoctorSettlement, self).create(vals_list)

    def action_load_fee_lines(self):
        """Menarik semua baris jasa medis dokter berstatus accrued dalam rentang tanggal."""
        self.ensure_one()
        lines = self.env['medical.fee.accrual'].search([
            ('doctor_id', '=', self.doctor_id.id),
            ('encounter_date', '>=', self.date_from),
            ('encounter_date', '<=', self.date_to),
            ('state', '=', 'accrued'),
            ('settlement_id', '=', False),
        ])
        lines.write({'settlement_id': self.id, 'state': 'in_settlement'})
        self.state = 'calculated'

    @api.depends('fee_line_ids.doctor_fee_amount', 'doctor_id.has_npwp')
    def _compute_totals(self):
        for rec in self:
            gross = sum(rec.fee_line_ids.mapped('doctor_fee_amount'))
            rec.total_gross_fee = gross
            # DPP Tenaga Ahli Dokter = 50% x Penghasilan Bruto
            dpp = gross * 0.50
            rec.dpp_amount = dpp

            # Perhitungan PPh 21 Progresif Pasal 17 UU HPP
            pph = rec._calculate_pph21_progressive(dpp, has_npwp=rec.doctor_id.has_npwp)
            rec.pph21_amount = pph
            rec.net_fee_payable = gross - pph

    def _calculate_pph21_progressive(self, dpp, has_npwp=True):
        """Menghitung tarif progresif PPh 21 Non-Pegawai Tenaga Ahli Dokter:
           0 - 60 juta: 5%
           60 - 250 juta: 15%
           250 - 500 juta: 25%
           500 juta - 5 M: 30%
           > 5 M: 35%
           Jika tidak ber-NPWP dikenakan tarif 20% lebih tinggi (120%).
        """
        tax = 0.0
        rem = dpp

        brackets = [
            (60000000.0, 0.05),
            (190000000.0, 0.15),
            (250000000.0, 0.25),
            (4500000000.0, 0.30),
            (float('inf'), 0.35),
        ]

        for limit, rate in brackets:
            if rem <= 0:
                break
            taxable_slice = min(rem, limit)
            tax += taxable_slice * rate
            rem -= taxable_slice

        if not has_npwp:
            tax *= 1.20

        return tax

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_post_disbursement(self):
        """Membuat jurnal disbursement: Dr 213010/213020 / Cr 111110 (Bank) & Cr 212030 (Utang PPh 21)."""
        self.ensure_one()
        if self.payment_move_id:
            raise UserError("Pembayaran settlement ini sudah dibukukan sebelumnya!")

        # Tentukan payable account sesuai kategori dokter
        if self.doctor_id.doctor_type == 'specialist_hd':
            payable_acc = self.env.ref('adera_core.account_213020', raise_if_not_found=False)
        else:
            payable_acc = self.env.ref('adera_core.account_213010', raise_if_not_found=False)

        tax_acc = self.env.ref('adera_core.account_212030', raise_if_not_found=False)
        bank_acc = self.bank_journal_id.default_account_id

        if not payable_acc or not tax_acc or not bank_acc:
            raise UserError("Konfigurasi akun Utang Jasa Medis (213010/213020), Utang PPh 21 (212030), atau Akun Bank belum lengkap!")

        move_vals = {
            'journal_id': self.bank_journal_id.id,
            'date': self.date_settlement,
            'ref': f"Disbursement Remunerasi & Potongan PPh 21: {self.name} - {self.doctor_id.name}",
            'move_type': 'entry',
            'line_ids': [
                # 1. Menghapus Utang Jasa Medis (Debit Full Gross)
                (0, 0, {
                    'name': f"Pelunasan Utang Jasa Medis: {self.doctor_id.name}",
                    'account_id': payable_acc.id,
                    'partner_id': self.doctor_id.id,
                    'debit': self.total_gross_fee,
                    'credit': 0.0,
                }),
                # 2. Pemotongan Pajak PPh 21 Tenaga Ahli (Kredit Kas Negara / Utang Pajak PPh 21)
                (0, 0, {
                    'name': f"Utang PPh 21 Tenaga Ahli Dokter: {self.doctor_id.name} (DPP: Rp {self.dpp_amount:,.2f})",
                    'account_id': tax_acc.id,
                    'partner_id': self.doctor_id.id,
                    'debit': 0.0,
                    'credit': self.pph21_amount,
                }),
                # 3. Pengeluaran Rekening Bank (Kredit Net Pay)
                (0, 0, {
                    'name': f"Transfer Bank Take Home Pay ke {self.doctor_id.name}",
                    'account_id': bank_acc.id,
                    'partner_id': self.doctor_id.id,
                    'debit': 0.0,
                    'credit': self.net_fee_payable,
                }),
            ]
        }

        payment_move = self.env['account.move'].create(move_vals)
        payment_move.action_post()
        self.payment_move_id = payment_move.id
        self.fee_line_ids.write({'state': 'disbursed'})
        
        # Update YTD cumulative figures pada record dokter
        self.doctor_id.ytd_gross_fee += self.total_gross_fee
        self.doctor_id.ytd_dpp_cumulative += self.dpp_amount

        self.state = 'paid'
