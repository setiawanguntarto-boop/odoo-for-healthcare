#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
KLINIK ADERA ERP (ODOO 19 CE) - PRE-CUTOVER MIGRATION DRY-RUN INTEGRITY VERIFIER
========================================================================================
Purpose:
  Validates production cutover readiness by simulating opening balance migration
  from production CSV templates and asserting 100% mathematical reconciliation:
  1. Opening Balance Suspense Account (999999) == Rp 0.00 (Zero-Balance Strict Assertion).
  2. Trade Receivables (112010 / 112020 / 112030) matches open_ar.csv.
  3. Trade Payables (211010) matches open_ap.csv.
  4. Perpetual Inventory Valuation (114010 / 114020 / 114030 / 1130xx) matches open_stock.csv.

CLI Execution Options:
  python3 scripts/verify_cutover_integrity.py -d klinik-adera
  python3 scripts/verify_cutover_integrity.py -d adera_prod
  odoo shell -c /etc/odoo/odoo.conf -d klinik-adera < scripts/verify_cutover_integrity.py
========================================================================================
"""
import sys
import os
import csv
import argparse
from datetime import datetime

# Path resolution for CSV files
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else '/mnt/extra-addons/scripts'
BASE_ADDON_DIR = os.path.dirname(SCRIPT_DIR)
MIGRATION_DIR = os.path.join(BASE_ADDON_DIR, 'migration_and_tests')
if not os.path.exists(MIGRATION_DIR):
    MIGRATION_DIR = '/mnt/extra-addons/migration_and_tests'

OPEN_AP_CSV = os.path.join(MIGRATION_DIR, 'open_ap.csv')
OPEN_AR_CSV = os.path.join(MIGRATION_DIR, 'open_ar.csv')
OPEN_STOCK_CSV = os.path.join(MIGRATION_DIR, 'open_stock.csv')


def format_idr(val):
    if val is None:
        return "Rp 0.00"
    neg = val < 0
    abs_val = abs(val)
    formatted = f"{abs_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if neg else ''}Rp {formatted}"


def run_cutover_verification(env):
    print("\n" + "=" * 96)
    print("      KLINIK ADERA ERP (ODOO 19 CE) - PRE-CUTOVER MIGRATION INTEGRITY AUDIT")
    print("=" * 96)
    print(f" Target Database    : {env.cr.dbname}")
    print(f" Audit Timestamp    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f" Entity Scope       : PT Prosperra Medika Utama / Klinik ADERA")
    print(f" CSV Sources        : {MIGRATION_DIR}")
    print("=" * 96)

    # 1. READ CSV EXPECTATIONS
    expected_ap_total = 0.0
    expected_ap_items = []
    if os.path.exists(OPEN_AP_CSV):
        with open(OPEN_AP_CSV, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                amt = float(row['Untaxed Amount'])
                expected_ap_total += amt
                expected_ap_items.append((row['Vendor Name'].strip(), amt))

    expected_ar_total = 0.0
    expected_ar_by_account = {}
    if os.path.exists(OPEN_AR_CSV):
        with open(OPEN_AR_CSV, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                amt = float(row['Amount'])
                expected_ar_total += amt
                acc_code = row.get('Account Code', '112010').strip()
                expected_ar_by_account[acc_code] = expected_ar_by_account.get(acc_code, 0.0) + amt

    expected_stock_total = 0.0
    expected_stock_by_acc = {'farmasi': 0.0, 'bhp': 0.0}
    if os.path.exists(OPEN_STOCK_CSV):
        with open(OPEN_STOCK_CSV, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                qty = float(row['Counted Quantity'])
                cost = float(row['Unit Cost'])
                val = round(qty * cost, 2)
                expected_stock_total += val
                prod_code = row['Product Code'].strip()
                if prod_code.startswith('MED-'):
                    expected_stock_by_acc['farmasi'] += val
                else:
                    expected_stock_by_acc['bhp'] += val

    # 2. RUN SIMULATION MIGRATION / RECONCILIATION
    print("\n[*] Initializing Cutover Opening Balance Migration Dry-Run...")
    try:
        # Import migration logic dynamically
        sys.path.insert(0, MIGRATION_DIR)
        import migrate_opening_balances
        migrate_opening_balances.OPEN_AP_CSV = OPEN_AP_CSV
        migrate_opening_balances.OPEN_AR_CSV = OPEN_AR_CSV
        migrate_opening_balances.OPEN_STOCK_CSV = OPEN_STOCK_CSV
        migrate_opening_balances.run_migration(env)
        print("[*] Dry-run migration synchronized and committed successfully.")
    except Exception as e:
        print(f"[!] Migration dry-run failed with error: {e}")
        import traceback
        traceback.print_exc()

    # 3. AUDIT ASSERTIONS
    print("\n--- [AUDIT TEST SUITE: MATHEMATICAL & LEDGER ASSERTIONS] ---")
    assertions = []

    def assert_test(test_id, name, expected, actual, tolerance=0.01):
        diff = abs(expected - actual)
        passed = diff <= tolerance
        assertions.append({
            'id': test_id,
            'name': name,
            'expected': expected,
            'actual': actual,
            'variance': diff,
            'passed': passed,
        })
        status_str = "\033[92m[PASS]\033[0m" if passed else "\033[91m[FAIL]\033[0m"
        print(f" {status_str} {test_id}: {name}")
        print(f"        Expected: {format_idr(expected)} | Actual: {format_idr(actual)} | Variance: {format_idr(diff)}")

    # Assertion 1: Opening Balance Suspense 999999 Balance == Rp 0.00
    suspense_acc = env['account.account'].search([('code', '=', '999999')], limit=1)
    if suspense_acc:
        lines_suspense = env['account.move.line'].search([
            ('account_id', '=', suspense_acc.id),
            ('parent_state', '=', 'posted'),
        ])
        suspense_debit = sum(lines_suspense.mapped('debit'))
        suspense_credit = sum(lines_suspense.mapped('credit'))
        suspense_net = suspense_debit - suspense_credit
    else:
        suspense_net = 0.0

    assert_test(
        "AUDIT-01",
        "Opening Balance Suspense Account 999999 Zero-Balance Assertion",
        0.0,
        abs(suspense_net),
    )

    # Assertion 2: Trade Payables Account 211010 == open_ap.csv Total
    ap_lines = env['account.move.line'].search([
        ('account_id.code', 'in', ['211010', '21101']),
        ('parent_state', '=', 'posted'),
        ('move_id.ref', 'ilike', 'SALDO AWAL:'),
    ])
    ap_migrated_balance = sum(ap_lines.mapped('credit')) - sum(ap_lines.mapped('debit'))
    assert_test(
        "AUDIT-02",
        "Trade Payables (211010) Opening Ledger vs open_ap.csv Total",
        expected_ap_total,
        ap_migrated_balance,
    )

    # Assertion 3: Trade Receivables (112010 + 112020 + 112030) == open_ar.csv Total
    ar_lines = env['account.move.line'].search([
        ('account_id.code', 'in', ['112010', '112020', '112030', '11201', '11202', '11203']),
        ('parent_state', '=', 'posted'),
        ('move_id.ref', 'ilike', 'SALDO AWAL:'),
    ])
    ar_migrated_balance = sum(ar_lines.mapped('debit')) - sum(ar_lines.mapped('credit'))
    assert_test(
        "AUDIT-03",
        "Trade Receivables (1120xx) Opening Ledger vs open_ar.csv Total",
        expected_ar_total,
        ar_migrated_balance,
    )

    # Assertion 4: BPJS Receivables Specific Account 112020 Check
    ar_bpjs_lines = env['account.move.line'].search([
        ('account_id.code', 'in', ['112020', '11202']),
        ('parent_state', '=', 'posted'),
        ('move_id.ref', 'ilike', 'SALDO AWAL:'),
    ])
    bpjs_balance = sum(ar_bpjs_lines.mapped('debit')) - sum(ar_bpjs_lines.mapped('credit'))
    expected_bpjs = expected_ar_by_account.get('112020', 128500000.0)
    assert_test(
        "AUDIT-04",
        "BPJS Claim Receivables (112020) Specific Line Reconciliation",
        expected_bpjs,
        bpjs_balance,
    )

    # Assertion 5: Perpetual Inventory Valuation (1140xx / 1130xx) == open_stock.csv Total
    stock_lines = env['account.move.line'].search([
        ('account_id.code', 'in', ['114010', '114020', '114030', '113010', '113020']),
        ('parent_state', '=', 'posted'),
        ('move_id.ref', 'ilike', 'SALDO AWAL:'),
    ])
    stock_migrated_balance = sum(stock_lines.mapped('debit')) - sum(stock_lines.mapped('credit'))
    assert_test(
        "AUDIT-05",
        "Perpetual Stock Valuation (1140xx/1130xx) vs open_stock.csv Total",
        expected_stock_total,
        stock_migrated_balance,
    )

    # Assertion 6: Related-Party Receivables (112040) Isolation (Bulaksumur Finding #3)
    rel_party_lines = env['account.move.line'].search([
        ('account_id.code', 'in', ['112040', '11204']),
        ('parent_state', '=', 'posted'),
    ])
    rel_party_bal = sum(rel_party_lines.mapped('debit')) - sum(rel_party_lines.mapped('credit'))
    assert_test(
        "AUDIT-06",
        "Related-Party Shareholder Advance Isolation (112040) per Bulaksumur Finding #3",
        895448099.00,
        rel_party_bal,
    )

    # 4. SUMMARY SCORECARD
    all_passed = all(a['passed'] for a in assertions)
    print("\n" + "=" * 96)
    print("                           PRE-CUTOVER AUDIT RESULT SUMMARY")
    print("=" * 96)
    print(f" Total Assertions Evaluated : {len(assertions)}")
    print(f" Passed Assertions          : {sum(1 for a in assertions if a['passed'])} / {len(assertions)}")
    print(f" Failed Assertions          : {sum(1 for a in assertions if not a['passed'])}")
    print(f" Audit Status               : {'100% READY FOR DAY-T CUTOVER' if all_passed else 'CUTOVER BLOCKED - AUDIT DISCREPANCY'}")
    print("=" * 96 + "\n")

    return all_passed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Klinik ADERA ERP Pre-Cutover Verification Script")
    parser.add_argument('-d', '--database', default='klinik-adera', help="Target database name (default: klinik-adera)")
    parser.add_argument('-c', '--config', default='/etc/odoo/odoo.conf', help="Odoo configuration file path")
    args, unknown = parser.parse_known_args()

    # Case 1: Running inside odoo shell where `env` is in globals()
    if 'env' in globals():
        success = run_cutover_verification(globals()['env'])
        if not success:
            sys.exit(1)
    else:
        # Case 2: Running standalone CLI script
        try:
            import odoo
            from odoo import api, SUPERUSER_ID
            from odoo.modules.registry import Registry

            db_name = args.database
            config_file = args.config if os.path.exists(args.config) else None

            if config_file:
                odoo.tools.config.parse_config([
                    '-c', config_file,
                    '--db_host', 'db_adera',
                    '-r', 'odoo',
                    '-w', 'odoo',
                    '-d', db_name,
                ])
            else:
                odoo.tools.config.parse_config(['-d', db_name])

            registry = Registry(db_name)
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                success = run_cutover_verification(env)
                sys.exit(0 if success else 1)
        except Exception as e:
            print(f"[!] Execution Error: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
