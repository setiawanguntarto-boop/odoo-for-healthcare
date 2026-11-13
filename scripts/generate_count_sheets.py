#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
KLINIK ADERA ERP (ODOO 19 CE) - STANDARDIZED PHYSICAL STOCK COUNT SHEET GENERATOR
========================================================================================
Purpose:
  Extracts active clinical products from master catalog and exports two pre-filled,
  standardized CSV count sheet templates for physical shelf audit teams:
  1. stock_count_farmasi_template.csv (Destination: WH/Stock/Farmasi - Analytic: ACC-PRATAMA)
  2. stock_count_hemodialysis_template.csv (Destination: WH/Stock/HD - Analytic: ACC-HD)

Guidelines printed in sheets:
  - Strict FEFO: If multiple lots exist for the same item, record each lot on a separate row.
  - Expiration Date format must be strict ISO YYYY-MM-DD.
  - Quantities must be counted accurately at the physical shelf with counter and verifier initials.
========================================================================================
"""

import os
import sys
import csv
from datetime import datetime

# Path definitions
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else '/mnt/extra-addons/scripts'
BASE_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR = os.path.join(BASE_DIR, 'adera_data', 'stock_count_sheets')


# Outpatient Pharmacy Master Items (Farmasi Rawat Jalan & BHP Medis)
FARMASI_MASTER_PRODUCTS = [
    {
        "product_code": "FAR-AMOX500",
        "product_name": "Amoxicillin 500mg Kaplet",
        "uom_name": "Tablet",
        "packaging_desc": "Box isi 10 strip @ 10 tablet (100 tablet)",
        "conversion_to_base": 100,
        "storage_shelf_rack": "RAK-FAR-A01",
        "category": "Farmasi - Obat Ethical"
    },
    {
        "product_code": "FAR-PARA500",
        "product_name": "Paracetamol 500mg Tablet",
        "uom_name": "Tablet",
        "packaging_desc": "Box isi 10 strip @ 10 tablet (100 tablet)",
        "conversion_to_base": 100,
        "storage_shelf_rack": "RAK-FAR-A02",
        "category": "Farmasi - Obat Bebas & OTC"
    },
    {
        "product_code": "FAR-LANS30",
        "product_name": "Lansoprazole 30mg Kapsul",
        "uom_name": "Kapsul",
        "packaging_desc": "Box isi 3 strip @ 10 kapsul (30 kapsul)",
        "conversion_to_base": 30,
        "storage_shelf_rack": "RAK-FAR-B01",
        "category": "Farmasi - Obat Ethical"
    },
    {
        "product_code": "FAR-ACET200",
        "product_name": "Acetylcysteine 200mg Kapsul",
        "uom_name": "Kapsul",
        "packaging_desc": "Box isi 10 strip @ 10 kapsul (100 kapsul)",
        "conversion_to_base": 100,
        "storage_shelf_rack": "RAK-FAR-B02",
        "category": "Farmasi - Obat Ethical"
    },
    {
        "product_code": "FAR-ACYC200",
        "product_name": "Acyclovir 200mg Tablet",
        "uom_name": "Tablet",
        "packaging_desc": "Box isi 5 strip @ 10 tablet (50 tablet)",
        "conversion_to_base": 50,
        "storage_shelf_rack": "RAK-FAR-B03",
        "category": "Farmasi - Obat Ethical"
    },
    {
        "product_code": "BHP-SYR3CC",
        "product_name": "Spuit 3cc Disposable with Needle",
        "uom_name": "Pcs",
        "packaging_desc": "Box isi 100 pcs spuit 3cc",
        "conversion_to_base": 100,
        "storage_shelf_rack": "RAK-BHP-01",
        "category": "BHP Medis - Rawat Jalan"
    },
    {
        "product_code": "BHP-INF-SET",
        "product_name": "Infusion Set Dewasa Disposable",
        "uom_name": "Pcs",
        "packaging_desc": "Box isi 50 pcs infus set",
        "conversion_to_base": 50,
        "storage_shelf_rack": "RAK-BHP-02",
        "category": "BHP Medis - Rawat Jalan"
    },
    {
        "product_code": "VAC-GARD-9",
        "product_name": "Gardasil 9 HPV Vaccine 0.5ml Suspension",
        "uom_name": "Dosis",
        "packaging_desc": "Single-dose prefilled syringe (1 dosis)",
        "conversion_to_base": 1,
        "storage_shelf_rack": "CHILLER-VAKSIN-01 (2-8 C)",
        "category": "Farmasi - Vaksin & Imunisasi"
    }
]

# Hemodialysis Logistics Master Items (Dialyzer, Bloodline, AV Fistula, Concentrates)
HEMODIALYSIS_MASTER_PRODUCTS = [
    {
        "product_code": "HD-DIAL-140H",
        "product_name": "High-Flux Dialyzer Single-Use (HIPS 1.4m2)",
        "dialyzer_type_or_item": "High-Flux Polysulfone 1.4m2",
        "packaging_desc": "Box isi 24 dialyzer steril",
        "conversion_to_base": 24,
        "uom_name": "Unit",
        "storage_location": "WH/Stock/HD",
        "shelf_zone": "RACK-HD-DIALYZER-A"
    },
    {
        "product_code": "HD-DIAL-180H",
        "product_name": "High-Flux Dialyzer Single-Use (HIPS 1.8m2)",
        "dialyzer_type_or_item": "High-Flux Polysulfone 1.8m2",
        "packaging_desc": "Box isi 24 dialyzer steril",
        "conversion_to_base": 24,
        "uom_name": "Unit",
        "storage_location": "WH/Stock/HD",
        "shelf_zone": "RACK-HD-DIALYZER-B"
    },
    {
        "product_code": "HD-BLD-LINE",
        "product_name": "Blood Tubing Set AV Line for Hemodialysis",
        "dialyzer_type_or_item": "Arterial & Venous Bloodline Set",
        "packaging_desc": "Box isi 30 set steril",
        "conversion_to_base": 30,
        "uom_name": "Set",
        "storage_location": "WH/Stock/HD",
        "shelf_zone": "RACK-HD-BLOODLINE"
    },
    {
        "product_code": "HD-AVF-16G",
        "product_name": "AV Fistula Needle 16G Backeye Fixed Wing",
        "dialyzer_type_or_item": "Fistula Needle 16 Gauge",
        "packaging_desc": "Box isi 50 pasang jarum AVF",
        "conversion_to_base": 50,
        "uom_name": "Pasang",
        "storage_location": "WH/Stock/HD",
        "shelf_zone": "RACK-HD-NEEDLE"
    },
    {
        "product_code": "HD-ACID-10L",
        "product_name": "Cairan Acidic Hemodialisis Plus 10 Liter",
        "dialyzer_type_or_item": "Liquid Acidic Concentrate Gallon",
        "packaging_desc": "Jerigen 10 Liter",
        "conversion_to_base": 1,
        "uom_name": "Jerigen",
        "storage_location": "WH/Stock/HD",
        "shelf_zone": "PALLET-HD-CONCENTRATE-ACID"
    },
    {
        "product_code": "HD-BICARB-CAR",
        "product_name": "Sodium Bicarbonate Dry Cartridge 650g",
        "dialyzer_type_or_item": "Online Bicarbonate Cartridge",
        "packaging_desc": "Box isi 10 cartridge",
        "conversion_to_base": 10,
        "uom_name": "Pcs",
        "storage_location": "WH/Stock/HD",
        "shelf_zone": "PALLET-HD-CONCENTRATE-BIC"
    },
    {
        "product_code": "HD-HEP-5000",
        "product_name": "Heparin Sodium Injection 5000 IU/ml 5ml",
        "dialyzer_type_or_item": "Anticoagulant Vial",
        "packaging_desc": "Box isi 10 vial @ 5ml",
        "conversion_to_base": 10,
        "uom_name": "Vial",
        "storage_location": "WH/Stock/HD",
        "shelf_zone": "CHILLER-HD-MED (2-8 C)"
    }
]


def generate_count_sheets(output_dir=OUTPUT_DIR):
    os.makedirs(output_dir, exist_ok=True)
    print("=" * 85)
    print(" KLINIK ADERA ERP (ODOO 19 CE) - PHYSICAL STOCK COUNT SHEET GENERATOR")
    print(f" Target Directory: {output_dir}")
    print(f" Timestamp       : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 85)

    # 1. Farmasi Template
    farmasi_file = os.path.join(output_dir, "stock_count_farmasi_template.csv")
    farmasi_fields = [
        "product_code",
        "product_name",
        "manufacturer_lot_number",
        "expiration_date_YYYY_MM_DD",
        "physical_qty_boxes_or_strips",
        "packaging_conversion_factor",
        "physical_qty_base_uom",
        "uom_name",
        "storage_shelf_rack",
        "counter_initials",
        "verifier_pharmacist_initials",
        "audit_notes"
    ]
    with open(farmasi_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=farmasi_fields)
        writer.writeheader()
        for prod in FARMASI_MASTER_PRODUCTS:
            writer.writerow({
                "product_code": prod["product_code"],
                "product_name": prod["product_name"],
                "manufacturer_lot_number": "",  # To be filled by field auditor
                "expiration_date_YYYY_MM_DD": "",  # To be filled (YYYY-MM-DD)
                "physical_qty_boxes_or_strips": "",
                "packaging_conversion_factor": prod["conversion_to_base"],
                "physical_qty_base_uom": "",  # Calculated or counted directly in base
                "uom_name": prod["uom_name"],
                "storage_shelf_rack": prod["storage_shelf_rack"],
                "counter_initials": "",
                "verifier_pharmacist_initials": "",
                "audit_notes": f"Satuan Dispensing: {prod['uom_name']} | Kemasan: {prod['packaging_desc']}"
            })
    print(f" [+] Generated Outpatient Pharmacy Template: {farmasi_file}")

    # 2. Hemodialysis Template
    hd_file = os.path.join(output_dir, "stock_count_hemodialysis_template.csv")
    hd_fields = [
        "product_code",
        "product_name",
        "dialyzer_type_or_item",
        "manufacturer_lot_number",
        "sterilization_expiry_date",
        "physical_qty_boxes",
        "packaging_conversion_factor",
        "base_quantity",
        "uom_name",
        "storage_location",
        "shelf_zone",
        "counter_nurse_initials",
        "head_nurse_hd_initials",
        "audit_notes"
    ]
    with open(hd_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=hd_fields)
        writer.writeheader()
        for prod in HEMODIALYSIS_MASTER_PRODUCTS:
            writer.writerow({
                "product_code": prod["product_code"],
                "product_name": prod["product_name"],
                "dialyzer_type_or_item": prod["dialyzer_type_or_item"],
                "manufacturer_lot_number": "",  # To be filled by HD nurse
                "sterilization_expiry_date": "",  # Must be valid sterilization date (YYYY-MM-DD)
                "physical_qty_boxes": "",
                "packaging_conversion_factor": prod["conversion_to_base"],
                "base_quantity": "",  # Base units (Pcs/Unit/Jerigen/Vial)
                "uom_name": prod["uom_name"],
                "storage_location": prod["storage_location"],
                "shelf_zone": prod["shelf_zone"],
                "counter_nurse_initials": "",
                "head_nurse_hd_initials": "",
                "audit_notes": f"Sterilisasi Kritis | Kemasan: {prod['packaging_desc']}"
            })
    print(f" [+] Generated Hemodialysis Depo Template : {hd_file}")
    print("=" * 85)
    print(" [INSTRUCTION FOR CLINICAL TEAMS]:")
    print("  1. Fill manufacturer batch/lot number and expiration date (YYYY-MM-DD) directly from box labels.")
    print("  2. If multiple lots are present on the shelf, add a new row with the same product code.")
    print("  3. Both counter and supervising pharmacist/nurse must sign with initials.")
    print("=" * 85 + "\n")
    return farmasi_file, hd_file


if __name__ == "__main__":
    generate_count_sheets()

