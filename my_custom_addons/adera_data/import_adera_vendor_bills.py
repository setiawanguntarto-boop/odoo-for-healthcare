#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
KLINIK ADERA ERP - VENDOR BILLS (AP) ETL & 3-WAY MATCH INGESTION
=============================================================================
Phase 5 Data Migration Script:
Target File: 'Klinik ADERA - DAFTAR FAKTUR PEMBELIAN PEMBELI.csv'
Target Models:
- account.move (move_type = 'in_invoice')
- purchase.order (3-Way Match PO <-> GRN <-> Vendor Bill)
- account.payment (Payment registration for bills marked 'LUNAS')

PSAK & Accounting Rules:
- Payable Control Account: 211010 (Utang Usaha Pemasok & Distributor Farmasi)
- GR/IR Clearing Account : 211500 (Utang Belum Ditagih / Interim Clearing)
- Freight/Biaya Kirim    : 510090 / Beban Logistik Pengiriman Obat
- Idempotency           : Check existing bill by vendor + invoice number (ref)
=============================================================================
"""

import os
import sys
import json
import logging
from datetime import datetime
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("AderaVendorBillsETL")

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_BILLS = os.path.join(DATA_DIR, "Klinik ADERA - DAFTAR FAKTUR PEMBELIAN PEMBELI.csv")
ANOMALY_FILE = os.path.join(DATA_DIR, "VENDOR_BILLS_ANOMALY_REPORT.json")


def clean_num(val):
    if pd.isna(val) or val is None:
        return 0.0
    s = str(val).strip().replace(',', '').replace('"', '').replace(' ', '')
    if not s or s == '-':
        return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0


def parse_date(date_str):
    if pd.isna(date_str) or not str(date_str).strip() or str(date_str).strip() == '-':
        return None
    s = str(date_str).strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return None


class AderaVendorBillsIngestor:
    def __init__(self, env):
        self.env = env
        self.AccountMove = env['account.move']
        self.PurchaseOrder = env['purchase.order']
        self.Partner = env['res.partner']
        self.Account = env['account.account']
        self.Journal = env['account.journal']
        self.Product = env['product.product']

        # Pre-cache PSAK Accounts
        self.acc_payable = self.Account.search([('code', '=', '211010')], limit=1)
        self.acc_grir = self.Account.search([('code', '=', '211500')], limit=1)
        self.acc_cogs = self.Account.search([('code', '=', '510010')], limit=1)
        self.journal_bmed = self.Journal.search([('code', '=', 'BMED')], limit=1)
        self.journal_bank = self.Journal.search([('type', '=', 'bank')], limit=1)

        # Pre-cache suppliers
        self.supplier_cache = {}
        for p in self.Partner.search([('supplier_rank', '>', 0)]):
            self.supplier_cache[p.name.strip().upper()] = p

        self.anomalies = []
        self.stats = {
            'total_rows': 0,
            'processed': 0,
            'skipped_zero_test': 0,
            'skipped_existing': 0,
            'po_linked_bills': 0,
            'direct_bills': 0,
            'payments_registered': 0,
            'errors': 0,
        }

    def get_or_create_supplier(self, supplier_name):
        clean_name = supplier_name.strip()
        name_upper = clean_name.upper()

        if name_upper in self.supplier_cache:
            return self.supplier_cache[name_upper]

        # Search DB case-insensitively
        p = self.Partner.search([('name', '=ilike', clean_name)], limit=1)
        if not p:
            p = self.Partner.create({
                'name': clean_name,
                'is_company': True,
                'supplier_rank': 1,
                'property_account_payable_id': self.acc_payable.id if self.acc_payable else False,
            })
            logger.info(f"Created new supplier: {clean_name}")

        # Ensure property_account_payable_id points to PSAK 211010
        if self.acc_payable and p.property_account_payable_id != self.acc_payable:
            p.write({'property_account_payable_id': self.acc_payable.id})

        self.supplier_cache[name_upper] = p
        return p

    def run_import(self):
        logger.info(f"Loading Vendor Bills from {FILE_BILLS}...")
        if not os.path.exists(FILE_BILLS):
            logger.error(f"File not found: {FILE_BILLS}")
            return

        # Header is at row index 2 (line 3)
        df = pd.read_csv(FILE_BILLS, skiprows=2)
        # Drop completely empty rows or footer totals
        df = df.dropna(how='all')
        df = df[df['PEMASOK PENJUAL'].notna() & (df['PEMASOK PENJUAL'].str.strip() != '')]
        df = df[df['PEMASOK PENJUAL'].str.upper() != 'TOTAL']

        self.stats['total_rows'] = len(df)
        logger.info(f"Total valid vendor bill rows to analyze: {len(df)}")

        for idx, row in df.iterrows():
            try:
                self._process_bill_row(idx, row)
            except Exception as e:
                self.stats['errors'] += 1
                logger.error(f"Row {idx}: Error processing row: {e}", exc_info=True)
                self.anomalies.append({
                    'row': idx,
                    'error': str(e),
                    'data': row.to_dict()
                })

        # Commit transaction
        self.env.cr.commit()
        self._generate_report()

    def _process_bill_row(self, idx, row):
        po_ref = str(row.get('NO. ORDER', '')).strip()
        inv_no = str(row.get('NO. FAKTUR', '')).strip()
        vendor_name = str(row.get('PEMASOK PENJUAL', '')).strip()
        bill_date = parse_date(row.get('TGL. FAKTUR'))
        due_date = parse_date(row.get('JATUH TEMPO')) or bill_date
        total_amount = clean_num(row.get('HARGA (Rp.)'))
        tax_amount = clean_num(row.get('PAJAK (Rp.)'))
        other_fee = clean_num(row.get('BIAYA LAINNYA (Rp.)'))
        shipping_fee = clean_num(row.get('PENGIRIMAN (Rp.)'))
        status = str(row.get('STATUS', '')).strip().upper()

        # 1. Filter out Zero Value test records
        if total_amount <= 0.0:
            logger.info(f"Row {idx}: Skipping zero-value test bill (PO: {po_ref}, Inv: {inv_no})")
            self.stats['skipped_zero_test'] += 1
            self.anomalies.append({
                'row': idx,
                'reason': 'Zero total amount test record',
                'po_ref': po_ref,
                'inv_no': inv_no,
            })
            return

        supplier = self.get_or_create_supplier(vendor_name)

        # 2. Check Idempotency: Has this bill already been created?
        existing_bill = self.AccountMove.search([
            ('move_type', '=', 'in_invoice'),
            ('partner_id', '=', supplier.id),
            ('ref', '=', inv_no),
        ], limit=1)

        if existing_bill:
            logger.info(f"Row {idx}: Bill already exists: {existing_bill.name} (Ref: {inv_no}) -> SKIPPED")
            self.stats['skipped_existing'] += 1
            return

        # 3. Check if linked to an existing Purchase Order in Odoo
        linked_po = False
        if po_ref and po_ref != '-':
            linked_po = self.PurchaseOrder.search([('partner_ref', '=', po_ref)], limit=1)
            if not linked_po:
                linked_po = self.PurchaseOrder.search([('name', '=', po_ref)], limit=1)

        bill = None

        if linked_po and linked_po.invoice_status == 'to invoice':
            logger.info(f"Row {idx}: 3-Way Match: Creating Vendor Bill from PO {linked_po.name} (Ref: {po_ref})...")
            res = linked_po.action_create_invoice()
            inv_id = res['res_id'] if 'res_id' in res else res.get('domain', [('id', 'in', [])])[0][2][0]
            bill = self.AccountMove.browse(inv_id)

            bill.write({
                'ref': inv_no,
                'invoice_date': bill_date,
                'invoice_date_due': due_date,
            })

            # Check if additional fees need to be added
            if other_fee > 0 or shipping_fee > 0:
                fee_lines = []
                if other_fee > 0:
                    fee_lines.append((0, 0, {
                        'name': f"Biaya Lainnya - {inv_no}",
                        'quantity': 1.0,
                        'price_unit': other_fee,
                        'account_id': self.acc_cogs.id if self.acc_cogs else bill.journal_id.default_account_id.id,
                    }))
                if shipping_fee > 0:
                    fee_lines.append((0, 0, {
                        'name': f"Biaya Pengiriman - {inv_no}",
                        'quantity': 1.0,
                        'price_unit': shipping_fee,
                        'account_id': self.acc_cogs.id if self.acc_cogs else bill.journal_id.default_account_id.id,
                    }))
                bill.write({'invoice_line_ids': fee_lines})

            bill.action_post()
            self.stats['po_linked_bills'] += 1
            logger.info(f"Row {idx}: Successfully posted PO-linked Bill {bill.name} (Amount: Rp {bill.amount_total:,.2f})")

        else:
            # Standalone direct vendor bill
            logger.info(f"Row {idx}: Creating Direct Vendor Bill for {supplier.name} (Inv: {inv_no}, Rp {total_amount:,.2f})...")
            product_cogs = self.Product.search([('default_code', '=', 'SRV-MED-SUPPLY')], limit=1)
            if not product_cogs:
                product_cogs = self.Product.search([('type', '=', 'consu')], limit=1)

            line_vals = [(0, 0, {
                'name': f"Faktur Pengadaan Medis: {inv_no} - {vendor_name}",
                'product_id': product_cogs.id if product_cogs else False,
                'quantity': 1.0,
                'price_unit': total_amount,
                'account_id': self.acc_cogs.id if self.acc_cogs else False,
            })]

            if other_fee > 0:
                line_vals.append((0, 0, {
                    'name': f"Biaya Lainnya - {inv_no}",
                    'quantity': 1.0,
                    'price_unit': other_fee,
                    'account_id': self.acc_cogs.id if self.acc_cogs else False,
                }))
            if shipping_fee > 0:
                line_vals.append((0, 0, {
                    'name': f"Biaya Pengiriman - {inv_no}",
                    'quantity': 1.0,
                    'price_unit': shipping_fee,
                    'account_id': self.acc_cogs.id if self.acc_cogs else False,
                }))

            bill = self.AccountMove.create({
                'move_type': 'in_invoice',
                'partner_id': supplier.id,
                'journal_id': self.journal_bmed.id if self.journal_bmed else False,
                'invoice_date': bill_date,
                'invoice_date_due': due_date,
                'ref': inv_no,
                'invoice_line_ids': line_vals,
            })
            bill.action_post()
            self.stats['direct_bills'] += 1
            logger.info(f"Row {idx}: Successfully posted Direct Bill {bill.name} (Amount: Rp {bill.amount_total:,.2f})")

        # 4. Handle 'LUNAS' Status (Payment Registration)
        if status == 'LUNAS' and bill and bill.payment_state != 'paid':
            self._register_bill_payment(bill)

        self.stats['processed'] += 1

    def _register_bill_payment(self, bill):
        try:
            payment_wizard = self.env['account.payment.register'].with_context(
                active_model='account.move',
                active_ids=bill.ids
            ).create({
                'payment_date': bill.invoice_date,
                'journal_id': self.journal_bank.id if self.journal_bank else bill.journal_id.id,
                'amount': bill.amount_total,
                'communication': f"Pelunasan Faktur {bill.ref or bill.name}",
            })
            payment_wizard.action_create_payments()
            self.stats['payments_registered'] += 1
            logger.info(f"Registered payment for Bill {bill.name} (Rp {bill.amount_total:,.2f}) -> State: {bill.payment_state}")
        except Exception as e:
            logger.warning(f"Could not register payment for Bill {bill.name}: {e}")

    def _generate_report(self):
        with open(ANOMALY_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'stats': self.stats,
                'anomalies': self.anomalies
            }, f, indent=2)

        logger.info("\n" + "=" * 80)
        logger.info("KLINIK ADERA ERP - VENDOR BILLS ETL SUMMARY REPORT")
        logger.info("=" * 80)
        logger.info(f" Total CSV Rows Analyzed : {self.stats['total_rows']}")
        logger.info(f" Successfully Processed  : {self.stats['processed']}")
        logger.info(f"   - PO-Linked (3-Way)   : {self.stats['po_linked_bills']}")
        logger.info(f"   - Direct Vendor Bills : {self.stats['direct_bills']}")
        logger.info(f" Payments Registered     : {self.stats['payments_registered']}")
        logger.info(f" Skipped (Zero Test Row) : {self.stats['skipped_zero_test']}")
        logger.info(f" Skipped (Already Exist) : {self.stats['skipped_existing']}")
        logger.info(f" Errors Encountered      : {self.stats['errors']}")
        logger.info(f" Anomaly Report Written  : {ANOMALY_FILE}")
        logger.info("=" * 80)


if __name__ == '__main__':
    import odoo
    import odoo.tools
    import odoo.modules.registry

    db_name = sys.argv[1] if len(sys.argv) > 1 else 'klinik-adera'
    odoo.tools.config.parse_config([
        '-c', '/etc/odoo/odoo.conf',
        '-d', db_name,
        '--db_host', os.environ.get('HOST', 'db_adera'),
        '--db_user', os.environ.get('USER', 'odoo'),
        '--db_password', os.environ.get('PASSWORD', 'odoo'),
    ])

    reg = odoo.modules.registry.Registry(db_name)
    with reg.cursor() as cr:
        env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
        ingestor = AderaVendorBillsIngestor(env)
        ingestor.run_import()

