# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class ClinicPaymentGatewayReconcile(models.Model):
    _name = "clinic.pg.settlement.reconcile"
    _description = "Rekonsiliasi Settlement Payment Gateway (GoPay / QRIS) & Beban MDR"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Referensi Settlement",
        required=True,
        copy=False,
        default="/",
        tracking=True,
    )
    date = fields.Date(
        string="Tanggal Settlement Bank",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
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

    pg_journal_id = fields.Many2one(
        "account.journal",
        string="Jurnal Clearing Payment Gateway",
        domain="[('type', '=', 'bank')]",
        required=True,
        default=lambda self: self._default_pg_journal(),
        tracking=True,
    )
    bank_journal_id = fields.Many2one(
        "account.journal",
        string="Bank Penerima Dana Net",
        domain="[('type', '=', 'bank')]",
        required=True,
        default=lambda self: self._default_bank_journal(),
        tracking=True,
    )

    gross_amount = fields.Monetary(
        string="Total Bruto Settlement (Gross)",
        currency_field="currency_id",
        required=True,
        tracking=True,
    )
    mdr_rate = fields.Float(
        string="Tarif MDR (%)",
        default=0.7,
        digits=(5, 2),
        tracking=True,
    )
    use_manual_mdr = fields.Boolean(
        string="Input Nominal MDR Manual",
        default=False,
    )
    mdr_amount = fields.Monetary(
        string="Potongan Biaya MDR (610090)",
        currency_field="currency_id",
        compute="_compute_settlement_amounts",
        inverse="_inverse_mdr_amount",
        store=True,
        tracking=True,
    )
    net_bank_amount = fields.Monetary(
        string="Dana Net Masuk Bank",
        currency_field="currency_id",
        compute="_compute_settlement_amounts",
        store=True,
        tracking=True,
    )
    move_id = fields.Many2one(
        "account.move",
        string="Jurnal Rekonsiliasi MDR",
        readonly=True,
        copy=False,
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Terkonfirmasi"),
            ("posted", "Terjurnal"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )

    def _default_pg_journal(self):
        j = self.env["account.journal"].search([("code", "in", ["GOPAY", "QRIS", "PGATE"])], limit=1)
        if not j:
            j = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        return j

    def _default_bank_journal(self):
        j = self.env["account.journal"].search([("code", "in", ["BR569", "BMDRI", "BBCA"])], limit=1)
        if not j:
            j = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        return j

    @api.depends("gross_amount", "mdr_rate", "use_manual_mdr")
    def _compute_settlement_amounts(self):
        for rec in self:
            gross = rec.gross_amount or 0.0
            if not rec.use_manual_mdr:
                rec.mdr_amount = round(gross * ((rec.mdr_rate or 0.0) / 100.0), 2)
            rec.net_bank_amount = round(gross - (rec.mdr_amount or 0.0), 2)

    def _inverse_mdr_amount(self):
        for rec in self:
            rec.use_manual_mdr = True
            rec.net_bank_amount = round((rec.gross_amount or 0.0) - (rec.mdr_amount or 0.0), 2)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("clinic.pg.settlement.reconcile") or "/"
        return super().create(vals_list)

    def action_confirm(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Hanya rekonsiliasi Draft yang dapat dikonfirmasi."))
            if rec.gross_amount <= 0:
                raise ValidationError(_("Total bruto settlement harus lebih besar dari Rp 0."))
            if rec.mdr_amount < 0 or rec.mdr_amount >= rec.gross_amount:
                raise ValidationError(_("Potongan MDR tidak valid terhadap nilai bruto settlement."))
            rec.write({"state": "confirmed"})
        return True

    def action_reconcile_pg_settlement(self):
        """Eksekusi rekonsiliasi otomatis GoPay/QRIS:
        Dr. Bank Net (111120/111130) + Dr. Beban MDR (610090) / Cr. Clearing PG (111220).
        """
        for rec in self:
            if rec.state == "draft":
                rec.action_confirm()
            if rec.move_id:
                raise UserError(_("Jurnal rekonsiliasi sudah pernah diterbitkan."))

            clearing_acc = rec.pg_journal_id.default_account_id
            if not clearing_acc or clearing_acc.code != "111220":
                acc_111220 = self.env["account.account"].search([("code", "=", "111220")], limit=1)
                if acc_111220:
                    clearing_acc = acc_111220

            bank_acc = rec.bank_journal_id.default_account_id
            if not bank_acc:
                bank_acc = self.env["account.account"].search([("code", "in", ["111120", "111130"])], limit=1)

            mdr_acc = self.env["account.account"].search([("code", "=", "610090")], limit=1)

            if not clearing_acc or not bank_acc or not mdr_acc:
                raise UserError(_("Akun Clearing PG (111220), Akun Bank, atau Beban MDR (610090) belum terkonfigurasi!"))

            net_amt = round(rec.gross_amount - rec.mdr_amount, 2)
            label = f"Settlement PG GoPay/QRIS - {rec.name} ({rec.date.strftime('%Y-%m-%d')})"

            move_lines = [
                (0, 0, {
                    "name": f"{label} (Net Bank Inflow)",
                    "account_id": bank_acc.id,
                    "debit": net_amt,
                    "credit": 0.0,
                }),
                (0, 0, {
                    "name": f"{label} (Gross Clearing)",
                    "account_id": clearing_acc.id,
                    "debit": 0.0,
                    "credit": rec.gross_amount,
                }),
            ]
            if rec.mdr_amount > 0:
                move_lines.append((0, 0, {
                    "name": f"Beban MDR Payment Gateway ({rec.mdr_rate:.2f}%)",
                    "account_id": mdr_acc.id,
                    "debit": rec.mdr_amount,
                    "credit": 0.0,
                }))

            move = self.env["account.move"].create({
                "journal_id": rec.bank_journal_id.id,
                "date": rec.date,
                "ref": label,
                "move_type": "entry",
                "line_ids": move_lines,
            })
            move.action_post()

            rec.write({
                "move_id": move.id,
                "state": "posted",
            })
            rec.message_post(
                body=_("Rekonsiliasi PG selesai (%s): Net Bank Rp %s, MDR (610090) Rp %s.") % (
                    move.name, f"{net_amt:,.2f}", f"{rec.mdr_amount:,.2f}"
                ),
                subtype_xmlid="mail.mt_note",
            )
        return True

