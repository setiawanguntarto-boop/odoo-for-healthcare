# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class ClinicBpjsReconciliationBatch(models.Model):
    _name = "clinic.bpjs.reconciliation.batch"
    _description = "Rekonsiliasi Klaim BPJS Kesehatan (FPK / VClaim)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "claim_period_end desc, id desc"

    name = fields.Char(
        string="Nomor Batch FPK",
        required=True,
        copy=False,
        default="/",
        tracking=True,
    )
    claim_period_start = fields.Date(
        string="Periode Layanan Awal",
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
        tracking=True,
    )
    claim_period_end = fields.Date(
        string="Periode Layanan Akhir",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    service_unit = fields.Selection(
        [
            ("pratama", "Klinik Pratama Rawat Jalan (ACC-PRATAMA)"),
            ("hemodialysis", "Klinik Utama Hemodialisis (ACC-HD)"),
        ],
        string="Unit Pelayanan",
        required=True,
        default="hemodialysis",
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
    bank_journal_id = fields.Many2one(
        "account.journal",
        string="Bank Penerima Pencairan (Mandiri / BRI)",
        domain="[('type', '=', 'bank')]",
        required=True,
        default=lambda self: self._default_bank_journal(),
        tracking=True,
    )

    dispute_line_ids = fields.One2many(
        "clinic.bpjs.reconciliation.line",
        "batch_id",
        string="Rincian SEP & Klaim FPK",
    )

    total_claimed_amount = fields.Monetary(
        string="Total Diajukan (SEP)",
        currency_field="currency_id",
        compute="_compute_totals",
        inverse="_inverse_totals",
        store=True,
        tracking=True,
    )
    total_approved_amount = fields.Monetary(
        string="Total Disetujui Cair (FPK)",
        currency_field="currency_id",
        compute="_compute_totals",
        inverse="_inverse_totals",
        store=True,
        tracking=True,
    )
    total_disputed_amount = fields.Monetary(
        string="Total Pending / Dispute",
        currency_field="currency_id",
        compute="_compute_totals",
        inverse="_inverse_totals",
        store=True,
        tracking=True,
    )
    total_rejected_amount = fields.Monetary(
        string="Total Ditolak (Write-Off)",
        currency_field="currency_id",
        compute="_compute_totals",
        inverse="_inverse_totals",
        store=True,
        tracking=True,
    )

    settlement_move_id = fields.Many2one(
        "account.move",
        string="Jurnal Pencairan Bank BPJS",
        readonly=True,
        copy=False,
    )
    writeoff_move_id = fields.Many2one(
        "account.move",
        string="Jurnal Write-Off Penolakan Klaim",
        readonly=True,
        copy=False,
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("verified", "Terverifikasi"),
            ("reconciled", "Terekonsiliasi"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )

    def _default_bank_journal(self):
        j = self.env["account.journal"].search([("code", "in", ["BMDRI", "BR569", "BBCA"])], limit=1)
        if not j:
            j = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        return j

    @api.depends(
        "dispute_line_ids.claimed_amount",
        "dispute_line_ids.approved_amount",
        "dispute_line_ids.disputed_amount",
        "dispute_line_ids.rejected_amount",
    )
    def _compute_totals(self):
        for rec in self:
            if rec.dispute_line_ids:
                rec.total_claimed_amount = sum(rec.dispute_line_ids.mapped("claimed_amount"))
                rec.total_approved_amount = sum(rec.dispute_line_ids.mapped("approved_amount"))
                rec.total_disputed_amount = sum(rec.dispute_line_ids.mapped("disputed_amount"))
                rec.total_rejected_amount = sum(rec.dispute_line_ids.mapped("rejected_amount"))

    def _inverse_totals(self):
        pass

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("clinic.bpjs.reconciliation.batch") or "/"
        return super().create(vals_list)

    def action_verify(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Hanya batch Draft yang dapat diverifikasi."))
            if rec.total_claimed_amount <= 0:
                raise ValidationError(_("Total klaim diajukan harus lebih besar dari Rp 0."))
            rec.write({"state": "verified"})
        return True

    def action_reconcile(self):
        """Eksekusi rekonsiliasi FPK BPJS:
        1. Dr. Bank Penerima (111130/111120) / Cr. 112020 untuk total_approved_amount.
        2. Klaim dispute_pending tetap tinggal di 112020.
        3. Dr. 112990 (Cadangan Dispute) / Cr. 112020 untuk total_rejected_amount.
        """
        Account = self.env["account.account"]
        Move = self.env["account.move"]

        acc_112020 = Account.search([("code", "=", "112020")], limit=1)
        acc_112990 = Account.search([("code", "=", "112990")], limit=1) or Account.search([("code", "=", "619990")], limit=1)
        misc_j = self.env["account.journal"].search([("code", "in", ["JBPJS", "MISCL", "MISC"])], limit=1) or self.env["account.journal"].search([("type", "=", "general")], limit=1)

        if not acc_112020:
            raise UserError(_("Akun Piutang Klaim BPJS (112020) tidak ditemukan!"))

        for rec in self:
            if rec.state == "draft":
                rec.action_verify()
            if rec.state != "verified":
                raise UserError(_("Batch harus berstatus Terverifikasi sebelum direkonsiliasi."))

            bank_acc = rec.bank_journal_id.default_account_id
            if not bank_acc:
                raise UserError(_("Akun default bank penerima belum terkonfigurasi."))

            # 1. Bank Settlement Entry
            if rec.total_approved_amount > 0 and not rec.settlement_move_id:
                s_move = Move.create({
                    "journal_id": rec.bank_journal_id.id,
                    "date": rec.claim_period_end,
                    "ref": f"Pencairan FPK BPJS: {rec.name}",
                    "move_type": "entry",
                    "line_ids": [
                        (0, 0, {
                            "name": f"Pencairan Klaim BPJS Disetujui ({rec.name})",
                            "account_id": bank_acc.id,
                            "debit": rec.total_approved_amount,
                            "credit": 0.0,
                        }),
                        (0, 0, {
                            "name": f"Pelunasan Piutang BPJS 112020 ({rec.name})",
                            "account_id": acc_112020.id,
                            "debit": 0.0,
                            "credit": rec.total_approved_amount,
                        }),
                    ],
                })
                s_move.action_post()
                rec.settlement_move_id = s_move.id

            # 2. Rejection Write-Off Entry against 112990
            if rec.total_rejected_amount > 0 and not rec.writeoff_move_id:
                if not acc_112990:
                    raise UserError(_("Akun Cadangan Penurunan Nilai Piutang (112990) tidak ditemukan!"))
                w_move = Move.create({
                    "journal_id": misc_j.id,
                    "date": rec.claim_period_end,
                    "ref": f"Write-Off Penolakan FPK BPJS: {rec.name}",
                    "move_type": "entry",
                    "line_ids": [
                        (0, 0, {
                            "name": f"Penghapusan Klaim BPJS Ditolak ({rec.name})",
                            "account_id": acc_112990.id,
                            "debit": rec.total_rejected_amount,
                            "credit": 0.0,
                        }),
                        (0, 0, {
                            "name": f"Koreksi Piutang BPJS Ditolak ({rec.name})",
                            "account_id": acc_112020.id,
                            "debit": 0.0,
                            "credit": rec.total_rejected_amount,
                        }),
                    ],
                })
                w_move.action_post()
                rec.writeoff_move_id = w_move.id

            rec.write({"state": "reconciled"})
            rec.message_post(
                body=_(
                    "Rekonsiliasi FPK %s selesai. Disetujui: Rp %s | Dispute Pending (112020): Rp %s | Write-Off (112990): Rp %s."
                ) % (
                    rec.name,
                    f"{rec.total_approved_amount:,.2f}",
                    f"{rec.total_disputed_amount:,.2f}",
                    f"{rec.total_rejected_amount:,.2f}",
                ),
                subtype_xmlid="mail.mt_note",
            )
        return True


class ClinicBpjsReconciliationLine(models.Model):
    _name = "clinic.bpjs.reconciliation.line"
    _description = "Rincian SEP Rekonsiliasi Klaim BPJS"

    batch_id = fields.Many2one("clinic.bpjs.reconciliation.batch", ondelete="cascade", required=True)
    sep_number = fields.Char(string="Nomor SEP", required=True)
    patient_id = fields.Many2one("res.partner", string="Pasien")
    currency_id = fields.Many2one("res.currency", related="batch_id.currency_id")

    claimed_amount = fields.Monetary(string="Diajukan", currency_field="currency_id", required=True)
    approved_amount = fields.Monetary(string="Disetujui", currency_field="currency_id", default=0.0)
    disputed_amount = fields.Monetary(string="Pending / Dispute", currency_field="currency_id", default=0.0)
    rejected_amount = fields.Monetary(string="Ditolak (Write-Off)", currency_field="currency_id", default=0.0)

    status = fields.Selection(
        [
            ("approved", "Disetujui Penuh"),
            ("dispute_pending", "Dispute Pending"),
            ("rejected", "Ditolak (Ineligible)"),
        ],
        string="Status SEP",
        default="approved",
        required=True,
    )
    notes = fields.Char(string="Catatan Verifikator BPJS")
