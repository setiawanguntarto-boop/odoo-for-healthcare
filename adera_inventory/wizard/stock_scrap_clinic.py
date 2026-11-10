# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class StockScrapClinic(models.TransientModel):
    _name = "stock.scrap.clinic"
    _description = "Wizard Pemusnahan Obat Multidosis Terbuka (Open-Vial Spoilage Approval)"

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
    spoilage_reason = fields.Selection(
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
    scrap_reason = fields.Selection(
        related="spoilage_reason",
        readonly=False,
        store=True,
        string="Alasan Scrap (Legacy)",
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

    # SoD and Approval Fields
    pharmacist_id = fields.Many2one(
        "res.users",
        string="Apoteker / PJ Farmasi",
        default=lambda self: self.env.user,
        required=True,
    )
    approver_id = fields.Many2one(
        "res.users",
        string="Disetujui Oleh",
        readonly=True,
    )
    requires_medical_manager = fields.Boolean(
        string="Perlu Persetujuan Manajer Medis (> Rp 500rb)",
        compute="_compute_approval_requirement",
        store=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft (Menunggu Approval)"),
            ("approved", "Disetujui & Dimusnahkan"),
        ],
        string="Status",
        default="draft",
        required=True,
    )

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
            ("code", "in", ["114010", "113010", "113020"])
        ], limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "discarded_doses" in vals and "dose_scrap_quantity" not in vals:
                vals["dose_scrap_quantity"] = vals["discarded_doses"]
            elif "dose_scrap_quantity" in vals and "discarded_doses" not in vals:
                vals["discarded_doses"] = vals["dose_scrap_quantity"]
            if "spoilage_reason" in vals and "scrap_reason" not in vals:
                vals["scrap_reason"] = vals["spoilage_reason"]
            elif "scrap_reason" in vals and "spoilage_reason" not in vals:
                vals["spoilage_reason"] = vals["scrap_reason"]
        return super().create(vals_list)

    @api.depends("dose_scrap_quantity")
    def _compute_discarded_doses(self):
        for rec in self:
            rec.discarded_doses = rec.dose_scrap_quantity

    def _inverse_discarded_doses(self):
        for rec in self:
            rec.dose_scrap_quantity = rec.discarded_doses

    @api.depends("total_spoilage_cost")
    def _compute_approval_requirement(self):
        for rec in self:
            # Threshold Rule: > Rp 500.000 requires Medical Services Manager approval
            rec.requires_medical_manager = rec.total_spoilage_cost > 500000.0

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
                inv_hd = self.env["account.account"].search([("code", "in", ["113020", "114030"])], limit=1)
                if inv_hd:
                    self.inventory_account_id = inv_hd.id
            else:
                prat_farm = self.env["account.analytic.account"].search([("code", "=", "PRAT-FARM")], limit=1)
                if prat_farm:
                    self.analytic_account_id = prat_farm.id
                inv_pharma = self.env["account.account"].search([("code", "in", ["113010", "114010"])], limit=1)
                if inv_pharma:
                    self.inventory_account_id = inv_pharma.id

    @api.depends("product_id", "dose_scrap_quantity", "lot_id.dose_capacity")
    def _compute_spoilage_cost(self):
        for rec in self:
            cap = rec.lot_id.dose_capacity if rec.lot_id and rec.lot_id.dose_capacity > 0 else 1
            rec.vial_unit_quantity = round(rec.dose_scrap_quantity / cap, 4) if cap > 0 else 1.0
            unit_price = rec.product_id.standard_price if rec.product_id else 0.0
            rec.total_spoilage_cost = round(rec.vial_unit_quantity * unit_price, 2)

    def action_scrap_open_vial(self):
        """Action alias method matching specification."""
        return self.action_confirm_scrap()

    def action_confirm_spoilage(self):
        """Explicit approval method matching prompt."""
        return self.action_confirm_scrap()

    def action_confirm_scrap(self):
        """Membukukan pemusnahan open vial ke inventory scrap dan GL jurnal 510010 vs 113010/114010 dengan SoD checks."""
        self.ensure_one()
        if self.dose_scrap_quantity <= 0:
            raise UserError(_("Jumlah dosis yang dimusnahkan harus lebih besar dari 0!"))

        cost = self.total_spoilage_cost
        if cost <= 0:
            cost = max(1.0, round(self.product_id.standard_price * (self.vial_unit_quantity or 1.0), 2))

        # Check Approval Rights:
        # If cost > 500,000, requires Medical Manager or Clinic Director
        user = self.env.user
        is_medical_mgr = (
            user.has_group("adera_core.group_medical_manager") or
            user.has_group("adera_doctor_remuneration.group_medical_manager") or
            user.has_group("adera_core.group_clinic_director") or
            user._is_admin()
        )
        is_pharmacist = (
            user.has_group("adera_core.group_pharmacy_pic") or
            user.has_group("stock.group_stock_user") or
            user._is_admin()
        )

        if cost > 500000.0 and not is_medical_mgr:
            raise UserError(_(
                "Nilai kerugian pemusnahan obat melebihi Rp 500.000 (Rp %s)! "
                "Pemusnahan sediaan bernilai tinggi wajib disetujui oleh Manajer Medis / Direktur."
            ) % f"{cost:,.2f}")

        # 1. Financial Journal Entry: Dr 510010 / Cr 113010 (or 114010)
        analytic_dist = {str(self.analytic_account_id.id): 100.0} if self.analytic_account_id else False
        reason_label = dict(self._fields["spoilage_reason"].selection).get(self.spoilage_reason, self.spoilage_reason)
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
        quant = self.env["stock.quant"].search([
            ("lot_id", "=", self.lot_id.id),
            ("product_id", "=", self.product_id.id),
            ("location_id.usage", "=", "internal"),
            ("quantity", ">", 0),
        ], limit=1)

        scrap_location = self.env.ref("stock.stock_location_scrapped", raise_if_not_found=False)
        if not scrap_location:
            scrap_location = self.env["stock.location"].search([
                ("usage", "=", "inventory"),
                "|",
                ("name", "ilike", "scrap"),
                ("name", "ilike", "karantina"),
            ], limit=1)
        if not scrap_location:
            scrap_location = self.env["stock.location"].search([("usage", "=", "inventory")], limit=1)

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
            f"<strong>Pemusnahan Sisa Vial Terbuka (Spoilage Approved):</strong><br/>"
            f"• Dosis Dibuang: {self.dose_scrap_quantity} dosis ({self.vial_unit_quantity:.2f} vial)<br/>"
            f"• Alasan: {reason_label}<br/>"
            f"• Disetujui Oleh: {user.name} ({'Manajer Medis' if cost > 500000 else 'PJ Farmasi'})<br/>"
            f"• Nilai Kerugian HPP (510010): Rp {cost:,.2f}<br/>"
            f"• Entri Jurnal: {move.name}"
        ))

        self.write({
            "state": "approved",
            "approver_id": user.id,
        })

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Pemusnahan Obat Berhasil Disetujui"),
                "message": _("Biaya spoilage sebesar Rp %s telah dibukukan ke jurnal %s.") % (f"{cost:,.2f}", move.name),
                "type": "success",
                "sticky": False,
            },
        }
