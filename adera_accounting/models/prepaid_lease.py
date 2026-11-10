# -*- coding: utf-8 -*-
from odoo import fields, models, api
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta
from datetime import date
import logging

_logger = logging.getLogger(__name__)


class ClinicPrepaidLease(models.Model):
    _name = "clinic.prepaid.lease"
    _description = "Jadwal Amortisasi Sewa Gedung & Biaya Dibayar di Muka"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "start_date desc, id desc"

    name = fields.Char(string="Nama Kontrak / Lokasi Gedung", required=True, tracking=True)
    contract_number = fields.Char(string="Nomor Kontrak Sewa", tracking=True)
    partner_id = fields.Many2one("res.partner", string="Pemilik Gedung / Lessor", required=True, tracking=True)

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
            ("running", "Berjalan (Aktif)"),
            ("completed", "Selesai Diamortisasi"),
        ],
        string="Status",
        default="draft",
        tracking=True,
        required=True,
    )

    start_date = fields.Date(
        string="Tanggal Mulai Sewa",
        required=True,
        default=fields.Date.today,
        tracking=True,
    )
    end_date = fields.Date(
        string="Tanggal Berakhir Sewa",
        compute="_compute_end_date",
        store=True,
        readonly=False,
        tracking=True,
    )
    duration_months = fields.Integer(
        string="Durasi Sewa (Bulan)",
        required=True,
        default=12,
        tracking=True,
    )

    total_amount = fields.Monetary(
        string="Total Nilai Sewa Dibayar di Muka",
        required=True,
        currency_field="currency_id",
        tracking=True,
    )
    monthly_amount = fields.Monetary(
        string="Beban Amortisasi Bulanan",
        compute="_compute_monthly_amount",
        store=True,
        currency_field="currency_id",
    )
    amortized_amount = fields.Monetary(
        string="Total Telah Diamortisasi",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
    )
    remaining_amount = fields.Monetary(
        string="Sisa Saldo Uang Muka (NBV)",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
    )

    prepaid_account_id = fields.Many2one(
        "account.account",
        string="Akun Biaya Dibayar di Muka (115010)",
        required=True,
        default=lambda self: self._default_prepaid_account(),
        tracking=True,
    )
    expense_account_id = fields.Many2one(
        "account.account",
        string="Akun Beban Sewa Gedung (610020)",
        required=True,
        default=lambda self: self._default_expense_account(),
        tracking=True,
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Jurnal Amortisasi",
        required=True,
        default=lambda self: self._default_journal(),
        tracking=True,
    )
    analytic_distribution = fields.Json(
        string="Unit Bisnis / Cabang Analitik",
        help="Alokasi biaya sewa ke unit bisnis (ACC-PRATAMA, ACC-HD, ACC-HOLDING)",
    )

    line_ids = fields.One2many(
        "clinic.prepaid.lease.line",
        "lease_id",
        string="Rincian Jadwal Bulanan",
    )

    @api.model
    def _default_prepaid_account(self):
        acc = self.env["account.account"].search([
            ("code", "=", "115010"),
        ], limit=1)
        if not acc:
            acc = self.env.ref("adera_core.account_115010", raise_if_not_found=False)
        return acc

    @api.model
    def _default_expense_account(self):
        acc = self.env["account.account"].search([
            ("code", "=", "610020"),
        ], limit=1)
        if not acc:
            acc = self.env.ref("adera_core.account_610020", raise_if_not_found=False)
        return acc

    @api.model
    def _default_journal(self):
        return self.env["account.journal"].search([
            ("type", "=", "general"),
            ("company_id", "=", self.env.company.id),
        ], limit=1)

    @api.depends("start_date", "duration_months")
    def _compute_end_date(self):
        for rec in self:
            if rec.start_date and rec.duration_months:
                rec.end_date = rec.start_date + relativedelta(months=rec.duration_months, days=-1)
            else:
                rec.end_date = False

    @api.depends("total_amount", "duration_months")
    def _compute_monthly_amount(self):
        for rec in self:
            if rec.duration_months > 0:
                rec.monthly_amount = round(rec.total_amount / rec.duration_months, 2)
            else:
                rec.monthly_amount = 0.0

    @api.depends("line_ids.state", "line_ids.amount", "total_amount")
    def _compute_totals(self):
        for rec in self:
            posted_lines = rec.line_ids.filtered(lambda l: l.state == "posted")
            amortized = sum(posted_lines.mapped("amount"))
            rec.amortized_amount = amortized
            rec.remaining_amount = rec.total_amount - amortized
            if rec.line_ids and all(l.state == "posted" for l in rec.line_ids) and rec.state == "running":
                rec.state = "completed"

    def compute_schedule(self):
        """Membuat jadwal amortisasi garis lurus per bulan dari start_date s.d. end_date."""
        self.ensure_one()
        if self.duration_months <= 0 or self.total_amount <= 0:
            raise UserError("Durasi sewa (bulan) dan total nilai sewa harus lebih dari 0!")

        self.line_ids.unlink()

        lines = []
        base_monthly = round(self.total_amount / self.duration_months, 2)
        accumulated = 0.0
        current_date = self.start_date

        for i in range(1, self.duration_months + 1):
            if i == self.duration_months:
                amount = self.total_amount - accumulated
            else:
                amount = base_monthly

            accumulated += amount
            remaining = self.total_amount - accumulated

            lines.append((0, 0, {
                "sequence": i,
                "schedule_date": current_date,
                "amount": amount,
                "accumulated_amount": accumulated,
                "remaining_balance": remaining,
                "state": "draft",
            }))
            current_date = current_date + relativedelta(months=1)

        self.write({"line_ids": lines})
        return True

    def action_confirm(self):
        self.ensure_one()
        if not self.line_ids:
            self.compute_schedule()
        self.write({"state": "running"})
        return True

    def action_set_to_draft(self):
        self.ensure_one()
        posted_lines = self.line_ids.filtered(lambda l: l.state == "posted")
        if posted_lines:
            raise UserError("Tidak dapat membatalkan kontrak sewa yang baris amortisasinya sudah dibukukan di GL!")
        self.write({"state": "draft"})
        return True

    def action_post_line(self, line_id):
        """Membukukan entri jurnal GL untuk 1 baris jadwal amortisasi."""
        self.ensure_one()
        line = self.line_ids.browse(line_id)
        if line.state == "posted":
            raise UserError("Baris amortisasi ini sudah dibukukan sebelumnya!")

        move_vals = {
            "journal_id": self.journal_id.id,
            "date": line.schedule_date,
            "ref": f"Amortisasi Sewa: {self.name} (Bulan {line.sequence}/{self.duration_months})",
            "move_type": "entry",
            "line_ids": [
                (0, 0, {
                    "name": f"Beban Sewa Gedung: {self.name}",
                    "account_id": self.expense_account_id.id,
                    "partner_id": self.partner_id.id,
                    "debit": line.amount,
                    "credit": 0.0,
                    "analytic_distribution": self.analytic_distribution or {},
                }),
                (0, 0, {
                    "name": f"Amortisasi Sewa Dibayar Dimuka: {self.name}",
                    "account_id": self.prepaid_account_id.id,
                    "partner_id": self.partner_id.id,
                    "debit": 0.0,
                    "credit": line.amount,
                }),
            ],
        }
        move = self.env["account.move"].create(move_vals)
        move.action_post()

        line.write({
            "state": "posted",
            "move_id": move.id,
        })
        return move

    @api.model
    def cron_post_monthly_lease_amortization(self):
        """Scheduled action untuk otomatis membukukan amortisasi sewa gedung bulanan."""
        today = fields.Date.today()
        due_lines = self.env["clinic.prepaid.lease.line"].search([
            ("lease_id.state", "=", "running"),
            ("state", "=", "draft"),
            ("schedule_date", "<=", today),
        ])
        _logger.info("Executing monthly lease amortization cron. Total due lines: %d", len(due_lines))
        posted_count = 0
        for line in due_lines:
            try:
                line.lease_id.action_post_line(line.id)
                posted_count += 1
            except Exception as e:
                _logger.error("Failed to post lease line %d for %s: %s", line.id, line.lease_id.name, str(e))
        _logger.info("Completed lease amortization cron. Successfully posted: %d lines.", posted_count)
        return True

    @api.model
    def cron_post_monthly_prepaid_amortization(self):
        """Alias for backward compatibility."""
        return self.cron_post_monthly_lease_amortization()


class ClinicPrepaidLeaseLine(models.Model):
    _name = "clinic.prepaid.lease.line"
    _description = "Baris Jadwal Amortisasi Sewa Gedung Klinik"
    _order = "schedule_date asc, id asc"

    lease_id = fields.Many2one("clinic.prepaid.lease", string="Kontrak Sewa", required=True, ondelete="cascade")
    sequence = fields.Integer(string="Bulan Ke-", default=1)
    schedule_date = fields.Date(string="Tanggal Amortisasi", required=True)
    amount = fields.Monetary(string="Beban Amortisasi", required=True, currency_field="currency_id")
    accumulated_amount = fields.Monetary(string="Total Diamortisasi", required=True, currency_field="currency_id")
    remaining_balance = fields.Monetary(string="Sisa Saldo Uang Muka", required=True, currency_field="currency_id")
    move_id = fields.Many2one("account.move", string="Entri Jurnal GL", readonly=True)
    state = fields.Selection(
        [
            ("draft", "Belum Diamortisasi"),
            ("posted", "Telah Diamortisasi"),
        ],
        string="Status",
        default="draft",
        required=True,
    )
    company_id = fields.Many2one("res.company", related="lease_id.company_id", store=True)
    currency_id = fields.Many2one("res.currency", related="lease_id.currency_id")

    def action_post(self):
        self.ensure_one()
        return self.lease_id.action_post_line(self.id)
