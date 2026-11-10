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
        string="Akun Biaya Dibayar di Muka",
        required=True,
        default=lambda self: self._default_prepaid_account(),
        tracking=True,
    )
    expense_account_id = fields.Many2one(
        "account.account",
        string="Akun Beban Sewa Gedung",
        required=True,
        default=lambda self: self._default_expense_account(),
        tracking=True,
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Jurnal Amortisasi",
        required=True,
        default=lambda self: self.env["account.journal"].search([("type", "=", "general")], limit=1),
    )
    analytic_distribution = fields.Json(
        string="Alokasi Unit Bisnis (Analytic Unit)",
        help="Tagging alokasi cabang (contoh: ACC-PRATAMA atau ACC-HD)",
    )

    line_ids = fields.One2many(
        "clinic.prepaid.lease.line",
        "lease_id",
        string="Jadwal Amortisasi Bulanan",
    )

    def _default_prepaid_account(self):
        return self.env["account.account"].search([("code", "in", ["115010", "11501"])], limit=1)

    def _default_expense_account(self):
        return self.env["account.account"].search([("code", "in", ["610020", "61002"])], limit=1)

    @api.depends("start_date", "duration_months")
    def _compute_end_date(self):
        for rec in self:
            if rec.start_date and rec.duration_months > 0:
                rec.end_date = rec.start_date + relativedelta(months=rec.duration_months, days=-1)
            else:
                rec.end_date = rec.start_date

    @api.depends("total_amount", "duration_months")
    def _compute_monthly_amount(self):
        for rec in self:
            if rec.duration_months > 0 and rec.total_amount > 0:
                rec.monthly_amount = round(rec.total_amount / rec.duration_months, 2)
            else:
                rec.monthly_amount = 0.0

    @api.depends("total_amount", "line_ids.state", "line_ids.amount")
    def _compute_totals(self):
        for rec in self:
            posted_lines = rec.line_ids.filtered(lambda l: l.state == "posted")
            amortized = sum(posted_lines.mapped("amount"))
            rec.amortized_amount = amortized
            rec.remaining_amount = max(0.0, rec.total_amount - amortized)
            if rec.state == "running" and rec.remaining_amount <= 0.0 and len(posted_lines) == rec.duration_months:
                rec.state = "completed"

    def compute_schedule(self):
        """Membuat rincian jadwal amortisasi bulanan."""
        for lease in self:
            if lease.total_amount <= 0:
                raise UserError("Total nilai sewa harus lebih besar dari Rp 0,00!")
            if lease.duration_months <= 0:
                raise UserError("Durasi sewa harus lebih besar dari 0 bulan!")

            # Unlink unposted draft lines only
            lease.line_ids.filtered(lambda l: l.state == "draft").unlink()

            posted_lines = lease.line_ids.filtered(lambda l: l.state == "posted").sorted("schedule_date")
            posted_count = len(posted_lines)
            accumulated = sum(posted_lines.mapped("amount"))

            remaining_months = lease.duration_months - posted_count
            if remaining_months <= 0:
                continue

            monthly = round(lease.total_amount / lease.duration_months, 2)
            start = lease.start_date
            if posted_lines:
                start = posted_lines[-1].schedule_date

            new_lines = []
            curr_accum = accumulated
            for m in range(1, remaining_months + 1):
                sch_date = start + relativedelta(months=m)
                if m == remaining_months:
                    amt = max(0.0, lease.total_amount - curr_accum)
                else:
                    amt = min(monthly, lease.total_amount - curr_accum)

                curr_accum += amt
                new_lines.append({
                    "lease_id": lease.id,
                    "sequence": posted_count + m,
                    "schedule_date": sch_date,
                    "amount": amt,
                    "accumulated_amount": curr_accum,
                    "remaining_balance": max(0.0, lease.total_amount - curr_accum),
                    "state": "draft",
                })

            if new_lines:
                self.env["clinic.prepaid.lease.line"].create(new_lines)
        return True

    def action_confirm(self):
        for rec in self:
            if not rec.line_ids:
                rec.compute_schedule()
            rec.write({"state": "running"})
        return True

    def action_set_to_draft(self):
        for rec in self:
            posted = rec.line_ids.filtered(lambda l: l.state == "posted")
            if posted:
                raise UserError("Tidak dapat membatalkan kontrak sewa karena terdapat baris amortisasi yang sudah dibukukan!")
            rec.line_ids.unlink()
            rec.write({"state": "draft"})
        return True

    def action_post_line(self, line_id):
        self.ensure_one()
        line = self.env["clinic.prepaid.lease.line"].browse(line_id)
        if line.lease_id.id != self.id:
            raise UserError("Baris tidak sesuai dengan kontrak sewa yang dipilih!")
        if line.state == "posted":
            raise UserError("Baris amortisasi ini sudah dibukukan sebelumnya!")
        if self.state != "running":
            raise UserError("Hanya kontrak sewa berstatus 'Berjalan' yang dapat dibukukan amortisasinya!")

        # Create balanced journal entry: Dr 610020 / Cr 115010
        move_vals = {
            "journal_id": self.journal_id.id,
            "date": line.schedule_date,
            "ref": f"Amortisasi Sewa Gedung: {self.name} ({line.schedule_date.strftime('%m/%Y')})",
            "move_type": "entry",
            "line_ids": [
                (0, 0, {
                    "name": f"Beban Sewa Gedung Klinik: {self.name}",
                    "account_id": self.expense_account_id.id,
                    "debit": line.amount,
                    "credit": 0.0,
                    "analytic_distribution": self.analytic_distribution or False,
                }),
                (0, 0, {
                    "name": f"Pengurangan Sewa Dibayar di Muka: {self.name}",
                    "account_id": self.prepaid_account_id.id,
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
    def cron_post_monthly_prepaid_amortization(self):
        """Scheduled action untuk otomatis membukukan amortisasi sewa bulanan yang jatuh tempo."""
        today = fields.Date.today()
        due_lines = self.env["clinic.prepaid.lease.line"].search([
            ("lease_id.state", "=", "running"),
            ("state", "=", "draft"),
            ("schedule_date", "<=", today),
        ])
        _logger.info("Executing prepaid lease amortization cron. Total due lines: %d", len(due_lines))
        posted_count = 0
        for line in due_lines:
            try:
                line.lease_id.action_post_line(line.id)
                posted_count += 1
            except Exception as e:
                _logger.error("Failed to post lease line %d for %s: %s", line.id, line.lease_id.name, str(e))
        _logger.info("Completed prepaid lease cron. Successfully posted: %d lines.", posted_count)
        return True


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
