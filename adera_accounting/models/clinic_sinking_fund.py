# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class ClinicSinkingFundAllocation(models.Model):
    _name = "clinic.sinking.fund.allocation"
    _description = "Alokasi Cadangan Sinking Fund & Pemeliharaan Sarpras Alkes (10%)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Nomor Alokasi",
        required=True,
        copy=False,
        default="/",
        tracking=True,
    )
    date = fields.Date(
        string="Tanggal Tutup Buku",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
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
        string="Klinik / Perusahaan",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        string="Mata Uang",
    )

    net_profit = fields.Monetary(
        string="Laba Bersih Terbuka (ACC-HD & ACC-PRATAMA)",
        currency_field="currency_id",
        compute="_compute_net_profit",
        inverse="_inverse_net_profit",
        store=True,
        tracking=True,
    )
    reserve_rate = fields.Float(
        string="Tarif Cadangan (%)",
        default=10.0,
        digits=(5, 2),
        tracking=True,
        help="Batas maksimal alokasi cadangan Sinking Fund adalah 10.0%.",
    )
    reserve_amount = fields.Monetary(
        string="Nominal Alokasi Sinking Fund (320020)",
        currency_field="currency_id",
        compute="_compute_reserve_amount",
        store=True,
        tracking=True,
    )

    transfer_liquidity = fields.Boolean(
        string="Transfer Likuiditas ke Rekening Cadangan",
        default=False,
        tracking=True,
    )
    source_bank_journal_id = fields.Many2one(
        "account.journal",
        string="Rekening Asal (Operasional BRI 569)",
        domain="[('type', '=', 'bank')]",
        default=lambda self: self._default_source_bank(),
    )
    target_reserve_bank_id = fields.Many2one(
        "account.journal",
        string="Rekening Tujuan Cadangan (BPD DIY / BRI 300)",
        domain="[('type', '=', 'bank')]",
        default=lambda self: self._default_target_bank(),
    )

    move_id = fields.Many2one("account.move", string="Jurnal Alokasi Ekuitas (320010->320020)", readonly=True, copy=False)
    liquidity_move_id = fields.Many2one("account.move", string="Jurnal Transfer Rekening Cadangan", readonly=True, copy=False)

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("posted", "Terjurnal"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )

    def _default_source_bank(self):
        return self.env["account.journal"].search([("code", "in", ["BR569", "BBCA"])], limit=1)

    def _default_target_bank(self):
        return self.env["account.journal"].search([("code", "in", ["BPDIY", "BR300"])], limit=1)

    @api.depends("date_from", "date_to")
    def _compute_net_profit(self):
        MoveLine = self.env["account.move.line"]
        for rec in self:
            if not rec.date_from or not rec.date_to:
                rec.net_profit = 0.0
                continue
            lines = MoveLine.search([
                ("parent_state", "=", "posted"),
                ("date", ">=", rec.date_from),
                ("date", "<=", rec.date_to),
                ("account_id.account_type", "in", [
                    "income", "income_other",
                    "expense", "expense_direct_cost", "expense_depreciation",
                ]),
            ])
            rev = sum(-l.balance for l in lines if l.account_id.account_type in ("income", "income_other"))
            exp = sum(l.balance for l in lines if l.account_id.account_type in ("expense", "expense_direct_cost", "expense_depreciation"))
            rec.net_profit = max(0.0, round(rev - exp, 2))

    def _inverse_net_profit(self):
        pass

    @api.depends("net_profit", "reserve_rate")
    def _compute_reserve_amount(self):
        for rec in self:
            rate = min(rec.reserve_rate or 0.0, 10.0)
            rec.reserve_amount = max(0.0, round((rec.net_profit or 0.0) * (rate / 100.0), 2))

    @api.constrains("reserve_rate")
    def _check_reserve_rate(self):
        for rec in self:
            if rec.reserve_rate < 0 or rec.reserve_rate > 10.0:
                raise ValidationError(_("Persentase Sinking Fund tidak boleh melebihi batas statuta 10.0%!"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("clinic.sinking.fund.allocation") or "/"
        return super().create(vals_list)

    def action_post_allocation(self):
        """Post Month-End Reserve Allocation: Dr. 320010 (Retained Earnings) / Cr. 320020 (Sinking Fund)."""
        Account = self.env["account.account"]
        Move = self.env["account.move"]

        acc_320010 = Account.search([("code", "=", "320010")], limit=1)
        acc_320020 = Account.search([("code", "=", "320020")], limit=1)
        misc_j = self.env["account.journal"].search([("code", "in", ["MISCL", "MISC"])], limit=1) or self.env["account.journal"].search([("type", "=", "general")], limit=1)

        if not acc_320010 or not acc_320020:
            raise UserError(_("Akun Laba Ditahan (320010) atau Cadangan Sinking Fund (320020) tidak ditemukan!"))

        for rec in self:
            if rec.state == "posted":
                raise UserError(_("Alokasi Sinking Fund sudah pernah diposting."))
            if rec.reserve_amount <= 0:
                raise ValidationError(_("Nominal alokasi Sinking Fund harus lebih besar dari Rp 0."))

            move = Move.create({
                "journal_id": misc_j.id,
                "date": rec.date,
                "ref": f"Alokasi Sinking Fund {rec.reserve_rate:.1f}%: {rec.name}",
                "move_type": "entry",
                "line_ids": [
                    (0, 0, {
                        "name": f"Penyisihan Laba Ditahan ke Sinking Fund ({rec.name})",
                        "account_id": acc_320010.id,
                        "debit": rec.reserve_amount,
                        "credit": 0.0,
                    }),
                    (0, 0, {
                        "name": f"Cadangan Sinking Fund & Pemeliharaan Sarpras ({rec.name})",
                        "account_id": acc_320020.id,
                        "debit": 0.0,
                        "credit": rec.reserve_amount,
                    }),
                ],
            })
            move.action_post()
            rec.move_id = move.id

            if rec.transfer_liquidity and rec.source_bank_journal_id and rec.target_reserve_bank_id:
                src_acc = rec.source_bank_journal_id.default_account_id
                dst_acc = rec.target_reserve_bank_id.default_account_id
                if src_acc and dst_acc:
                    liq_move = Move.create({
                        "journal_id": rec.target_reserve_bank_id.id,
                        "date": rec.date,
                        "ref": f"Transfer Likuiditas Sinking Fund: {rec.name}",
                        "move_type": "entry",
                        "line_ids": [
                            (0, 0, {
                                "name": f"Dana Masuk Rekening Cadangan ({rec.name})",
                                "account_id": dst_acc.id,
                                "debit": rec.reserve_amount,
                                "credit": 0.0,
                            }),
                            (0, 0, {
                                "name": f"Transfer Keluar Operasional ke Cadangan ({rec.name})",
                                "account_id": src_acc.id,
                                "debit": 0.0,
                                "credit": rec.reserve_amount,
                            }),
                        ],
                    })
                    liq_move.action_post()
                    rec.liquidity_move_id = liq_move.id

            rec.write({"state": "posted"})
            rec.message_post(
                body=_("Alokasi Sinking Fund Rp %s (%.1f%%) diposting ke 320020 (%s).") % (
                    f"{rec.reserve_amount:,.2f}", rec.reserve_rate, move.name
                ),
                subtype_xmlid="mail.mt_note",
            )
        return True

