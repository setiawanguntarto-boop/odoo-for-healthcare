# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class ClinicAssetDisposal(models.Model):
    _name = "clinic.asset.disposal"
    _description = "Berita Acara & Approval Pelepasan / Penghapusan Aset Medis"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "disposal_date desc, id desc"

    name = fields.Char(
        string="Nomor Berita Acara (BAST)",
        required=True,
        copy=False,
        default="/",
        tracking=True,
    )
    asset_id = fields.Many2one(
        "clinic.asset",
        string="Aset Medis / Fasilitas",
        required=True,
        domain="[('state', 'in', ('running', 'depreciated'))]",
        tracking=True,
    )
    asset_category = fields.Selection(
        related="asset_id.asset_category",
        string="Kategori Aset",
    )
    disposal_date = fields.Date(
        string="Tanggal Penghapusan / Afkir",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Klinik / Perusahaan",
        related="asset_id.company_id",
        store=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="asset_id.currency_id",
    )

    # Financial Values at Disposal
    purchase_value = fields.Monetary(
        string="Nilai Perolehan Historis (Cost)",
        currency_field="currency_id",
        compute="_compute_disposal_values",
        store=True,
    )
    accumulated_depreciation = fields.Monetary(
        string="Total Akumulasi Penyusutan",
        currency_field="currency_id",
        compute="_compute_disposal_values",
        store=True,
    )
    net_book_value = fields.Monetary(
        string="Nilai Buku Bersih (NBV / Kerugian)",
        currency_field="currency_id",
        compute="_compute_disposal_values",
        store=True,
    )

    disposal_reason = fields.Selection(
        [
            ("damage_unrepairable", "Kerusakan Fatal & Tidak Layak Pakai (Unrepairable)"),
            ("obsolete_technology", "Usang / Digantikan Teknologi Baru (Obsolescence)"),
            ("safety_hazard", "Gagal Kalibrasi BPFK / Bahaya Klinis (Safety Hazard)"),
            ("lost_stolen", "Hilang / Musnah Akibat Bencana"),
            ("sold_scrapped", "Dijual sebagai Besi Tua / Dihibahkan"),
        ],
        string="Alasan Penghapusan",
        required=True,
        default="damage_unrepairable",
        tracking=True,
    )
    technical_notes = fields.Text(
        string="Catatan Teknis / Rekomendasi Teknisi Medis (ATEM)",
        tracking=True,
    )

    # COA Integration Accounts
    asset_account_id = fields.Many2one(
        "account.account",
        string="Akun Aset Tetap",
        compute="_compute_disposal_accounts",
        store=True,
        readonly=False,
    )
    depreciation_account_id = fields.Many2one(
        "account.account",
        string="Akun Akumulasi Penyusutan",
        compute="_compute_disposal_accounts",
        store=True,
        readonly=False,
    )
    loss_account_id = fields.Many2one(
        "account.account",
        string="Akun Beban Kerugian Penghapusan Aset (619020)",
        compute="_compute_disposal_accounts",
        store=True,
        readonly=False,
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Jurnal Operasional",
        compute="_compute_disposal_accounts",
        store=True,
        readonly=False,
    )

    # SoD and Approvals
    prepared_by_id = fields.Many2one(
        "res.users",
        string="Disusun Oleh (Teknisi Medis / Sarpras)",
        default=lambda self: self.env.user,
        tracking=True,
    )
    approved_by_id = fields.Many2one(
        "res.users",
        string="Disetujui Oleh (Direktur Klinik)",
        readonly=True,
        tracking=True,
    )
    approval_datetime = fields.Datetime(
        string="Waktu Persetujuan Direksi",
        readonly=True,
        tracking=True,
    )
    rejection_reason = fields.Text(
        string="Alasan Penolakan Direksi",
        readonly=True,
        tracking=True,
    )

    disposal_move_id = fields.Many2one(
        "account.move",
        string="Entri Jurnal Penghapusan GL",
        readonly=True,
        tracking=True,
    )

    state = fields.Selection(
        [
            ("draft", "Draft (Disusun Teknisi)"),
            ("to_approve", "Menunggu Persetujuan Direksi"),
            ("approved", "Disetujui & Dihapusbukukan"),
            ("rejected", "Ditolak"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("clinic.asset.disposal") or "/"
        return super().create(vals_list)

    @api.depends("asset_id")
    def _compute_disposal_values(self):
        for rec in self:
            if rec.asset_id:
                rec.purchase_value = rec.asset_id.purchase_value
                rec.accumulated_depreciation = rec.asset_id.accumulated_depreciation
                rec.net_book_value = rec.asset_id.net_book_value
            else:
                rec.purchase_value = 0.0
                rec.accumulated_depreciation = 0.0
                rec.net_book_value = 0.0

    @api.depends("asset_id")
    def _compute_disposal_accounts(self):
        for rec in self:
            if rec.asset_id:
                rec.asset_account_id = rec.asset_id.asset_account_id.id
                rec.depreciation_account_id = rec.asset_id.depreciation_account_id.id
                rec.journal_id = rec.asset_id.journal_id.id
            else:
                rec.asset_account_id = False
                rec.depreciation_account_id = False
                rec.journal_id = False

            loss_acc = self.env["account.account"].search([("code", "=", "619020")], limit=1)
            if not loss_acc:
                loss_acc = self.env["account.account"].search([("code", "in", ["619000", "610030"])], limit=1)
            rec.loss_account_id = loss_acc.id if loss_acc else False

    def action_submit_for_approval(self):
        """Teknisi Medis / Sarpras mengajukan berita acara ke Direktur Klinik."""
        self.ensure_one()
        if not self.asset_id:
            raise UserError(_("Pilih aset medis yang akan dihapusbukukan!"))
        if self.asset_id.state not in ("running", "depreciated"):
            raise UserError(_("Aset harus berstatus 'Berjalan' atau 'Selesai Disusutkan'!"))

        self.write({
            "state": "to_approve",
        })
        self.message_post(
            body=_("Berita acara penghapusan aset diajukan oleh %s kepada Direktur Klinik.") % self.env.user.name,
            subtype_xmlid="mail.mt_note",
        )
        return True

    def action_approve_disposal(self):
        """Direktur Klinik menyetujui penghapusan aset: hitung NBV, update status aset, dan post jurnal GL."""
        self.ensure_one()
        if self.state != "to_approve":
            raise UserError(_("Hanya dokumen yang berstatus 'Menunggu Persetujuan' yang dapat disetujui!"))
        if self.disposal_move_id:
            raise UserError(_("Jurnal penghapusan aset sudah pernah dibuat!"))

        asset = self.asset_id
        # Refresh nilai buku terkini
        cost = asset.purchase_value
        accum = asset.accumulated_depreciation
        nbv = asset.net_book_value

        asset_acc = self.asset_account_id or asset.asset_account_id
        depr_acc = self.depreciation_account_id or asset.depreciation_account_id
        loss_acc = self.loss_account_id or self.env["account.account"].search([("code", "=", "619020")], limit=1)
        journal = self.journal_id or asset.journal_id

        if not asset_acc or not depr_acc or not loss_acc or not journal:
            raise UserError(_("Konfigurasi akun Aset (121010), Akumulasi (122010), Kerugian (619020), atau Jurnal belum lengkap!"))

        # Analytic distribution tagging
        analytic_dist = asset.analytic_distribution or False

        # Build compound balanced disposal journal entry
        move_lines = []

        # 1. Credit Akun Aset Tetap untuk harga perolehan penuh (menghapus nilai historis aset)
        move_lines.append((0, 0, {
            "name": f"Penghapusan Nilai Perolehan Aset: {asset.name}",
            "account_id": asset_acc.id,
            "debit": 0.0,
            "credit": cost,
            "analytic_distribution": analytic_dist,
        }))

        # 2. Debit Akun Akumulasi Penyusutan (menghapus akumulasi penyusutan yang telah dibukukan)
        if accum > 0:
            move_lines.append((0, 0, {
                "name": f"Penghapusan Akumulasi Penyusutan: {asset.name}",
                "account_id": depr_acc.id,
                "debit": accum,
                "credit": 0.0,
                "analytic_distribution": analytic_dist,
            }))

        # 3. Debit Akun Beban Kerugian Penghapusan Aset Tetap (NBV)
        if nbv > 0:
            move_lines.append((0, 0, {
                "name": f"Beban Kerugian Penghapusan Aset (NBV): {asset.name}",
                "account_id": loss_acc.id,
                "debit": nbv,
                "credit": 0.0,
                "analytic_distribution": analytic_dist,
            }))

        # Periksa keseimbangan debit vs credit
        total_debit = sum(l[2]["debit"] for l in move_lines)
        total_credit = sum(l[2]["credit"] for l in move_lines)
        diff = round(total_debit - total_credit, 2)
        if diff != 0:
            # Sesuaikan pembulatan desimal ke akun beban kerugian
            if nbv > 0:
                for l in move_lines:
                    if l[2]["account_id"] == loss_acc.id:
                        l[2]["debit"] = round(l[2]["debit"] - diff, 2)
                        break

        move = self.env["account.move"].create({
            "journal_id": journal.id,
            "date": self.disposal_date,
            "ref": f"Penghapusan Aset Tetap: {self.name} - {asset.name}",
            "move_type": "entry",
            "line_ids": move_lines,
        })
        move.action_post()

        # Update status aset menjadi 'disposed'
        asset.write({"state": "disposed"})
        asset.message_post(body=_("Aset telah dihapusbukukan melalui Berita Acara %s (Jurnal: %s)") % (self.name, move.name))

        self.write({
            "state": "approved",
            "approved_by_id": self.env.user.id,
            "approval_datetime": fields.Datetime.now(),
            "disposal_move_id": move.id,
            "purchase_value": cost,
            "accumulated_depreciation": accum,
            "net_book_value": nbv,
        })

        self.message_post(
            body=_("Penghapusan aset disetujui oleh Direktur Klinik %s. Jurnal GL berhasil diposting: %s") % (self.env.user.name, move.name),
            subtype_xmlid="mail.mt_note",
        )
        return True

    def action_reject(self, reason=False):
        """Direktur Klinik menolak usulan penghapusan aset."""
        self.ensure_one()
        self.write({
            "state": "rejected",
            "rejection_reason": reason or _("Ditolak oleh Direktur Klinik."),
        })
        self.message_post(
            body=_("Usulan penghapusan aset ditolak oleh Direktur Klinik %s.") % self.env.user.name,
            subtype_xmlid="mail.mt_note",
        )
        return True

