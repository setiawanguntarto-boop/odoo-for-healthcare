# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import date
from dateutil.relativedelta import relativedelta


class FinancialReportWizard(models.TransientModel):
    _name = "financial.report.wizard"
    _description = "Wizard Laporan Keuangan Klinik ADERA"

    company_id = fields.Many2one(
        "res.company",
        string="Perusahaan",
        required=True,
        default=lambda self: self.env.company,
    )

    report_type = fields.Selection(
        [
            ("pl", "Laporan Laba Rugi"),
            ("bs", "Neraca Keuangan"),
            ("cf", "Laporan Arus Kas"),
            ("equity", "Laporan Perubahan Ekuitas"),
            ("calk", "Catatan atas Laporan Keuangan (CaLK)"),
        ],
        string="Jenis Laporan Keuangan",
        default="pl",
        required=True,
    )

    cash_flow_method = fields.Selection(
        [
            ("indirect", "Metode Tidak Langsung (Indirect Method)"),
            ("direct", "Metode Langsung (Direct Method)"),
        ],
        string="Metode Arus Kas",
        default="indirect",
    )

    date_range_preset = fields.Selection(
        [
            ("this_month", "Bulan Ini"),
            ("last_month", "Bulan Lalu"),
            ("this_quarter", "Kuartal Ini"),
            ("this_year", "Tahun Berjalan (YTD)"),
            ("custom", "Kustom"),
        ],
        string="Periode Pelaporan",
        default="this_month",
        required=True,
    )

    date_from = fields.Date(
        string="Dari Tanggal",
        required=True,
        default=lambda self: date.today().replace(day=1),
    )
    date_to = fields.Date(
        string="Sampai Tanggal",
        required=True,
        default=lambda self: date.today(),
    )

    target_move = fields.Selection(
        [
            ("posted", "Entri Terposting (Posted Only)"),
            ("all", "Semua Entri (Termasuk Draf)"),
        ],
        string="Target Transaksi",
        default="posted",
        required=True,
    )

    analytic_plan_id = fields.Many2one(
        "account.analytic.plan",
        string="Rencana Analitik",
        default=lambda self: self.env.ref("adera_core.analytic_plan_business_units", raise_if_not_found=False),
    )

    analytic_account_id = fields.Many2one(
        "account.analytic.account",
        string="Unit Bisnis / Poli",
        domain="[('plan_id', '=?', analytic_plan_id)]",
        help="Kosongkan untuk melihat konsolidasi seluruh unit klinik.",
    )

    journal_ids = fields.Many2many(
        "account.journal",
        string="Filter Jurnal Tertentu",
        help="Kosongkan untuk menyertakan seluruh jurnal operasional klinik.",
    )

    comparison_mode = fields.Selection(
        [
            ("none", "Tanpa Perbandingan"),
            ("prev_period", "Periode Sebelumnya"),
            ("same_last_year", "Periode yang Sama Tahun Lalu"),
        ],
        string="Perbandingan Periode",
        default="none",
        required=True,
    )

    date_from_cmp = fields.Date(string="Dari Tanggal Pembanding")
    date_to_cmp = fields.Date(string="Sampai Tanggal Pembanding")

    # Legacy/internal fields maintained invisibly for backward compatibility with existing engine
    accounting_standard = fields.Selection(
        [
            ("sak_emkm", "Standard Accounting"),
            ("emkm", "SAK EMKM"),
            ("sak_ep", "SAK EP / PSAK"),
        ],
        string="Standar Akuntansi",
        default="sak_emkm",
    )
    framework_standard = fields.Selection(
        [
            ("emkm", "SAK EMKM"),
            ("sak_ep", "SAK EP / PSAK"),
        ],
        string="Kerangka Regulasi",
        default="emkm",
    )

    @api.onchange("date_range_preset")
    def _onchange_date_range_preset(self):
        today = date.today()
        if self.date_range_preset == "this_month":
            self.date_from = today.replace(day=1)
            self.date_to = today
        elif self.date_range_preset == "last_month":
            first_day_current = today.replace(day=1)
            last_month_end = first_day_current - relativedelta(days=1)
            self.date_from = last_month_end.replace(day=1)
            self.date_to = last_month_end
        elif self.date_range_preset == "this_quarter":
            quarter = (today.month - 1) // 3 + 1
            self.date_from = date(today.year, 3 * quarter - 2, 1)
            self.date_to = today
        elif self.date_range_preset == "this_year":
            self.date_from = date(today.year, 1, 1)
            self.date_to = today

    @api.onchange("comparison_mode", "date_from", "date_to")
    def _onchange_comparison_mode(self):
        if self.comparison_mode == "none" or not self.date_from or not self.date_to:
            self.date_from_cmp = False
            self.date_to_cmp = False
            return

        if self.comparison_mode == "same_last_year":
            self.date_from_cmp = self.date_from - relativedelta(years=1)
            self.date_to_cmp = self.date_to - relativedelta(years=1)
        elif self.comparison_mode == "prev_period":
            # Smart Month-to-Date (MTD) Alignment:
            # If starting on 1st of month (e.g. 01/11 to 10/11), align comparison to same days of previous month (01/10 to 10/10)
            if self.date_from.day == 1 and self.date_from.month == self.date_to.month:
                prev_month_first = self.date_from - relativedelta(months=1)
                last_day_prev = (self.date_from - relativedelta(days=1)).day
                target_day = min(self.date_to.day, last_day_prev)
                self.date_from_cmp = prev_month_first
                self.date_to_cmp = prev_month_first.replace(day=target_day)
            else:
                diff_days = (self.date_to - self.date_from).days + 1
                self.date_to_cmp = self.date_from - relativedelta(days=1)
                self.date_from_cmp = self.date_to_cmp - relativedelta(days=diff_days - 1)

    def _map_report_type_to_engine(self):
        mapping = {
            "pl": "profit_loss",
            "bs": "balance_sheet",
            "cf": "cash_flow",
            "equity": "equity_change",
            "calk": "calk",
            # Fallback if raw engine values passed
            "profit_loss": "profit_loss",
            "balance_sheet": "balance_sheet",
            "cash_flow": "cash_flow",
            "equity_change": "equity_change",
        }
        return mapping.get(self.report_type, "profit_loss")

    def _map_comparison_to_engine(self):
        mapping = {
            "none": "none",
            "prev_period": "previous_period",
            "same_last_year": "previous_year",
            "previous_period": "previous_period",
            "previous_year": "previous_year",
        }
        return mapping.get(self.comparison_mode, "none")

    def action_generate_report(self):
        self.ensure_one()
        engine_report_type = self._map_report_type_to_engine()
        engine_comparison = self._map_comparison_to_engine()

        report_titles = {
            "profit_loss": "Laporan Laba Rugi",
            "balance_sheet": "Laporan Posisi Keuangan",
            "cash_flow": f"Laporan Arus Kas ({'Tidak Langsung' if self.cash_flow_method == 'indirect' else 'Langsung'})",
            "equity_change": "Laporan Perubahan Ekuitas",
            "calk": "Catatan Atas Laporan Keuangan (CaLK)",
        }
        unit_label = f"[{self.analytic_account_id.name}] " if self.analytic_account_id else "[Konsolidasi Klinik] "
        name = f"{unit_label}{report_titles.get(engine_report_type, 'Laporan Keuangan')} ({self.date_from.strftime('%d/%m/%Y')} - {self.date_to.strftime('%d/%m/%Y')})"

        # SAK EP required for equity change and cash flow
        framework = "sak_ep" if engine_report_type in ("equity_change", "cash_flow") else "emkm"

        report = self.env["psak.financial.report"].create({
            "name": name,
            "company_id": self.company_id.id,
            "framework_standard": framework,
            "report_type": engine_report_type,
            "cash_flow_method": self.cash_flow_method or "indirect",
            "date_preset": "custom",
            "date_from": self.date_from,
            "date_to": self.date_to,
            "target_move": self.target_move,
            "comparison_type": engine_comparison,
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

    def action_print_report(self):
        self.ensure_one()
        act = self.action_generate_report()
        report = self.env["psak.financial.report"].browse(act["res_id"])
        return self.env.ref("adera_accounting.action_report_psak_financial_statement").report_action(report)

    def action_view_html(self):
        return self.action_generate_report()


# Alias class for backward compatibility with existing views / actions
class PsakReportWizard(models.TransientModel):
    _name = "psak.report.wizard"
    _inherit = "financial.report.wizard"
    _description = "Wizard Laporan Keuangan (Compatibility Alias)"

    framework_standard = fields.Selection(
        [
            ("emkm", "SAK EMKM"),
            ("sak_ep", "SAK EP / PSAK"),
        ],
        string="Standar Akuntansi Regulasi",
        default="emkm",
    )
