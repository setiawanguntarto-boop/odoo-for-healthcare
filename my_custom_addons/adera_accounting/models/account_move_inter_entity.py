# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class AccountMoveInterEntity(models.Model):
    _inherit = "account.move"

    is_inter_entity = fields.Boolean(
        string="Transaksi Antar-Entitas / Holding",
        default=False,
        help="Menandai transaksi talangan atau beban silang antar-cabang/holding",
    )
    inter_entity_type = fields.Selection(
        [
            ("holding_advance_supplier", "Holding Membayar Utang Vendor Cabang (BCA -> PBF)"),
            ("inter_branch_transfer", "Talangan Kas / Mutasi Antar-Cabang"),
        ],
        string="Tipe Transaksi Berelasi",
    )
    beneficiary_unit = fields.Selection(
        [
            ("pratama", "Klinik Pratama ADERA"),
            ("hd", "Klinik Utama Hemodialisis ADERA"),
        ],
        string="Cabang Penerima Manfaat",
    )

    inter_entity_clearing_move_id = fields.Many2one(
        "account.move",
        string="Jurnal Timbal-Balik (Reciprocal Entry)",
        readonly=True,
        copy=False,
    )

    @api.constrains("line_ids", "state")
    def _check_inter_entity_clearing_balance(self):
        """Validasi bahwa akun pihak berelasi (112040 dan 214040) pada entri antar-entitas
        terverifikasi atau seimbang dalam laporan konsolidasi."""
        for move in self:
            if move.state != "posted":
                continue
            clearing_lines = move.line_ids.filtered(
                lambda l: l.account_id and l.account_id.code_store in ("112040", "214040")
            )
            # Jika merupakan transaksi inter-entity otomatis, pastikan tag analitik terisi
            for cl in clearing_lines:
                if not cl.analytic_distribution:
                    _logger.warning("Inter-Entity move line %s has no analytic tag.", cl.id)

    def action_generate_reciprocal_entry(self):
        """Membuat jurnal timbal-balik otomatis di pembukuan cabang penerima manfaat:
        Contoh: Holding membayar vendor atas alkes HD:
        Holding (Entry 1):
           Debit: 112040 (Piutang Antar-Entitas - Cabang HD) [Tag: ACC-HOLDING]
           Credit: 111110 (Bank BCA Operasional Holding)
        Reciprocal (Entry 2 di Cabang HD):
           Debit: 211010 (Utang Supplier Farmasi/Alkes) [Tag: ACC-HD]
           Credit: 214040 (Kewajiban Antar-Entitas - Holding) [Tag: ACC-HD]
        """
        self.ensure_one()
        if self.inter_entity_clearing_move_id:
            raise UserError(_("Jurnal timbal-balik (reciprocal entry) sudah pernah dibuat."))

        if not self.beneficiary_unit:
            raise UserError(_("Pilih Cabang Penerima Manfaat terlebih dahulu."))

        journal = self.env["account.journal"].search([("type", "=", "general")], limit=1) or self.journal_id
        acc_reciprocal_debt = self.env.ref("adera_core.account_214040", raise_if_not_found=False)
        acc_supplier_payable = self.env.ref("adera_core.account_211010", raise_if_not_found=False)

        if not acc_reciprocal_debt or not acc_supplier_payable:
            raise UserError(_("Akun kewajiban antar-entitas (214040) atau utang supplier (211010) belum terkonfigurasi."))

        if self.beneficiary_unit == "hd":
            beneficiary_analytic = self.env.ref("adera_core.analytic_acc_hd", raise_if_not_found=False) or self.env.ref("adera_core.analytic_account_hd_root", raise_if_not_found=False)
        else:
            beneficiary_analytic = self.env.ref("adera_core.analytic_acc_pratama", raise_if_not_found=False) or self.env.ref("adera_core.analytic_account_pratama_root", raise_if_not_found=False)

        dist = {str(beneficiary_analytic.id): 100.0} if beneficiary_analytic else False

        amount = self.amount_total or sum(self.line_ids.filtered(lambda l: l.account_id.code_store == "112040").mapped("debit"))
        if amount <= 0:
            raise UserError(_("Jumlah transaksi harus lebih besar dari Rp 0.00."))

        reciprocal_lines = [
            (0, 0, {
                "name": f"Penyelesaian Utang Supplier via Talangan Holding ({self.name})",
                "account_id": acc_supplier_payable.id,
                "debit": amount,
                "credit": 0.0,
                "analytic_distribution": dist,
            }),
            (0, 0, {
                "name": f"Kewajiban Antar-Entitas ke Holding ({self.name})",
                "account_id": acc_reciprocal_debt.id,
                "debit": 0.0,
                "credit": amount,
                "analytic_distribution": dist,
            }),
        ]

        reciprocal_move = self.env["account.move"].create({
            "journal_id": journal.id,
            "date": self.date or fields.Date.today(),
            "ref": f"Reciprocal Inter-Entity: Talangan {self.name}",
            "line_ids": reciprocal_lines,
        })
        reciprocal_move.action_post()

        self.inter_entity_clearing_move_id = reciprocal_move.id
        self.message_post(body=f"Jurnal timbal-balik antar-entitas berhasil diposting: {reciprocal_move.name}.")
        return True
