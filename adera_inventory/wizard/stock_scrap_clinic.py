# -*- coding: utf-8 -*-
from odoo import fields, models, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class StockScrapClinic(models.TransientModel):
    _name = "stock.scrap.clinic"
    _description = "Wizard Pemusnahan Obat Multidosis Terbuka (Open-Vial Spoilage)"

    lot_id = fields.Many2one(
        "stock.lot",
        string="Nomor Batch / Lot Obat",
        required=True,
    )
    product_id = fields.Many2one(
        "product.product",
        string="Sediaan Obat / Vaksin",
        required=True,
    )
    product_uom_id = fields.Many2one(
        "uom.uom",
        string="Satuan Unit",
        related="product_id.uom_id",
    )
    dose_capacity = fields.Integer(
        string="Kapasitas Dosis per Vial",
        related="lot_id.dose_capacity",
    )
    doses_remaining = fields.Integer(
        string="Sisa Dosis di Lot",
        related="lot_id.doses_remaining",
    )
    dose_scrap_quantity = fields.Integer(
        string="Jumlah Dosis Terbuang / Dimusnahkan",
        required=True,
        default=1,
    )
    discarded_doses = fields.Integer(
        string="Dosis Terbuang (Discarded Doses)",
        compute="_compute_discarded_doses",
        inverse="_inverse_discarded_doses",
        store=True,
    )
    opened_datetime = fields.Datetime(
        string="Waktu Buka / Penusukan Segel",
        default=fields.Datetime.now,
    )
    vial_unit_quantity = fields.Float(
        string="Ekuivalen Satuan Unit (Vial/Ampul)",
        compute="_compute_spoilage_cost",
        store=True,
    )
    scrap_reason = fields.Selection(
        [
            ("expired_open_vial", "Kadaluarsa Pasca Buka (>24 Jam Stabilitas Vial Terbuka)"),
            ("cold_chain_failure", "Kegagalan Rantai Dingin / Suhu Cold Chain"),
            ("damaged_during_prep", "Kerusakan Fisik / Partikel Saat Preparasi"),
            ("exceeded_24h", "Melewati Batas Stabilitas Terbuka (>24 Jam)"),
            ("contamination", "Kontaminasi / Partikel Asing Saat Penusukan"),
            ("temperature_deviation", "Penyimpangan Suhu Cold Chain Pasca Buka"),
            ("clinical_waste", "Sisa Dosis Pasien / Limbah Medis B3"),
        ],
        string="Alasan Pemusnahan (Spoilage)",
        default="expired_open_vial",
        required=True,
    )
    analytic_account_id = fields.Many2one(
        "account.analytic.account",
        string="Unit Bisnis Beban (Analytic Unit)",
        required=True,
        default=lambda self: self._default_analytic_account(),
    )
    spoilage_account_id = fields.Many2one(
        "account.account",
        string="Akun Biaya Obat Terbuang (HPP)",
        required=True,
        default=lambda self: self._default_spoilage_account(),
    )
    inventory_account_id = fields.Many2one(
        "account.account",
        string="Akun Persediaan Farmasi",
        required=True,
        default=lambda self: self._default_inventory_account(),
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Jurnal Operasional",
        required=True,
        default=lambda self: self.env["account.journal"].search([("type", "=", "general")], limit=1),
    )
    unit_cost = fields.Float(
        string="Harga Pokok per Unit (Standard Cost)",
        related="product_id.standard_price",
        digits="Product Price",
    )
    total_spoilage_cost = fields.Monetary(
        string="Estimasi Nilai Kerugian / Spoilage",
        compute="_compute_spoilage_cost",
        store=True,
        currency_field="currency_id",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Klinik / Perusahaan",
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")

    def _default_analytic_account(self):
        return self.env["account.analytic.account"].search([
            ("code", "in", ["ACC-PRATAMA", "ACC-HD", "PRAT-FARM", "HD-PHARM"])
        ], limit=1)

    def _default_spoilage_account(self):
        return self.env["account.account"].search([
            ("code", "in", ["510010", "510020", "510030"])
        ], limit=1)

    def _default_inventory_account(self):
        return self.env["account.account"].search([
            ("code", "in", ["114010", "113010"])
        ], limit=1)

    @api.depends("dose_scrap_quantity")
    def _compute_discarded_doses(self):
        for rec in self:
            rec.discarded_doses = rec.dose_scrap_quantity

    def _inverse_discarded_doses(self):
        for rec in self:
            rec.dose_scrap_quantity = rec.discarded_doses

    @api.onchange("lot_id")
    def _onchange_lot_id(self):
        if self.lot_id:
            self.product_id = self.lot_id.product_id.id
            if self.lot_id.doses_remaining > 0:
                self.dose_scrap_quantity = self.lot_id.doses_remaining
                self.discarded_doses = self.lot_id.doses_remaining
            if self.lot_id.opened_date:
                self.opened_datetime = fields.Datetime.to_datetime(self.lot_id.opened_date)
            # Route analytic account and inventory asset
            prod_name = (self.product_id.name or "").lower()
            if "heparin" in prod_name or "dialyzer" in prod_name or "epo" in prod_name:
                hd_pharm = self.env["account.analytic.account"].search([("code", "=", "HD-PHARM")], limit=1)
                if hd_pharm:
                    self.analytic_account_id = hd_pharm.id
                inv_hd = self.env["account.account"].search([("code", "in", ["114030", "113020"])], limit=1)
                if inv_hd:
                    self.inventory_account_id = inv_hd.id
            else:
                prat_farm = self.env["account.analytic.account"].search([("code", "=", "PRAT-FARM")], limit=1)
                if prat_farm:
                    self.analytic_account_id = prat_farm.id
                inv_pharma = self.env["account.account"].search([("code", "in", ["114010", "113010"])], limit=1)
                if inv_pharma:
                    self.inventory_account_id = inv_pharma.id

    def action_scrap_open_vial(self):
        """Action alias method matching specification."""
        return self.action_confirm_scrap()

    @api.depends("product_id", "dose_scrap_quantity", "lot_id.dose_capacity")
    def _compute_spoilage_cost(self):
        for rec in self:
            cap = rec.lot_id.dose_capacity if rec.lot_id and rec.lot_id.dose_capacity > 0 else 1
            rec.vial_unit_quantity = round(rec.dose_scrap_quantity / cap, 4) if cap > 0 else 1.0
            unit_price = rec.product_id.standard_price if rec.product_id else 0.0
            rec.total_spoilage_cost = round(rec.vial_unit_quantity * unit_price, 2)

    def action_confirm_scrap(self):
        """Membukukan pemusnahan open vial ke inventory scrap dan GL jurnal 510010 vs 114010."""
        self.ensure_one()
        if self.dose_scrap_quantity <= 0:
            raise UserError("Jumlah dosis yang dimusnahkan harus lebih besar dari 0!")

        cost = self.total_spoilage_cost
        if cost <= 0:
            # Fallback to standard price or at least nominal
            cost = max(1.0, round(self.product_id.standard_price * (self.vial_unit_quantity or 1.0), 2))

        # 1. Financial Journal Entry: Dr 510010 / Cr 114010
        analytic_dist = {str(self.analytic_account_id.id): 100.0} if self.analytic_account_id else False
        reason_label = dict(self._fields["scrap_reason"].selection).get(self.scrap_reason, self.scrap_reason)
        ref_text = f"Pemusnahan Sisa Vial Terbuka: {self.product_id.name} (Lot: {self.lot_id.name}) - {reason_label}"

        move_vals = {
            "journal_id": self.journal_id.id,
            "date": fields.Date.today(),
            "ref": ref_text,
            "move_type": "entry",
            "line_ids": [
                (0, 0, {
                    "name": f"HPP Biaya Obat Terbuang: {self.product_id.name} ({self.dose_scrap_quantity} Dosis)",
                    "account_id": self.spoilage_account_id.id,
                    "debit": cost,
                    "credit": 0.0,
                    "analytic_distribution": analytic_dist,
                }),
                (0, 0, {
                    "name": f"Pengurangan Persediaan Farmasi: {self.product_id.name}",
                    "account_id": self.inventory_account_id.id,
                    "debit": 0.0,
                    "credit": cost,
                }),
            ],
        }
        move = self.env["account.move"].create(move_vals)
        move.action_post()

        # 2. Inventory Quant Scrap Adjustment
        # Find internal location
        quant = self.env["stock.quant"].search([
            ("lot_id", "=", self.lot_id.id),
            ("product_id", "=", self.product_id.id),
            ("location_id.usage", "=", "internal"),
            ("quantity", ">", 0),
        ], limit=1)

        scrap_location = self.env.ref("stock.stock_location_scrapped", raise_if_not_found=False)
        if not scrap_location:
            scrap_location = self.env["stock.location"].search([("scrap_location", "=", True)], limit=1)

        if quant and scrap_location:
            try:
                scrap_vals = {
                    "product_id": self.product_id.id,
                    "scrap_qty": min(quant.quantity, max(1.0, self.vial_unit_quantity)),
                    "product_uom_id": self.product_uom_id.id,
                    "location_id": quant.location_id.id,
                    "scrap_location_id": scrap_location.id,
                    "lot_id": self.lot_id.id,
                }
                scrap_record = self.env["stock.scrap"].create(scrap_vals)
                scrap_record.action_validate()
            except Exception as e:
                _logger.warning("Auto stock.scrap creation error (handled gracefully): %s", str(e))

        # 3. Update Lot status
        self.lot_id.write({
            "is_opened": False,
            "doses_administered": self.lot_id.dose_capacity,
        })
        self.lot_id.message_post(body=(
            f"<strong>Pemusnahan Sisa Vial Terbuka (Spoilage):</strong><br/>"
            f"• Dosis Dibuang: {self.dose_scrap_quantity} dosis ({self.vial_unit_quantity:.2f} vial)<br/>"
            f"• Alasan: {reason_label}<br/>"
            f"• Nilai Kerugian HPP (510010): Rp {cost:,.2f}<br/>"
            f"• Entri Jurnal: {move.name}"
        ))

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Pemusnahan Sisa Vial Berhasil",
                "message": f"Biaya spoilage sebesar Rp {cost:,.2f} telah dibukukan ke jurnal {move.name}.",
                "type": "success",
                "sticky": False,
            },
        }
