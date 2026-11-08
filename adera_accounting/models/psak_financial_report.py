# -*- coding: utf-8 -*-
from odoo import fields, models, api
from dateutil.relativedelta import relativedelta
import json


class PsakFinancialReport(models.Model):
    _name = "psak.financial.report"
    _description = "Laporan Keuangan PSAK Klinik ADERA"
    _order = "date_to desc, id desc"

    name = fields.Char(string="Nama Laporan", required=True)
    report_type = fields.Selection(
        [
            ("profit_loss", "Laporan Laba Rugi (Statement of Profit or Loss)"),
            ("balance_sheet", "Neraca Keuangan (Statement of Financial Position)"),
            ("cash_flow", "Laporan Arus Kas (Statement of Cash Flows)"),
        ],
        string="Tipe Laporan PSAK",
        required=True,
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

    date_from_cmp = fields.Date(string="Tanggal Awal Pembanding")
    date_to_cmp = fields.Date(string="Tanggal Akhir Pembanding")

    analytic_account_id = fields.Many2one(
        "account.analytic.account",
        string="Unit Bisnis Analitik",
        help="Pilih ACC-PRATAMA atau ACC-HD untuk breakdown unit bisnis, atau kosongkan untuk Konsolidasi Seluruh Klinik",
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

    def action_recompute(self):
        """Menghitung ulang baris laporan sesuai filter."""
        self.ensure_one()
        self.line_ids.unlink()

        if self.report_type == "profit_loss":
            self._compute_profit_loss()
        elif self.report_type == "balance_sheet":
            self._compute_balance_sheet()
        elif self.report_type == "cash_flow":
            self._compute_cash_flow()

    def _get_account_balance(self, code_prefix, date_from, date_to, is_cumulative=False):
        """Menghitung saldo akun (debit - credit) atau (credit - debit) berdasarkan kode prefix."""
        domain = [("company_id", "=", self.company_id.id)]
        if self.target_move == "posted":
            domain.append(("parent_state", "=", "posted"))

        if is_cumulative:
            domain.append(("date", "<=", date_to))
        else:
            domain.extend([("date", ">=", date_from), ("date", "<=", date_to)])

        lines = self.env["account.move.line"].search(domain)

        # Filter by code prefix (JSONB code_store in Odoo 19)
        matched_lines = lines.filtered(
            lambda l: l.account_id.code and l.account_id.code.startswith(code_prefix)
        )

        # Filter analytic account if specified
        if self.analytic_account_id:
            acc_id_str = str(self.analytic_account_id.id)
            matched_lines = matched_lines.filtered(
                lambda l: l.analytic_distribution and acc_id_str in l.analytic_distribution
            )

        debit = sum(matched_lines.mapped("debit"))
        credit = sum(matched_lines.mapped("credit"))
        return debit, credit

    def _compute_profit_loss(self):
        """Kalkulasi Laporan Laba Rugi Berstandar PSAK."""
        lines_data = []
        seq = 10

        # Kategori 1: PENDAPATAN USAHA (REVENUE)
        lines_data.append((0, 0, {
            "sequence": seq, "name": "PENDAPATAN USAHA (OPERATING REVENUES)",
            "line_type": "header",
        }))
        seq += 10

        rev_accounts = [
            ("41001", "Pendapatan Pelayanan Rawat Jalan (Konsultasi & Tindakan)"),
            ("41011", "Pendapatan Pelayanan Hemodialisis"),
            ("41006", "Pendapatan Penjualan Farmasi & Resep Obat"),
            ("41900", "Pendapatan Operasional Klinik Lainnya"),
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

            total_rev_cur += amt_cur
            total_rev_cmp += amt_cmp

            lines_data.append((0, 0, {
                "sequence": seq, "name": label, "code": prefix,
                "line_type": "account", "amount_current": amt_cur, "amount_comparison": amt_cmp,
            }))
            seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "TOTAL PENDAPATAN USAHA",
            "line_type": "subtotal", "amount_current": total_rev_cur, "amount_comparison": total_rev_cmp,
        }))
        seq += 10

        # Kategori 2: BEBAN POKOK PENDAPATAN (HPP / COGS)
        lines_data.append((0, 0, {
            "sequence": seq, "name": "BEBAN POKOK PENDAPATAN (COGS / HPP)",
            "line_type": "header",
        }))
        seq += 10

        cogs_accounts = [
            ("51001", "HPP Obat & BHP Farmasi Rawat Jalan"),
            ("51002", "HPP Dialyzer & BHP Khusus Hemodialisis"),
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
            ("61003", "Beban Pemeliharaan Mesin HD & Peralatan Medis"),
            ("61999", "Beban Selisih Rekonsiliasi Kas Kasir (Blind Count)"),
            ("61900", "Beban Operasional & Umum Lainnya"),
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

            total_opex_cur += amt_cur
            total_opex_cmp += amt_cmp

            lines_data.append((0, 0, {
                "sequence": seq, "name": label, "code": prefix,
                "line_type": "account", "amount_current": amt_cur, "amount_comparison": amt_cmp,
            }))
            seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "TOTAL BEBAN OPERASIONAL",
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

        # LABA BERSIH (NET INCOME)
        net_profit_cur = op_profit_cur + net_other_cur
        net_profit_cmp = op_profit_cmp + net_other_cmp
        lines_data.append((0, 0, {
            "sequence": seq, "name": "LABA / (RUGI) BERSIH PERIODE BERJALAN",
            "line_type": "total", "amount_current": net_profit_cur, "amount_comparison": net_profit_cmp,
        }))

        self.write({"line_ids": lines_data})

    def _compute_balance_sheet(self):
        """Kalkulasi Neraca Keuangan Berstandar PSAK."""
        lines_data = []
        seq = 10

        # BAGIAN I: ASET (ASSETS)
        lines_data.append((0, 0, {"sequence": seq, "name": "ASET LANCAR (CURRENT ASSETS)", "line_type": "header"}))
        seq += 10

        current_assets = [
            ("11101", "Kas Kasir Rawat Jalan (Cash Safe)"),
            ("11102", "Kas Kasir Hemodialisis"),
            ("11111", "Bank BCA Operasional"),
            ("11121", "Kliring Payment Gateway Midtrans"),
            ("11122", "Kliring EDC / QRIS"),
            ("11201", "Piutang Pasien Umum (Co-Pay)"),
            ("11202", "Piutang Klaim BPJS Kesehatan (VClaim)"),
            ("11203", "Piutang Klaim Asuransi Swasta & Korporasi"),
            ("11401", "Persediaan Obat Farmasi Rawat Jalan"),
            ("11402", "Persediaan BHP & Reagen Lab"),
            ("11403", "Persediaan Dialyzer & BHP Khusus HD"),
            ("11501", "Uang Muka & Biaya Dibayar Dimuka"),
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

        # ASET TIDAK LANCAR
        lines_data.append((0, 0, {"sequence": seq, "name": "ASET TIDAK LANCAR (NON-CURRENT ASSETS)", "line_type": "header"}))
        seq += 10

        fixed_assets = [
            ("12101", "Peralatan Medis & Laboratorium"),
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

            tot_fix_asset_now += amt_now
            tot_fix_asset_cmp += amt_cmp

            lines_data.append((0, 0, {
                "sequence": seq, "name": label, "code": prefix,
                "line_type": "account", "amount_current": amt_now, "amount_comparison": amt_cmp,
            }))
            seq += 10

        # Akumulasi Penyusutan
        d_dep_now, c_dep_now = self._get_account_balance("1220", False, self.date_to, is_cumulative=True)
        amt_dep_now = -(c_dep_now - d_dep_now)
        amt_dep_cmp = 0.0
        if self.comparison_type != "none" and self.date_to_cmp:
            d_d_c, c_d_c = self._get_account_balance("1220", False, self.date_to_cmp, is_cumulative=True)
            amt_dep_cmp = -(c_d_c - d_d_c)

        tot_fix_asset_now += amt_dep_now
        tot_fix_asset_cmp += amt_dep_cmp

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Akumulasi Penyusutan Alat Medis & Mesin HD", "code": "1220",
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
            ("21150", "GR/IR Clearing (Utang Belum Ditagih)"),
            ("21201", "Utang Pajak PPN"),
            ("21203", "Utang PPh 21 Tenaga Ahli Dokter"),
            ("21301", "Akrual Utang Jasa Medis Dokter Rawat Jalan"),
            ("21302", "Akrual Utang Jasa Medis Dokter Hemodialisis"),
            ("21401", "Pendapatan Diterima Dimuka Pasien (Deposit)"),
            ("21402", "Pendapatan Diterima Dimuka Paket Dialisis (PSAK 72)"),
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

        # BAGIAN III: EKUITAS (EQUITY)
        lines_data.append((0, 0, {"sequence": seq, "name": "EKUITAS (EQUITY)", "line_type": "header"}))
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
            "sequence": seq, "name": "Modal Disetor PT Prosperra Medika Utama", "code": "310010",
            "line_type": "account", "amount_current": amt_cap_now, "amount_comparison": amt_cap_cmp,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Saldo Laba Ditahan", "code": "320010",
            "line_type": "account", "amount_current": amt_ret_now, "amount_comparison": amt_ret_cmp,
        }))
        seq += 10

        # Laba Berjalan (Computed to balance)
        net_curr_now = total_assets_now - tot_liab_now - (amt_cap_now + amt_ret_now)
        net_curr_cmp = total_assets_cmp - tot_liab_cmp - (amt_cap_cmp + amt_ret_cmp)

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Laba / (Rugi) Periode Berjalan", "code": "RETAINED-CURR",
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

        self.write({"line_ids": lines_data})

    def _compute_cash_flow(self):
        """Kalkulasi Laporan Arus Kas Berstandar PSAK 2."""
        lines_data = []
        seq = 10

        lines_data.append((0, 0, {"sequence": seq, "name": "ARUS KAS DARI AKTIVITAS OPERASI", "line_type": "header"}))
        seq += 10

        # 1. Penerimaan dari Pasien & Klaim
        d_p, c_p = self._get_account_balance("4100", self.date_from, self.date_to)
        cash_rec_patient = c_p - d_p
        d_h, c_h = self._get_account_balance("4101", self.date_from, self.date_to)
        cash_rec_hd = c_h - d_h

        lines_data.append((0, 0, {
            "sequence": seq, "name": "Penerimaan Kas dari Pelayanan Pasien Rawat Jalan",
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
            "sequence": seq, "name": "Pembayaran Beban Operasional, Gaji & Pemeliharaan",
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
            "sequence": seq, "name": "Perolehan Mesin Hemodialisis & Peralatan Medis",
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


class PsakFinancialReportLine(models.Model):
    _name = "psak.financial.report.line"
    _description = "Baris Laporan Keuangan PSAK"
    _order = "sequence, id"

    report_id = fields.Many2one("psak.financial.report", string="Laporan Induk", ondelete="cascade")
    sequence = fields.Integer(string="Urutan", default=10)
    name = fields.Char(string="Pos Akun / Kategori PSAK", required=True)
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
