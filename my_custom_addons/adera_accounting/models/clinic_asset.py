# -*- coding: utf-8 -*-
from odoo import fields, models, api
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
from datetime import date
import logging

_logger = logging.getLogger(__name__)


class ClinicAsset(models.Model):
    _name = "clinic.asset"
    _description = "Aset Tetap & Peralatan Medis Klinik"
    _inherit = ["mail.thread", "mail.activity.mixin", "analytic.mixin"]
    _order = "purchase_date desc, id desc"

    name = fields.Char(string="Nama Aset / Peralatan", required=True, tracking=True)
    asset_code = fields.Char(string="Kode / Nomor Seri Aset", copy=False, tracking=True)

    asset_category = fields.Selection(
        [
            ("medical_device_hd", "Alat Medis / Mesin HD & RO (Direct COGS 510030)"),
            ("medical_device_pratama", "Alat Medis Rawat Jalan Pratama (Beban OpEx 610030)"),
            ("general_facility", "Fasilitas & Peralatan Umum Klinik (Beban OpEx 610030)"),
            ("medical_equipment", "Peralatan Medis & Fasilitas Umum"),
            ("office_equipment", "Peralatan Kantor & IT"),
            ("vehicle", "Kendaraan / Ambulans"),
            ("building_improvement", "Renovasi Gedung Klinik"),
        ],
        string="Kategori Aset",
        required=True,
        default="medical_device_hd",
        tracking=True,
    )

    analytic_distribution = fields.Json(
        string="Distribusi Analitik Unit",
        help="Tagging alokasi unit bisnis (misal: ACC-PRATAMA vs ACC-HD)",
    )
    analytic_precision = fields.Integer(
        string="Analytic Precision",
        store=False,
        default=lambda self: self.env['decimal.precision'].precision_get('Percentage Analytic') or 2,
    )

    purchase_date = fields.Date(
        string="Tanggal Perolehan",
        required=True,
        default=fields.Date.today,
        tracking=True,
    )
    purchase_value = fields.Monetary(
        string="Nilai Perolehan (Historical Cost)",
        required=True,
        currency_field="currency_id",
        tracking=True,
    )
    salvage_value = fields.Monetary(
        string="Nilai Residu",
        default=0.0,
        currency_field="currency_id",
        tracking=True,
    )
    depreciation_method = fields.Selection(
        [("straight_line", "Garis Lurus (Straight-Line)")],
        string="Metode Penyusutan",
        default="straight_line",
        required=True,
        tracking=True,
    )

    useful_life_months = fields.Integer(
        string="Masa Manfaat (Bulan)",
        required=True,
        default=60,
        tracking=True,
        help="Contoh: 60 bulan (5 tahun) untuk alat medis; 96 bulan (8 tahun) untuk Water Treatment RO",
    )

    asset_account_id = fields.Many2one(
        "account.account",
        string="Akun Aset Tetap",
        required=True,
        tracking=True,
        default=lambda self: self._default_asset_account(),
    )
    depreciation_account_id = fields.Many2one(
        "account.account",
        string="Akun Akumulasi Penyusutan",
        required=True,
        tracking=True,
        default=lambda self: self._default_depreciation_account(),
    )
    expense_account_id = fields.Many2one(
        "account.account",
        string="Akun Beban Penyusutan",
        required=True,
        tracking=True,
        default=lambda self: self._default_expense_account(),
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Jurnal Penyusutan",
        required=True,
        default=lambda self: self.env["account.journal"].search([("type", "=", "general")], limit=1),
    )

    state = fields.Selection(
        [
            ("draft", "Draf"),
            ("running", "Berjalan"),
            ("depreciated", "Selesai Disusutkan"),
            ("disposed", "Dilepas / Afkir"),
        ],
        string="Status Aset",
        default="draft",
        tracking=True,
        required=True,
    )

    company_id = fields.Many2one(
        "res.company",
        string="Perusahaan / Klinik",
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")

    depreciation_line_ids = fields.One2many(
        "clinic.asset.depreciation.line",
        "asset_id",
        string="Jadwal Amortisasi Penyusutan",
    )

    # Computed Summary Fields
    monthly_depreciation = fields.Monetary(
        string="Penyusutan per Bulan",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
    )
    accumulated_depreciation = fields.Monetary(
        string="Total Akumulasi Penyusutan",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
    )
    net_book_value = fields.Monetary(
        string="Nilai Buku Bersih (Net Book Value)",
        compute="_compute_totals",
        store=True,
        currency_field="currency_id",
    )
    depreciated_months_count = fields.Integer(
        string="Bulan Teramortisasi",
        compute="_compute_totals",
        store=True,
    )
    remaining_months_count = fields.Integer(
        string="Sisa Bulan Amortisasi",
        compute="_compute_totals",
        store=True,
    )

    def _default_asset_account(self):
        return self.env["account.account"].search([("code", "in", ["121010", "121020"])], limit=1)

    def _default_depreciation_account(self):
        return self.env["account.account"].search([("code", "=", "122010")], limit=1)

    def _default_expense_account(self):
        return self.env["account.account"].search([("code", "in", ["510030", "610030", "610050"])], limit=1)

    @api.onchange("asset_category")
    def _onchange_asset_category(self):
        category_config = {
            "medical_device_hd": {
                "useful_life": 60,
                "asset_code": "121010",
                "expense_code": "510030",
                "analytic_code": "ACC-HD",
            },
            "medical_device_pratama": {
                "useful_life": 60,
                "asset_code": "121010",
                "expense_code": "610030",
                "analytic_code": "ACC-PRATAMA",
            },
            "general_facility": {
                "useful_life": 60,
                "asset_code": "121010",
                "expense_code": "610030",
                "analytic_code": "ACC-PRATAMA",
            },
            "medical_equipment": {
                "useful_life": 60,
                "asset_code": "121010",
                "expense_code": "610030",
                "analytic_code": "ACC-PRATAMA",
            },
            "office_equipment": {
                "useful_life": 48,
                "asset_code": "121010",
                "expense_code": "610030",
                "analytic_code": "HOLDING-IT",
            },
            "vehicle": {
                "useful_life": 96,
                "asset_code": "121010",
                "expense_code": "610030",
                "analytic_code": "ACC-PRATAMA",
            },
            "building_improvement": {
                "useful_life": 120,
                "asset_code": "121010",
                "expense_code": "610030",
                "analytic_code": "ACC-HOLDING",
            },
        }
        cfg = category_config.get(self.asset_category)
        if cfg:
            self.useful_life_months = cfg["useful_life"]
            asset_acc = self.env["account.account"].search([("code", "=", cfg["asset_code"])], limit=1)
            if asset_acc:
                self.asset_account_id = asset_acc.id
            exp_acc = self.env["account.account"].search([("code", "=", cfg["expense_code"])], limit=1)
            if exp_acc:
                self.expense_account_id = exp_acc.id
            analytic_acc = self.env["account.analytic.account"].search([("code", "=", cfg["analytic_code"])], limit=1)
            if analytic_acc:
                self.analytic_distribution = {str(analytic_acc.id): 100.0}

    @api.depends("purchase_value", "salvage_value", "useful_life_months", "depreciation_line_ids.state", "depreciation_line_ids.amount")
    def _compute_totals(self):
        for rec in self:
            if rec.useful_life_months > 0:
                rec.monthly_depreciation = round((rec.purchase_value - rec.salvage_value) / rec.useful_life_months, 2)
            else:
                rec.monthly_depreciation = 0.0

            posted_lines = rec.depreciation_line_ids.filtered(lambda l: l.state == "posted")
            posted_amt = sum(posted_lines.mapped("amount"))
            rec.accumulated_depreciation = posted_amt
            rec.net_book_value = max(rec.salvage_value, rec.purchase_value - posted_amt)
            rec.depreciated_months_count = len(posted_lines)
            rec.remaining_months_count = max(0, rec.useful_life_months - len(posted_lines))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            cat = vals.get("asset_category")
            if cat == "medical_device_hd":
                if "expense_account_id" not in vals:
                    acc_510030 = self.env["account.account"].search([("code", "=", "510030")], limit=1)
                    if acc_510030:
                        vals["expense_account_id"] = acc_510030.id
                if "analytic_distribution" not in vals:
                    hd_acc = self.env["account.analytic.account"].search([("code", "=", "ACC-HD")], limit=1)
                    if hd_acc:
                        vals["analytic_distribution"] = {str(hd_acc.id): 100.0}
            elif cat in ("medical_device_pratama", "general_facility", "medical_equipment"):
                if "expense_account_id" not in vals:
                    acc_610030 = self.env["account.account"].search([("code", "=", "610030")], limit=1)
                    if acc_610030:
                        vals["expense_account_id"] = acc_610030.id
                if "analytic_distribution" not in vals:
                    prat_acc = self.env["account.analytic.account"].search([("code", "=", "ACC-PRATAMA")], limit=1)
                    if prat_acc:
                        vals["analytic_distribution"] = {str(prat_acc.id): 100.0}
        records = super().create(vals_list)
        for rec in records:
            if rec.state == "running" and not rec.depreciation_line_ids:
                rec.compute_depreciation_board()
        return records

    def compute_depreciation_board(self):
        """Membuat jadwal amortisasi penyusutan bulanan (straight-line) secara atomik."""
        for asset in self:
            if asset.purchase_value <= 0:
                raise UserError("Nilai perolehan aset harus lebih besar dari Rp 0,00!")
            if asset.useful_life_months <= 0:
                raise UserError("Masa manfaat aset dalam bulan harus lebih besar dari 0!")

            # Unlink unposted draft lines only
            asset.depreciation_line_ids.filtered(lambda l: l.state == "draft").unlink()

            posted_lines = asset.depreciation_line_ids.filtered(lambda l: l.state == "posted").sorted("depreciation_date")
            posted_count = len(posted_lines)
            accumulated = sum(posted_lines.mapped("amount"))

            remaining_life = asset.useful_life_months - posted_count
            if remaining_life <= 0:
                continue

            depreciable_base = asset.purchase_value - asset.salvage_value
            remaining_to_depreciate = depreciable_base - accumulated
            if remaining_to_depreciate <= 0:
                continue

            monthly_amt = round(depreciable_base / asset.useful_life_months, 2)

            start_date = asset.purchase_date
            if posted_lines:
                start_date = posted_lines[-1].depreciation_date

            new_lines = []
            curr_accum = accumulated
            curr_remaining = asset.purchase_value - curr_accum

            for m in range(1, remaining_life + 1):
                deprec_date = start_date + relativedelta(months=m)
                if m == remaining_life:
                    # Final month absorbs any fractional rounding variance
                    amt = max(0.0, depreciable_base - curr_accum)
                else:
                    amt = min(monthly_amt, max(0.0, curr_remaining - asset.salvage_value))

                curr_accum += amt
                curr_remaining = max(asset.salvage_value, asset.purchase_value - curr_accum)

                new_lines.append({
                    "asset_id": asset.id,
                    "sequence": posted_count + m,
                    "depreciation_date": deprec_date,
                    "amount": amt,
                    "accumulated_amount": curr_accum,
                    "remaining_value": curr_remaining,
                    "state": "draft",
                })

            if new_lines:
                self.env["clinic.asset.depreciation.line"].create(new_lines)

        return True

    def action_confirm(self):
        """Validasi dan operasikan aset dari status Draf ke Berjalan."""
        for rec in self:
            if not rec.depreciation_line_ids:
                rec.compute_depreciation_board()
            rec.write({"state": "running"})
        return True

    def action_set_to_draft(self):
        """Mengembalikan aset ke status Draf (hanya jika belum ada jurnal yang diposting)."""
        for rec in self:
            posted = rec.depreciation_line_ids.filtered(lambda l: l.state == "posted")
            if posted:
                raise UserError("Tidak dapat mengembalikan aset ke status Draf karena terdapat entri jurnal penyusutan yang telah diposting!")
            rec.depreciation_line_ids.unlink()
            rec.write({"state": "draft"})
        return True

    def action_dispose(self):
        """Pelepasan / Afkir Aset Tetap."""
        for rec in self:
            rec.write({"state": "disposed"})
        return True

    def action_post_depreciation_line(self, line_id):
        """Membukukan baris amortisasi penyusutan ke General Ledger (account.move)."""
        self.ensure_one()
        line = self.env["clinic.asset.depreciation.line"].browse(line_id)
        if line.asset_id.id != self.id:
            raise UserError("Baris penyusutan tidak sesuai dengan aset yang dipilih!")
        if line.state == "posted":
            raise UserError("Baris amortisasi ini sudah dibukukan sebelumnya!")
        if self.state != "running":
            raise UserError("Hanya aset berstatus 'Berjalan' yang dapat dibukukan penyusutannya!")

        # Create balanced journal entry
        move_vals = {
            "journal_id": self.journal_id.id,
            "date": line.depreciation_date,
            "ref": f"Penyusutan: {self.name} ({line.depreciation_date.strftime('%m/%Y')})",
            "move_type": "entry",
            "line_ids": [
                (0, 0, {
                    "name": f"Beban Penyusutan: {self.name}",
                    "account_id": self.expense_account_id.id,
                    "debit": line.amount,
                    "credit": 0.0,
                    "analytic_distribution": self.analytic_distribution or False,
                }),
                (0, 0, {
                    "name": f"Akumulasi Penyusutan: {self.name}",
                    "account_id": self.depreciation_account_id.id,
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

        if line.remaining_value <= self.salvage_value:
            self.write({"state": "depreciated"})

        return move

    @api.model
    def cron_post_monthly_asset_depreciation(self):
        """Scheduled action untuk otomatis memposting penyusutan bulanan yang telah jatuh tempo."""
        today = fields.Date.today()
        due_lines = self.env["clinic.asset.depreciation.line"].search([
            ("asset_id.state", "=", "running"),
            ("state", "=", "draft"),
            ("depreciation_date", "<=", today),
        ])
        _logger.info("Executing clinic asset depreciation cron. Total due lines: %d", len(due_lines))
        posted_count = 0
        for line in due_lines:
            try:
                line.asset_id.action_post_depreciation_line(line.id)
                posted_count += 1
            except Exception as e:
                _logger.error("Failed to post depreciation line %d for asset %s: %s", line.id, line.asset_id.name, str(e))
        _logger.info("Completed asset depreciation cron. Successfully posted: %d lines.", posted_count)
        return True


class ClinicAssetDepreciationLine(models.Model):
    _name = "clinic.asset.depreciation.line"
    _description = "Jadwal Baris Amortisasi Penyusutan Aset Klinik"
    _order = "depreciation_date asc, id asc"

    asset_id = fields.Many2one("clinic.asset", string="Aset Tetap", required=True, ondelete="cascade")
    sequence = fields.Integer(string="Bulan Ke-", default=1)
    depreciation_date = fields.Date(string="Tanggal Amortisasi", required=True)
    amount = fields.Monetary(string="Beban Penyusutan", required=True, currency_field="currency_id")
    accumulated_amount = fields.Monetary(string="Akumulasi Penyusutan", required=True, currency_field="currency_id")
    remaining_value = fields.Monetary(string="Nilai Buku Bersih", required=True, currency_field="currency_id")
    move_id = fields.Many2one("account.move", string="Entri Jurnal GL", readonly=True)
    state = fields.Selection(
        [
            ("draft", "Belum Dibukukan"),
            ("posted", "Telah Dibukukan"),
        ],
        string="Status",
        default="draft",
        required=True,
    )

    company_id = fields.Many2one("res.company", related="asset_id.company_id", store=True)
    currency_id = fields.Many2one("res.currency", related="asset_id.currency_id")

    def action_post_line(self):
        self.ensure_one()
        return self.asset_id.action_post_depreciation_line(self.id)

