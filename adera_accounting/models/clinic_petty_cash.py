# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


IMPREST_PETTY_CASH_CEILING = 2000000.0


class ClinicPettyCashReplenishment(models.Model):
    _name = "clinic.petty.cash.replenishment"
    _description = "Pengisian Kembali Kas Kecil Imprest (Plafon Rp 2.000.000)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Nomor Pengisian Kas Kecil",
        required=True,
        copy=False,
        default="/",
        tracking=True,
    )
    date = fields.Date(
        string="Tanggal Pengajuan",
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

    petty_cash_journal_id = fields.Many2one(
        "account.journal",
        string="Jurnal Kas Kecil",
        domain="[('type', '=', 'cash')]",
        required=True,
        default=lambda self: self._default_petty_cash_journal(),
        tracking=True,
    )
    funding_journal_id = fields.Many2one(
        "account.journal",
        string="Sumber Dana (Bank BRI / Kas Besar)",
        domain="[('type', 'in', ('bank', 'cash'))]",
        required=True,
        default=lambda self: self._default_funding_journal(),
        tracking=True,
    )

    imprest_ceiling = fields.Monetary(
        string="Plafon Imprest Maksimal",
        currency_field="currency_id",
        default=IMPREST_PETTY_CASH_CEILING,
        readonly=True,
    )
    current_balance = fields.Monetary(
        string="Saldo Kas Kecil Saat Ini (GL)",
        currency_field="currency_id",
        compute="_compute_petty_cash_metrics",
        store=True,
    )
    requested_amount = fields.Monetary(
        string="Nominal Pengisian Diajukan",
        currency_field="currency_id",
        required=True,
        tracking=True,
    )
    director_override = fields.Boolean(
        string="Override Plafon Direksi",
        default=False,
        tracking=True,
        help="Hanya Direktur Klinik yang dapat mengizinkan pengisian melebihi plafon imprest Rp 2.000.000.",
    )
    notes = fields.Text(string="Rincian Voucher Pengeluaran Kas Kecil")

    requested_by_id = fields.Many2one(
        "res.users",
        string="Diajukan Oleh",
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )
    approved_by_id = fields.Many2one(
        "res.users",
        string="Disetujui Oleh (Direktur)",
        readonly=True,
        tracking=True,
    )
    move_id = fields.Many2one(
        "account.move",
        string="Jurnal Pencairan Kas Kecil",
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

    def _default_petty_cash_journal(self):
        j = self.env["account.journal"].search([("code", "=", "KKCIL")], limit=1)
        if not j:
            j = self.env["account.journal"].search([("type", "=", "cash")], limit=1)
        return j

    def _default_funding_journal(self):
        j = self.env["account.journal"].search([("code", "in", ["BR569", "KKSR", "BBCA"])], limit=1)
        if not j:
            j = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        return j

    @api.depends("petty_cash_journal_id")
    def _compute_petty_cash_metrics(self):
        for rec in self:
            acc = rec.petty_cash_journal_id.default_account_id
            if not acc:
                acc = self.env["account.account"].search([("code", "=", "111020")], limit=1)
            if acc:
                lines = self.env["account.move.line"].search([
                    ("account_id", "=", acc.id),
                    ("parent_state", "=", "posted"),
                ])
                rec.current_balance = sum(lines.mapped("balance"))
            else:
                rec.current_balance = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("clinic.petty.cash.replenishment") or "/"
        return super().create(vals_list)

    def _validate_ceiling(self):
        for rec in self:
            if rec.requested_amount <= 0:
                raise ValidationError(_("Nominal pengisian Kas Kecil harus lebih besar dari Rp 0."))
            if rec.requested_amount > rec.imprest_ceiling and not rec.director_override:
                raise ValidationError(_(
                    "Permintaan pengisian Kas Kecil (Rp %s) melebihi plafon imprest maksimal Rp %s! "
                    "Aktifkan 'Override Plafon Direksi' jika telah disetujui Direktur."
                ) % (f"{rec.requested_amount:,.2f}", f"{rec.imprest_ceiling:,.2f}"))

    def action_request_replenishment(self):
        """Ajukan Pengisian Kas Kecil & validasi plafon Rp 2.000.000."""
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Hanya pengajuan berstatus Draft yang dapat dikonfirmasi."))
            rec._validate_ceiling()
            rec.write({"state": "confirmed"})
            rec.message_post(
                body=_("Pengisian Kas Kecil Rp %s diajukan untuk persetujuan Direktur.") % f"{rec.requested_amount:,.2f}",
                subtype_xmlid="mail.mt_note",
            )
        return True

    def action_disburse_tranche(self):
        """Cairkan Kas Kecil: Dr. 111020 (Kas Kecil) / Cr. 111120 (Bank BRI) atau 111010 (Kas Besar)."""
        for rec in self:
            if rec.state == "draft":
                rec.action_request_replenishment()
            if rec.state != "confirmed":
                raise UserError(_("Pengajuan harus berstatus Terkonfirmasi sebelum dicairkan."))
            rec._validate_ceiling()
            if rec.move_id:
                raise UserError(_("Jurnal pencairan Kas Kecil sudah pernah diposting."))

            petty_acc = rec.petty_cash_journal_id.default_account_id
            if not petty_acc:
                petty_acc = self.env["account.account"].search([("code", "=", "111020")], limit=1)

            fund_acc = rec.funding_journal_id.default_account_id
            if not fund_acc:
                fund_acc = self.env["account.account"].search([("code", "in", ["111120", "111010"])], limit=1)

            if not petty_acc or not fund_acc:
                raise UserError(_("Akun Kas Kecil (111020) atau Sumber Dana belum terkonfigurasi!"))

            label = f"Pengisian Imprest Kas Kecil - {rec.name} ({rec.date.strftime('%Y-%m-%d')})"
            move = self.env["account.move"].create({
                "journal_id": rec.funding_journal_id.id,
                "date": rec.date,
                "ref": label,
                "move_type": "entry",
                "line_ids": [
                    (0, 0, {
                        "name": label,
                        "account_id": petty_acc.id,
                        "debit": rec.requested_amount,
                        "credit": 0.0,
                    }),
                    (0, 0, {
                        "name": label,
                        "account_id": fund_acc.id,
                        "debit": 0.0,
                        "credit": rec.requested_amount,
                    }),
                ],
            })
            move.action_post()

            rec.write({
                "move_id": move.id,
                "approved_by_id": self.env.user.id,
                "state": "posted",
            })
            rec.message_post(
                body=_("Pencairan Kas Kecil selesai. Jurnal GL: %s (Dr. %s / Cr. %s)") % (
                    move.name, petty_acc.code, fund_acc.code
                ),
                subtype_xmlid="mail.mt_note",
            )
        return True

    def action_approve(self):
        return self.action_disburse_tranche()

    def action_reject(self, reason=None):
        for rec in self:
            if rec.state == "posted":
                raise UserError(_("Pengajuan yang sudah terjurnal tidak dapat ditolak."))
            rec.write({"state": "draft"})
            if reason:
                rec.message_post(body=_("Pengajuan ditolak: %s") % reason, subtype_xmlid="mail.mt_note")
        return True
