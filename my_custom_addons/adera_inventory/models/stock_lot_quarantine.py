# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class StockLot(models.Model):
    _inherit = "stock.lot"

    is_quarantined = fields.Boolean(
        string="Status Karantina / Batch Recall",
        default=False,
        tracking=True,
        help="Jika dicentang, nomor batch/lot ini diblokir total dari resep dokter, kasir POS, dan mutasi pengeluaran ke pasien.",
    )
    quarantine_reason = fields.Selection([
        ("recall_bpom", "Penarikan Resmi BPOM / Prinsipal"),
        ("quality_defect", "Cacat Fisik / Perubahan Warna / Partikel Terlihat"),
        ("cold_chain_breach", "Kerusakan Rantai Dingin (Cold Chain Failure)"),
        ("suspected_adverse_event", "Investigasi Kejadian Tidak Diharapkan (KTD)"),
    ], string="Alasan Karantina", tracking=True)

    quarantine_notes = fields.Text(string="Catatan Klinis & Nomor Surat Edaran", tracking=True)
    quarantined_by_id = fields.Many2one("res.users", string="Dibersihkan / Dikarantina Oleh", readonly=True)
    quarantined_datetime = fields.Datetime(string="Waktu Karantina", readonly=True)

    def action_quarantine_batch(self):
        """Karantina nomor batch secara instan:
        1. Set flag is_quarantined = True
        2. Bentuk transfer internal darurat untuk memindahkan seluruh fisik stok batch ini ke WH/Quarantine
        """
        for lot in self:
            lot.write({
                "is_quarantined": True,
                "quarantined_by_id": self.env.user.id,
                "quarantined_datetime": fields.Datetime.now(),
            })

            quarantine_loc = self.env.ref("adera_inventory.stock_location_pharma_quarantine", raise_if_not_found=False)
            if not quarantine_loc:
                quarantine_loc = self.env["stock.location"].search([
                    ("usage", "in", ["inventory", "internal"]),
                    ("name", "ilike", "Karantina")
                ], limit=1)

            if not quarantine_loc:
                continue

            # Cari seluruh stock.quant aktif untuk batch ini di lokasi internal selain lokasi karantina
            quants = self.env["stock.quant"].search([
                ("lot_id", "=", lot.id),
                ("quantity", ">", 0),
                ("location_id.usage", "=", "internal"),
                ("location_id", "!=", quarantine_loc.id),
            ])

            if quants:
                picking_type = self.env["stock.picking.type"].search([
                    ("code", "=", "internal"),
                    ("warehouse_id.company_id", "=", self.env.company.id),
                ], limit=1)

                if picking_type:
                    reason_label = dict(lot._fields["quarantine_reason"].selection).get(lot.quarantine_reason, "Batch Recall")
                    picking = self.env["stock.picking"].create({
                        "picking_type_id": picking_type.id,
                        "location_id": quants[0].location_id.id,
                        "location_dest_id": quarantine_loc.id,
                        "origin": f"KARANTINA BATCH RECALL: {lot.name} ({reason_label})",
                        "priority": "2",  # Urgent
                    })

                    for q in quants:
                        move = self.env["stock.move"].create({
                            "name": f"Karantina Recall: {q.product_id.name} [Lot {lot.name}]",
                            "product_id": q.product_id.id,
                            "product_uom_qty": q.quantity,
                            "product_uom": q.product_id.uom_id.id,
                            "picking_id": picking.id,
                            "location_id": q.location_id.id,
                            "location_dest_id": quarantine_loc.id,
                        })

                    # Konfirmasi transfer agar siap dieksekusi atau langsung divalidasi oleh petugas gudang
                    try:
                        picking.action_confirm()
                        picking.action_assign()
                    except Exception:
                        pass

            # Audit trail di chatter
            if hasattr(lot, "message_post"):
                lot.message_post(
                    body=f"<strong>⚠️ PERINGATAN BATCH RECALL:</strong> Lot {lot.name} telah berhasil DIKARANTINA.<br/>"
                         f"• Alasan: {dict(lot._fields['quarantine_reason'].selection).get(lot.quarantine_reason, '-')}<br/>"
                         f"• Catatan: {lot.quarantine_notes or '-'}<br/>"
                         f"• Eksekutor: {self.env.user.name}"
                )

        return True

    def action_release_quarantine(self):
        """Membatalkan karantina setelah hasil investigasi klinis/BPOM menyatakan aman."""
        for lot in self:
            lot.write({
                "is_quarantined": False,
                "quarantine_reason": False,
                "quarantine_notes": (lot.quarantine_notes or "") + f"\n[RELEASED] Dikeluarkan dari karantina oleh {self.env.user.name} pada {fields.Datetime.now()}",
            })
            if hasattr(lot, "message_post"):
                lot.message_post(body=f"✅ Karantina untuk Lot {lot.name} telah DICABUT oleh {self.env.user.name}.")
        return True

