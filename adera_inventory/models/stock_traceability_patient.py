# -*- coding: utf-8 -*-
from odoo import models, fields, tools, api


class StockLotTraceabilityReport(models.Model):
    _name = "stock.lot.traceability.report"
    _description = "Kartu Keterlacakan Pasien vs Batch/Lot Recall BPOM"
    _auto = False
    _order = "event_date desc"

    event_type = fields.Selection([
        ("upstream", "Penerimaan PBF (Upstream)"),
        ("downstream", "Dispensing Pasien (Downstream)"),
    ], string="Arah Alur Distribusi", readonly=True)

    event_date = fields.Datetime(string="Tanggal Transaksi", readonly=True)
    product_id = fields.Many2one("product.product", string="Produk Obat / Alkes", readonly=True)
    lot_id = fields.Many2one("stock.lot", string="Nomor Batch / Lot", readonly=True)
    lot_name = fields.Char(string="Nomor Lot", readonly=True)
    quantity = fields.Float(string="Kuantitas", readonly=True)
    uom_name = fields.Char(string="Satuan", readonly=True)

    # Upstream details
    vendor_id = fields.Many2one("res.partner", string="Distributor PBF", readonly=True)
    po_reference = fields.Char(string="No. Surat Pesanan (PO)", readonly=True)
    grn_reference = fields.Char(string="No. Penerimaan (GRN)", readonly=True)
    warehouse_officer_id = fields.Many2one("res.users", string="Petugas Penerima", readonly=True)

    # Downstream patient details
    patient_name = fields.Char(string="Nama Pasien", readonly=True)
    patient_mrn = fields.Char(string="No. Rekam Medis (RM)", readonly=True)
    doctor_id = fields.Many2one("res.partner", string="Dokter Penanggung Jawab", readonly=True)
    encounter_reference = fields.Char(string="Referensi Encounter (EHR)", readonly=True)
    service_unit = fields.Char(string="Unit Pelayanan / Poli", readonly=True)
    is_quarantined = fields.Boolean(string="Status Karantina Batch", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                -- 1. UPSTREAM: Penerimaan dari PBF via stock_move_line
                SELECT
                    (sml.id * 2) AS id,
                    'upstream' AS event_type,
                    COALESCE(sp.date_done, sml.date) AS event_date,
                    sml.product_id AS product_id,
                    sml.lot_id AS lot_id,
                    COALESCE(sl.name, sml.lot_name) AS lot_name,
                    sml.quantity AS quantity,
                    uom.name AS uom_name,
                    sp.partner_id AS vendor_id,
                    sp.origin AS po_reference,
                    sp.name AS grn_reference,
                    sp.write_uid AS warehouse_officer_id,
                    NULL::VARCHAR AS patient_name,
                    NULL::VARCHAR AS patient_mrn,
                    NULL::INTEGER AS doctor_id,
                    NULL::VARCHAR AS encounter_reference,
                    'Gudang Medis Pusat'::VARCHAR AS service_unit,
                    COALESCE(sl.is_quarantined, FALSE) AS is_quarantined
                FROM stock_move_line sml
                JOIN stock_picking sp ON sml.picking_id = sp.id
                JOIN stock_picking_type spt ON sp.picking_type_id = spt.id
                JOIN product_product pp ON sml.product_id = pp.id
                JOIN uom_uom uom ON sml.product_uom_id = uom.id
                LEFT JOIN stock_lot sl ON sml.lot_id = sl.id
                WHERE spt.code = 'incoming'

                UNION ALL

                -- 2. DOWNSTREAM: Pengeluaran ke Pasien via clinic.encounter.line
                SELECT
                    (cel.id * 2 + 1) AS id,
                    'downstream' AS event_type,
                    ce.encounter_date AS event_date,
                    cel.product_id AS product_id,
                    cel.lot_id AS lot_id,
                    sl.name AS lot_name,
                    cel.qty AS quantity,
                    uom.name AS uom_name,
                    NULL::INTEGER AS vendor_id,
                    NULL::VARCHAR AS po_reference,
                    NULL::VARCHAR AS grn_reference,
                    ce.create_uid AS warehouse_officer_id,
                    ce.patient_name AS patient_name,
                    ce.patient_mrn AS patient_mrn,
                    cel.doctor_id AS doctor_id,
                    ce.name AS encounter_reference,
                    CASE
                        WHEN ce.clinic_unit = 'hd' THEN 'Klinik Utama Hemodialisis'
                        ELSE 'Klinik Pratama - Poli ' || COALESCE(ce.poli_code, 'Umum')
                    END AS service_unit,
                    COALESCE(sl.is_quarantined, FALSE) AS is_quarantined
                FROM clinic_encounter_line cel
                JOIN clinic_encounter ce ON cel.encounter_id = ce.id
                JOIN product_product pp ON cel.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                JOIN uom_uom uom ON pt.uom_id = uom.id
                LEFT JOIN stock_lot sl ON cel.lot_id = sl.id
                WHERE cel.lot_id IS NOT NULL OR cel.line_type = 'medication'
            )
        """)
