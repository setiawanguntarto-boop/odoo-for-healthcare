# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ClinicCashDeposit(models.Model):
    _name = "clinic.cash.deposit"
    _description = "Setoran Tunai Kas Besar ke Bank (Cash Vault Deposit)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Nomor Setoran",
        required=True,
        copy=False,
        default="/",
        tracking=True,
    )
    date = fields.Date(
        string="Tanggal Setor Bank",
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

    source_journal_id = fields.Many2one(
        "account.journal",
        string="Jurnal Sumber (Kas Besar)",
        domain="[('type', '=', 'cash')]",
        required=True,
        default=lambda self: self._default_source_journal(),
        tracking=True,
    )
    destination_bank_id = fields.Many2one(
        "account.journal",
        string="Bank Tujuan Setoran",
        domain="[('type', '=', 'bank')]",
        required=True,
        default=lambda self: self._default_destination_bank(),
        tracking=True,
    )
    amount = fields.Monetary(
        string="Nominal Setoran Tunai",
        currency_field="currency_id",
        required=True,
        tracking=True,
    )
    bank_deposit_slip = fields.Binary(
        string="Slip Setoran Bank (Scan)",
        attachment=True,
    )
    bank_deposit_slip_filename = fields.Char(string="Nama File Slip")

    prepared_by_id = fields.Many2one(
        "res.users",
        string="Diserahkan Oleh",
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )
    confirmed_by_id = fields.Many2one(
        "res.users",
        string="Dikonfirmasi Oleh",
        readonly=True,
        tracking=True,
    )
    move_id = fields.Many2one(
        "account.move",
        string="Jurnal Setoran Bank",
        readonly=True,
        copy=False,
        tracking=True,
    )
    notes = fields.Text(string="Catatan / Referensi Shift Kasir")

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

    def _default_source_journal(self):
        j = self.env["account.journal"].search([("code", "=", "KKSR")], limit=1)
        if not j:
            j = self.env["account.journal"].search([("type", "=", "cash")], limit=1)
        return j

    def _default_destination_bank(self):
        j = self.env["account.journal"].search([("code", "in", ["BR569", "BMDRI", "BSI78", "BBCA"])], limit=1)
        if not j:
            j = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        return j

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("clinic.cash.deposit") or "/"
        return super().create(vals_list)

    def action_confirm(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Hanya dokumen Draft yang dapat dikonfirmasi."))
            if rec.amount <= 0:
                raise UserError(_("Nominal setoran tunai harus lebih besar dari Rp 0."))
            rec.write({
                "state": "confirmed",
                "confirmed_by_id": self.env.user.id,
            })
            rec.message_post(
                body=_("Setoran tunai sebesar %s dikonfirmasi oleh %s.") % (
                    f"Rp {rec.amount:,.2f}", self.env.user.name
                ),
                subtype_xmlid="mail.mt_note",
            )
        return True

    def action_post(self):
        for rec in self:
            if rec.state == "draft":
                rec.action_confirm()
            if rec.state != "confirmed":
                raise UserError(_("Setoran harus berstatus Terkonfirmasi sebelum dijurnal."))
            if rec.move_id:
                raise UserError(_("Jurnal setoran sudah pernah diposting."))

            source_acc = rec.source_journal_id.default_account_id
            if not source_acc:
                source_acc = self.env["account.account"].search([("code", "=", "111010")], limit=1)

            dest_acc = rec.destination_bank_id.default_account_id
            if not dest_acc:
                dest_acc = self.env["account.account"].search([("code", "in", ["111120", "111130"])], limit=1)

            if not source_acc or not dest_acc:
                raise UserError(_("Akun Kas Besar (111010) atau Akun Bank Tujuan belum terkonfigurasi!"))

            label = f"Setoran Tunai Kas Harian - {rec.date.strftime('%Y-%m-%d')}"
            move = self.env["account.move"].create({
                "journal_id": rec.destination_bank_id.id,
                "date": rec.date,
                "ref": f"{rec.name} | {label}",
                "move_type": "entry",
                "line_ids": [
                    (0, 0, {
                        "name": label,
                        "account_id": dest_acc.id,
                        "debit": rec.amount,
                        "credit": 0.0,
                    }),
                    (0, 0, {
                        "name": label,
                        "account_id": source_acc.id,
                        "debit": 0.0,
                        "credit": rec.amount,
                    }),
                ],
            })
            move.action_post()

            rec.write({
                "move_id": move.id,
                "state": "posted",
            })
            rec.message_post(
                body=_("Setoran tunai terjurnal ke GL: %s (Dr. %s / Cr. %s)") % (
                    move.name, dest_acc.code, source_acc.code
                ),
                subtype_xmlid="mail.mt_note",
            )
        return True

    def action_reset_draft(self):
        for rec in self:
            if rec.state == "posted" or rec.move_id:
                raise UserError(_("Setoran yang sudah terjurnal tidak dapat dikembalikan ke Draft."))
            rec.write({"state": "draft"})
        return True

