# -*- coding: utf-8 -*-
from odoo import models, fields, tools


class StockLotAgingReport(models.Model):
    _name = "stock.lot.aging.report"
    _description = "Analisis Kedaluwarsa & Batch Aging Matrix (Value-at-Risk)"
    _auto = False
    _order = "days_to_expiry asc"

    product_id = fields.Many2one("product.product", string="Produk Obat / Alkes", readonly=True)
    lot_id = fields.Many2one("stock.lot", string="Nomor Batch / Lot", readonly=True)
    location_id = fields.Many2one("stock.location", string="Lokasi Depo / Gudang", readonly=True)
    quantity = fields.Float(string="Kuantitas Fisik On-Hand", readonly=True)
    unit_cost = fields.Float(string="Biaya Per Unit (FIFO)", readonly=True)
    total_value_at_risk = fields.Monetary(
        string="Total Nilai Terancam (Rp)",
        currency_field="currency_id",
        readonly=True,
        help="Nilai buku rupiah (Valuasi FIFO) yang terancam kerugian finansial akibat mendekati/melewati kedaluwarsa.",
    )
    days_to_expiry = fields.Integer(string="Sisa Hari Kedaluwarsa", readonly=True)
    aging_bucket = fields.Selection([
        ("critical_quarantine", "Kritis / Kadaluwarsa (<30 Hari)"),
        ("near_expiry", "Waspada FEFO (30-60 Hari)"),
        ("safe", "Aman (>60 Hari)"),
    ], string="Kategori Usia Batch", readonly=True)
    is_quarantined = fields.Boolean(string="Status Karantina / Recall", readonly=True)
    currency_id = fields.Many2one("res.currency", string="Mata Uang", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    sq.id AS id,
                    sq.product_id AS product_id,
                    sq.lot_id AS lot_id,
                    sq.location_id AS location_id,
                    sq.quantity AS quantity,
                    COALESCE(
                        (pp.standard_price->>'1')::NUMERIC,
                        pt.list_price,
                        0.0
                    ) AS unit_cost,
                    ROUND(
                        sq.quantity * COALESCE(
                            (pp.standard_price->>'1')::NUMERIC,
                            pt.list_price,
                            0.0
                        ), 2
                    ) AS total_value_at_risk,
                    COALESCE(DATE_PART('day', sl.expiration_date - CURRENT_DATE), 9999)::INTEGER AS days_to_expiry,
                    CASE
                        WHEN sl.expiration_date IS NULL THEN 'safe'
                        WHEN DATE_PART('day', sl.expiration_date - CURRENT_DATE) <= 30 THEN 'critical_quarantine'
                        WHEN DATE_PART('day', sl.expiration_date - CURRENT_DATE) <= 60 THEN 'near_expiry'
                        ELSE 'safe'
                    END AS aging_bucket,
                    COALESCE(sl.is_quarantined, FALSE) AS is_quarantined,
                    comp.currency_id AS currency_id
                FROM stock_quant sq
                JOIN product_product pp ON sq.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                JOIN stock_location sloc ON sq.location_id = sloc.id
                CROSS JOIN (SELECT id, currency_id FROM res_company ORDER BY id ASC LIMIT 1) comp
                LEFT JOIN stock_lot sl ON sq.lot_id = sl.id
                WHERE sq.quantity > 0
                  AND sloc.usage = 'internal'
            )
        """)
