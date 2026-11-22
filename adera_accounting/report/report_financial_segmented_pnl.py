# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ClinicSegmentedPnlReport(models.TransientModel):
    _name = "clinic.segmented.pnl.report"
    _description = "Laporan Laba Rugi Tersegmentasi Multi-Unit (PSAK / SAK EMKM)"

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
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
        required=True,
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")

    pratama_net_profit = fields.Monetary(string="Laba Bersih ACC-PRATAMA", currency_field="currency_id", compute="_compute_segmented_pnl")
    hd_net_profit = fields.Monetary(string="Laba Bersih ACC-HD", currency_field="currency_id", compute="_compute_segmented_pnl")
    holding_net_profit = fields.Monetary(string="Laba/(Beban) Bersih ACC-HOLDING", currency_field="currency_id", compute="_compute_segmented_pnl")
    consolidated_net_profit = fields.Monetary(string="Laba Bersih Konsolidasi", currency_field="currency_id", compute="_compute_segmented_pnl")
    inter_entity_elimination_net = fields.Monetary(string="Saldo Eliminasi Antar-Entitas (112040/214040)", currency_field="currency_id", compute="_compute_segmented_pnl")

    @api.depends("date_from", "date_to")
    def _compute_segmented_pnl(self):
        for rec in self:
            data = rec.get_segmented_pnl_data(rec.date_from, rec.date_to)
            rec.pratama_net_profit = data["ACC-PRATAMA"]["net_profit"]
            rec.hd_net_profit = data["ACC-HD"]["net_profit"]
            rec.holding_net_profit = data["ACC-HOLDING"]["net_profit"]
            rec.consolidated_net_profit = data["CONSOLIDATED"]["net_profit"]
            rec.inter_entity_elimination_net = data["inter_entity_net"]

    @api.model
    def get_segmented_pnl_data(self, date_from, date_to):
        Analytic = self.env["account.analytic.account"]
        MoveLine = self.env["account.move.line"]

        prat_ids = set(Analytic.search(["|", ("code", "=", "ACC-PRATAMA"), ("code", "=like", "PRAT-%")]).ids)
        hd_ids = set(Analytic.search(["|", ("code", "=", "ACC-HD"), ("code", "=like", "HD-%")]).ids)
        hold_ids = set(Analytic.search([("code", "=", "ACC-HOLDING")]).ids)

        pnl_types = ("income", "income_other", "expense", "expense_direct_cost", "expense_depreciation")
        lines = MoveLine.search([
            ("parent_state", "=", "posted"),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
            ("account_id.account_type", "in", pnl_types),
        ])

        segments = {
            "ACC-PRATAMA": {"revenue": 0.0, "expense": 0.0, "net_profit": 0.0},
            "ACC-HD": {"revenue": 0.0, "expense": 0.0, "net_profit": 0.0},
            "ACC-HOLDING": {"revenue": 0.0, "expense": 0.0, "net_profit": 0.0},
            "UNSEGMENTED": {"revenue": 0.0, "expense": 0.0, "net_profit": 0.0},
        }

        for l in lines:
            dist = l.analytic_distribution or {}
            dist_ids = {int(k) for k in dist.keys() if str(k).isdigit()}
            is_rev = l.account_id.account_type in ("income", "income_other")
            val = (-l.balance) if is_rev else l.balance
            bucket = "revenue" if is_rev else "expense"

            if dist_ids & prat_ids:
                segments["ACC-PRATAMA"][bucket] += val
            elif dist_ids & hd_ids:
                segments["ACC-HD"][bucket] += val
            elif dist_ids & hold_ids:
                segments["ACC-HOLDING"][bucket] += val
            else:
                segments["UNSEGMENTED"][bucket] += val

        for key, vals in segments.items():
            vals["net_profit"] = round(vals["revenue"] - vals["expense"], 2)

        # Inter-entity elimination check (112040 / 214040)
        inter_lines = MoveLine.search([
            ("parent_state", "=", "posted"),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
            ("account_id.code", "in", ["112040", "214040"]),
        ])
        inter_entity_net = round(sum(inter_lines.mapped("balance")), 2)

        consolidated_rev = sum(segments[k]["revenue"] for k in ("ACC-PRATAMA", "ACC-HD", "ACC-HOLDING", "UNSEGMENTED"))
        consolidated_exp = sum(segments[k]["expense"] for k in ("ACC-PRATAMA", "ACC-HD", "ACC-HOLDING", "UNSEGMENTED"))

        return {
            "ACC-PRATAMA": segments["ACC-PRATAMA"],
            "ACC-HD": segments["ACC-HD"],
            "ACC-HOLDING": segments["ACC-HOLDING"],
            "UNSEGMENTED": segments["UNSEGMENTED"],
            "CONSOLIDATED": {
                "revenue": round(consolidated_rev, 2),
                "expense": round(consolidated_exp, 2),
                "net_profit": round(consolidated_rev - consolidated_exp, 2),
            },
            "inter_entity_net": inter_entity_net,
        }
