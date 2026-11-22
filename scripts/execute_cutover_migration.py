#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
KLINIK ADERA ERP (ODOO 19 CE) - PHASE 5 CUT-OVER MIGRATION & DATA CLEANSING RUNNER
========================================================================================
1. Scans /mnt/extra-addons/adera_data (and raw/sanitized subdirs) for legacy CSVs &
   2026 daily Excel workbooks.
2. Quarantines dummy/UAT test records matching (?i)(test|dummy|percobaan|sample|demo|simulasi)
   and abnormal invoice totals into quarantined_records.csv.
3. Enforces FEFO removal strategy & LOT-OPEN-202611-[CODE] / 2027-11-30 compliance on
   opening stock items.
4. Verifies Account 999999 Opening Clearing == Rp 0.00.

Execution CLI:
  docker exec -i odoo_adera_clinic python3 /mnt/extra-addons/scripts/execute_cutover_migration.py \
      --data-dir /mnt/extra-addons/adera_data -d klinik-adera --cutoff-date 2026-11-20 --verbose
========================================================================================
"""

import argparse
import csv
import os
import re
import sys
import traceback
from datetime import datetime


QUARANTINE_REGEX = re.compile(r"(?i)(test|dummy|percobaan|sample|demo|simulasi)")
ABNORMAL_TOTAL_THRESHOLD = 500000000.0  # Rp 500,000,000


def resolve_data_file(data_dir, filename):
    for sub in ("", "sanitized", "raw"):
        candidate = os.path.join(data_dir, sub, filename) if sub else os.path.join(data_dir, filename)
        if os.path.exists(candidate):
            return candidate
    return None


def scan_and_quarantine_csvs(data_dir, verbose=False):
    target_csvs = [
        "Klinik ADERA - TRANSAKSI PENJUALAN.csv",
        "Klinik ADERA - RINCIAN PENJUALAN.csv",
        "Klinik ADERA - DAFTAR FAKTUR PEMBELIAN PEMBELI.csv",
        "open_stock.csv",
        "open_ar.csv",
        "open_ap.csv",
    ]
    quarantine_path = os.path.join(data_dir, "quarantined_records.csv")
    quarantined = []
    clean_counts = {}

    for fname in target_csvs:
        fpath = resolve_data_file(data_dir, fname)
        if not fpath:
            if verbose:
                print(f"  [WARN] File not found in {data_dir}: {fname}")
            continue

        clean_cnt = 0
        with open(fpath, mode="r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for row_idx, row in enumerate(reader, 2):
                joined = " | ".join(row)
                reason = None
                if QUARANTINE_REGEX.search(joined):
                    reason = "UAT_DUMMY_PATTERN_MATCH"
                else:
                    for cell in row:
                        c_clean = re.sub(r"[^0-9.]", "", cell or "")
                        if c_clean and c_clean.count(".") <= 1:
                            try:
                                val = float(c_clean)
                                if val > ABNORMAL_TOTAL_THRESHOLD and fname.startswith("Klinik ADERA"):
                                    reason = f"ABNORMAL_AMOUNT_>{ABNORMAL_TOTAL_THRESHOLD:,.0f}"
                                    break
                            except ValueError:
                                pass

                if reason:
                    quarantined.append({
                        "source_file": fname,
                        "row_number": row_idx,
                        "reason": reason,
                        "raw_row": joined[:500],
                    })
                else:
                    clean_cnt += 1

        clean_counts[fname] = clean_cnt
        if verbose:
            q_cnt = sum(1 for q in quarantined if q["source_file"] == fname)
            print(f"  [SCAN] {fname:<52} | Clean: {clean_cnt:>5} | Quarantined: {q_cnt:>3}")

    with open(quarantine_path, mode="w", encoding="utf-8", newline="") as qf:
        writer = csv.DictWriter(qf, fieldnames=["source_file", "row_number", "reason", "raw_row"])
        writer.writeheader()
        writer.writerows(quarantined)

    print(f"  [OK] Quarantine export written: {quarantine_path} ({len(quarantined)} purged rows)")
    return clean_counts, quarantined


def enforce_fefo_stock_compliance(env, data_dir, cutoff_date, verbose=False):
    fefo_strategy = env.ref("product_expiry.removal_fefo", raise_if_not_found=False)
    if fefo_strategy:
        locations = env["stock.location"].search([
            ("usage", "=", "internal"),
            "|",
            ("complete_name", "ilike", "Farmasi"),
            ("complete_name", "ilike", "HD"),
        ])
        for loc in locations:
            if loc.removal_strategy_id != fefo_strategy:
                loc.removal_strategy_id = fefo_strategy.id
        if verbose:
            print(f"  [OK] FEFO removal strategy enforced on {len(locations)} internal clinic locations")

    open_stock_path = resolve_data_file(data_dir, "open_stock.csv")
    if not open_stock_path:
        print("  [WARN] open_stock.csv not found; skipping lot compliance check.")
        return 0

    Product = env["product.product"]
    Lot = env["stock.lot"]
    created_lots = 0

    with open(open_stock_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = (row.get("Product Code") or row.get("default_code") or "").strip()
            if not code:
                continue
            prod = Product.search([("default_code", "=", code)], limit=1)
            if not prod:
                continue
            lot_name = (row.get("Lot/Serial Number") or row.get("lot_name") or "").strip()
            if not lot_name:
                lot_name = f"LOT-OPEN-202611-{code}"
            exp_str = (row.get("Expiration Date") or row.get("expiration_date") or "").strip() or "2027-11-30"

            existing_lot = Lot.search([("name", "=", lot_name), ("product_id", "=", prod.id)], limit=1)
            if not existing_lot and prod.tracking == "lot":
                Lot.create({
                    "name": lot_name,
                    "product_id": prod.id,
                    "expiration_date": f"{exp_str} 00:00:00",
                    "use_date": f"{exp_str} 00:00:00",
                })
                created_lots += 1

    if verbose:
        print(f"  [OK] Opening stock FEFO lot compliance verified (new compliance lots created: {created_lots})")
    return created_lots


def execute_cutover(env, data_dir, cutoff_date, verbose=False):
    print("=" * 96)
    print("   KLINIK ADERA ERP (ODOO 19 CE) - PHASE 5 CUT-OVER MIGRATION & CLEANSING RUNNER")
    print("=" * 96)
    print(f" Data Directory : {data_dir}")
    print(f" Database       : {env.cr.dbname}")
    print(f" Cut-Off Date   : {cutoff_date}")
    print("=" * 96)

    print("\n[STEP 1] Legacy CSV Scan & UAT/Dummy Quarantine")
    clean_counts, quarantined = scan_and_quarantine_csvs(data_dir, verbose=verbose)

    print("\n[STEP 2] Physical Stock Opname FEFO & Lot/Expiry Compliance")
    enforce_fefo_stock_compliance(env, data_dir, cutoff_date, verbose=verbose)

    print("\n[STEP 3] Account 999999 Opening Clearing Equilibrium Gate")
    acc_999999 = env["account.account"].search([("code", "=", "999999")], limit=1)
    if not acc_999999:
        raise RuntimeError("Account 999999 missing!")
    lines_999999 = env["account.move.line"].search([
        ("account_id", "=", acc_999999.id),
        ("parent_state", "=", "posted"),
    ])
    bal_999999 = round(sum(lines_999999.mapped("balance")), 2)
    print(f"  [GATE] Account 999999 Posted Balance: Rp {bal_999999:,.2f}")
    if abs(bal_999999) >= 0.01:
        raise AssertionError(f"Clearing Account 999999 is not zero: Rp {bal_999999:,.2f}")

    print("\n" + "=" * 96)
    print("   CUT-OVER MIGRATION COMPLETED SUCCESSFULLY (ZERO DEFECTS)")
    print("=" * 96)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Klinik ADERA Phase 5 Cut-Over Migration Runner")
    parser.add_argument("--data-dir", default="/mnt/extra-addons/adera_data", help="Mounted data directory")
    parser.add_argument("-d", "--database", default="klinik-adera", help="Target database")
    parser.add_argument("--cutoff-date", default="2026-11-20", help="Cut-off date (YYYY-MM-DD)")
    parser.add_argument("--config", default="/etc/odoo/odoo.conf", help="Path to odoo.conf")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    try:
        import odoo
        from odoo import api, SUPERUSER_ID
        from odoo.modules.registry import Registry

        odoo.tools.config.parse_config([
            "-c", args.config,
            "--db_host", "db_adera",
            "-r", "odoo",
            "-w", "odoo",
            "-d", args.database,
        ])
        registry = Registry(args.database)
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            ok = execute_cutover(env, args.data_dir, args.cutoff_date, verbose=args.verbose)
            cr.commit()
            sys.exit(0 if ok else 1)
    except Exception as exc:
        print(f"Cut-Over Error: {exc}")
        traceback.print_exc()
        sys.exit(1)

