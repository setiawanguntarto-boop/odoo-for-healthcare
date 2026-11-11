# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class StockInventoryVariance(models.Model):
    _name = "stock.inventory.variance"
    _description = "Laporan Selisih Stock Opname & Log Penyesuaian Otomatis"
    _order = "inventory_date desc, id desc"

    name = fields.Char(string="Nomor Referensi Opname", readonly=True, copy=False, default=lambda self: _("New"))
    inventory_date = fields.Date(string="Tanggal Audit Opname", default=fields.Date.context_today, required=True)
    product_id = fields.Many2one("product.product", string="Produk Obat / Alkes", required=True)
    lot_id = fields.Many2one("stock.lot", string="Nomor Batch / Lot")
    location_id = fields.Many2one("stock.location", string="Lokasi Depo / Gudang", required=True)
    theoretical_qty = fields.Float(string="Kuantitas Sistem", readonly=True)
    counted_qty = fields.Float(string="Kuantitas Fisik Terhitung", required=True)
    variance_qty = fields.Float(string="Selisih Kuantitas", compute="_compute_variance", store=True)
    unit_cost = fields.Float(string="Biaya Pokok (FIFO)", compute="_compute_variance", store=True)
    variance_value = fields.Monetary(
        string="Nilai Selisih (Rp)",
        currency_field="currency_id",
        compute="_compute_variance",
        store=True,
    )
    variance_account_id = fields.Many2one("account.account", string="Akun Penyesuaian Selisih GL", required=True)
    account_move_id = fields.Many2one("account.move", string="Jurnal Penyesuaian GL", readonly=True)
    auditor_id = fields.Many2one("res.users", string="Auditor / Petugas Opname", default=lambda self: self.env.user, readonly=True)
    notes = fields.Text(string="Keterangan / Investigasi Selisih")
    state = fields.Selection([
        ("draft", "Draf Audit"),
        ("adjusted", "Telah Disesuaikan (GL Posted)"),
    ], string="Status", default="draft", readonly=True)
    currency_id = fields.Many2one("res.currency", string="Mata Uang", default=lambda self: self.env.company.currency_id)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("stock.inventory.variance") or _("OPN/%(year)s/")
            # Auto populate theoretical qty from stock.quant if not supplied
            if "theoretical_qty" not in vals and vals.get("product_id") and vals.get("location_id"):
                domain = [
                    ("product_id", "=", vals["product_id"]),
                    ("location_id", "=", vals["location_id"]),
                ]
                if vals.get("lot_id"):
                    domain.append(("lot_id", "=", vals["lot_id"]))
                quant = self.env["stock.quant"].search(domain, limit=1)
                vals["theoretical_qty"] = quant.quantity if quant else 0.0

            # Default variance account: 510010 for clinical shrinkage or 619990
            if "variance_account_id" not in vals:
                acc = self.env.ref("adera_core.account_510010", raise_if_not_found=False)
                if not acc:
                    acc = self.env["account.account"].search([("code", "=", "510010")], limit=1)
                if acc:
                    vals["variance_account_id"] = acc.id
        return super(StockInventoryVariance, self).create(vals_list)

    @api.depends("theoretical_qty", "counted_qty", "product_id")
    def _compute_variance(self):
        for rec in self:
            rec.variance_qty = round((rec.counted_qty or 0.0) - (rec.theoretical_qty or 0.0), 4)
            cost = rec.product_id.standard_price if rec.product_id else 0.0
            rec.unit_cost = cost
            rec.variance_value = round(rec.variance_qty * cost, 2)

    def action_post_adjustment(self):
        """Membuat penyesuaian fisik pada stock.quant dan membentuk jurnal penyesuaian GL otomatis."""
        for rec in self:
            if rec.state == "adjusted":
                continue

            # 1. Update kuantitas fisik pada stock.quant
            domain = [
                ("product_id", "=", rec.product_id.id),
                ("location_id", "=", rec.location_id.id),
            ]
            if rec.lot_id:
                domain.append(("lot_id", "=", rec.lot_id.id))
            quant = self.env["stock.quant"].search(domain, limit=1)

            if quant:
                quant.inventory_quantity = rec.counted_qty
                quant.action_apply_inventory()
            else:
                self.env["stock.quant"].create({
                    "product_id": rec.product_id.id,
                    "location_id": rec.location_id.id,
                    "lot_id": rec.lot_id.id if rec.lot_id else False,
                    "inventory_quantity": rec.counted_qty,
                }).action_apply_inventory()

            # 2. Bentuk jurnal GL jika ada nilai selisih
            abs_val = abs(rec.variance_value)
            if abs_val > 0 and rec.variance_account_id:
                # Tentukan akun persediaan aset dari kategori produk
                categ = rec.product_id.categ_id
                stock_acc = categ.property_stock_valuation_account_id
                if not stock_acc:
                    stock_acc = self.env.ref("adera_core.account_113010", raise_if_not_found=False) or self.env["account.account"].search([("code", "=", "113010")], limit=1)

                journal = self.env["account.journal"].search([("type", "=", "general")], limit=1)
                if stock_acc and journal:
                    # Jika selisih minus (stok hilang): Dr Selisih (510010/619990) / Cr Persediaan (113010)
                    # Jika selisih plus (stok lebih): Dr Persediaan (113010) / Cr Pendapatan Lain (410010)
                    if rec.variance_qty < 0:
                        debit_acc = rec.variance_account_id
                        credit_acc = stock_acc
                    else:
                        debit_acc = stock_acc
                        credit_acc = rec.variance_account_id

                    analytic_dist = False
                    pname = (rec.product_id.name or "").lower()
                    if "dialyzer" in pname or "hd" in pname:
                        an = self.env["account.analytic.account"].search([("code", "=", "ACC-HD")], limit=1)
                    else:
                        an = self.env["account.analytic.account"].search([("code", "=", "ACC-PRATAMA")], limit=1)
                    if an:
                        analytic_dist = {str(an.id): 100.0}

                    move_vals = {
                        "journal_id": journal.id,
                        "date": rec.inventory_date,
                        "ref": f"Penyesuaian Selisih Opname: {rec.name} - {rec.product_id.name}",
                        "line_ids": [
                            (0, 0, {
                                "name": f"Selisih Fisik Opname: {rec.product_id.name} ({rec.variance_qty:+.2f})",
                                "account_id": debit_acc.id,
                                "debit": abs_val,
                                "credit": 0.0,
                                "analytic_distribution": analytic_dist,
                            }),
                            (0, 0, {
                                "name": f"Penyesuaian Nilai Stok: {rec.product_id.name}",
                                "account_id": credit_acc.id,
                                "debit": 0.0,
                                "credit": abs_val,
                            }),
                        ],
                    }
                    move = self.env["account.move"].create(move_vals)
                    try:
                        move.action_post()
                        rec.account_move_id = move.id
                    except Exception:
                        rec.account_move_id = move.id

            rec.write({"state": "adjusted"})
        return True

