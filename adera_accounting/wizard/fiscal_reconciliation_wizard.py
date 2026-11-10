# -*- coding: utf-8 -*-
from odoo import fields, models, api
from datetime import date


class ClinicFiscalReconciliationWizard(models.TransientModel):
    _name = "clinic.fiscal.reconciliation.wizard"
    _description = "Wizard Penyiapan Kertas Kerja Rekonsiliasi Fiskal"

    fiscal_year = fields.Integer(
        string="Tahun Pajak (SPT)",
        required=True,
        default=lambda self: date.today().year,
    )
    date_from = fields.Date(
        string="Tanggal Mulai Pembukuan",
        required=True,
        default=lambda self: date(date.today().year, 1, 1),
    )
    date_to = fields.Date(
        string="Tanggal Selesai Pembukuan",
        required=True,
        default=lambda self: date(date.today().year, 12, 31),
    )
    tax_facility = fields.Selection(
        [
            ("pasal_31e", "Fasilitas Pasal 31E UU HPP (Tarif Efektif 11% - Omzet <= Rp 4,8 M)"),
            ("standard_rate", "Tarif Normal PPh Badan (22%)"),
        ],
        string="Skema Tarif Pajak",
        default="pasal_31e",
        required=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Klinik / Perusahaan",
        required=True,
        default=lambda self: self.env.company,
    )

    @api.onchange("fiscal_year")
    def _onchange_fiscal_year(self):
        if self.fiscal_year:
            self.date_from = date(self.fiscal_year, 1, 1)
            self.date_to = date(self.fiscal_year, 12, 31)

    def action_generate(self):
        self.ensure_one()
        rec_model = self.env["clinic.fiscal.reconciliation"]
        existing = rec_model.search([
            ("fiscal_year", "=", self.fiscal_year),
            ("company_id", "=", self.company_id.id),
        ], limit=1)

        vals = {
            "name": f"Kertas Kerja Rekonsiliasi Fiskal Form 1771 - Tahun {self.fiscal_year}",
            "fiscal_year": self.fiscal_year,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "company_id": self.company_id.id,
            "tax_facility": self.tax_facility,
        }

        if existing:
            existing.write(vals)
            reconciliation = existing
        else:
            reconciliation = rec_model.create(vals)

        reconciliation.action_compute()

        return {
            "type": "ir.actions.act_window",
            "name": f"Rekonsiliasi Fiskal Tahun {self.fiscal_year}",
            "res_model": "clinic.fiscal.reconciliation",
            "res_id": reconciliation.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_export_xlsx(self):
        self.ensure_one()
        res = self.action_generate()
        rec_id = res.get("res_id")
        reconciliation = self.env["clinic.fiscal.reconciliation"].browse(rec_id)
        return reconciliation.action_export_xlsx()

