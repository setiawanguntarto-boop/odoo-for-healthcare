# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
import json


class DoctorSettlement(models.Model):
    _name = 'doctor.settlement'
    _description = 'Rekapitulasi Remunerasi & Bukti Potong PPh 21 Dokter (PMK 168/2023 & UU HPP)'
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

    # PMK 168/2023 & UU HPP Cumulative YTD Tracking
    cumulative_gross_prior = fields.Monetary(
        string='Penghasilan Bruto Kumulatif Sebelumnya YTD',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
        help='Akumulasi penghasilan bruto yang telah dibayarkan kepada dokter ini sejak 1 Januari tahun pajak berjalan.',
    )
    cumulative_dpp_prior = fields.Monetary(
        string='DPP Kumulatif Sebelumnya YTD',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )
    cumulative_dpp_total = fields.Monetary(
        string='Total DPP Kumulatif Sampai Periode Ini',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )

    pph21_amount = fields.Monetary(
        string='Potongan PPh 21 Tenaga Ahli (Pasal 17 / PMK 168)',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )
    effective_tax_rate = fields.Float(
        string='Tarif Pajak Efektif (%)',
        compute='_compute_totals',
        store=True,
    )
    net_fee_payable = fields.Monetary(
        string='Jasa Medis Bersih (Take Home Pay)',
        currency_field='currency_id',
        compute='_compute_totals',
        store=True,
    )

    # DJP e-Bupot Unifikasi 21/26 Integration Fields
    ebupot_tax_code = fields.Char(
        string='Kode Objek Pajak DJP',
        default='21-100-07',
        readonly=True,
        help='21-100-07: Imbalan Kepada Tenaga Ahli yang Melakukan Pekerjaan Bebas (Dokter Spesialis/Umum)',
    )
    ebupot_bupot_number = fields.Char(
        string='Nomor Bukti Potong DJP',
        compute='_compute_ebupot_number',
        store=True,
    )
    ebupot_json_data = fields.Text(
        string='Payload JSON e-Bupot 21/26',
        compute='_compute_ebupot_payload',
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

    @api.depends('fee_line_ids.doctor_fee_amount', 'doctor_id', 'date_settlement')
    def _compute_totals(self):
        for rec in self:
            gross = sum(rec.fee_line_ids.mapped('doctor_fee_amount'))
            rec.total_gross_fee = gross
            # DPP Tenaga Ahli Dokter = 50% x Penghasilan Bruto
            dpp = gross * 0.50
            rec.dpp_amount = dpp

            # Hitung penghasilan bruto dan DPP kumulatif tahun berjalan (YTD) per PMK 168/2023
            target_year = (rec.date_settlement or fields.Date.today()).year
            prior_settlements = self.search([
                ('doctor_id', '=', rec.doctor_id.id),
                ('id', '!=', rec.id or 0),
                ('state', 'in', ('approved', 'paid')),
                ('date_settlement', '>=', f"{target_year}-01-01"),
                ('date_settlement', '<=', rec.date_settlement or fields.Date.today()),
            ])

            prior_gross = sum(prior_settlements.mapped('total_gross_fee'))
            prior_dpp = prior_gross * 0.50
            rec.cumulative_gross_prior = prior_gross
            rec.cumulative_dpp_prior = prior_dpp
            total_cum_dpp = prior_dpp + dpp
            rec.cumulative_dpp_total = total_cum_dpp

            # Perhitungan PPh 21 Progresif Pasal 17 UU HPP pada Lapisan Kumulatif Marginal
            pph = rec._calculate_pph21_marginal(prior_dpp, total_cum_dpp, has_npwp=rec.doctor_id.has_npwp)
            rec.pph21_amount = pph
            rec.effective_tax_rate = (pph / gross * 100.0) if gross > 0 else 0.0
            rec.net_fee_payable = gross - pph

    def _tax_for_dpp_bracket(self, dpp_value):
        """Menghitung total pajak akumulatif untuk suatu nilai DPP berdasarkan tarif Pasal 17 UU HPP:
           - s.d 60 juta: 5%
           - > 60 juta s.d 250 juta: 15%
           - > 250 juta s.d 500 juta: 25%
           - > 500 juta s.d 5 milyar: 30%
           - > 5 milyar: 35%
        """
        if dpp_value <= 0:
            return 0.0

        tax = 0.0
        rem = dpp_value

        brackets = [
            (60000000.0, 0.05),
            (190000000.0, 0.15),
            (250000000.0, 0.25),
            (4500000000.0, 0.30),
            (float('inf'), 0.35),
        ]

        for slice_limit, rate in brackets:
            if rem <= 0:
                break
            taxable_slice = min(rem, slice_limit)
            tax += taxable_slice * rate
            rem -= taxable_slice

        return tax

    def _calculate_pph21_marginal(self, prior_dpp, total_cum_dpp, has_npwp=True):
        """Menghitung pajak marginal untuk transaksi berjalan sesuai PMK 168/2023:
           Pajak = Total Pajak(DPP Total Kumulatif) - Total Pajak(DPP Kumulatif Sebelumnya).
           Penalti non-NPWP = 120% (1.2x).
        """
        tax_total = self._tax_for_dpp_bracket(total_cum_dpp)
        tax_prior = self._tax_for_dpp_bracket(prior_dpp)
        marginal_tax = tax_total - tax_prior

        if not has_npwp:
            marginal_tax *= 1.20

        return marginal_tax

    @api.depends('name', 'date_settlement')
    def _compute_ebupot_number(self):
        for rec in self:
            dt = rec.date_settlement or fields.Date.today()
            seq_num = rec.name.replace('/', '').replace('-', '')[-5:] if rec.name else '00001'
            rec.ebupot_bupot_number = f"BP-21/{dt.strftime('%Y/%m')}/{seq_num}"

    @api.depends('name', 'doctor_id', 'total_gross_fee', 'pph21_amount', 'date_settlement')
    def _compute_ebupot_payload(self):
        for rec in self:
            dt = rec.date_settlement or fields.Date.today()
            payload = {
                "header": {
                    "kode_transaksi": "EBUPOT-2126",
                    "tahun_pajak": dt.year,
                    "masa_pajak": dt.month,
                    "nomor_bukti_potong": rec.ebupot_bupot_number or "",
                    "tanggal_bukti_potong": dt.strftime('%Y-%m-%d'),
                },
                "pemotong": {
                    "npwp": "01.234.567.8-012.000",
                    "nama": "PT Prosperra Medika Utama / Klinik ADERA",
                },
                "penerima_penghasilan": {
                    "nama": rec.doctor_id.name or "",
                    "npwp_nik": rec.doctor_id.npwp_nik or "",
                    "has_npwp": rec.doctor_id.has_npwp,
                    "jenis_wajib_pajak": "Orang Pribadi (Bukan Pegawai / Tenaga Ahli Dokter)",
                    "nomor_sip": rec.doctor_id.sip_number or "",
                },
                "rincian_pajak": {
                    "kode_objek_pajak": rec.ebupot_tax_code,
                    "deskripsi_objek_pajak": "Imbalan Kepada Tenaga Ahli yang Melakukan Pekerjaan Bebas",
                    "penghasilan_bruto": rec.total_gross_fee,
                    "dpp_persentase": 50.0,
                    "dasar_pengenaan_pajak": rec.dpp_amount,
                    "dpp_kumulatif_ytd": rec.cumulative_dpp_total,
                    "pph_21_terutang": rec.pph21_amount,
                    "penalti_non_npwp": not rec.doctor_id.has_npwp,
                }
            }
            rec.ebupot_json_data = json.dumps(payload, indent=2)

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
                # 2. Pengeluaran Kas Bank (Credit Net Take Home Pay)
                (0, 0, {
                    'name': f"Transfer Bank Net Take-Home Pay Dokter: {self.doctor_id.name}",
                    'account_id': bank_acc.id,
                    'partner_id': self.doctor_id.id,
                    'debit': 0.0,
                    'credit': self.net_fee_payable,
                }),
                # 3. Kewajiban Pemotongan Pajak PPh 21 (Credit Utang Pajak PPh 21)
                (0, 0, {
                    'name': f"Utang PPh 21 Ps 17/PMK 168 (DJP): {self.doctor_id.name}",
                    'account_id': tax_acc.id,
                    'partner_id': self.doctor_id.id,
                    'debit': 0.0,
                    'credit': self.pph21_amount,
                }),
            ]
        }

        # Filter jika pph21_amount 0, hapus baris tax jika tidak ada nominal
        if self.pph21_amount == 0.0:
            move_vals['line_ids'].pop()

        move = self.env['account.move'].create(move_vals)
        move.action_post()

        self.fee_line_ids.write({'state': 'disbursed'})
        self.write({
            'payment_move_id': move.id,
            'state': 'paid',
        })
