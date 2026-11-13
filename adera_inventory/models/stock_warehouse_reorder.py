# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class StockWarehouseReorder(models.Model):
    _inherit = "purchase.order"

    @api.model
    def action_generate_express_rfq(self, product_id, order_qty=1.0, vendor_id=False):
        """Membuat draft Purchase Order (RFQ) kilat langsung dari tabel stok kritis Cockpit Inventori."""
        product = self.env["product.product"].browse(product_id)
        if not product.exists():
            raise UserError(_("Produk tidak ditemukan!"))

        # Tentukan Vendor PBF
        if vendor_id:
            vendor = self.env["res.partner"].browse(vendor_id)
        elif product.seller_ids:
            vendor = product.seller_ids[0].partner_id
        else:
            vendor = self.env["res.partner"].search([
                ("supplier_rank", ">", 0),
                ("is_company", "=", True)
            ], limit=1)

        if not vendor:
            raise UserError(_("PBF / Vendor rekanan untuk produk %s belum ditentukan!") % product.name)

        # Analytic Account Mapping
        pname = (product.name or "").lower()
        if "dialyzer" in pname or "bloodline" in pname or "bicarbonate" in pname or "heparin" in pname:
            analytic_acc = self.env["account.analytic.account"].search([("code", "=", "ACC-HD")], limit=1)
            dest_location = self.env.ref("adera_inventory.stock_location_hd", raise_if_not_found=False)
        else:
            analytic_acc = self.env["account.analytic.account"].search([("code", "=", "ACC-PRATAMA")], limit=1)
            dest_location = self.env.ref("adera_inventory.stock_location_farmasi", raise_if_not_found=False)

        analytic_dist = {str(analytic_acc.id): 100.0} if analytic_acc else False

        # Cari Draft RFQ yang masih terbuka untuk vendor yang sama agar digabungkan (konsolidasi PO)
        existing_rfq = self.search([
            ("partner_id", "=", vendor.id),
            ("state", "=", "draft"),
            ("company_id", "=", self.env.company.id),
        ], limit=1)

        unit_price = product.standard_price or product.list_price or 1.0

        uom_id = product.uom_id.id
        line_vals = {
            "product_id": product.id,
            "name": f"{product.name} (Reorder Cepat Cockpit Rantai Pasok)",
            "product_qty": order_qty,
            "product_uom_id": uom_id,
            "price_unit": unit_price,
            "analytic_distribution": analytic_dist,
            "date_planned": fields.Datetime.now(),
        }

        if existing_rfq:
            # Check if line already exists in draft
            existing_line = existing_rfq.order_line.filtered(lambda l: l.product_id == product)
            if existing_line:
                existing_line.write({"product_qty": existing_line.product_qty + order_qty})
            else:
                line_vals["order_id"] = existing_rfq.id
                self.env["purchase.order.line"].create(line_vals)
            po = existing_rfq
        else:
            po = self.create({
                "partner_id": vendor.id,
                "company_id": self.env.company.id,
                "date_order": fields.Datetime.now(),
                "order_line": [(0, 0, line_vals)],
            })

        return {
            "type": "ir.actions.act_window",
            "name": _("Draft Surat Pesanan (RFQ)"),
            "res_model": "purchase.order",
            "res_id": po.id,
            "view_mode": "form",
            "target": "current",
        }
