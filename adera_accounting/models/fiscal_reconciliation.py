# -*- coding: utf-8 -*-
from odoo import fields, models, api
from odoo.exceptions import UserError
from datetime import date
import math
import io
import base64
import xlsxwriter
import logging

_logger = logging.getLogger(__name__)


class ClinicFiscalReconciliation(models.Model):
    _name = "clinic.fiscal.reconciliation"
    _description = "Rekonsiliasi Fiskal & SPT Tahunan PPh Badan Form 1771"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "fiscal_year desc, id desc"

    name = fields.Char(string="Nomor / Judul Rekonsiliasi", required=True, tracking=True)
    fiscal_year = fields.Integer(
        string="Tahun Pajak",
        required=True,
        default=lambda self: date.today().year,
        tracking=True,
    )
    date_from = fields.Date(
        string="Tanggal Mulai",
        required=True,
        default=lambda self: date(date.today().year, 1, 1),
    )
    date_to = fields.Date(
        string="Tanggal Selesai",
        required=True,
        default=lambda self: date(date.today().year, 12, 31),
    )
    company_id = fields.Many2one(
        "res.company",
        string="Klinik / Perusahaan",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")
    state = fields.Selection(
        [
            ("draft", "Draf"),
            ("calculated", "Dihitung"),
            ("approved", "Disetujui (Final SPT)"),
        ],
        string="Status",
        default="draft",
        tracking=True,
        required=True,
    )

    # 1. Komersial P&L Summary
    gross_revenue = fields.Monetary(
        string="Peredaran Usaha Bruto Komersial",
        currency_field="currency_id",
        tracking=True,
    )
    cogs = fields.Monetary(
        string="Harga Pokok Pendapatan (HPP Medis)",
        currency_field="currency_id",
        tracking=True,
    )
    gross_profit = fields.Monetary(
        string="Laba Bruto Komersial",
        currency_field="currency_id",
        compute="_compute_totals",
        store=True,
    )
    opex = fields.Monetary(
        string="Beban Operasional & Administrasi Umum",
        currency_field="currency_id",
        tracking=True,
    )
    other_income = fields.Monetary(
        string="Penghasilan Luar Usaha (Termasuk Bunga)",
        currency_field="currency_id",
        tracking=True,
    )
    commercial_net_profit = fields.Monetary(
        string="Laba / (Rugi) Komersial Sebelum Pajak",
        currency_field="currency_id",
        compute="_compute_totals",
        store=True,
        tracking=True,
    )

    # 2. Koreksi Fiskal Positif
    adj_cashier_variance = fields.Monetary(
        string="Selisih Rekonsiliasi Kasir (619990)",
        currency_field="currency_id",
        tracking=True,
        help="Kerugian selisih kas fisik vs sistem tanpa dokumen pengesahan penanggung jawab.",
    )
    adj_natura = fields.Monetary(
        string="Kenikmatan & Natura Tanpa Daftar Nominatif (619100)",
        currency_field="currency_id",
        tracking=True,
        help="Biaya natura yang tidak memenuhi syarat PMK 66/2023.",
    )
    adj_donations = fields.Monetary(
        string="Sumbangan & Donasi Non-Deductible (619200)",
        currency_field="currency_id",
        tracking=True,
        help="Sumbangan di luar ketentuan Pasal 6 ayat 1 UU PPh.",
    )
    adj_tax_penalties = fields.Monetary(
        string="Sanksi & Denda Pajak (619300)",
        currency_field="currency_id",
        tracking=True,
        help="Sanksi administrasi STP/SKP PPh/PPN Pasal 9 ayat 1 huruf k UU PPh.",
    )
    adj_depreciation_pos = fields.Monetary(
        string="Penyusutan Komersial > Fiskal",
        currency_field="currency_id",
        tracking=True,
        help="Beban penyusutan komersial yang lebih tinggi dari batas penyusutan fiskal straight-line.",
    )
    adj_other_pos = fields.Monetary(
        string="Koreksi Positif Lainnya",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
    )
    total_positive_adjustments = fields.Monetary(
        string="Total Koreksi Fiskal Positif",
        currency_field="currency_id",
        compute="_compute_totals",
        store=True,
    )

    # 3. Koreksi Fiskal Negatif
    adj_bank_interest = fields.Monetary(
        string="Penghasilan Bunga Bank Kena PPh Final (420010)",
        currency_field="currency_id",
        tracking=True,
        help="Bunga jasa giro & tabungan yang telah dipotong PPh Final 20% oleh perbankan.",
    )
    adj_depreciation_neg = fields.Monetary(
        string="Penyusutan Fiskal > Komersial",
        currency_field="currency_id",
        tracking=True,
        help="Penyusutan fiskal yang lebih besar dari komersial.",
    )
    adj_other_neg = fields.Monetary(
        string="Koreksi Negatif Lainnya",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
    )
    total_negative_adjustments = fields.Monetary(
        string="Total Koreksi Fiskal Negatif",
        currency_field="currency_id",
        compute="_compute_totals",
        store=True,
    )

    # 4. Hasil Fiskal & Pajak Terutang
    fiscal_net_income = fields.Monetary(
        string="Penghasilan Neto Fiskal (Laba Fiskal)",
        currency_field="currency_id",
        compute="_compute_totals",
        store=True,
        tracking=True,
    )
    taxable_income = fields.Monetary(
        string="Penghasilan Kena Pajak (PKP Bulat)",
        currency_field="currency_id",
        compute="_compute_tax",
        store=True,
    )
    tax_facility = fields.Selection(
        [
            ("pasal_31e", "Fasilitas Pasal 31E UU HPP (Tarif Efektif 11% - Omzet <= Rp 4,8 M)"),
            ("standard_rate", "Tarif Normal PPh Badan (22%)"),
        ],
        string="Skema Tarif Pajak",
        default="pasal_31e",
        required=True,
        tracking=True,
    )
    effective_tax_rate = fields.Float(
        string="Tarif Pajak Efektif (%)",
        compute="_compute_tax",
        store=True,
    )
    corporate_tax_due = fields.Monetary(
        string="PPh Badan Terutang",
        currency_field="currency_id",
        compute="_compute_tax",
        store=True,
    )
    tax_credit_pph23 = fields.Monetary(
        string="Kredit Pajak PPh Pasal 23",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
        help="Bukti potong PPh 23 dari rekanan asuransi/perusahaan atas jasa medik.",
    )
    tax_underpayment = fields.Monetary(
        string="PPh Kurang / (Lebih) Bayar (PPh Pasal 29)",
        currency_field="currency_id",
        compute="_compute_tax",
        store=True,
    )

    line_ids = fields.One2many(
        "clinic.fiscal.reconciliation.line",
        "reconciliation_id",
        string="Rincian Pos Kertas Kerja",
    )

    @api.depends("gross_revenue", "cogs", "opex", "other_income",
                 "adj_cashier_variance", "adj_natura", "adj_donations", "adj_tax_penalties",
                 "adj_depreciation_pos", "adj_other_pos",
                 "adj_bank_interest", "adj_depreciation_neg", "adj_other_neg")
    def _compute_totals(self):
        for rec in self:
            rec.gross_profit = rec.gross_revenue - rec.cogs
            rec.commercial_net_profit = rec.gross_profit - rec.opex + rec.other_income

            rec.total_positive_adjustments = (
                rec.adj_cashier_variance
                + rec.adj_natura
                + rec.adj_donations
                + rec.adj_tax_penalties
                + rec.adj_depreciation_pos
                + rec.adj_other_pos
            )

            rec.total_negative_adjustments = (
                rec.adj_bank_interest
                + rec.adj_depreciation_neg
                + rec.adj_other_neg
            )

            rec.fiscal_net_income = rec.commercial_net_profit + rec.total_positive_adjustments - rec.total_negative_adjustments

    @api.depends("fiscal_net_income", "tax_facility", "tax_credit_pph23")
    def _compute_tax(self):
        for rec in self:
            if rec.fiscal_net_income > 0:
                # PKP dibulatkan ke bawah ribuan rupiah penuh
                rec.taxable_income = math.floor(rec.fiscal_net_income / 1000.0) * 1000.0
            else:
                rec.taxable_income = 0.0

            rate = 11.0 if rec.tax_facility == "pasal_31e" else 22.0
            rec.effective_tax_rate = rate

            rec.corporate_tax_due = round(rec.taxable_income * (rate / 100.0), 2)
            rec.tax_underpayment = rec.corporate_tax_due - rec.tax_credit_pph23

    def _get_balance(self, code_prefix):
        """Helper to get debit, credit, net for code prefix in date range."""
        self.ensure_one()
        moves = self.env["account.move.line"].search([
            ("account_id.code", "=like", f"{code_prefix}%"),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
            ("parent_state", "=", "posted"),
            ("company_id", "=", self.company_id.id),
        ])
        debit = sum(moves.mapped("debit"))
        credit = sum(moves.mapped("credit"))
        return debit, credit

    def action_compute(self):
        """Menghitung saldo buku besar komersial & mengekstrak pos koreksi fiskal otomatis."""
        self.ensure_one()

        # 1. Pendapatan Usaha (410xxx)
        d_rev, c_rev = self._get_balance("41")
        gross_rev = c_rev - d_rev

        # 2. HPP Medis (510xxx)
        d_cogs, c_cogs = self._get_balance("51")
        cogs_val = d_cogs - c_cogs

        # 3. Beban Operasional Umum (610xxx s/d 619xxx)
        d_opex, c_opex = self._get_balance("61")
        opex_val = d_opex - c_opex

        # 4. Pendapatan Lain-lain / Bunga Bank (420010)
        d_oth, c_oth = self._get_balance("420")
        other_inc = c_oth - d_oth

        # 5. Pos Koreksi Fiskal Positif
        d_var, c_var = self._get_balance("619990")
        cashier_var = d_var - c_var

        d_nat, c_nat = self._get_balance("619100")
        natura_val = d_nat - c_nat

        d_don, c_don = self._get_balance("619200")
        donations_val = d_don - c_don

        d_pen, c_pen = self._get_balance("619300")
        penalties_val = d_pen - c_pen

        # 6. Pos Koreksi Fiskal Negatif (Bunga Bank Pajak Final)
        d_int, c_int = self._get_balance("420010")
        bank_int = c_int - d_int

        self.write({
            "gross_revenue": gross_rev,
            "cogs": cogs_val,
            "opex": opex_val,
            "other_income": other_inc,
            "adj_cashier_variance": max(self.adj_cashier_variance or 0.0, cashier_var),
            "adj_natura": max(self.adj_natura or 0.0, natura_val),
            "adj_donations": max(self.adj_donations or 0.0, donations_val),
            "adj_tax_penalties": max(self.adj_tax_penalties or 0.0, penalties_val),
            "adj_bank_interest": max(self.adj_bank_interest or 0.0, bank_int),
            "state": "calculated",
        })

        self._generate_lines()
        return True

    def _generate_lines(self):
        """Membuat rincian baris Form 1771 Lampiran I."""
        self.ensure_one()
        self.line_ids.unlink()
        lines = []
        seq = 10

        def add_line(code, desc, comm, pos, neg, fisc, ltype="item"):
            nonlocal seq
            lines.append((0, 0, {
                "sequence": seq,
                "form_1771_code": code,
                "name": desc,
                "amount_commercial": comm,
                "adj_positive": pos,
                "adj_negative": neg,
                "amount_fiscal": fisc,
                "line_type": ltype,
            }))
            seq += 10

        add_line("1", "Peredaran Usaha Pelayanan Kesehatan (Omzet)", self.gross_revenue, 0.0, 0.0, self.gross_revenue, "header")
        add_line("2", "Harga Pokok Pendapatan (HPP Farmasi & Tindakan)", self.cogs, 0.0, 0.0, self.cogs, "header")
        add_line("3", "Laba Bruto Komersial & Fiskal", self.gross_profit, 0.0, 0.0, self.gross_profit, "subtotal")
        add_line("4", "Biaya Operasional & Administrasi Umum", self.opex, 0.0, 0.0, self.opex, "header")
        add_line("5.a", "Koreksi Positif: Selisih Rekonsiliasi Kasir (619990)", 0.0, self.adj_cashier_variance, 0.0, self.adj_cashier_variance, "adj_pos")
        add_line("5.b", "Koreksi Positif: Kenikmatan/Natura Tanpa Nominatif (619100)", 0.0, self.adj_natura, 0.0, self.adj_natura, "adj_pos")
        add_line("5.c", "Koreksi Positif: Sumbangan & Donasi Non-Deductible (619200)", 0.0, self.adj_donations, 0.0, self.adj_donations, "adj_pos")
        add_line("5.d", "Koreksi Positif: Sanksi Administrasi & Denda Pajak (619300)", 0.0, self.adj_tax_penalties, 0.0, self.adj_tax_penalties, "adj_pos")
        add_line("5.e", "Koreksi Positif: Penyusutan Komersial > Fiskal", 0.0, self.adj_depreciation_pos, 0.0, self.adj_depreciation_pos, "adj_pos")
        add_line("6.a", "Koreksi Negatif: Bunga Bank PPh Final (420010)", self.adj_bank_interest, 0.0, self.adj_bank_interest, 0.0, "adj_neg")
        add_line("6.b", "Koreksi Negatif: Penyusutan Fiskal > Komersial", 0.0, 0.0, self.adj_depreciation_neg, 0.0, "adj_neg")
        add_line("7", "Penghasilan Neto Fiskal (Laba Kena Pajak)", self.commercial_net_profit, self.total_positive_adjustments, self.total_negative_adjustments, self.fiscal_net_income, "total")

        self.write({"line_ids": lines})

    def action_approve(self):
        for rec in self:
            rec.write({"state": "approved"})
        return True

    def action_set_to_draft(self):
        for rec in self:
            rec.write({"state": "draft"})
        return True

    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref("adera_accounting.action_report_fiscal_reconciliation").report_action(self)

    def action_export_xlsx(self):
        """Menghasilkan file Excel (.xlsx) Kertas Kerja Rekonsiliasi Fiskal Form 1771 Lampiran I."""
        self.ensure_one()
        if not self.line_ids:
            self.action_compute()

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        ws = workbook.add_worksheet("Form 1771-I")

        # Formats
        title_fmt = workbook.add_format({
            "bold": True, "font_size": 14, "align": "center", "valign": "vcenter",
            "font_color": "#1B365D"
        })
        sub_fmt = workbook.add_format({
            "italic": True, "font_size": 10, "align": "center", "font_color": "#555555"
        })
        header_fmt = workbook.add_format({
            "bold": True, "bg_color": "#1B365D", "font_color": "#FFFFFF",
            "align": "center", "valign": "vcenter", "border": 1
        })
        sec_header_fmt = workbook.add_format({
            "bold": True, "bg_color": "#F0F4F8", "font_color": "#1B365D",
            "border": 1
        })
        num_fmt = workbook.add_format({
            "num_format": "#,##0", "align": "right", "border": 1
        })
        total_num_fmt = workbook.add_format({
            "bold": True, "num_format": "#,##0", "align": "right",
            "bg_color": "#E8F0FE", "border": 1
        })
        text_fmt = workbook.add_format({"border": 1})
        code_fmt = workbook.add_format({"align": "center", "border": 1})

        # Columns width
        ws.set_column(0, 0, 10)  # Kode 1771
        ws.set_column(1, 1, 52)  # Uraian
        ws.set_column(2, 2, 22)  # Komersial
        ws.set_column(3, 3, 22)  # Koreksi Positif
        ws.set_column(4, 4, 22)  # Koreksi Negatif
        ws.set_column(5, 5, 22)  # Fiskal

        # Title Block
        ws.merge_range("A1:F1", f"{self.company_id.name.upper()} - KERTAS KERJA REKONSILIASI FISKAL", title_fmt)
        ws.merge_range("A2:F2", f"LAMPIRAN I FORMULIR 1771 SPT TAHUNAN PPh BADAN TAHUN PAJAK {self.fiscal_year}", sub_fmt)
        ws.merge_range("A3:F3", f"Periode Pembukuan: {self.date_from.strftime('%d/%m/%Y')} s.d. {self.date_to.strftime('%d/%m/%Y')} | NPWP: {self.company_id.vat or '-'}", sub_fmt)

        row = 4
        # Table Headers
        headers = ["Kode 1771", "Uraian Pos Keuangan / Koreksi Fiskal", "Saldo Komersial (Rp)", "Koreksi Fiskal Positif (+)", "Koreksi Fiskal Negatif (-)", "Saldo Fiskal (Rp)"]
        for col, h in enumerate(headers):
            ws.write(row, col, h, header_fmt)

        row += 1
        for line in self.line_ids:
            is_hdr = line.line_type in ["header", "subtotal", "total"]
            f_code = code_fmt
            f_text = sec_header_fmt if is_hdr else text_fmt
            f_num = total_num_fmt if is_hdr else num_fmt

            ws.write(row, 0, line.form_1771_code or "", f_code)
            ws.write(row, 1, line.name or "", f_text)
            ws.write(row, 2, line.amount_commercial or 0.0, f_num)
            ws.write(row, 3, line.adj_positive or 0.0, f_num)
            ws.write(row, 4, line.adj_negative or 0.0, f_num)
            ws.write(row, 5, line.amount_fiscal or 0.0, f_num)
            row += 1

        # Summary Block: Perhitungan Pajak
        row += 1
        ws.merge_range(row, 0, row, 4, "Penghasilan Neto Fiskal (Laba Fiskal)", total_num_fmt)
        ws.write(row, 5, self.fiscal_net_income, total_num_fmt)
        row += 1
        ws.merge_range(row, 0, row, 4, "Penghasilan Kena Pajak (PKP Dibulatkan Ribuan Rupiah Penuh)", total_num_fmt)
        ws.write(row, 5, self.taxable_income, total_num_fmt)
        row += 1
        facility_label = f"Fasilitas Pajak ({'Pasal 31E UU HPP - Tarif Efektif 11%' if self.tax_facility == 'pasal_31e' else 'Tarif Standar 22%'})"
        ws.merge_range(row, 0, row, 4, facility_label, text_fmt)
        ws.write(row, 5, f"{self.effective_tax_rate}%", code_fmt)
        row += 1
        ws.merge_range(row, 0, row, 4, "PPh Badan Terutang Tahun Pajak Bersangkutan", total_num_fmt)
        ws.write(row, 5, self.corporate_tax_due, total_num_fmt)
        row += 1
        ws.merge_range(row, 0, row, 4, "Kredit Pajak PPh Pasal 23 Dipotong Pihak Lain", text_fmt)
        ws.write(row, 5, self.tax_credit_pph23, num_fmt)
        row += 1
        ws.merge_range(row, 0, row, 4, "PPh Kurang / (Lebih) Bayar (PPh Pasal 29)", total_num_fmt)
        ws.write(row, 5, self.tax_underpayment, total_num_fmt)

        workbook.close()
        output.seek(0)
        file_data = output.read()

        attachment = self.env["ir.attachment"].create({
            "name": f"Kertas_Kerja_Rekonsiliasi_Fiskal_{self.fiscal_year}.xlsx",
            "type": "binary",
            "datas": base64.b64encode(file_data),
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "res_model": self._name,
            "res_id": self.id,
        })

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }


class ClinicFiscalReconciliationLine(models.Model):
    _name = "clinic.fiscal.reconciliation.line"
    _description = "Baris Kertas Kerja Rekonsiliasi Fiskal"
    _order = "sequence asc, id asc"

    reconciliation_id = fields.Many2one(
        "clinic.fiscal.reconciliation",
        string="Induk Rekonsiliasi",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(string="No", default=10)
    form_1771_code = fields.Char(string="Kode Form 1771-I")
    name = fields.Char(string="Uraian Pos Keuangan / Koreksi", required=True)
    amount_commercial = fields.Monetary(string="Saldo Komersial", currency_field="currency_id")
    adj_positive = fields.Monetary(string="Koreksi Positif", currency_field="currency_id")
    adj_negative = fields.Monetary(string="Koreksi Negatif", currency_field="currency_id")
    amount_fiscal = fields.Monetary(string="Saldo Fiskal", currency_field="currency_id")
    line_type = fields.Selection(
        [
            ("header", "Header"),
            ("item", "Item"),
            ("adj_pos", "Koreksi Positif"),
            ("adj_neg", "Koreksi Negatif"),
            ("subtotal", "Subtotal"),
            ("total", "Total"),
        ],
        string="Tipe Baris",
        default="item",
    )
    currency_id = fields.Many2one("res.currency", related="reconciliation_id.currency_id")
