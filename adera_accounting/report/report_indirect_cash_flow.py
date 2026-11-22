# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ClinicIndirectCashFlowReport(models.TransientModel):
    _name = "clinic.indirect.cash.flow.report"
    _description = "Laporan Arus Kas Metode Tidak Langsung (Indirect Cash Flow PSAK 2)"

    date_from = fields.Date(
        string="Periode Awal",
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
    )
    date_to = fields.Date(
        string="Periode Akhir",
        required=True,
        default=fields.Date.context_today,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")

    net_operating_income = fields.Monetary(string="Laba/(Rugi) Bersih Operasional", currency_field="currency_id", compute="_compute_cash_flow")
    depreciation_addback = fields.Monetary(string="(+) Penyusutan & Amortisasi (510030/510031)", currency_field="currency_id", compute="_compute_cash_flow")
    impairment_addback = fields.Monetary(string="(+) Cadangan Penurunan Nilai Piutang (112990)", currency_field="currency_id", compute="_compute_cash_flow")
    delta_receivables = fields.Monetary(string="Perubahan Piutang Usaha (112010/112020)", currency_field="currency_id", compute="_compute_cash_flow")
    delta_inventory = fields.Monetary(string="Perubahan Persediaan Medis (113010)", currency_field="currency_id", compute="_compute_cash_flow")
    delta_payables_and_fees = fields.Monetary(string="Perubahan Utang Usaha & Jasa Medis (211010/2130xx)", currency_field="currency_id", compute="_compute_cash_flow")
    net_operating_cash_flow = fields.Monetary(string="Arus Kas Bersih Aktivitas Operasi", currency_field="currency_id", compute="_compute_cash_flow")
    net_investing_cash_flow = fields.Monetary(string="Arus Kas Bersih Aktivitas Investasi (Capex)", currency_field="currency_id", compute="_compute_cash_flow")
    net_financing_cash_flow = fields.Monetary(string="Arus Kas Bersih Aktivitas Pendanaan (221010/310020/320020)", currency_field="currency_id", compute="_compute_cash_flow")

    @api.depends("date_from", "date_to")
    def _compute_cash_flow(self):
        MoveLine = self.env["account.move.line"]
        for rec in self:
            lines = MoveLine.search([
                ("parent_state", "=", "posted"),
                ("date", ">=", rec.date_from),
                ("date", "<=", rec.date_to),
            ])

            rev = sum(-l.balance for l in lines if l.account_id.account_type in ("income", "income_other"))
            exp = sum(l.balance for l in lines if l.account_id.account_type in ("expense", "expense_direct_cost", "expense_depreciation"))
            net_inc = round(rev - exp, 2)

            dep_add = round(sum(l.balance for l in lines if (l.account_id.code or "").startswith("51003") or l.account_id.account_type == "expense_depreciation"), 2)
            imp_add = round(sum(-l.balance for l in lines if l.account_id.code == "112990"), 2)

            # Working capital deltas: increase in asset = cash outflow (-), increase in liability = cash inflow (+)
            d_ar = round(-sum(l.balance for l in lines if l.account_id.code in ("112010", "112020")), 2)
            d_inv = round(-sum(l.balance for l in lines if (l.account_id.code or "").startswith("1130") or (l.account_id.code or "").startswith("1140")), 2)
            d_ap = round(-sum(l.balance for l in lines if (l.account_id.code or "") in ("211010", "213010", "213020", "213011", "213012")), 2)

            cfo = round(net_inc + dep_add + imp_add + d_ar + d_inv + d_ap, 2)
            cfi = round(-sum(l.balance for l in lines if (l.account_id.code or "").startswith("1210")), 2)
            cff = round(-sum(l.balance for l in lines if l.account_id.code in ("221010", "310010", "310020")), 2)

            rec.net_operating_income = net_inc
            rec.depreciation_addback = dep_add
            rec.impairment_addback = imp_add
            rec.delta_receivables = d_ar
            rec.delta_inventory = d_inv
            rec.delta_payables_and_fees = d_ap
            rec.net_operating_cash_flow = cfo
            rec.net_investing_cash_flow = cfi
            rec.net_financing_cash_flow = cff

