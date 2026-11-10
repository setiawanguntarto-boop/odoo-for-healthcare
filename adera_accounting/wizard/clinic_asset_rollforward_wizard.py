# -*- coding: utf-8 -*-
from odoo import fields, models, api
from dateutil.relativedelta import relativedelta
from datetime import date


class ClinicAssetRollforwardWizard(models.TransientModel):
    _name = "clinic.asset.rollforward.wizard"
    _description = "Wizard Daftar Rincian Aset Tetap & Penyusutan (Roll-Forward Schedule)"

    date_from = fields.Date(
        string="Tanggal Mulai",
        required=True,
        default=lambda self: date.today().replace(month=1, day=1),
    )
    date_to = fields.Date(
        string="Tanggal Selesai",
        required=True,
        default=fields.Date.today,
    )
    asset_category = fields.Selection(
        [
            ("all", "Semua Golongan Aset"),
            ("medical_equipment", "Alat Medis / Hemodialisis (Permenkes 14/2021)"),
            ("office_equipment", "Peralatan Kantor & IT"),
            ("vehicle", "Kendaraan / Ambulans"),
            ("building_improvement", "Renovasi Gedung Klinik"),
        ],
        string="Filter Kategori",
        default="all",
        required=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Klinik / Perusahaan",
        default=lambda self: self.env.company,
        required=True,
    )

    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref("adera_accounting.action_report_clinic_asset_rollforward").report_action(self)

    def get_asset_rollforward_data(self):
        """Menghasilkan dataset roll-forward aset tetap sesuai format Table 7 / Note 1.e Panacea benchmark."""
        self.ensure_one()
        domain = [("company_id", "=", self.company_id.id)]
        if self.asset_category != "all":
            domain.append(("asset_category", "=", self.asset_category))

        assets = self.env["clinic.asset"].search(domain, order="asset_category, purchase_date asc")
        
        category_labels = {
            "medical_equipment": "I. Peralatan Medis & Fasilitas Hemodialisis (Permenkes 14/2021)",
            "office_equipment": "II. Peralatan Kantor & Infrastruktur IT",
            "vehicle": "III. Kendaraan Operasional & Ambulans",
            "building_improvement": "IV. Renovasi Gedung & Prasarana Klinik",
        }

        grouped_data = {}
        for cat_key, cat_label in category_labels.items():
            cat_assets = assets.filtered(lambda a: a.asset_category == cat_key)
            if not cat_assets and self.asset_category != "all":
                continue
            
            rows = []
            sub_init_cost = 0.0
            sub_period_add = 0.0
            sub_ending_cost = 0.0
            sub_init_deprec = 0.0
            sub_period_deprec = 0.0
            sub_total_deprec = 0.0
            sub_nbv = 0.0

            for asset in cat_assets:
                # Perolehan
                if asset.purchase_date < self.date_from:
                    init_cost = asset.purchase_value
                    period_add = 0.0
                elif self.date_from <= asset.purchase_date <= self.date_to:
                    init_cost = 0.0
                    period_add = asset.purchase_value
                else:
                    # Acquired after date_to (exclude)
                    continue

                ending_cost = init_cost + period_add

                # Penyusutan
                posted_lines = asset.depreciation_line_ids.filtered(lambda l: l.state == "posted")
                init_lines = posted_lines.filtered(lambda l: l.depreciation_date < self.date_from)
                period_lines = posted_lines.filtered(lambda l: self.date_from <= l.depreciation_date <= self.date_to)

                init_deprec = sum(init_lines.mapped("amount"))
                period_deprec = sum(period_lines.mapped("amount"))
                total_deprec = init_deprec + period_deprec
                nbv = max(asset.salvage_value, ending_cost - total_deprec)

                sub_init_cost += init_cost
                sub_period_add += period_add
                sub_ending_cost += ending_cost
                sub_init_deprec += init_deprec
                sub_period_deprec += period_deprec
                sub_total_deprec += total_deprec
                sub_nbv += nbv

                rows.append({
                    "name": asset.name,
                    "code": asset.asset_code or "-",
                    "purchase_date": asset.purchase_date.strftime("%d/%m/%Y"),
                    "useful_life": asset.useful_life_months,
                    "init_cost": init_cost,
                    "period_add": period_add,
                    "ending_cost": ending_cost,
                    "init_deprec": init_deprec,
                    "period_deprec": period_deprec,
                    "total_deprec": total_deprec,
                    "nbv": nbv,
                    "state": dict(asset._fields["state"].selection).get(asset.state, asset.state),
                })

            if rows or self.asset_category == cat_key:
                grouped_data[cat_label] = {
                    "rows": rows,
                    "totals": {
                        "init_cost": sub_init_cost,
                        "period_add": sub_period_add,
                        "ending_cost": sub_ending_cost,
                        "init_deprec": sub_init_deprec,
                        "period_deprec": sub_period_deprec,
                        "total_deprec": sub_total_deprec,
                        "nbv": sub_nbv,
                    }
                }

        grand_totals = {
            "init_cost": sum(g["totals"]["init_cost"] for g in grouped_data.values()),
            "period_add": sum(g["totals"]["period_add"] for g in grouped_data.values()),
            "ending_cost": sum(g["totals"]["ending_cost"] for g in grouped_data.values()),
            "init_deprec": sum(g["totals"]["init_deprec"] for g in grouped_data.values()),
            "period_deprec": sum(g["totals"]["period_deprec"] for g in grouped_data.values()),
            "total_deprec": sum(g["totals"]["total_deprec"] for g in grouped_data.values()),
            "nbv": sum(g["totals"]["nbv"] for g in grouped_data.values()),
        }

        return {
            "grouped_data": grouped_data,
            "grand_totals": grand_totals,
            "currency": self.company_id.currency_id,
        }

