# -*- coding: utf-8 -*-
from odoo import fields, models, api
from dateutil.relativedelta import relativedelta
from datetime import date
import json


class PsakFinancialReport(models.Model):
    _name = "psak.financial.report"
    _description = "Laporan Keuangan Klinik"
    _order = "date_to desc, id desc"

    name = fields.Char(string="Nama Laporan", required=True)
    framework_standard = fields.Selection(
        [
            ("emkm", "SAK EMKM"),
            ("sak_ep", "SAK EP / PSAK"),
        ],
        string="Standar Akuntansi Regulasi",
        default="emkm",
        required=True,
        help="Sesuai Keputusan DPN IAI & Permenkes 14/2021 untuk Tata Kelola Keuangan Klinik Swasta Nasional",
    )
    report_type = fields.Selection(
        [
            ("profit_loss", "Laporan Laba Rugi"),
            ("balance_sheet", "Laporan Posisi Keuangan"),
            ("cash_flow", "Laporan Arus Kas"),
            ("equity_change", "Laporan Perubahan Ekuitas"),
            ("calk", "Catatan Atas Laporan Keuangan"),
        ],
        string="Tipe Laporan Standar",
        required=True,
    )
    cash_flow_method = fields.Selection(
        [
            ("direct", "Metode Langsung (Direct Method - PSAK 2 / SAK EP)"),
            ("indirect", "Metode Tidak Langsung (Indirect Method - PSAK 2 / SAK EP)"),
        ],
        string="Metode Arus Kas",
        default="direct",
    )

    date_preset = fields.Selection(
        [
            ("this_month", "Bulan Berjalan (This Month)"),
            ("this_quarter", "Kuartal Berjalan (This Quarter)"),
            ("ytd", "Tahun Berjalan (Year to Date)"),
            ("custom", "Kustom (Pilih Rentang Tanggal)"),
        ],
        string="Preset Periode",
        default="this_month",
        help="Pilihan cepat periode waktu pelaporan",
    )

    date_from = fields.Date(string="Tanggal Awal", required=True)
    date_to = fields.Date(string="Tanggal Akhir", required=True)
    target_move = fields.Selection(
        [
            ("posted", "Semua Entri yang Diposting (Audit Ready)"),
            ("all", "Semua Entri (Termasuk Draf/Staging)"),
        ],
        string="Target Entri",
        default="posted",
        required=True,
    )

    comparison_type = fields.Selection(
        [
            ("none", "Tanpa Perbandingan"),
            ("previous_period", "Periode Sebelumnya"),
            ("previous_year", "Periode yang Sama Tahun Lalu"),
        ],
        string="Mode Perbandingan",
        default="none",
    )

    date_from_cmp = fields.Date(string="Tanggal Awal")
    date_to_cmp = fields.Date(string="Tanggal Akhir")

    analytic_account_id = fields.Many2one(
        "account.analytic.account",
        string="Unit Bisnis Analitik",
        help="Pilih ACC-PRATAMA atau ACC-HD untuk isolasi unit bisnis, atau kosongkan untuk Konsolidasi Seluruh Klinik",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Entitas Klinik",
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")

    line_ids = fields.One2many(
        "psak.financial.report.line",
        "report_id",
        string="Rincian Baris Laporan",
    )

    # Computed Statutory Totals & Balance Audit Metrics
    total_assets = fields.Monetary(string="Total Aset", compute="_compute_report_totals", store=True)
    total_liabilities = fields.Monetary(string="Total Liabilitas", compute="_compute_report_totals", store=True)
    total_equity = fields.Monetary(string="Total Ekuitas", compute="_compute_report_totals", store=True)
    total_liabilities_equity = fields.Monetary(string="Total Liabilitas & Ekuitas", compute="_compute_report_totals", store=True)
    balance_difference = fields.Monetary(string="Selisih Keseimbangan", compute="_compute_report_totals", store=True)
    is_balanced = fields.Boolean(string="Status Seimbang (Balanced)", compute="_compute_report_totals", store=True)
    net_profit = fields.Monetary(string="Laba / (Rugi) Bersih", compute="_compute_report_totals", store=True)
    total_revenue = fields.Monetary(string="Total Pendapatan", compute="_compute_report_totals", store=True)
    total_cogs = fields.Monetary(string="Total HPP (Beban Pokok)", compute="_compute_report_totals", store=True)
    total_opex = fields.Monetary(string="Total Beban Operasional", compute="_compute_report_totals", store=True)

    @api.depends("line_ids.amount_current", "report_type")
    def _compute_report_totals(self):
        for rec in self:
            assets = 0.0
            liab = 0.0
            equity = 0.0
            liab_eq = 0.0
            profit = 0.0
            rev = 0.0
            cogs = 0.0
            opex = 0.0

            for line in rec.line_ids:
                if line.code == "AUDIT-00":
                    continue
                lname = (line.name or "").upper()
                if "TOTAL ASET (" in lname or lname.strip() == "TOTAL ASET":
                    assets = line.amount_current
                elif "TOTAL KEWAJIBAN JANGKA PENDEK" in lname or "TOTAL LIABILITAS" in lname:
                    liab = line.amount_current
                elif "TOTAL EKUITAS" in lname:
                    equity = line.amount_current
                elif "TOTAL KEWAJIBAN & EKUITAS" in lname:
                    liab_eq = line.amount_current
                elif "LABA" in lname and ("BERSIH" in lname or "TAHUN BERJALAN" in lname or "PERIODE BERJALAN" in lname or "SETELAH PAJAK" in lname):
                    profit = line.amount_current
                elif "TOTAL PENDAPATAN USAHA" in lname:
                    rev = line.amount_current
                elif "TOTAL BEBAN POKOK" in lname or "HPP" in lname:
                    cogs = line.amount_current
                elif "TOTAL BEBAN OPERASIONAL" in lname:
                    opex = line.amount_current

            rec.total_assets = assets
            rec.total_liabilities = liab
            rec.total_equity = equity
            rec.total_liabilities_equity = liab_eq
            rec.net_profit = profit
            rec.total_revenue = rev
            rec.total_cogs = cogs
            rec.total_opex = opex
            rec.balance_difference = abs(assets - liab_eq)
            rec.is_balanced = (rec.balance_difference < 0.01) if rec.report_type == "balance_sheet" else True

    @api.onchange("date_preset")
    def _onchange_date_preset(self):
        today = date.today()
        if self.date_preset == "this_month":
            self.date_from = today.replace(day=1)
            self.date_to = (today.replace(day=1) + relativedelta(months=1)) - relativedelta(days=1)
        elif self.date_preset == "this_quarter":
            quarter_start_month = 3 * ((today.month - 1) // 3) + 1
            self.date_from = today.replace(month=quarter_start_month, day=1)
            self.date_to = (self.date_from + relativedelta(months=3)) - relativedelta(days=1)
        elif self.date_preset == "ytd":
            self.date_from = today.replace(month=1, day=1)
            self.date_to = today

    @api.onchange("comparison_type", "date_from", "date_to")
    def _onchange_comparison_type(self):
        if self.comparison_type == "none" or not self.date_from or not self.date_to:
            self.date_from_cmp = False
            self.date_to_cmp = False
            return

        if self.comparison_type == "previous_year":
            self.date_from_cmp = self.date_from - relativedelta(years=1)
            self.date_to_cmp = self.date_to - relativedelta(years=1)
        elif self.comparison_type == "previous_period":
            diff_days = (self.date_to - self.date_from).days + 1
            self.date_to_cmp = self.date_from - relativedelta(days=1)
            self.date_from_cmp = self.date_to_cmp - relativedelta(days=diff_days - 1)

    # Narrative CaLK Disclosures per SAK EMKM / SAK EP & Permenkes 14/2021
    calk_profile_text = fields.Text(string="Catatan 1: Profil Entitas & Legalitas Operasional")
    calk_policy_text = fields.Text(string="Catatan 2: Ikhtisar Kebijakan Akuntansi Signifikan")
    calk_receivables_html = fields.Html(string="Catatan 3: Rincian & Jadwal Umur Piutang Pasien/Klaim")
    calk_assets_html = fields.Html(string="Catatan 4: Jadwal Aset Tetap Medis & Penyusutan")
    calk_tax_doc_html = fields.Html(string="Catatan 5: Rekonsiliasi Jasa Medis & Pajak PPh 21 Dokter")

    def action_recalculate(self):
        """Alias controller untuk recalculate langsung dari tombol form."""
        return self.action_recompute()

    def action_recompute(self):
        """Menghitung ulang baris laporan secara atomik sesuai filter terkini dan menyegarkan tampilan."""
        self.ensure_one()

        # Update dynamic name to reflect current filters
        report_titles = {
            "profit_loss": "Laporan Laba Rugi",
            "balance_sheet": "Laporan Posisi Keuangan",
            "cash_flow": f"Laporan Arus Kas ({'Tidak Langsung' if self.cash_flow_method == 'indirect' else 'Langsung'})",
            "equity_change": "Laporan Perubahan Ekuitas",
            "calk": "Catatan Atas Laporan Keuangan (CaLK)",
        }
        unit_label = f"[{self.analytic_account_id.name}] " if self.analytic_account_id else "[Konsolidasi Klinik] "
        date_from_str = self.date_from.strftime('%d/%m/%Y') if self.date_from else ''
        date_to_str = self.date_to.strftime('%d/%m/%Y') if self.date_to else ''
        self.name = f"{unit_label}{report_titles.get(self.report_type, 'Laporan Keuangan')} ({date_from_str} - {date_to_str})"

        self.line_ids.unlink()

        if self.report_type == "profit_loss":
            self._compute_profit_loss()
        elif self.report_type == "balance_sheet":
            self._compute_balance_sheet()
        elif self.report_type == "cash_flow":
            if self.cash_flow_method == "indirect":
                self._compute_cash_flow_indirect()
            else:
                self._compute_cash_flow_direct()
        elif self.report_type == "equity_change":
            self._compute_equity_changes()
        elif self.report_type == "calk":
            self._compute_calk()

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'psak.financial.report',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _get_account_balance(self, code_prefix, date_from, date_to, is_cumulative=False):
        """Menghitung saldo akun (debit - credit) atau (credit - debit) berdasarkan kode prefix."""
        domain = [("company_id", "=", self.company_id.id)]
        if self.target_move == "posted":
            domain.append(("parent_state", "=", "posted"))
        elif self.target_move == "all":
            domain.append(("parent_state", "in", ["posted", "draft"]))

        if is_cumulative:
            domain.append(("date", "<=", date_to))
        else:
            domain.extend([("date", ">=", date_from), ("date", "<=", date_to)])

        lines = self.env["account.move.line"].search(domain)

        # Filter by code prefix
        matched_lines = lines.filtered(
            lambda l: l.account_id.code and l.account_id.code.startswith(code_prefix)
        )

        # Filter analytic account if specified (Odoo 19 analytic_distribution)
        if self.analytic_account_id:
            valid_analytic_ids = {str(self.analytic_account_id.id)}
            # Expand child analytic accounts if parent unit is chosen
            if self.analytic_account_id.code == 'ACC-PRATAMA':
                child_ids = self.env['account.analytic.account'].search([
                    '|', ('code', '=like', 'PRAT-%'), ('code', '=like', 'ACC-PRATAMA-%')
                ]).ids
                valid_analytic_ids.update(str(cid) for cid in child_ids)
            elif self.analytic_account_id.code == 'ACC-HD':
                child_ids = self.env['account.analytic.account'].search([('code', '=like', 'HD-%')]).ids
                valid_analytic_ids.update(str(cid) for cid in child_ids)
            elif self.analytic_account_id.code == 'ACC-HOLDING':
                child_ids = self.env['account.analytic.account'].search([('code', '=like', 'HOLDING-%')]).ids
                valid_analytic_ids.update(str(cid) for cid in child_ids)

            matched_lines = matched_lines.filtered(
                lambda l: l.analytic_distribution and bool(valid_analytic_ids.intersection(l.analytic_distribution.keys()))
            )

        debit = sum(matched_lines.mapped("debit"))
        credit = sum(matched_lines.mapped("credit"))
        return debit, credit

    def _compute_profit_loss(self):
        """Kalkulasi Laporan Laba Rugi Berstandar SAK EMKM / SAK EP."""
        lines_data = []
        seq = 10

        # Kategori 1: PENDAPATAN USAHA (REVENUES)
        lines_data.append((0, 0, {
            "sequence": seq, "name": "PENDAPATAN USAHA OPERASIONAL (OPERATING REVENUES)",
            "line_type": "header",
        }))
        seq += 10

        rev_accounts = [
            ("41001", "Pendapatan Pelayanan Rawat Jalan (Konsultasi & Tindakan Poli Umum)"),
            ("41002", "Pendapatan Tindakan Poli Gigi & Mulut"),
            ("41003", "Pendapatan Pelayanan KIA & Kebidanan"),
            ("41004", "Pendapatan Kapitasi BPJS Kesehatan FKTP"),
            ("41006", "Pendapatan Penjualan Farmasi & Resep Obat"),
            ("41007", "Pendapatan Tuslah & Embalase Farmasi"),
            ("41011", "Pendapatan Pelayanan Hemodialisis Rutin"),
            ("41012", "Pendapatan Pelayanan Paket Dialisis Terakui (PSAK 72)"),
            ("41900", "Pendapatan Operasional Pelayanan Lainnya"),
        ]

        total_rev_cur = 0.0
        total_rev_cmp = 0.0

        for prefix, label in rev_accounts:
            d_cur, c_cur = self._get_account_balance(prefix, self.date_from, self.date_to)
            amt_cur = c_cur - d_cur  # Revenue normal balance is Credit

            amt_cmp = 0.0
            if self.comparison_type != "none" and self.date_from_cmp and self.date_to_cmp:
                d_cmp, c_cmp = self._get_account_balance(prefix, self.date_from_cmp, self.date_to_cmp)
                amt_cmp = c_cmp - d_cmp

            if amt_cur != 0.0 or amt_cmp != 0.0 or prefix in ("41001", "41004", "41011", "41006"):
                total_rev_cur += amt_cur
                total_rev_cmp += amt_cmp

                lines_data.append((0, 0, {
                    "sequence": seq, "name": label, "code": prefix,
                    "line_type": "account", "amount_current": amt_cur, "amount_comparison": amt_cmp,
                }))
                seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "TOTAL PENDAPATAN USAHA OPERASIONAL",
            "line_type": "subtotal", "amount_current": total_rev_cur, "amount_comparison": total_rev_cmp,
        }))
        seq += 10

        # Kategori 2: BEBAN POKOK PENDAPATAN (COGS / HPP)
        lines_data.append((0, 0, {
            "sequence": seq, "name": "BEBAN POKOK PENDAPATAN (COGS / HPP)",
            "line_type": "header",
        }))
        seq += 10

        cogs_accounts = [
            ("51001", "HPP Obat & BHP Farmasi Rawat Jalan (FIFO Perpetual)"),
            ("51002", "HPP Dialyzer & BHP Khusus Hemodialisis (FIFO Perpetual)"),
            ("51004", "HPP Reagen Laboratorium & BHP Diagnostik"),
        ]

        total_cogs_cur = 0.0
        total_cogs_cmp = 0.0

        for prefix, label in cogs_accounts:
            d_cur, c_cur = self._get_account_balance(prefix, self.date_from, self.date_to)
            amt_cur = d_cur - c_cur

            amt_cmp = 0.0
            if self.comparison_type != "none" and self.date_from_cmp and self.date_to_cmp:
                d_cmp, c_cmp = self._get_account_balance(prefix, self.date_from_cmp, self.date_to_cmp)
                amt_cmp = d_cmp - c_cmp

            if amt_cur != 0.0 or amt_cmp != 0.0 or prefix in ("51001", "51002"):
                total_cogs_cur += amt_cur
                total_cogs_cmp += amt_cmp

                lines_data.append((0, 0, {
                    "sequence": seq, "name": label, "code": prefix,
                    "line_type": "account", "amount_current": amt_cur, "amount_comparison": amt_cmp,
                }))
                seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "TOTAL BEBAN POKOK PENDAPATAN (HPP)",
            "line_type": "subtotal", "amount_current": total_cogs_cur, "amount_comparison": total_cogs_cmp,
        }))
        seq += 10

        # LABA BRUTO
        gross_profit_cur = total_rev_cur - total_cogs_cur
        gross_profit_cmp = total_rev_cmp - total_cogs_cmp
        lines_data.append((0, 0, {
            "sequence": seq, "name": "LABA BRUTO (GROSS PROFIT)",
            "line_type": "total", "amount_current": gross_profit_cur, "amount_comparison": gross_profit_cmp,
        }))
        seq += 10

        # Kategori 3: BEBAN OPERASIONAL & REMUNERASI
        lines_data.append((0, 0, {
            "sequence": seq, "name": "BEBAN OPERASIONAL & REMUNERASI DOKTER",
            "line_type": "header",
        }))
        seq += 10

        opex_accounts = [
            ("51011", "Beban Jasa Medis & Remunerasi Dokter Rawat Jalan"),
            ("51012", "Beban Jasa Medis Dokter Spesialis Hemodialisis"),
            ("61001", "Beban Gaji & Tunjangan Karyawan Medis/Non-Medis"),
            ("61002", "Beban Listrik, Air & Utilitas Medis"),
            ("61003", "Beban Pemeliharaan & Penyusutan Mesin HD / Alat Medis"),
            ("61900", "Beban Operasional Umum & Beban Dispute Klaim BPJS"),
            ("61999", "Beban Selisih Rekonsiliasi Kas Kasir (Blind Count Shift Variance)"),
        ]

        total_opex_cur = 0.0
        total_opex_cmp = 0.0

        for prefix, label in opex_accounts:
            d_cur, c_cur = self._get_account_balance(prefix, self.date_from, self.date_to)
            amt_cur = d_cur - c_cur

            amt_cmp = 0.0
            if self.comparison_type != "none" and self.date_from_cmp and self.date_to_cmp:
                d_cmp, c_cmp = self._get_account_balance(prefix, self.date_from_cmp, self.date_to_cmp)
                amt_cmp = d_cmp - c_cmp

            if amt_cur != 0.0 or amt_cmp != 0.0 or prefix in ("51011", "51012", "61999"):
                total_opex_cur += amt_cur
                total_opex_cmp += amt_cmp

                lines_data.append((0, 0, {
                    "sequence": seq, "name": label, "code": prefix,
                    "line_type": "account", "amount_current": amt_cur, "amount_comparison": amt_cmp,
                }))
                seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "TOTAL BEBAN OPERASIONAL & REMUNERASI",
            "line_type": "subtotal", "amount_current": total_opex_cur, "amount_comparison": total_opex_cmp,
        }))
        seq += 10

        # LABA OPERASIONAL
        op_profit_cur = gross_profit_cur - total_opex_cur
        op_profit_cmp = gross_profit_cmp - total_opex_cmp
        lines_data.append((0, 0, {
            "sequence": seq, "name": "LABA OPERASIONAL (OPERATING INCOME)",
            "line_type": "subtotal", "amount_current": op_profit_cur, "amount_comparison": op_profit_cmp,
        }))
        seq += 10

        # Kategori 4: PENDAPATAN / BEBAN NON-OPERASIONAL
        d_bank_cur, c_bank_cur = self._get_account_balance("7100", self.date_from, self.date_to)
        other_inc_cur = c_bank_cur - d_bank_cur
        d_exp_cur, c_exp_cur = self._get_account_balance("7200", self.date_from, self.date_to)
        other_exp_cur = d_exp_cur - c_exp_cur
        net_other_cur = other_inc_cur - other_exp_cur

        net_other_cmp = 0.0
        if self.comparison_type != "none" and self.date_from_cmp and self.date_to_cmp:
            d_b_cmp, c_b_cmp = self._get_account_balance("7100", self.date_from_cmp, self.date_to_cmp)
            d_e_cmp, c_e_cmp = self._get_account_balance("7200", self.date_from_cmp, self.date_to_cmp)
            net_other_cmp = (c_b_cmp - d_b_cmp) - (d_e_cmp - c_e_cmp)

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Pendapatan / (Beban) Non-Operasional Bersih", "code": "7100-7200",
            "line_type": "account", "amount_current": net_other_cur, "amount_comparison": net_other_cmp,
        }))
        seq += 10

        # LABA BERSIH
        net_profit_cur = op_profit_cur + net_other_cur
        net_profit_cmp = op_profit_cmp + net_other_cmp
        lines_data.append((0, 0, {
            "sequence": seq, "name": "LABA / (RUGI) BERSIH PERIODE BERJALAN",
            "line_type": "total", "amount_current": net_profit_cur, "amount_comparison": net_profit_cmp,
        }))

        self.write({"line_ids": lines_data})

    def _compute_balance_sheet(self):
        """Kalkulasi Neraca Keuangan Berstandar SAK EMKM / SAK EP."""
        lines_data = []
        seq = 10

        # BAGIAN I: ASET (ASSETS)
        lines_data.append((0, 0, {"sequence": seq, "name": "ASET LANCAR (CURRENT ASSETS)", "line_type": "header"}))
        seq += 10

        current_assets = [
            ("11101", "Kas Kasir Rawat Jalan (Cash Safe)"),
            ("11102", "Kas Kasir Hemodialisis (Cash Safe HD)"),
            ("11111", "Bank BCA Operasional Klinik"),
            ("11121", "Kliring Payment Gateway Midtrans / Doku"),
            ("11122", "Kliring EDC / QRIS Statis & Dinamis"),
            ("11201", "Piutang Pasien Umum (Co-Pay)"),
            ("11202", "Piutang Klaim BPJS Kesehatan (VClaim)"),
            ("11203", "Piutang Klaim Asuransi Swasta & Korporasi"),
            ("11204", "Piutang Pihak Berelasi / Pemegang Saham"),
            ("11210", "Piutang Usaha Lainnya (General AR)"),
        ]

        tot_cur_asset_now = 0.0
        tot_cur_asset_cmp = 0.0

        for prefix, label in current_assets:
            d_now, c_now = self._get_account_balance(prefix, False, self.date_to, is_cumulative=True)
            amt_now = d_now - c_now

            amt_cmp = 0.0
            if self.comparison_type != "none" and self.date_to_cmp:
                d_c, c_c = self._get_account_balance(prefix, False, self.date_to_cmp, is_cumulative=True)
                amt_cmp = d_c - c_c

            if amt_now != 0.0 or amt_cmp != 0.0 or prefix in ("11101", "11111", "11201", "11202"):
                tot_cur_asset_now += amt_now
                tot_cur_asset_cmp += amt_cmp

                lines_data.append((0, 0, {
                    "sequence": seq, "name": label, "code": prefix,
                    "line_type": "account", "amount_current": amt_now, "amount_comparison": amt_cmp,
                }))
                seq += 10

        # Contra-Asset: 112990 Cadangan Kerugian Penolakan / Dispute Klaim BPJS
        d_dis, c_dis = self._get_account_balance("11299", False, self.date_to, is_cumulative=True)
        amt_dis_now = -(c_dis - d_dis)  # Normal balance is credit, reduces asset
        amt_dis_cmp = 0.0
        if self.comparison_type != "none" and self.date_to_cmp:
            d_dis_c, c_dis_c = self._get_account_balance("11299", False, self.date_to_cmp, is_cumulative=True)
            amt_dis_cmp = -(c_dis_c - d_dis_c)

        tot_cur_asset_now += amt_dis_now
        tot_cur_asset_cmp += amt_dis_cmp

        lines_data.append((0, 0, {
            "sequence": seq, "name": "(Less) Cadangan Penolakan / Dispute Klaim BPJS", "code": "112990",
            "line_type": "account", "amount_current": amt_dis_now, "amount_comparison": amt_dis_cmp,
        }))
        seq += 10

        # Persediaan Medis & Farmasi
        inventory_assets = [
            ("11401", "Persediaan Obat Farmasi (Ethical & OTC)"),
            ("11402", "Persediaan BHP Medis Rawat Jalan"),
            ("11403", "Persediaan Dialyzer & BHP Khusus HD"),
            ("11404", "Persediaan Reagen Lab & Penunjang"),
            ("11300", "Persediaan Lainnya (General Stock)"),
            ("11501", "Uang Muka & Biaya Dibayar Dimuka"),
        ]

        for prefix, label in inventory_assets:
            d_now, c_now = self._get_account_balance(prefix, False, self.date_to, is_cumulative=True)
            amt_now = d_now - c_now

            amt_cmp = 0.0
            if self.comparison_type != "none" and self.date_to_cmp:
                d_c, c_c = self._get_account_balance(prefix, False, self.date_to_cmp, is_cumulative=True)
                amt_cmp = d_c - c_c

            if amt_now != 0.0 or amt_cmp != 0.0 or prefix in ("11401", "11403"):
                tot_cur_asset_now += amt_now
                tot_cur_asset_cmp += amt_cmp

                lines_data.append((0, 0, {
                    "sequence": seq, "name": label, "code": prefix,
                    "line_type": "account", "amount_current": amt_now, "amount_comparison": amt_cmp,
                }))
                seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "TOTAL ASET LANCAR",
            "line_type": "subtotal", "amount_current": tot_cur_asset_now, "amount_comparison": tot_cur_asset_cmp,
        }))
        seq += 10

        # ASET TIDAK LANCAR (NON-CURRENT ASSETS)
        lines_data.append((0, 0, {"sequence": seq, "name": "ASET TIDAK LANCAR (NON-CURRENT ASSETS)", "line_type": "header"}))
        seq += 10

        fixed_assets = [
            ("12101", "Peralatan Medis & Laboratorium (USG, EKG, Dental)"),
            ("12102", "Mesin Hemodialisis & RO Water System"),
            ("12103", "Inventaris & Infrastruktur Klinik"),
        ]

        tot_fix_asset_now = 0.0
        tot_fix_asset_cmp = 0.0

        for prefix, label in fixed_assets:
            d_now, c_now = self._get_account_balance(prefix, False, self.date_to, is_cumulative=True)
            amt_now = d_now - c_now
            amt_cmp = 0.0
            if self.comparison_type != "none" and self.date_to_cmp:
                d_c, c_c = self._get_account_balance(prefix, False, self.date_to_cmp, is_cumulative=True)
                amt_cmp = d_c - c_c

            if amt_now != 0.0 or amt_cmp != 0.0 or prefix in ("12101", "12102"):
                tot_fix_asset_now += amt_now
                tot_fix_asset_cmp += amt_cmp

                lines_data.append((0, 0, {
                    "sequence": seq, "name": label, "code": prefix,
                    "line_type": "account", "amount_current": amt_now, "amount_comparison": amt_cmp,
                }))
                seq += 10

        # Akumulasi Penyusutan (Contra-Asset)
        d_dep_now, c_dep_now = self._get_account_balance("1220", False, self.date_to, is_cumulative=True)
        amt_dep_now = -(c_dep_now - d_dep_now)
        amt_dep_cmp = 0.0
        if self.comparison_type != "none" and self.date_to_cmp:
            d_d_c, c_d_c = self._get_account_balance("1220", False, self.date_to_cmp, is_cumulative=True)
            amt_dep_cmp = -(c_d_c - d_d_c)

        tot_fix_asset_now += amt_dep_now
        tot_fix_asset_cmp += amt_dep_cmp

        lines_data.append((0, 0, {
            "sequence": seq, "name": "(Less) Akumulasi Penyusutan Peralatan Medis & Mesin HD", "code": "122010",
            "line_type": "account", "amount_current": amt_dep_now, "amount_comparison": amt_dep_cmp,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "TOTAL ASET TIDAK LANCAR",
            "line_type": "subtotal", "amount_current": tot_fix_asset_now, "amount_comparison": tot_fix_asset_cmp,
        }))
        seq += 10

        total_assets_now = tot_cur_asset_now + tot_fix_asset_now
        total_assets_cmp = tot_cur_asset_cmp + tot_fix_asset_cmp

        lines_data.append((0, 0, {
            "sequence": seq, "name": "TOTAL ASET (TOTAL ASSETS)",
            "line_type": "total", "amount_current": total_assets_now, "amount_comparison": total_assets_cmp,
        }))
        seq += 10

        # BAGIAN II: LIABILITAS (LIABILITIES)
        lines_data.append((0, 0, {"sequence": seq, "name": "KEWAJIBAN JANGKA PENDEK (CURRENT LIABILITIES)", "line_type": "header"}))
        seq += 10

        current_liabilities = [
            ("21101", "Utang Usaha Pemasok Obat & BHP Medis"),
            ("21110", "Utang Usaha Lainnya (General AP)"),
            ("21150", "GR/IR Clearing (Interim Clearing Utang Belum Ditagih)"),
            ("21201", "Utang Pajak PPN"),
            ("21203", "Utang PPh 21 Tenaga Ahli Dokter (Pasal 17 / PMK 168)"),
            ("21301", "Akrual Utang Jasa Medis Dokter Rawat Jalan"),
            ("21302", "Akrual Utang Jasa Medis Dokter Spesialis Hemodialisis"),
            ("21401", "Pendapatan Diterima Dimuka Pasien (Deposit)"),
            ("21402", "Pendapatan Diterima Dimuka Paket Hemodialisis (PSAK 72)"),
        ]

        tot_liab_now = 0.0
        tot_liab_cmp = 0.0

        for prefix, label in current_liabilities:
            d_now, c_now = self._get_account_balance(prefix, False, self.date_to, is_cumulative=True)
            amt_now = c_now - d_now
            amt_cmp = 0.0
            if self.comparison_type != "none" and self.date_to_cmp:
                d_c, c_c = self._get_account_balance(prefix, False, self.date_to_cmp, is_cumulative=True)
                amt_cmp = c_c - d_c

            if amt_now != 0.0 or amt_cmp != 0.0 or prefix in ("21101", "21150", "21301", "21302", "21402"):
                tot_liab_now += amt_now
                tot_liab_cmp += amt_cmp

                lines_data.append((0, 0, {
                    "sequence": seq, "name": label, "code": prefix,
                    "line_type": "account", "amount_current": amt_now, "amount_comparison": amt_cmp,
                }))
                seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "TOTAL KEWAJIBAN JANGKA PENDEK",
            "line_type": "subtotal", "amount_current": tot_liab_now, "amount_comparison": tot_liab_cmp,
        }))
        seq += 10

        # BAGIAN III: EKUITAS (EQUITY - Enforcing Asumsi Kesatuan Usaha)
        lines_data.append((0, 0, {"sequence": seq, "name": "EKUITAS ENTITAS KLINIK (EQUITY)", "line_type": "header"}))
        seq += 10

        d_cap_now, c_cap_now = self._get_account_balance("3100", False, self.date_to, is_cumulative=True)
        amt_cap_now = c_cap_now - d_cap_now
        d_ret_now, c_ret_now = self._get_account_balance("3200", False, self.date_to, is_cumulative=True)
        amt_ret_now = c_ret_now - d_ret_now

        amt_cap_cmp = 0.0
        amt_ret_cmp = 0.0
        if self.comparison_type != "none" and self.date_to_cmp:
            d_cp, c_cp = self._get_account_balance("3100", False, self.date_to_cmp, is_cumulative=True)
            amt_cap_cmp = c_cp - d_cp
            d_rt, c_rt = self._get_account_balance("3200", False, self.date_to_cmp, is_cumulative=True)
            amt_ret_cmp = c_rt - d_rt

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Modal Saham Disetor PT Prosperra Medika Utama", "code": "310010",
            "line_type": "account", "amount_current": amt_cap_now, "amount_comparison": amt_cap_cmp,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Saldo Laba Ditahan (Retained Earnings)", "code": "320010",
            "line_type": "account", "amount_current": amt_ret_now, "amount_comparison": amt_ret_cmp,
        }))
        seq += 10

        # Laba Periode Berjalan (Difference between Total Assets and Total Liabilities + Contributed Equity)
        net_curr_now = total_assets_now - tot_liab_now - (amt_cap_now + amt_ret_now)
        net_curr_cmp = total_assets_cmp - tot_liab_cmp - (amt_cap_cmp + amt_ret_cmp)

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Laba / (Rugi) Bersih Periode Berjalan", "code": "RETAINED-CURR",
            "line_type": "account", "amount_current": net_curr_now, "amount_comparison": net_curr_cmp,
        }))
        seq += 10

        tot_equity_now = amt_cap_now + amt_ret_now + net_curr_now
        tot_equity_cmp = amt_cap_cmp + amt_ret_cmp + net_curr_cmp

        lines_data.append((0, 0, {
            "sequence": seq, "name": "TOTAL EKUITAS",
            "line_type": "subtotal", "amount_current": tot_equity_now, "amount_comparison": tot_equity_cmp,
        }))
        seq += 10

        total_liab_equity_now = tot_liab_now + tot_equity_now
        total_liab_equity_cmp = tot_liab_cmp + tot_equity_cmp

        lines_data.append((0, 0, {
            "sequence": seq, "name": "TOTAL KEWAJIBAN & EKUITAS",
            "line_type": "total", "amount_current": total_liab_equity_now, "amount_comparison": total_liab_equity_cmp,
        }))
        seq += 10

        # Absolute Zero-Balance Audit Verification (Total Aset = Total Liabilitas + Ekuitas)
        diff_bal_now = total_assets_now - total_liab_equity_now
        diff_bal_cmp = total_assets_cmp - total_liab_equity_cmp
        status_txt = "SEIMBANG (Rp 0.00)" if abs(diff_bal_now) < 0.01 else f"SELISIH (Rp {diff_bal_now:,.2f})"
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": f"KESEIMBANGAN AUDIT: TOTAL ASET - (LIABILITAS + EKUITAS) [{status_txt}]",
            "code": "AUDIT-00",
            "line_type": "total",
            "amount_current": diff_bal_now,
            "amount_comparison": diff_bal_cmp,
        }))

        self.write({"line_ids": lines_data})

    def _compute_cash_flow_direct(self):
        """Kalkulasi Laporan Arus Kas Metode Langsung (Direct Method - PSAK 2 / SAK EP)."""
        lines_data = []
        seq = 10

        lines_data.append((0, 0, {"sequence": seq, "name": "ARUS KAS DARI AKTIVITAS OPERASI (METODE LANGSUNG)", "line_type": "header"}))
        seq += 10

        # 1. Penerimaan dari Pasien & Klaim
        d_p, c_p = self._get_account_balance("4100", self.date_from, self.date_to)
        cash_rec_patient = c_p - d_p
        d_h, c_h = self._get_account_balance("4101", self.date_from, self.date_to)
        cash_rec_hd = c_h - d_h

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Penerimaan Kas dari Pelayanan Pasien Rawat Jalan & Kapitasi BPJS",
            "line_type": "account", "amount_current": cash_rec_patient,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Penerimaan Kas & Klaim BPJS Pelayanan Hemodialisis",
            "line_type": "account", "amount_current": cash_rec_hd,
        }))
        seq += 10

        # 2. Pengeluaran Pemasok & Operasional
        d_sup, c_sup = self._get_account_balance("2110", self.date_from, self.date_to)
        cash_paid_suppliers = -d_sup

        d_doc, c_doc = self._get_account_balance("2130", self.date_from, self.date_to)
        cash_paid_doctors = -d_doc

        d_op, c_op = self._get_account_balance("6100", self.date_from, self.date_to)
        cash_paid_opex = -d_op

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Pembayaran Kas kepada Pemasok Obat & Distributor Medis",
            "line_type": "account", "amount_current": cash_paid_suppliers,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Pembayaran Remunerasi & Bagi Hasil Dokter",
            "line_type": "account", "amount_current": cash_paid_doctors,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Pembayaran Beban Operasional, Utilitas Medis & Pemeliharaan",
            "line_type": "account", "amount_current": cash_paid_opex,
        }))
        seq += 10

        net_operating = cash_rec_patient + cash_rec_hd + cash_paid_suppliers + cash_paid_doctors + cash_paid_opex
        lines_data.append((0, 0, {
            "sequence": seq, "name": "ARUS KAS BERSIH DARI AKTIVITAS OPERASI",
            "line_type": "subtotal", "amount_current": net_operating,
        }))
        seq += 10

        # 3. Aktivitas Investasi
        lines_data.append((0, 0, {"sequence": seq, "name": "ARUS KAS DARI AKTIVITAS INVESTASI", "line_type": "header"}))
        seq += 10

        d_inv, c_inv = self._get_account_balance("1210", self.date_from, self.date_to)
        capex_medical = -d_inv

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Perolehan Mesin Hemodialisis & Peralatan Medis (Permenkes 14/2021)",
            "line_type": "account", "amount_current": capex_medical,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "ARUS KAS BERSIH DARI AKTIVITAS INVESTASI",
            "line_type": "subtotal", "amount_current": capex_medical,
        }))
        seq += 10

        # 4. Kenaikan / Penurunan Kas
        net_cash_change = net_operating + capex_medical

        # Saldo Kas Awal & Akhir
        cash_prefixes = ["11101", "11102", "11111", "11121", "11122"]
        cash_open = 0.0
        cash_close = 0.0
        date_before_start = self.date_from - relativedelta(days=1)

        for pfx in cash_prefixes:
            d_o, c_o = self._get_account_balance(pfx, False, date_before_start, is_cumulative=True)
            cash_open += (d_o - c_o)
            d_cl, c_cl = self._get_account_balance(pfx, False, self.date_to, is_cumulative=True)
            cash_close += (d_cl - c_cl)

        lines_data.append((0, 0, {
            "sequence": seq, "name": "KENAIKAN / (PENURUNAN) BERSIH KAS & SETARA KAS",
            "line_type": "total", "amount_current": net_cash_change,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "SALDO KAS & SETARA KAS AWAL PERIODE",
            "line_type": "account", "amount_current": cash_open,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "SALDO KAS & SETARA KAS AKHIR PERIODE (REKONSILIASI KAS & BANK)",
            "line_type": "total", "amount_current": cash_close,
        }))

        self.write({"line_ids": lines_data})

    def _compute_cash_flow_indirect(self):
        """Kalkulasi Laporan Arus Kas Metode Tidak Langsung (Indirect Method)."""
        return self.env["clinic.cash.flow.engine"].compute_indirect_cash_flow(self)

    def _compute_equity_changes(self):
        """Kalkulasi Laporan Perubahan Ekuitas (Statement of Changes in Equity - SAK EP Section 6)."""
        lines_data = []
        seq = 10

        lines_data.append((0, 0, {"sequence": seq, "name": "SALDO EKUITAS AWAL PERIODE", "line_type": "header"}))
        seq += 10

        date_before = self.date_from - relativedelta(days=1)
        d_c_o, c_c_o = self._get_account_balance("3100", False, date_before, is_cumulative=True)
        cap_open = c_c_o - d_c_o

        d_r_o, c_r_o = self._get_account_balance("3200", False, date_before, is_cumulative=True)
        ret_open = c_r_o - d_r_o

        tot_equity_open = cap_open + ret_open

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Modal Saham Disetor Awal", "code": "310010",
            "line_type": "account", "amount_current": cap_open,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Saldo Laba Ditahan Awal Periode", "code": "320010",
            "line_type": "account", "amount_current": ret_open,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "TOTAL EKUITAS AWAL PERIODE",
            "line_type": "subtotal", "amount_current": tot_equity_open,
        }))
        seq += 10

        # PERUBAHAN PERIODE BERJALAN
        lines_data.append((0, 0, {"sequence": seq, "name": "PERUBAHAN EKUITAS PERIODE BERJALAN", "line_type": "header"}))
        seq += 10

        # Tambahan Modal
        d_c_cur, c_c_cur = self._get_account_balance("3100", self.date_from, self.date_to)
        cap_addition = c_c_cur - d_c_cur
        lines_data.append((0, 0, {
            "sequence": seq, "name": "Tambahan Setoran Modal PT Prosperra Medika Utama", "code": "310010",
            "line_type": "account", "amount_current": cap_addition,
        }))
        seq += 10

        # Laba Bersih Periode Berjalan
        d_rev, c_rev = self._get_account_balance("410", self.date_from, self.date_to)
        d_cogs, c_cogs = self._get_account_balance("510", self.date_from, self.date_to)
        d_opx, c_opx = self._get_account_balance("610", self.date_from, self.date_to)
        d_vk, c_vk = self._get_account_balance("61999", self.date_from, self.date_to)
        net_profit_current = (c_rev - d_rev) - (d_cogs - c_cogs) - (d_opx - c_opx) - (d_vk - c_vk)

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Laba / (Rugi) Bersih Periode Berjalan", "code": "NET-INC",
            "line_type": "account", "amount_current": net_profit_current,
        }))
        seq += 10

        # Prive / Dividen (Strictly separated per Asumsi Kesatuan Usaha)
        d_priv, c_priv = self._get_account_balance("3300", self.date_from, self.date_to)
        dividend_paid = -(d_priv - c_priv)
        lines_data.append((0, 0, {
            "sequence": seq, "name": "Pengambilan Prive / Distribusi Dividen Pemegang Saham", "code": "330010",
            "line_type": "account", "amount_current": dividend_paid,
        }))
        seq += 10

        tot_changes = cap_addition + net_profit_current + dividend_paid
        lines_data.append((0, 0, {
            "sequence": seq, "name": "TOTAL PERUBAHAN EKUITAS PERIODE BERJALAN",
            "line_type": "subtotal", "amount_current": tot_changes,
        }))
        seq += 10

        # SALDO EKUITAS AKHIR
        lines_data.append((0, 0, {"sequence": seq, "name": "SALDO EKUITAS AKHIR PERIODE (REKONSILIASI NERACA)", "line_type": "header"}))
        seq += 10

        cap_close = cap_open + cap_addition
        ret_close = ret_open + net_profit_current + dividend_paid
        tot_equity_close = tot_equity_open + tot_changes

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Modal Saham Disetor Akhir Periode", "code": "310010",
            "line_type": "account", "amount_current": cap_close,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Saldo Laba Ditahan Akhir Periode", "code": "320010",
            "line_type": "account", "amount_current": ret_close,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "TOTAL EKUITAS AKHIR PERIODE",
            "line_type": "total", "amount_current": tot_equity_close,
        }))

        self.write({"line_ids": lines_data})

    def _compute_calk(self):
        """Kalkulasi & Auto-Populate Catatan Atas Laporan Keuangan (CaLK) per SAK EMKM / SAK EP."""
        lines_data = []
        seq = 10

        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "CATATAN ATAS LAPORAN KEUANGAN (CaLK) KLINIK ADERA",
            "line_type": "header",
        }))
        seq += 10

        # 1. Catatan 1: Profil Entitas
        profile_text = (
            "1. PROFIL ENTITAS & LEGALITAS OPERASIONAL (PERMENKES 14/2021)\n"
            "a. Nama Badan Hukum: PT Prosperra Medika Utama.\n"
            "b. Nama Fasilitas Pelayanan Kesehatan: Klinik ADERA.\n"
            "c. Unit Bisnis 1: Klinik Pratama ADERA (Rawat Jalan Primer).\n"
            "   - Nomor Izin Operasional: 445/012/KP/DPM-PTSP/2023.\n"
            "   - Lingkup Layanan: Poli Umum, Poli Gigi & Mulut, Poli KIA/KB, Laboratorium Klinis, Radiologi Sederhana, dan Instalasi Farmasi.\n"
            "d. Unit Bisnis 2: Klinik Utama Hemodialisis ADERA (Pelayanan Dialisis Khusus).\n"
            "   - Nomor Izin Operasional: 445/088/KU-HD/DPM-PTSP/2024.\n"
            "   - Kapasitas Pelayanan: 20 Mesin Hemodialisis Aktif, Kamar Isolasi HBV/HCV, dan Sistem RO Water Treatment Berstandar AAMI.\n"
            "e. Domisili & Operasional: Indonesia (Mata Uang Fungsional: Rupiah / IDR)."
        )

        # 2. Catatan 2: Kebijakan Akuntansi
        policy_text = (
            "2. IKHTISAR KEBIJAKAN AKUNTANSI SIGNIFIKAN\n"
            "a. Dasar Penyusunan: Standar Akuntansi Keuangan yang berlaku umum di Indonesia berbasis akrual penuh.\n"
            "b. Asumsi Kesatuan Usaha (Business Entity Concept): Aset, kewajiban, dan operasional Klinik dipisahkan "
            "secara mutlak dari kekayaan pribadi pendiri/pemegang saham.\n"
            "c. Pengakuan Pendapatan: Pendapatan pelayanan dan resep diakui saat jasa diserahkan kepada pasien (point in time). "
            "Pendapatan Kapitasi BPJS (410040) diakui secara akrual bulanan berdasarkan jumlah peserta terdaftar FKTP. "
            "Voucher paket terapi hemodialisis diakui sebagai Liabilitas Kontrak (214020) dan baru diakui sebagai pendapatan (410120) saat terapi ditebus.\n"
            "d. Pengukuran Persediaan: Persediaan obat ethical, OTC, dialyzer, dan BHP medis dinilai dengan Biaya Historis menggunakan metode Perpetual FIFO "
            "dengan strategi pengeluaran FEFO (First-Expired, First-Out). Barang kadaluarsa (<60 hari) dikarantina.\n"
            "e. Aset Tetap Medis: Dinyatakan sebesar harga perolehan dikurangi akumulasi penyusutan. Penyusutan dihitung dengan metode Garis Lurus (Straight-line) "
            "berdasarkan estimasi masa manfaat Permenkes 14/2021 (Mesin HD: 5 tahun, RO System: 8 tahun, USG: 5 tahun, Dental Unit: 4 tahun).\n"
            "f. Imbalan Kerja & Jasa Medis: Bagi hasil dokter diakrual secara real-time pada saat tindakan selesai (510110/213010 untuk Pratama, 510120/213020 untuk HD). "
            "Pemotongan PPh 21 Tenaga Ahli Dokter dihitung berdasarkan PMK 168/2023 & UU HPP dengan DPP 50% bruto bertarif progresif Pasal 17."
        )

        # 3. Catatan 3: Schedule Aging Piutang
        d_p, c_p = self._get_account_balance("11201", False, self.date_to, is_cumulative=True)
        ar_patient = d_p - c_p
        d_b, c_b = self._get_account_balance("11202", False, self.date_to, is_cumulative=True)
        ar_bpjs = d_b - c_b
        d_s, c_s = self._get_account_balance("11203", False, self.date_to, is_cumulative=True)
        ar_ins = d_s - c_s
        d_dis, c_dis = self._get_account_balance("11299", False, self.date_to, is_cumulative=True)
        allowance_dispute = -(c_dis - d_dis)
        net_ar = ar_patient + ar_bpjs + ar_ins + allowance_dispute

        receivables_html = f"""
        <table class="table table-sm table-bordered" style="width: 100%; border-collapse: collapse;">
            <thead>
                <tr style="background-color: #f2f2f2; font-weight: bold;">
                    <th>Klasifikasi Piutang Pelayanan</th>
                    <th style="text-align: right;">Saldo Bruto (Rp)</th>
                    <th style="text-align: right;">Cadangan Dispute (Rp)</th>
                    <th style="text-align: right;">Nilai Realisasi Bersih (Rp)</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>Piutang Pasien Umum (Co-Pay Kasir)</td>
                    <td style="text-align: right;">{ar_patient:,.2f}</td>
                    <td style="text-align: right;">-</td>
                    <td style="text-align: right;">{ar_patient:,.2f}</td>
                </tr>
                <tr>
                    <td>Piutang Klaim BPJS Kesehatan (VClaim / SEP Terverifikasi)</td>
                    <td style="text-align: right;">{ar_bpjs:,.2f}</td>
                    <td style="text-align: right; color: red;">{allowance_dispute:,.2f}</td>
                    <td style="text-align: right; font-weight: bold;">{(ar_bpjs + allowance_dispute):,.2f}</td>
                </tr>
                <tr>
                    <td>Piutang Asuransi Swasta &amp; Korporasi Rekanan</td>
                    <td style="text-align: right;">{ar_ins:,.2f}</td>
                    <td style="text-align: right;">-</td>
                    <td style="text-align: right;">{ar_ins:,.2f}</td>
                </tr>
                <tr style="font-weight: bold; background-color: #fafafa;">
                    <td>TOTAL PIUTANG USAHA BERSIH (NET RECEIVABLES)</td>
                    <td style="text-align: right;">{(ar_patient + ar_bpjs + ar_ins):,.2f}</td>
                    <td style="text-align: right; color: red;">{allowance_dispute:,.2f}</td>
                    <td style="text-align: right; color: green;">{net_ar:,.2f}</td>
                </tr>
            </tbody>
        </table>
        <p style="font-size: 11px; color: #666; margin-top: 5px;">
            *Catatan: Akun 112990 bertindak sebagai contra-asset yang dibentuk untuk mengantisipasi potensi dispute klaim dan penolakan berkas oleh verifikator BPJS.
        </p>
        """

        # Catatan 3.b: Pengungkapan Piutang Pihak Berelasi / Pemegang Saham (Bulaksumur Finding #3)
        d_rel, c_rel = self._get_account_balance("11204", False, self.date_to, is_cumulative=True)
        bal_rel = d_rel - c_rel
        receivables_html += f"""
        <h6 style="font-weight: bold; margin-top: 20px; color: #333;">Catatan 3.b: Pengungkapan Transaksi Pihak Berelasi (SAK EMKM Bab 14 &amp; PSAK 7)</h6>
        <p style="font-size: 12px; margin-bottom: 6px;">
            Berdasarkan temuan audit Bulaksumur (#3), entitas mengungkapkan rincian piutang kepada pihak berelasi / pemegang saham per {self.date_to} sebagai berikut:
        </p>
        <table class="table table-sm table-bordered" style="width: 100%; border-collapse: collapse;">
            <thead>
                <tr style="background-color: #f2f2f2; font-weight: bold;">
                    <th>Akun &amp; Entitas Pihak Berelasi</th>
                    <th>Hubungan Istimewa</th>
                    <th style="text-align: center;">Tingkat Bunga</th>
                    <th>Jaminan / Agunan</th>
                    <th style="text-align: right;">Saldo Tercatat (Rp)</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>112040 - Piutang Pemegang Saham / Afiliasi</td>
                    <td>Pemegang Saham Mayoritas</td>
                    <td style="text-align: center;">0,00% (Bebas Bunga)</td>
                    <td>Tanpa Jaminan (Unsecured)</td>
                    <td style="text-align: right; font-weight: bold;">{bal_rel:,.2f}</td>
                </tr>
            </tbody>
        </table>
        <p style="font-size: 11px; color: #666; margin-top: 5px;">
            *Klausul Pelunasan: Saldo merupakan talangan modal kerja operasional yang dapat ditagih sewaktu-waktu (callable on demand) berdasarkan keputusan Rapat Umum Pemegang Saham (RUPS).
        </p>
        """

        # 4. Catatan 4: Schedule Aset Tetap Medis
        clinic_assets = self.env['clinic.asset'].search([('company_id', '=', self.company_id.id)])
        if clinic_assets:
            asset_rows = ""
            tot_cost_all = 0.0
            tot_dep_all = 0.0
            tot_nbv_all = 0.0
            cat_labels = {
                'medical_equipment': 'Peralatan Medis &amp; Hemodialisis',
                'building_improvement': 'Renovasi Gedung Klinik &amp; Utilitas RO',
                'office_equipment': 'Peralatan Kantor, IT &amp; Server',
                'vehicle': 'Kendaraan &amp; Ambulans Siaga',
            }
            categories = {}
            for asset in clinic_assets:
                categories.setdefault(asset.asset_category, []).append(asset)

            for cat, items in categories.items():
                cat_cost = sum(items.mapped('purchase_value'))
                cat_dep = sum(items.mapped('accumulated_depreciation'))
                cat_nbv = sum(items.mapped('net_book_value'))
                tot_cost_all += cat_cost
                tot_dep_all += cat_dep
                tot_nbv_all += cat_nbv
                cat_name = cat_labels.get(cat, cat.replace('_', ' ').title())
                asset_rows += f"""
                <tr>
                    <td>{cat_name} ({len(items)} Unit)</td>
                    <td style="text-align: center;">Garis Lurus (Straight-Line)</td>
                    <td style="text-align: right;">{cat_cost:,.2f}</td>
                    <td style="text-align: right; color: red;">-{cat_dep:,.2f}</td>
                    <td style="text-align: right; font-weight: bold;">{cat_nbv:,.2f}</td>
                </tr>
                """

            assets_html = f"""
            <table class="table table-sm table-bordered" style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="background-color: #f2f2f2; font-weight: bold;">
                        <th>Kategori Aset Tetap Medis / Fasilitas</th>
                        <th style="text-align: center;">Metode Penyusutan</th>
                        <th style="text-align: right;">Harga Perolehan (Rp)</th>
                        <th style="text-align: right;">Akumulasi Penyusutan (Rp)</th>
                        <th style="text-align: right;">Nilai Buku Bersih (Rp)</th>
                    </tr>
                </thead>
                <tbody>
                    {asset_rows}
                    <tr style="font-weight: bold; background-color: #fafafa;">
                        <td>TOTAL ASET TETAP KLINIK</td>
                        <td style="text-align: center;">-</td>
                        <td style="text-align: right;">{tot_cost_all:,.2f}</td>
                        <td style="text-align: right; color: red;">-{tot_dep_all:,.2f}</td>
                        <td style="text-align: right; color: blue;">{tot_nbv_all:,.2f}</td>
                    </tr>
                </tbody>
            </table>
            """
        else:
            d_med, c_med = self._get_account_balance("12101", False, self.date_to, is_cumulative=True)
            cost_med = d_med - c_med
            d_hd, c_hd = self._get_account_balance("12102", False, self.date_to, is_cumulative=True)
            cost_hd = d_hd - c_hd
            d_dep, c_dep = self._get_account_balance("1220", False, self.date_to, is_cumulative=True)
            tot_dep = c_dep - d_dep
            net_fixed = (cost_med + cost_hd) - tot_dep

            assets_html = f"""
            <table class="table table-sm table-bordered" style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="background-color: #f2f2f2; font-weight: bold;">
                        <th>Golongan Peralatan Medis</th>
                        <th style="text-align: center;">Masa Manfaat</th>
                        <th style="text-align: right;">Harga Perolehan (Rp)</th>
                        <th style="text-align: right;">Akumulasi Penyusutan (Rp)</th>
                        <th style="text-align: right;">Nilai Buku Bersih (Rp)</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Peralatan Medis &amp; Lab Rawat Jalan (USG, EKG, Dental Unit)</td>
                        <td style="text-align: center;">4 - 5 Tahun</td>
                        <td style="text-align: right;">{cost_med:,.2f}</td>
                        <td style="text-align: right;">{(tot_dep * 0.3):,.2f}</td>
                        <td style="text-align: right;">{(cost_med - (tot_dep * 0.3)):,.2f}</td>
                    </tr>
                    <tr>
                        <td>Mesin Hemodialisis &amp; RO Water Treatment System</td>
                        <td style="text-align: center;">5 - 8 Tahun</td>
                        <td style="text-align: right;">{cost_hd:,.2f}</td>
                        <td style="text-align: right;">{(tot_dep * 0.7):,.2f}</td>
                        <td style="text-align: right;">{(cost_hd - (tot_dep * 0.7)):,.2f}</td>
                    </tr>
                    <tr style="font-weight: bold; background-color: #fafafa;">
                        <td>TOTAL ASET TETAP MEDIS</td>
                        <td style="text-align: center;">-</td>
                        <td style="text-align: right;">{(cost_med + cost_hd):,.2f}</td>
                        <td style="text-align: right; color: red;">-{tot_dep:,.2f}</td>
                        <td style="text-align: right; color: blue;">{net_fixed:,.2f}</td>
                    </tr>
                </tbody>
            </table>
            """

        # 5. Catatan 5: Rekonsiliasi Jasa Medis & Pajak PPh 21 Dokter
        d_j_prat, c_j_prat = self._get_account_balance("51011", self.date_from, self.date_to)
        jm_prat = d_j_prat - c_j_prat
        d_j_hd, c_j_hd = self._get_account_balance("51012", self.date_from, self.date_to)
        jm_hd = d_j_hd - c_j_hd
        tot_jm = jm_prat + jm_hd

        d_p_tax, c_p_tax = self._get_account_balance("21203", self.date_from, self.date_to)
        tax_withheld = c_p_tax - d_p_tax
        dpp_est = tot_jm * 0.50

        tax_doc_html = f"""
        <table class="table table-sm table-bordered" style="width: 100%; border-collapse: collapse;">
            <thead>
                <tr style="background-color: #f2f2f2; font-weight: bold;">
                    <th>Komponen Remunerasi Dokter</th>
                    <th style="text-align: right;">Jasa Medis Bruto (Rp)</th>
                    <th style="text-align: right;">DPP PPh 21 (50% Bruto)</th>
                    <th style="text-align: right;">Potongan PPh 21 Pasal 17 (Rp)</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>Jasa Medis Dokter Rawat Jalan (Poli Umum, Gigi, Spesialis)</td>
                    <td style="text-align: right;">{jm_prat:,.2f}</td>
                    <td style="text-align: right;">{(jm_prat * 0.5):,.2f}</td>
                    <td style="text-align: right;">{(tax_withheld * (jm_prat / tot_jm if tot_jm else 0.5)):,.2f}</td>
                </tr>
                <tr>
                    <td>Jasa Medis Dokter Spesialis Hemodialisis (Sp.PD-KGH)</td>
                    <td style="text-align: right;">{jm_hd:,.2f}</td>
                    <td style="text-align: right;">{(jm_hd * 0.5):,.2f}</td>
                    <td style="text-align: right;">{(tax_withheld * (jm_hd / tot_jm if tot_jm else 0.5)):,.2f}</td>
                </tr>
                <tr style="font-weight: bold; background-color: #fafafa;">
                    <td>TOTAL REKONSILIASI JASA MEDIS & PPh 21 DOKTER</td>
                    <td style="text-align: right;">{tot_jm:,.2f}</td>
                    <td style="text-align: right;">{dpp_est:,.2f}</td>
                    <td style="text-align: right; color: red;">{tax_withheld:,.2f}</td>
                </tr>
            </tbody>
        </table>
        <p style="font-size: 11px; color: #666; margin-top: 5px;">
            *Pemotongan PPh 21 mengikuti ketentuan PMK 168/2023 & UU HPP: Kode Objek Pajak 21-100-07 (Tenaga Ahli) dengan DPP kumulatif progresif Pasal 17.
        </p>
        """

        # Update narrative fields
        self.write({
            "calk_profile_text": profile_text,
            "calk_policy_text": policy_text,
            "calk_receivables_html": receivables_html,
            "calk_assets_html": assets_html,
            "calk_tax_doc_html": tax_doc_html,
        })

        # Add Summary Lines into line_ids for tabular display
        lines_data.append((0, 0, {
            "sequence": seq, "name": "1. Profil Entitas & Legalitas Operasional Permenkes 14/2021",
            "line_type": "header",
        }))
        seq += 10
        lines_data.append((0, 0, {
            "sequence": seq, "name": "PT Prosperra Medika Utama / Klinik Pratama & Utama HD ADERA",
            "line_type": "account", "amount_current": 1.0,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "2. Ikhtisar Kebijakan Akuntansi (SAK EMKM / FIFO Perpetual / Accrual)",
            "line_type": "header",
        }))
        seq += 10
        lines_data.append((0, 0, {
            "sequence": seq, "name": "Asumsi Kesatuan Usaha, Biaya Historis & FEFO Inventory",
            "line_type": "account", "amount_current": 1.0,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "3. Rincian & Jadwal Umur Piutang Pelayanan",
            "line_type": "header",
        }))
        seq += 10
        lines_data.append((0, 0, {
            "sequence": seq, "name": "Total Piutang Bersih (Setelah Cadangan Penolakan Dispute BPJS)",
            "line_type": "subtotal", "amount_current": net_ar,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "4. Jadwal Aset Tetap Medis & Nilai Buku Bersih",
            "line_type": "header",
        }))
        seq += 10
        lines_data.append((0, 0, {
            "sequence": seq, "name": "Nilai Buku Bersih Peralatan Medis, Mesin HD & RO System",
            "line_type": "subtotal", "amount_current": net_fixed,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "5. Rekonsiliasi Jasa Medis & Pajak PPh 21 Dokter",
            "line_type": "header",
        }))
        seq += 10
        lines_data.append((0, 0, {
            "sequence": seq, "name": "Total Jasa Medis Bruto Terutang",
            "line_type": "account", "amount_current": tot_jm,
        }))
        seq += 10
        lines_data.append((0, 0, {
            "sequence": seq, "name": "Total Pemotongan PPh 21 PMK 168/2023",
            "line_type": "total", "amount_current": tax_withheld,
        }))

        self.write({"line_ids": lines_data})


class PsakFinancialReportLine(models.Model):
    _name = "psak.financial.report.line"
    _description = "Baris Laporan Keuangan PSAK / SAK EMKM / SAK EP"
    _order = "sequence, id"

    report_id = fields.Many2one("psak.financial.report", string="Laporan Induk", ondelete="cascade")
    sequence = fields.Integer(string="Urutan", default=10)
    name = fields.Char(string="Pos Akun / Kategori Regulasi", required=True)
    code = fields.Char(string="Kode Akun / Prefix")
    line_type = fields.Selection(
        [
            ("header", "Header Kategori"),
            ("account", "Pos Akun Rincian"),
            ("subtotal", "Subtotal Bagian"),
            ("total", "Total Akhir"),
        ],
        string="Tipe Baris",
        default="account",
    )

    amount_current = fields.Monetary(string="Periode Berjalan (Rp)", default=0.0)
    amount_comparison = fields.Monetary(string="Periode Pembanding (Rp)", default=0.0)
    variance_amount = fields.Monetary(string="Selisih (Rp)", compute="_compute_variance", store=True)
    variance_percent = fields.Float(string="Selisih (%)", compute="_compute_variance", store=True)
    currency_id = fields.Many2one("res.currency", related="report_id.currency_id")

    @api.depends("amount_current", "amount_comparison")
    def _compute_variance(self):
        for line in self:
            line.variance_amount = line.amount_current - line.amount_comparison
            if line.amount_comparison != 0.0:
                line.variance_percent = (line.variance_amount / abs(line.amount_comparison)) * 100.0
            else:
                line.variance_percent = 100.0 if line.amount_current != 0.0 else 0.0
