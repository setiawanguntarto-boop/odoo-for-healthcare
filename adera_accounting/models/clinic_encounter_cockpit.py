# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ClinicEncounterCockpit(models.Model):
    _inherit = "clinic.encounter"

    total_billing_amount = fields.Monetary(
        string="Total Billing Bruto",
        currency_field="currency_id",
        compute="_compute_cockpit_metrics",
        store=True,
    )
    total_doctor_fee = fields.Monetary(
        string="Akrual Jasa Dokter",
        currency_field="currency_id",
        compute="_compute_cockpit_metrics",
        store=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
    )
    reconciliation_status = fields.Selection(
        [
            ("matched", "Sesuai (Matched)"),
            ("variance_alert", "Selisih > Rp 50.000"),
        ],
        string="Status Rekonsiliasi Kas",
        compute="_compute_cockpit_metrics",
        store=True,
    )

    @api.depends("line_ids.qty", "line_ids.unit_price", "account_move_id.amount_residual", "state")
    def _compute_cockpit_metrics(self):
        for rec in self:
            total_bill = sum((l.qty * l.unit_price) for l in rec.line_ids)
            rec.total_billing_amount = total_bill
            accruals = self.env["medical.fee.accrual"].search([
                ("encounter_reference", "=", rec.external_encounter_id)
            ])
            rec.total_doctor_fee = sum(accruals.mapped("doctor_fee_amount"))
            residual = rec.account_move_id.amount_residual if rec.account_move_id else 0.0
            if rec.payer_type in ("cash", "qris", "split") and abs(residual) > 50000.0:
                rec.reconciliation_status = "variance_alert"
            else:
                rec.reconciliation_status = "matched"
