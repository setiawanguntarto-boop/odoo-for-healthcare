#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
KLINIK ADERA ERP (ODOO 19 CE) - PHASE 2 OPENING BALANCE CALIBRATION ENGINE
========================================================================================
Establishes verified baseline balances across Treasury (Cash Vault, Imprest Petty Cash,
BRI 569/300/561, Mandiri, BSI 77858, BPD DIY), Liabilities (221010), and Equity
(310010, 310020, 320010), enforcing strict Rp 0.00 equilibrium on Clearing Account 999999.

Execution CLI:
  docker exec -i odoo_adera_clinic python3 /mnt/extra-addons/scripts/migrate_opening_balances.py \
      --config /etc/odoo/odoo.conf -d klinik-adera --verify-zero-clearing
========================================================================================
"""

import argparse
import os
import sys
import traceback
from datetime import date


def calibrate_opening_balances(env, verify_only=False, dry_run=False):
    Account = env["account.account"]
    Journal = env["account.journal"]
    Move = env["account.move"]
    MoveLine = env["account.move.line"]

    print("=" * 92)
    print("   KLINIK ADERA ERP - PHASE 2 OPENING BALANCE CALIBRATION & 999999 ZERO-CLEARING AUDIT")
    print("=" * 92)
    print(f" Database : {env.cr.dbname}")
    print("=" * 92)

    clearing_acc = Account.search([("code", "=", "999999")], limit=1)
    if not clearing_acc:
        raise RuntimeError("CRITICAL: Clearing Account 999999 not found in Chart of Accounts!")

    misc_journal = Journal.search([("code", "in", ["MISC", "MISCL"])], limit=1)
    if not misc_journal:
        misc_journal = Journal.search([("type", "=", "general")], limit=1)
    if not misc_journal:
        raise RuntimeError("CRITICAL: General/MISC Journal not found!")

    existing_op = Move.search([("ref", "=", "OP/2026/001"), ("state", "=", "posted")], limit=1)
    if not verify_only and not existing_op:
        # Calibrated opening baseline (Assets = Liabilities + Equity, routed through 999999)
        baseline_lines = [
            # Debit: Treasury Baseline
            ("111010", "Saldo Awal Kas Besar (Central Vault)", 5000000.0, 0.0),
            ("111020", "Saldo Awal Kas Kecil Imprest (Ceiling Rp 2.000.000)", 2000000.0, 0.0),
            ("111120", "Saldo Awal Bank BRI 569 - Operasional Utama", 125000000.0, 0.0),
            ("111121", "Saldo Awal Bank BRI 300 - Payroll & Cadangan", 45000000.0, 0.0),
            ("111122", "Saldo Awal Bank BRI 561 - Depo Operasional", 18000000.0, 0.0),
            ("111130", "Saldo Awal Bank Mandiri Operasional", 35000000.0, 0.0),
            ("111140", "Saldo Awal Bank Syariah Indonesia (BSI 77858)", 22000000.0, 0.0),
            ("111150", "Saldo Awal BPD DIY Liquidity Reserve", 15000000.0, 0.0),
            # Debit: YTD Prive (Direct Equity Debit)
            ("310020", "Saldo Awal Prive Pemilik (YTD)", 10000000.0, 0.0),
            # Credit: Liabilities & Equity Baseline
            ("221010", "Saldo Awal Utang Pokok Pinjaman Bank Jangka Panjang", 0.0, 120000000.0),
            ("310010", "Kalibrasi Modal Disetor Pemilik (Dr. Raudi Akmal)", 0.0, 100000000.0),
            ("320010", "Saldo Awal Laba Ditahan (Retained Earnings)", 0.0, 57000000.0),
        ]

        total_dr = sum(d for _, _, d, _ in baseline_lines)
        total_cr = sum(c for _, _, _, c in baseline_lines)
        assert abs(total_dr - total_cr) < 0.01, f"Baseline imbalanced: Dr={total_dr}, Cr={total_cr}"

        move_line_vals = []
        for code, label, dr, cr in baseline_lines:
            acc = Account.search([("code", "=", code)], limit=1)
            if not acc:
                raise RuntimeError(f"Required account {code} missing from Chart of Accounts!")
            move_line_vals.append((0, 0, {
                "name": label,
                "account_id": acc.id,
                "debit": dr,
                "credit": cr,
            }))

        # Route explicit symmetric clearing offset through Account 999999 (Net 999999 = Rp 0.00)
        move_line_vals.append((0, 0, {
            "name": "Clearing Offset Aktiva Awal (999999)",
            "account_id": clearing_acc.id,
            "debit": 0.0,
            "credit": total_dr,
        }))
        move_line_vals.append((0, 0, {
            "name": "Clearing Offset Pasiva & Ekuitas Awal (999999)",
            "account_id": clearing_acc.id,
            "debit": total_cr,
            "credit": 0.0,
        }))

        if not dry_run:
            op_move = Move.create({
                "journal_id": misc_journal.id,
                "date": date(2026, 1, 1),
                "ref": "OP/2026/001",
                "move_type": "entry",
                "line_ids": move_line_vals,
            })
            op_move.action_post()
            print(f"[OK] Posted Opening Calibration Entry: {op_move.name} (ref: OP/2026/001)")
        else:
            print("[DRY-RUN] Balanced opening entry OP/2026/001 validated (not committed).")
    elif existing_op:
        print(f"[INFO] Opening entry OP/2026/001 already posted: {existing_op.name}")

    # Verify Account 999999 Balance == Rp 0.00
    posted_999999 = MoveLine.search([
        ("account_id", "=", clearing_acc.id),
        ("parent_state", "=", "posted"),
    ])
    balance_999999 = sum(posted_999999.mapped("balance"))

    print("\n--- TREASURY & EQUITY BASELINE SUMMARY ---")
    for code in ["111010", "111020", "111120", "111121", "111122", "111130", "111140", "111150", "221010", "310010", "310020", "320010", "999999"]:
        acc = Account.search([("code", "=", code)], limit=1)
        if acc:
            lines = MoveLine.search([("account_id", "=", acc.id), ("parent_state", "=", "posted")])
            bal = sum(lines.mapped("balance"))
            print(f"  [{code}] {acc.name:<55} | Balance: Rp {bal:>15,.2f}")

    print("-" * 92)
    print(f"  CLEARING ACCOUNT 999999 FINAL BALANCE: Rp {balance_999999:,.2f}")
    print("=" * 92)

    if abs(balance_999999) >= 0.01:
        raise AssertionError(f"AUDIT FAILURE: Account 999999 balance is Rp {balance_999999:,.2f} (must be Rp 0.00)!")

    print("[VERIFIED] Account 999999 equilibrium strictly equals Rp 0.00.")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Klinik ADERA Opening Balance Calibration")
    parser.add_argument("--config", default="/etc/odoo/odoo.conf", help="Path to odoo.conf")
    parser.add_argument("-d", "--database", default="klinik-adera", help="Target database")
    parser.add_argument("--verify-zero-clearing", action="store_true", help="Verify Account 999999 == 0.00")
    parser.add_argument("--dry-run", action="store_true", help="Validate without committing")
    args = parser.parse_args()

    try:
        import odoo
        from odoo import api, SUPERUSER_ID
        from odoo.modules.registry import Registry

        if os.path.exists(args.config):
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
                ok = calibrate_opening_balances(env, verify_only=False, dry_run=args.dry_run)
                if not args.dry_run:
                    cr.commit()
                sys.exit(0 if ok else 1)
        else:
            print(f"Error: Config file {args.config} not found.")
            sys.exit(1)
    except Exception as exc:
        print(f"Execution Error: {exc}")
        traceback.print_exc()
        sys.exit(1)
