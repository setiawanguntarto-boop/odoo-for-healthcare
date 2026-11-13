#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
KLINIK ADERA ERP (ODOO 19 CE) - PHYSICAL STOCK AUDIT PARSER & FEFO NORMALIZER
========================================================================================
Purpose:
  Ingests filled physical stock count sheets from Pharmacy and Hemodialysis teams:
  - Validates mandatory lot/batch identifiers (rejects blank, dummy, test values).
  - Validates expiration dates (strict ISO YYYY-MM-DD, checks future validity, flags near-expiry).
  - Converts packaging units (boxes/strips) into base dispensing units (Tablet, Pcs, etc.).
  - Merges perpetual FIFO standard unit costs and assigns analytic account distributions.
  - Outputs production-ready 'adera_data/sanitized/open_stock.csv' formatted for Odoo 19 CE.

Usage:
  python scripts/parse_physical_stock_audit.py \
    --input-farmasi adera_data/filled_sheets/farmasi.csv \
    --input-hd adera_data/filled_sheets/hd.csv \
    --output adera_data/sanitized/open_stock.csv
========================================================================================
"""

import os
import sys
import csv
import re
import argparse
from datetime import datetime, date

# Standard Cut-Off Date for Opening Balances: 2026-10-31
DEFAULT_CUT_OFF_DATE = date(2026, 10, 31)

# Master Procurement Contract Unit Costs & Analytic Distribution
# Farmasi: WH/Stock/Farmasi (Analytic: ACC-PRATAMA ID: 1)
# HD: WH/Stock/HD (Analytic: ACC-HD ID: 8)
MASTER_COST_AND_ANALYTIC = {
    # Outpatient Primary Care
    "FAR-AMOX500": {
        "name": "Amoxicillin 500mg Kaplet",
        "unit_cost": 650.0,
        "base_uom": "Tablet",
        "category_code": "01-PHARMA",
        "location": "WH/Stock/Farmasi",
        "account_code": "113010",
        "analytic_code": "ACC-PRATAMA",
        "analytic_id": 1
    },
    "FAR-PARA500": {
        "name": "Paracetamol 500mg Tablet",
        "unit_cost": 450.0,
        "base_uom": "Tablet",
        "category_code": "01-PHARMA",
        "location": "WH/Stock/Farmasi",
        "account_code": "113010",
        "analytic_code": "ACC-PRATAMA",
        "analytic_id": 1
    },
    "FAR-LANS30": {
        "name": "Lansoprazole 30mg Kapsul",
        "unit_cost": 2200.0,
        "base_uom": "Kapsul",
        "category_code": "01-PHARMA",
        "location": "WH/Stock/Farmasi",
        "account_code": "113010",
        "analytic_code": "ACC-PRATAMA",
        "analytic_id": 1
    },
    "FAR-ACET200": {
        "name": "Acetylcysteine 200mg Kapsul",
        "unit_cost": 1800.0,
        "base_uom": "Kapsul",
        "category_code": "01-PHARMA",
        "location": "WH/Stock/Farmasi",
        "account_code": "113010",
        "analytic_code": "ACC-PRATAMA",
        "analytic_id": 1
    },
    "FAR-ACYC200": {
        "name": "Acyclovir 200mg Tablet",
        "unit_cost": 900.0,
        "base_uom": "Tablet",
        "category_code": "01-PHARMA",
        "location": "WH/Stock/Farmasi",
        "account_code": "113010",
        "analytic_code": "ACC-PRATAMA",
        "analytic_id": 1
    },
    "BHP-SYR3CC": {
        "name": "Spuit 3cc Disposable with Needle",
        "unit_cost": 2800.0,
        "base_uom": "Pcs",
        "category_code": "02-CONSUMABLES",
        "location": "WH/Stock/Farmasi",
        "account_code": "113010",
        "analytic_code": "ACC-PRATAMA",
        "analytic_id": 1
    },
    "BHP-INF-SET": {
        "name": "Infusion Set Dewasa Disposable",
        "unit_cost": 6500.0,
        "base_uom": "Pcs",
        "category_code": "02-CONSUMABLES",
        "location": "WH/Stock/Farmasi",
        "account_code": "113010",
        "analytic_code": "ACC-PRATAMA",
        "analytic_id": 1
    },
    "VAC-GARD-9": {
        "name": "Gardasil 9 HPV Vaccine 0.5ml Suspension",
        "unit_cost": 2150000.0,
        "base_uom": "Dosis",
        "category_code": "04-VACCINES",
        "location": "WH/Stock/Farmasi",
        "account_code": "113010",
        "analytic_code": "ACC-PRATAMA",
        "analytic_id": 1
    },

    # Hemodialysis Logistics
    "HD-DIAL-140H": {
        "name": "High-Flux Dialyzer Single-Use (HIPS 1.4m2)",
        "unit_cost": 285000.0,
        "base_uom": "Unit",
        "category_code": "03-HEMODIALYSIS",
        "location": "WH/Stock/HD",
        "account_code": "113020",
        "analytic_code": "ACC-HD",
        "analytic_id": 8
    },
    "HD-DIAL-180H": {
        "name": "High-Flux Dialyzer Single-Use (HIPS 1.8m2)",
        "unit_cost": 340000.0,
        "base_uom": "Unit",
        "category_code": "03-HEMODIALYSIS",
        "location": "WH/Stock/HD",
        "account_code": "113020",
        "analytic_code": "ACC-HD",
        "analytic_id": 8
    },
    "HD-BLD-LINE": {
        "name": "Blood Tubing Set AV Line for Hemodialysis",
        "unit_cost": 65000.0,
        "base_uom": "Set",
        "category_code": "03-HEMODIALYSIS",
        "location": "WH/Stock/HD",
        "account_code": "113020",
        "analytic_code": "ACC-HD",
        "analytic_id": 8
    },
    "HD-AVF-16G": {
        "name": "AV Fistula Needle 16G Backeye Fixed Wing",
        "unit_cost": 18500.0,
        "base_uom": "Pasang",
        "category_code": "03-HEMODIALYSIS",
        "location": "WH/Stock/HD",
        "account_code": "113020",
        "analytic_code": "ACC-HD",
        "analytic_id": 8
    },
    "HD-ACID-10L": {
        "name": "Cairan Acidic Hemodialisis Plus 10 Liter",
        "unit_cost": 145000.0,
        "base_uom": "Jerigen",
        "category_code": "03-HEMODIALYSIS",
        "location": "WH/Stock/HD",
        "account_code": "113020",
        "analytic_code": "ACC-HD",
        "analytic_id": 8
    },
    "HD-BICARB-CAR": {
        "name": "Sodium Bicarbonate Dry Cartridge 650g",
        "unit_cost": 85000.0,
        "base_uom": "Pcs",
        "category_code": "03-HEMODIALYSIS",
        "location": "WH/Stock/HD",
        "account_code": "113020",
        "analytic_code": "ACC-HD",
        "analytic_id": 8
    },
    "HD-HEP-5000": {
        "name": "Heparin Sodium Injection 5000 IU/ml 5ml",
        "unit_cost": 42000.0,
        "base_uom": "Vial",
        "category_code": "03-HEMODIALYSIS",
        "location": "WH/Stock/HD",
        "account_code": "113020",
        "analytic_code": "ACC-HD",
        "analytic_id": 8
    }
}


def validate_lot_number(lot):
    if not lot:
        return False, "Lot number is empty"
    lot_clean = str(lot).strip()
    if len(lot_clean) < 3 or lot_clean.lower() in ["-", "none", "test", "0", "dummy", "null", "n/a"]:
        return False, f"Invalid placeholder lot '{lot_clean}'"
    return True, lot_clean


def validate_expiration_date(exp_str, cut_off_date=DEFAULT_CUT_OFF_DATE):
    if not exp_str:
        return False, None, "Expiration date is empty"
    exp_str = str(exp_str).strip()
    try:
        exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
    except ValueError:
        return False, None, f"Invalid date format '{exp_str}'. Must be YYYY-MM-DD"

    if exp_date <= cut_off_date:
        return False, exp_date, f"Expired on or before cut-off date ({exp_date} <= {cut_off_date})"

    delta_days = (exp_date - cut_off_date).days
    is_near_expiry = delta_days <= 60
    return True, exp_date, is_near_expiry


def parse_physical_stock(farmasi_csv, hd_csv, output_csv, cut_off_date=DEFAULT_CUT_OFF_DATE):
    print("\n" + "=" * 90)
    print("      KLINIK ADERA ERP (ODOO 19 CE) - PHYSICAL STOCK AUDIT PARSER")
    print("=" * 90)
    print(f" Cut-Off Date    : {cut_off_date.strftime('%Y-%m-%d')}")
    print(f" Farmasi Source  : {farmasi_csv}")
    print(f" HD Source       : {hd_csv}")
    print(f" Output Path     : {output_csv}")
    print("=" * 90)

    clean_records = []
    line_index = 1
    total_debit_farmasi = 0.0
    total_debit_hd = 0.0
    near_expiry_items = []

    # 1. PROCESS FARMASI COUNT SHEET
    if os.path.exists(farmasi_csv):
        print("\n--- [1/2] Processing Pharmacy Sheet (WH/Stock/Farmasi) ---")
        with open(farmasi_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row_no, row in enumerate(reader, start=2):
                code = row.get("product_code", "").strip()
                if not code:
                    continue

                if code not in MASTER_COST_AND_ANALYTIC:
                    print(f"  [!] Row {row_no}: Unknown product_code '{code}'. Skipping.")
                    continue

                meta = MASTER_COST_AND_ANALYTIC[code]

                # Validate Lot
                lot_raw = row.get("manufacturer_lot_number", "")
                lot_ok, lot_val = validate_lot_number(lot_raw)
                if not lot_ok:
                    raise ValueError(f"Pharmacy Sheet Row {row_no} [{code}]: {lot_val}")

                # Validate Expiry Date
                exp_raw = row.get("expiration_date_YYYY_MM_DD", "")
                exp_ok, exp_date, exp_info = validate_expiration_date(exp_raw, cut_off_date)
                if not exp_ok:
                    raise ValueError(f"Pharmacy Sheet Row {row_no} [{code}]: {exp_info}")
                if exp_info is True:
                    near_expiry_items.append((code, meta["name"], lot_val, exp_date))

                # Compute Base Quantity
                base_qty = 0.0
                qty_base_raw = row.get("physical_qty_base_uom", "").strip()
                if qty_base_raw:
                    base_qty = float(qty_base_raw)
                else:
                    boxes = float(row.get("physical_qty_boxes_or_strips", 0))
                    factor = float(row.get("packaging_conversion_factor", 1))
                    base_qty = boxes * factor

                if base_qty <= 0:
                    raise ValueError(f"Pharmacy Sheet Row {row_no} [{code}]: Quantity must be > 0 (found {base_qty})")

                unit_cost = meta["unit_cost"]
                line_val = round(base_qty * unit_cost, 2)
                total_debit_farmasi += line_val

                clean_records.append({
                    "id": f"stock_init_{line_index:03d}",
                    "product_id/default_code": code,
                    "location_id/complete_name": meta["location"],
                    "lot_id/name": lot_val,
                    "lot_id/expiration_date": f"{exp_date.strftime('%Y-%m-%d')} 00:00:00",
                    "inventory_quantity": base_qty,
                    "product_uom_id/name": meta["base_uom"],
                    "unit_cost": unit_cost,
                    "total_valuation": line_val,
                    "account_code": meta["account_code"],
                    "analytic_distribution": f'{{"{meta["analytic_id"]}": 100.0}}'
                })
                print(f"  [+] Line {line_index:02d}: {code} | {meta['name']} | Qty: {base_qty:,.0f} {meta['base_uom']} | Lot: {lot_val} | Exp: {exp_date} | Val: Rp {line_val:,.2f}")
                line_index += 1
    else:
        raise FileNotFoundError(f"Farmasi sheet not found: {farmasi_csv}")

    # 2. PROCESS HEMODIALYSIS COUNT SHEET
    if os.path.exists(hd_csv):
        print("\n--- [2/2] Processing Hemodialysis Sheet (WH/Stock/HD) ---")
        with open(hd_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row_no, row in enumerate(reader, start=2):
                code = row.get("product_code", "").strip()
                if not code:
                    continue

                if code not in MASTER_COST_AND_ANALYTIC:
                    print(f"  [!] Row {row_no}: Unknown product_code '{code}'. Skipping.")
                    continue

                meta = MASTER_COST_AND_ANALYTIC[code]

                # Validate Lot
                lot_raw = row.get("manufacturer_lot_number", "")
                lot_ok, lot_val = validate_lot_number(lot_raw)
                if not lot_ok:
                    raise ValueError(f"HD Sheet Row {row_no} [{code}]: {lot_val}")

                # Validate Expiry Date
                exp_raw = row.get("sterilization_expiry_date", "")
                exp_ok, exp_date, exp_info = validate_expiration_date(exp_raw, cut_off_date)
                if not exp_ok:
                    raise ValueError(f"HD Sheet Row {row_no} [{code}]: {exp_info}")
                if exp_info is True:
                    near_expiry_items.append((code, meta["name"], lot_val, exp_date))

                # Compute Base Quantity
                base_qty = 0.0
                base_raw = row.get("base_quantity", "").strip()
                if base_raw:
                    base_qty = float(base_raw)
                else:
                    boxes = float(row.get("physical_qty_boxes", 0))
                    factor = float(row.get("packaging_conversion_factor", 1))
                    base_qty = boxes * factor

                if base_qty <= 0:
                    raise ValueError(f"HD Sheet Row {row_no} [{code}]: Quantity must be > 0 (found {base_qty})")

                unit_cost = meta["unit_cost"]
                line_val = round(base_qty * unit_cost, 2)
                total_debit_hd += line_val

                clean_records.append({
                    "id": f"stock_init_{line_index:03d}",
                    "product_id/default_code": code,
                    "location_id/complete_name": meta["location"],
                    "lot_id/name": lot_val,
                    "lot_id/expiration_date": f"{exp_date.strftime('%Y-%m-%d')} 00:00:00",
                    "inventory_quantity": base_qty,
                    "product_uom_id/name": meta["base_uom"],
                    "unit_cost": unit_cost,
                    "total_valuation": line_val,
                    "account_code": meta["account_code"],
                    "analytic_distribution": f'{{"{meta["analytic_id"]}": 100.0}}'
                })
                print(f"  [+] Line {line_index:02d}: {code} | {meta['name']} | Qty: {base_qty:,.0f} {meta['base_uom']} | Lot: {lot_val} | Exp: {exp_date} | Val: Rp {line_val:,.2f}")
                line_index += 1
    else:
        raise FileNotFoundError(f"HD sheet not found: {hd_csv}")

    # 3. WRITE SANITIZED OPEN_STOCK.CSV
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    out_fields = [
        "id",
        "product_id/default_code",
        "location_id/complete_name",
        "lot_id/name",
        "lot_id/expiration_date",
        "inventory_quantity",
        "product_uom_id/name",
        "unit_cost",
        "total_valuation",
        "account_code",
        "analytic_distribution"
    ]
    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(clean_records)

    total_inventory_valuation = total_debit_farmasi + total_debit_hd

    print("\n" + "=" * 90)
    print("      AUDIT RECONCILIATION SUMMARY & ACCOUNTING EQUILIBRIUM")
    print("=" * 90)
    print(f" Total Physical Stock Lines Parsed   : {len(clean_records)} lines")
    print(f" Total Farmasi Debit (Account 113010): Rp {total_debit_farmasi:,.2f} [ACC-PRATAMA]")
    print(f" Total HD Consumables (Account 113020): Rp {total_debit_hd:,.2f} [ACC-HD]")
    print(f" TOTAL INVENTORY VALUATION ASSET      : Rp {total_inventory_valuation:,.2f}")
    print(f" Offsetting Credit to Clearing 999999 : Rp {total_inventory_valuation:,.2f}")
    if near_expiry_items:
        print(f"\n [!] WARNING: {len(near_expiry_items)} items detected within 60 days of cut-off date:")
        for it in near_expiry_items:
            print(f"     - {it[0]}: {it[1]} (Lot: {it[2]}, Exp: {it[3]})")
    print("=" * 90 + "\n")

    return clean_records, total_debit_farmasi, total_debit_hd, total_inventory_valuation


def main():
    parser = argparse.ArgumentParser(description="Parse and validate physical stock count sheets.")
    parser.add_argument("--input-farmasi", default="adera_data/filled_sheets/farmasi.csv", help="Path to filled farmasi CSV")
    parser.add_argument("--input-hd", default="adera_data/filled_sheets/hd.csv", help="Path to filled HD CSV")
    parser.add_argument("--output", default="adera_data/sanitized/open_stock.csv", help="Path to output open_stock.csv")
    args = parser.parse_args()

    parse_physical_stock(args.input_farmasi, args.input_hd, args.output)


if __name__ == "__main__":
    main()
