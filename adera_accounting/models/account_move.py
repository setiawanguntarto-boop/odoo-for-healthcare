# -*- coding: utf-8 -*-
from odoo import fields, models, api


class AccountMove(models.Model):
    _inherit = "account.move"

    clinic_unit = fields.Selection(
        [
            ("pratama", "Klinik Pratama (Outpatient)"),
            ("hd", "Klinik Utama Hemodialisis (HD)"),
        ],
        string="Unit Bisnis Klinik",
        help="Pemisahan unit bisnis untuk pelaporan analitik laba rugi PSAK",
    )
    is_bpjs_claim = fields.Boolean(
        string="Klaim BPJS",
        compute="_compute_is_bpjs_claim",
        store=True,
    )

    @api.depends("line_ids.account_id")
    def _compute_is_bpjs_claim(self):
        for move in self:
            move.is_bpjs_claim = any(
                line.account_id.code and line.account_id.code.startswith("112020")
                for line in move.line_ids
            )

