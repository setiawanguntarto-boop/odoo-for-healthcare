# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import models, fields, api


class StockLot(models.Model):
    _inherit = "stock.lot"

    days_to_expiration = fields.Integer(
        string="Sisa Hari Kedaluwarsa",
        compute="_compute_expiration_metrics",
        store=True,
        help="Jumlah hari kalender tersisa hingga tanggal kedaluwarsa batch ini.",
    )

    expiration_status = fields.Selection([
        ("valid", "Aman (Valid > 60 Hari)"),
        ("expiring_soon", "Waspada: Mendekati Expired (< 60 Hari)"),
        ("expired", "BAHAYA: Sudah Kedaluwarsa"),
    ], string="Status Kedaluwarsa FEFO", compute="_compute_expiration_metrics", store=True)

    @api.depends("expiration_date")
    def _compute_expiration_metrics(self):
        today = fields.Date.context_today(self)
        for lot in self:
            if not lot.expiration_date:
                lot.days_to_expiration = 9999
                lot.expiration_status = "valid"
                continue

            exp_date = fields.Date.to_date(lot.expiration_date)
            delta = (exp_date - today).days
            lot.days_to_expiration = delta

            if delta <= 0:
                lot.expiration_status = "expired"
            elif delta <= 60:
                lot.expiration_status = "expiring_soon"
            else:
                lot.expiration_status = "valid"

