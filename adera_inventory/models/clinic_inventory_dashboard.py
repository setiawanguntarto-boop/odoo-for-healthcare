# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import date, datetime, timedelta
import logging

_logger = logging.getLogger(__name__)


class ClinicInventoryDashboard(models.AbstractModel):
    _name = "clinic.inventory.dashboard"
    _description = "Clinical Supply & Pharmacy Cockpit Metric Provider"

    @api.model
    def get_clinical_supply_metrics(self):
        """Menghitung metrik rantai pasok medis real-time:
        1. DIO (Days Inventory Outstanding) vs Target 14-21 Hari
        2. Tingkat Kekosongan Obat Esensial (Essential Stockout Rate)
        3. Total Valuasi Fisik FIFO (Akun 113010 Farmasi + 113020 BMHP HD)
        4. Peringatan FEFO (< 60 Hari Kadaluarsa)
        5. Peringatan Open-Vial (> 12 Jam Buka Segel)
        6. Buffer Hari Tindakan Hemodialisis (Dialyzer Coverage)
        """
        today = fields.Date.today()
        sixty_days_ahead = today + timedelta(days=60)
        company = self.env.company

        # -------------------------------------------------------------
        # 1. Total Valuasi FIFO (Perpetual FIFO Accounts 113010 & 113020)
        # -------------------------------------------------------------
        acc_farmasi = self.env["account.account"].search([("code", "in", ["113010", "114010"])], limit=1)
        acc_hd = self.env["account.account"].search([("code", "in", ["113020", "114030"])], limit=1)

        val_farmasi = 0.0
        val_hd = 0.0

        if acc_farmasi:
            lines = self.env["account.move.line"].search([
                ("account_id", "=", acc_farmasi.id),
                ("parent_state", "=", "posted"),
            ])
            val_farmasi = max(0.0, sum(lines.mapped("debit")) - sum(lines.mapped("credit")))

        if acc_hd:
            lines = self.env["account.move.line"].search([
                ("account_id", "=", acc_hd.id),
                ("parent_state", "=", "posted"),
            ])
            val_hd = max(0.0, sum(lines.mapped("debit")) - sum(lines.mapped("credit")))

        # Fallback to stock quants valuation if ledger empty
        total_fifo = val_farmasi + val_hd
        if total_fifo <= 0.0:
            quants = self.env["stock.quant"].search([
                ("location_id.usage", "=", "internal"),
                ("quantity", ">", 0),
            ])
            for q in quants:
                cost = q.product_id.standard_price or 0.0
                val = q.quantity * cost
                pname = (q.product_id.name or "").lower()
                if "dialyzer" in pname or "bicarbonate" in pname or "bloodline" in pname or "heparin" in pname:
                    val_hd += val
                else:
                    val_farmasi += val
            total_fifo = val_farmasi + val_hd

        # -------------------------------------------------------------
        # 2. DIO (Days Inventory Outstanding)
        # Formula: Total Stock Valuation / (Trailing 30-Day Average Daily COGS)
        # Accounts COGS: 510010 (Obat/BMHP Rawat Jalan) + 510020 (HD Consumables)
        # -------------------------------------------------------------
        thirty_days_ago = today - timedelta(days=30)
        cogs_accounts = self.env["account.account"].search([("code", "in", ["510010", "510020"])])
        cogs_lines = self.env["account.move.line"].search([
            ("account_id", "in", cogs_accounts.ids),
            ("date", ">=", thirty_days_ago),
            ("date", "<=", today),
            ("parent_state", "=", "posted"),
        ])
        total_cogs_30d = sum(cogs_lines.mapped("debit")) - sum(cogs_lines.mapped("credit"))
        daily_cogs = (total_cogs_30d / 30.0) if total_cogs_30d > 0 else 0.0

        if daily_cogs > 0:
            dio_days = round(total_fifo / daily_cogs, 1)
        else:
            # Baseline benchmark fallback: ~18 days standard
            dio_days = 18.5

        if dio_days <= 21.0:
            dio_status = "safe" # Green
            dio_label = "Optimal (14-21 Hari)"
        elif dio_days <= 30.0:
            dio_status = "warning" # Amber
            dio_label = "Perhatian (22-30 Hari)"
        else:
            dio_status = "danger" # Red
            dio_label = "Kelebihan Stok (>30 Hari)"

        # -------------------------------------------------------------
        # 3. Essential Stockout Rate
        # Emergency injections, vaccines, high-flux dialyzers, bloodlines
        # -------------------------------------------------------------
        essential_prods = self.env["product.product"].search([
            ("type", "in", ["consu", "product"]),
            "|",
            ("default_code", "ilike", "MED-"),
            ("name", "ilike", "Dialyzer"),
        ])
        total_essential = len(essential_prods) or 1
        stockout_count = 0
        for p in essential_prods:
            if p.qty_available <= 0:
                stockout_count += 1
        essential_stockout_rate = round((stockout_count / total_essential) * 100.0, 1)

        # -------------------------------------------------------------
        # 4. FEFO Alert (< 60 Hari Kadaluarsa)
        # -------------------------------------------------------------
        expiring_quants = self.env["stock.lot"].search([
            ("expiration_date", "!=", False),
            ("expiration_date", "<=", sixty_days_ahead),
            ("expiration_date", ">=", today),
            ("product_qty", ">", 0),
        ])
        expiring_soon_count = len(expiring_quants)

        # -------------------------------------------------------------
        # 5. Open-Vial Alert (> 12 Jam Buka Segel)
        # -------------------------------------------------------------
        twelve_hours_ago = fields.Datetime.now() - timedelta(hours=12)
        open_vial_lots = self.env["stock.lot"].search([
            ("is_opened", "=", True),
            ("opened_date", "<=", twelve_hours_ago),
            ("doses_remaining", ">", 0),
        ])
        open_vial_alert_count = len(open_vial_lots)

        # -------------------------------------------------------------
        # 6. Buffer Hari Sesi Hemodialisis (Dialyzer Kit Coverage)
        # Available Dialyzers / Average Daily HD Schedulings
        # -------------------------------------------------------------
        dialyzer_prods = self.env["product.product"].search([
            ("name", "ilike", "Dialyzer"),
            ("type", "in", ["consu", "product"]),
        ])
        total_dialyzer_qty = sum(dialyzer_prods.mapped("qty_available"))

        # Average HD encounters per day over trailing 14 days
        two_weeks_ago = today - timedelta(days=14)
        hd_encounters = self.env["clinic.encounter"].search_count([
            ("clinic_unit", "=", "hd"),
            ("encounter_date", ">=", two_weeks_ago),
            ("state", "=", "posted"),
        ]) if "clinic.encounter" in self.env else 0
        daily_hd_enc = (hd_encounters / 14.0) if hd_encounters > 0 else 6.0 # standard 6 sessions/day benchmark
        hd_buffer_days = round(total_dialyzer_qty / daily_hd_enc, 1) if daily_hd_enc > 0 else 10.0

        return {
            "dio_days": dio_days,
            "dio_status": dio_status,
            "dio_label": dio_label,
            "total_fifo_valuation": total_fifo,
            "val_farmasi": val_farmasi,
            "val_hd": val_hd,
            "essential_stockout_rate": essential_stockout_rate,
            "expiring_soon_count": expiring_soon_count,
            "open_vial_alert_count": open_vial_alert_count,
            "hd_buffer_days": hd_buffer_days,
            "total_dialyzer_qty": int(total_dialyzer_qty),
        }

    @api.model
    def get_critical_low_stock_items(self):
        """Menyajikan daftar obat dan BMHP di bawah safety stock / reorder point."""
        products = self.env["product.product"].search([
            ("type", "in", ["consu", "product"]),
            ("active", "=", True),
        ])
        items = []

        for p in products:
            qty_avail = p.qty_available
            # Ambil minimum reorder point jika ada
            orderpoint = self.env["stock.warehouse.orderpoint"].search([
                ("product_id", "=", p.id)
            ], limit=1)
            min_qty = orderpoint.product_min_qty if orderpoint else 10.0
            max_qty = orderpoint.product_max_qty if orderpoint else 50.0

            if qty_avail <= min_qty:
                suggested_qty = max(min_qty * 2.0, max_qty - qty_avail)

                # Deteksi kategori logistik
                pname = (p.name or "").lower()
                if "dialyzer" in pname or "bloodline" in pname or "bicarbonate" in pname or "fistula" in pname or "acid" in pname:
                    cat = "BMHP Hemodialisis"
                    unit_code = "ACC-HD"
                else:
                    cat = "Farmasi Rawat Jalan"
                    unit_code = "ACC-PRATAMA"

                # Vendor Rekanan Utama
                vendor_id = False
                vendor_name = "PBF Utama (Belum Ditentukan)"
                if p.seller_ids:
                    seller = p.seller_ids[0]
                    vendor_id = seller.partner_id.id
                    vendor_name = seller.partner_id.name
                else:
                    # Default PBF rekanan
                    default_pbf = self.env["res.partner"].search([
                        ("supplier_rank", ">", 0),
                        ("is_company", "=", True),
                    ], limit=1)
                    if default_pbf:
                        vendor_id = default_pbf.id
                        vendor_name = default_pbf.name

                items.append({
                    "product_id": p.id,
                    "product_code": p.default_code or "-",
                    "product_name": p.name,
                    "category": cat,
                    "unit_code": unit_code,
                    "qty_available": round(qty_avail, 2),
                    "min_qty": round(min_qty, 2),
                    "suggested_order_qty": int(suggested_qty),
                    "uom_name": p.uom_id.name or "Unit",
                    "unit_cost": p.standard_price,
                    "estimated_cost": round(suggested_qty * p.standard_price, 2),
                    "vendor_id": vendor_id,
                    "vendor_name": vendor_name,
                })

        return sorted(items, key=lambda x: (x["qty_available"] - x["min_qty"]))
