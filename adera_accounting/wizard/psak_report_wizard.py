# -*- coding: utf-8 -*-
from odoo import fields, models, api
from dateutil.relativedelta import relativedelta
from datetime import date


class PsakReportWizard(models.TransientModel):
    _name = "psak.report.wizard"
    _description = "Wizard Laporan Keuangan PSAK / SAK EMKM / SAK EP Klinik ADERA"

    framework_standard = fields.Selection(
        [
            ("emkm", "SAK EMKM (Phase 1 Baseline - Standar Entitas Mikro, Kecil, Menengah)"),
            ("sak_ep", "SAK EP / PSAK (Phase 2 Roadmap - Standar Entitas Privat)"),
        ],
        string="Standar Akuntansi Regulasi",
        default="emkm",
        required=True,
    )

    report_type = fields.Selection(
        [
            ("profit_loss", "Laporan Laba Rugi (Statement of Profit or Loss)"),
            ("balance_sheet", "Neraca Keuangan (Statement of Financial Position)"),
            ("cash_flow", "Laporan Arus Kas (Statement of Cash Flows - SAK EP)"),
            ("equity_change", "Laporan Perubahan Ekuitas (Statement of Changes in Equity - SAK EP)"),
            ("calk", "Catatan Atas Laporan Keuangan (CaLK - SAK EMKM / SAK EP)"),
        ],
        string="Jenis Laporan PSAK",
        required=True,
        default="profit_loss",
    )

    cash_flow_method = fields.Selection(
        [
            ("direct", "Metode Langsung (Direct Method)"),
            ("indirect", "Metode Tidak Langsung (Indirect Method)"),
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
        required=True,
    )

    date_from = fields.Date(string="Tanggal Mulai", required=True, default=lambda self: date.today().replace(day=1))
    date_to = fields.Date(string="Tanggal Selesai", required=True, default=fields.Date.today)

    target_move = fields.Selection(
        [
            ("posted", "Hanya Entri yang Sudah Diposting (Audit Ready)"),
            ("all", "Semua Entri (Termasuk Draf & Webhook Staged)"),
        ],
        string="Target Transaksi",
        default="posted",
        required=True,
    )

    comparison_type = fields.Selection(
        [
            ("none", "Tanpa Analisis Komparatif"),
            ("previous_period", "Bandingkan Periode Sebelumnya"),
            ("previous_year", "Bandingkan Periode yang Sama Tahun Lalu"),
        ],
        string="Analisis Komparasi",
        default="none",
        required=True,
    )

    date_from_cmp = fields.Date(string="Tanggal Awal Pembanding")
    date_to_cmp = fields.Date(string="Tanggal Akhir Pembanding")

    analytic_account_id = fields.Many2one(
        "account.analytic.account",
        string="Filter Unit Bisnis Analitik",
        help="Kosongkan untuk Laporan Konsolidasi Seluruh Klinik, atau pilih unit (ACC-PRATAMA vs ACC-HD)",
    )

    journal_ids = fields.Many2many(
        "account.journal",
        string="Filter Jurnal Tertentu",
        help="Kosongkan untuk menyertakan seluruh jurnal operasional klinik",
    )

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

    def action_generate_report(self):
        """Menghasilkan record psak.financial.report dan membuka interaktif view."""
        self.ensure_one()

        report_titles = {
            "profit_loss": "Laporan Laba Rugi Komprehensif",
            "balance_sheet": "Laporan Posisi Keuangan (Neraca)",
            "cash_flow": f"Laporan Arus Kas ({'Tidak Langsung' if self.cash_flow_method == 'indirect' else 'Langsung'})",
            "equity_change": "Laporan Perubahan Ekuitas (SAK EP)",
            "calk": "Catatan Atas Laporan Keuangan (CaLK)",
        }
        std_label = "[SAK EMKM] " if self.framework_standard == "emkm" else "[SAK EP] "
        unit_label = f"[{self.analytic_account_id.name}] " if self.analytic_account_id else "[Konsolidasi Klinik] "
        name = f"{std_label}{unit_label}{report_titles.get(self.report_type)} ({self.date_from.strftime('%d/%m/%Y')} - {self.date_to.strftime('%d/%m/%Y')})"

        report = self.env["psak.financial.report"].create({
            "name": name,
            "framework_standard": self.framework_standard,
            "report_type": self.report_type,
            "cash_flow_method": self.cash_flow_method,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "target_move": self.target_move,
            "comparison_type": self.comparison_type,
            "date_from_cmp": self.date_from_cmp,
            "date_to_cmp": self.date_to_cmp,
            "analytic_account_id": self.analytic_account_id.id if self.analytic_account_id else False,
        })
        report.action_recompute()

        return {
            "name": name,
            "type": "ir.actions.act_window",
            "res_model": "psak.financial.report",
            "res_id": report.id,
            "view_mode": "form",
            "target": "current",
        }
