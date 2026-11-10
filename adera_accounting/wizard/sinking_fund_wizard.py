# -*- coding: utf-8 -*-
from odoo import fields, models, api
from odoo.exceptions import UserError, ValidationError
from datetime import date
from dateutil.relativedelta import relativedelta
import logging

_logger = logging.getLogger(__name__)


class ClinicSinkingFundWizard(models.TransientModel):
    _name = "clinic.sinking.fund.wizard"
    _description = "Wizard Alokasi Cadangan Sinking Fund / Pemeliharaan Sarpras & Akreditasi"

    company_id = fields.Many2one(
        "res.company",
        string="Klinik / Perusahaan",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")

    date = fields.Date(
        string="Tanggal Pembukuan Cadangan",
        required=True,
        default=fields.Date.today,
        help="Tanggal posting jurnal cadangan (biasanya akhir bulan penutupan buku).",
    )
    fiscal_year = fields.Integer(
        string="Tahun Buku",
        required=True,
        default=lambda self: date.today().year,
    )
    period_month = fields.Selection(
        [
            ("1", "Januari"),
            ("2", "Februari"),
            ("3", "Maret"),
            ("4", "April"),
            ("5", "Mei"),
            ("6", "Juni"),
            ("7", "Juli"),
            ("8", "Agustus"),
            ("9", "September"),
            ("10", "Oktober"),
            ("11", "November"),
            ("12", "Desember"),
        ],
        string="Bulan Alokasi",
        required=True,
        default=lambda self: str(date.today().month),
    )

    date_from = fields.Date(string="Tanggal Awal Periode", compute="_compute_dates")
    date_to = fields.Date(string="Tanggal Akhir Periode", compute="_compute_dates")

    net_operating_profit = fields.Monetary(
        string="Laba Bersih Operasional Periode (Net Operating Profit)",
        currency_field="currency_id",
        default=lambda self: self._default_net_profit(),
        help="Laba bersih terposting dari buku besar (Pendapatan - HPP - Beban Operasional).",
    )

    allocation_percentage = fields.Float(
        string="Persentase Alokasi Cadangan (%)",
        required=True,
        default=10.0,
        help="Batas maksimal alokasi cadangan adalah 10.0% dari Laba Bersih Operasional.",
    )

    allocation_amount = fields.Monetary(
        string="Nilai Alokasi Sinking Fund (Rp)",
        currency_field="currency_id",
        compute="_compute_allocation_amount",
        readonly=False,
    )

    purpose = fields.Selection(
        [
            ("accreditation", "Cadangan Akreditasi Klinik Kemenkes / LAFKESPRI"),
            ("device_overhaul", "Overhaul & Rekondisi Mesin Hemodialisis & RO Plant"),
            ("facility_expansion", "Renovasi & Pengembangan Fasilitas Cabang"),
            ("general_sinking_fund", "Cadangan Umum Sarana, Prasarana & Akreditasi"),
        ],
        string="Tujuan Alokasi Cadangan",
        required=True,
        default="general_sinking_fund",
    )

    debit_account_id = fields.Many2one(
        "account.account",
        string="Akun Debit (320010 - Saldo Laba Ditahan)",
        required=True,
        default=lambda self: self._default_debit_account(),
    )
    credit_account_id = fields.Many2one(
        "account.account",
        string="Akun Kredit (320020 - Cadangan Sinking Fund)",
        required=True,
        default=lambda self: self._default_credit_account(),
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Jurnal Alokasi Cadangan",
        required=True,
        default=lambda self: self._default_journal(),
    )
    notes = fields.Text(string="Keterangan / Catatan Notulensi Direksi")

    @api.model
    def _default_debit_account(self):
        acc = self.env["account.account"].search([("code", "=", "320010")], limit=1)
        if not acc:
            acc = self.env.ref("adera_core.account_320010", raise_if_not_found=False)
        return acc

    @api.model
    def _default_credit_account(self):
        acc = self.env["account.account"].search([("code", "=", "320020")], limit=1)
        if not acc:
            acc = self.env.ref("adera_core.account_320020", raise_if_not_found=False)
        return acc

    @api.model
    def _default_journal(self):
        return self.env["account.journal"].search([
            ("type", "=", "general"),
            ("company_id", "=", self.env.company.id),
        ], limit=1)

    @api.model
    def _default_net_profit(self):
        today = date.today()
        start_d = date(today.year, today.month, 1)
        end_d = start_d + relativedelta(months=1, days=-1)
        lines = self.env["account.move.line"].search([
            ("company_id", "=", self.env.company.id),
            ("parent_state", "=", "posted"),
            ("date", ">=", start_d),
            ("date", "<=", end_d),
        ])
        rev = sum(l.credit - l.debit for l in lines if l.account_id.code and l.account_id.code.startswith("41"))
        cogs = sum(l.debit - l.credit for l in lines if l.account_id.code and l.account_id.code.startswith("51"))
        opex = sum(l.debit - l.credit for l in lines if l.account_id.code and l.account_id.code.startswith("61"))
        other_inc = sum(l.credit - l.debit for l in lines if l.account_id.code and l.account_id.code.startswith("42"))
        profit = float(rev - cogs - opex + other_inc)
        return max(0.0, profit)

    @api.depends("fiscal_year", "period_month")
    def _compute_dates(self):
        for rec in self:
            if rec.fiscal_year and rec.period_month:
                m = int(rec.period_month)
                start_d = date(rec.fiscal_year, m, 1)
                end_d = start_d + relativedelta(months=1, days=-1)
                rec.date_from = start_d
                rec.date_to = end_d
            else:
                rec.date_from = False
                rec.date_to = False

    @api.onchange("fiscal_year", "period_month")
    def _onchange_period(self):
        for rec in self:
            if rec.fiscal_year and rec.period_month:
                m = int(rec.period_month)
                start_d = date(rec.fiscal_year, m, 1)
                end_d = start_d + relativedelta(months=1, days=-1)
                lines = self.env["account.move.line"].search([
                    ("company_id", "=", rec.company_id.id),
                    ("parent_state", "=", "posted"),
                    ("date", ">=", start_d),
                    ("date", "<=", end_d),
                ])
                rev = sum(l.credit - l.debit for l in lines if l.account_id.code and l.account_id.code.startswith("41"))
                cogs = sum(l.debit - l.credit for l in lines if l.account_id.code and l.account_id.code.startswith("51"))
                opex = sum(l.debit - l.credit for l in lines if l.account_id.code and l.account_id.code.startswith("61"))
                other_inc = sum(l.credit - l.debit for l in lines if l.account_id.code and l.account_id.code.startswith("42"))
                profit = float(rev - cogs - opex + other_inc)
                rec.net_operating_profit = max(0.0, profit)

    @api.depends("net_operating_profit", "allocation_percentage")
    def _compute_allocation_amount(self):
        for rec in self:
            if rec.net_operating_profit > 0 and rec.allocation_percentage > 0:
                rec.allocation_amount = round(rec.net_operating_profit * (rec.allocation_percentage / 100.0), 2)
            else:
                rec.allocation_amount = 0.0

    @api.constrains("allocation_percentage")
    def _check_allocation_percentage(self):
        for rec in self:
            if rec.allocation_percentage < 0.0:
                raise ValidationError("Persentase alokasi tidak boleh negatif!")
            if rec.allocation_percentage > 10.0:
                raise ValidationError(
                    "Governance Limit Error: Sesuai aturan tata kelola keuangan klinik, "
                    "alokasi cadangan sinking fund dibatasi maksimal 10.0% dari Laba Operasional Bersih!"
                )

    def action_confirm_allocation(self):
        """Membukukan alokasi cadangan ke GL: Dr 320010 / Cr 320020."""
        self.ensure_one()
        if self.allocation_amount <= 0:
            raise UserError("Nilai alokasi cadangan harus lebih besar dari Rp 0,00!")

        month_names = dict(self._fields["period_month"].selection)
        month_str = month_names.get(self.period_month, self.period_month)
        purpose_label = dict(self._fields["purpose"].selection).get(self.purpose, self.purpose)

        move_vals = {
            "journal_id": self.journal_id.id,
            "date": self.date,
            "ref": f"Sinking Fund Sarkes {month_str} {self.fiscal_year} ({purpose_label})",
            "move_type": "entry",
            "line_ids": [
                (0, 0, {
                    "name": f"Alokasi Cadangan Sinking Fund - {purpose_label}",
                    "account_id": self.debit_account_id.id,
                    "debit": self.allocation_amount,
                    "credit": 0.0,
                }),
                (0, 0, {
                    "name": f"Penerimaan Cadangan Pengembangan Sarpras ({month_str} {self.fiscal_year})",
                    "account_id": self.credit_account_id.id,
                    "debit": 0.0,
                    "credit": self.allocation_amount,
                }),
            ],
        }

        move = self.env["account.move"].create(move_vals)
        move.action_post()

        return {
            "type": "ir.actions.act_window",
            "name": "Entri Jurnal Alokasi Sinking Fund",
            "res_model": "account.move",
            "res_id": move.id,
            "view_mode": "form",
            "target": "current",
        }
