# -*- coding: utf-8 -*-
from odoo import fields, models, api
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta
from datetime import date


class MedicalFixedAsset(models.Model):
    _name = "medical.fixed.asset"
    _description = "Aset Tetap Peralatan Medis & Penyusutan Permenkes 14/2021"
    _order = "acquisition_date desc, id desc"

    name = fields.Char(string="Nama Aset / Peralatan Medis", required=True)
    asset_code = fields.Char(string="Kode / No Seri Aset", required=True, copy=False)
    category = fields.Selection(
        [
            ("dialysis_machine", "Mesin Hemodialisis (Masa Manfaat: 5 Tahun / 60 Bulan)"),
            ("ro_water_system", "RO Water Treatment System HD (Masa Manfaat: 8 Tahun / 96 Bulan)"),
            ("usg", "Alat USG 4D & Diagnostik Medis (Masa Manfaat: 5 Tahun / 60 Bulan)"),
            ("dental_unit", "Dental Chair Unit Gigi (Masa Manfaat: 4 Tahun / 48 Bulan)"),
            ("ekg_monitor", "EKG & Monitor Pasien (Masa Manfaat: 4 Tahun / 48 Bulan)"),
            ("other", "Inventaris & Infrastruktur Klinik (Masa Manfaat: 4 Tahun / 48 Bulan)"),
        ],
        string="Golongan Alat Medis (Permenkes 14/2021)",
        required=True,
        default="dialysis_machine",
    )

    acquisition_date = fields.Date(string="Tanggal Perolehan", required=True, default=fields.Date.today)
    acquisition_cost = fields.Monetary(string="Harga Perolehan (Historical Cost)", required=True, currency_field="currency_id")
    salvage_value = fields.Monetary(string="Nilai Residu", default=0.0, currency_field="currency_id")
    useful_life_months = fields.Integer(string="Masa Manfaat (Bulan)", required=True, default=60)
    depreciation_method = fields.Selection(
        [("straight_line", "Garis Lurus (Straight-Line SAK EMKM / Permenkes 14/2021)")],
        string="Metode Penyusutan",
        default="straight_line",
        required=True,
    )

    company_id = fields.Many2one("res.company", string="Klinik", default=lambda self: self.env.company)
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")

    asset_account_id = fields.Many2one(
        "account.account",
        string="Akun Aset Tetap",
        required=True,
        default=lambda self: self.env.ref("adera_core.account_121020", raise_if_not_found=False),
    )
    accumulated_depreciation_account_id = fields.Many2one(
        "account.account",
        string="Akun Akumulasi Penyusutan (Contra-Asset)",
        required=True,
        default=lambda self: self.env.ref("adera_core.account_122010", raise_if_not_found=False),
    )
    depreciation_expense_account_id = fields.Many2one(
        "account.account",
        string="Akun Beban Penyusutan",
        required=True,
        default=lambda self: self.env.ref("adera_core.account_610030", raise_if_not_found=False),
    )
    analytic_account_id = fields.Many2one(
        "account.analytic.account",
        string="Unit Bisnis Analitik",
        help="Pilih ACC-HD untuk Mesin Hemodialisis atau ACC-PRATAMA untuk Alat Rawat Jalan",
    )

    monthly_depreciation = fields.Monetary(
        string="Penyusutan per Bulan",
        compute="_compute_depreciation_amounts",
        store=True,
        currency_field="currency_id",
    )
    accumulated_depreciation = fields.Monetary(
        string="Akumulasi Penyusutan Berjalan",
        compute="_compute_depreciation_amounts",
        store=True,
        currency_field="currency_id",
    )
    net_book_value = fields.Monetary(
        string="Nilai Buku Bersih (Net Book Value)",
        compute="_compute_depreciation_amounts",
        store=True,
        currency_field="currency_id",
    )

    depreciation_move_ids = fields.Many2many(
        "account.move",
        string="Entri Jurnal Penyusutan Bulanan",
        readonly=True,
    )

    state = fields.Selection(
        [
            ("draft", "Draf"),
            ("running", "Beroperasi & Menyusut Aktif"),
            ("closed", "Lunas Disusutkan (Fully Depreciated)"),
            ("disposed", "Dilepas / Afkir"),
        ],
        string="Status Aset",
        default="draft",
        required=True,
    )

    @api.onchange("category")
    def _onchange_category(self):
        life_map = {
            "dialysis_machine": 60,
            "ro_water_system": 96,
            "usg": 60,
            "dental_unit": 48,
            "ekg_monitor": 48,
            "other": 48,
        }
        if self.category in life_map:
            self.useful_life_months = life_map[self.category]

        if self.category in ("dialysis_machine", "ro_water_system"):
            self.asset_account_id = self.env.ref("adera_core.account_121020", raise_if_not_found=False)
            self.analytic_account_id = self.env.ref("adera_core.analytic_account_hd_root", raise_if_not_found=False)
        else:
            self.asset_account_id = self.env.ref("adera_core.account_121010", raise_if_not_found=False)
            self.analytic_account_id = self.env.ref("adera_core.analytic_account_pratama_root", raise_if_not_found=False)

    @api.depends("acquisition_cost", "salvage_value", "useful_life_months", "depreciation_move_ids.state")
    def _compute_depreciation_amounts(self):
        for rec in self:
            if rec.useful_life_months > 0:
                rec.monthly_depreciation = (rec.acquisition_cost - rec.salvage_value) / rec.useful_life_months
            else:
                rec.monthly_depreciation = 0.0

            # Sum posted moves
            posted_moves = rec.depreciation_move_ids.filtered(lambda m: m.state == "posted")
            accum = sum(posted_moves.mapped("amount_total"))
            rec.accumulated_depreciation = accum
            rec.net_book_value = max(rec.acquisition_cost - accum, rec.salvage_value)

    def action_confirm_running(self):
        self.write({"state": "running"})

    def action_post_monthly_depreciation(self, target_date=None):
        """Membukukan beban penyusutan bulanan ke GL: Dr Beban Penyusutan (610030) / Cr Akumulasi (122010)."""
        self.ensure_one()
        if self.state != "running":
            raise UserError("Hanya aset berstatus 'Beroperasi' yang dapat disusutkan!")

        if self.net_book_value <= self.salvage_value:
            self.state = "closed"
            raise UserError("Aset ini sudah lunas disusutkan (Nilai Buku = Nilai Residu)!")

        deprec_date = target_date or fields.Date.today()
        amt = min(self.monthly_depreciation, self.net_book_value - self.salvage_value)

        # Journal misc
        journal = self.env["account.journal"].search([("type", "=", "general")], limit=1)
        if not journal:
            raise UserError("Jurnal operasional umum tidak ditemukan!")

        analytic_dist = {str(self.analytic_account_id.id): 100.0} if self.analytic_account_id else False

        move_vals = {
            "journal_id": journal.id,
            "date": deprec_date,
            "ref": f"Penyusutan Bulanan: {self.name} ({self.asset_code})",
            "move_type": "entry",
            "line_ids": [
                (0, 0, {
                    "name": f"Beban Penyusutan {self.name}",
                    "account_id": self.depreciation_expense_account_id.id,
                    "debit": amt,
                    "credit": 0.0,
                    "analytic_distribution": analytic_dist,
                }),
                (0, 0, {
                    "name": f"Akumulasi Penyusutan {self.name}",
                    "account_id": self.accumulated_depreciation_account_id.id,
                    "debit": 0.0,
                    "credit": amt,
                }),
            ],
        }

        move = self.env["account.move"].create(move_vals)
        move.action_post()
        self.depreciation_move_ids = [(4, move.id)]

        if self.net_book_value <= self.salvage_value:
            self.state = "closed"

        return move

