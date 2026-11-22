#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
KLINIK ADERA ERP (ODOO 19 CE) - HISTORICAL 2026 DAILY SPREADSHEETS ETL PIPELINE
========================================================================================
Parses daily cash/bank operational spreadsheets (01 JANUARI 2026 - 11 NOVEMBER 2026),
classifies service inflows (PRAT-VAKSIN, PRAT-USG, PRAT-KHITAN, PRAT-GIGI, ACC-HD),
recurring vendor expenses (610040, 610050, 610060), and cash deposits, with MD5
idempotency checks to prevent duplicate journal postings.

Execution CLI:
  docker exec -i odoo_adera_clinic python3 /mnt/extra-addons/scripts/etl_daily_spreadsheets.py \
      --input "/mnt/extra-addons/adera_data/11 NOVEMBER 2026 - LAPORAN HARIAN.csv" \
      --dry-run --verbose
========================================================================================
"""

import argparse
import csv
import hashlib
import os
import re
import sys
import traceback
from datetime import datetime


def parse_idr_number(raw):
    if raw is None:
        return 0.0
    s = str(raw).strip()
    if not s or s in ("-", "Rp", "Rp 0", "0"):
        return 0.0
    s = s.replace("Rp", "").replace("IDR", "").strip()
    # Handle Indonesian format 1.500.000,00 vs 1500000.00
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts[-1]) == 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif "." in s and len(s.split(".")[-1]) == 3:
        s = s.replace(".", "")
    s = re.sub(r"[^0-9.\-]", "", s)
    return float(s) if s else 0.0


def parse_date_str(raw):
    s = str(raw or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return datetime.today().date()


def classify_row(desc, debit, credit, method_raw):
    d_low = desc.lower()
    m_low = (method_raw or "").lower()

    # Bank/Cash account resolution
    if "mandiri" in m_low:
        treasury_code = "111130"
    elif "bsi" in m_low:
        treasury_code = "111140"
    elif "bpd" in m_low:
        treasury_code = "111150"
    elif "qris" in m_low or "gopay" in m_low:
        treasury_code = "111220"
    elif "bri 300" in m_low:
        treasury_code = "111121"
    elif "bri 561" in m_low:
        treasury_code = "111122"
    elif "bri" in m_low or "transfer" in m_low:
        treasury_code = "111120"
    elif "kas kecil" in m_low or "petty" in m_low:
        treasury_code = "111020"
    else:
        treasury_code = "111010"

    # 1. Internal Bank Transfer / Cash Deposit / Petty Cash Replenishment
    if any(k in d_low for k in ("setoran kasir", "setor bri", "setoran tunai", "penyisihan kas kecil", "pengisian kas kecil")):
        if "kas kecil" in d_low:
            return ("petty_replenish", "111020", "111120", None)
        return ("cash_deposit", "111120", "111010", None)

    # 2. Inflows (Revenue)
    if debit > 0 and credit == 0:
        if any(k in d_low for k in ("vaksin", "hpv", "influenza", "booster")):
            return ("inflow", treasury_code, "410010", "PRAT-VAKSIN")
        if any(k in d_low for k in ("usg", "senam hamil")):
            return ("inflow", treasury_code, "410010", "PRAT-USG")
        if any(k in d_low for k in ("khitan", "sunat")):
            return ("inflow", treasury_code, "410010", "PRAT-KHITAN")
        if any(k in d_low for k in ("homecare", "kunjungan rumah")):
            return ("inflow", treasury_code, "410010", "PRAT-HOMECARE")
        if any(k in d_low for k in ("gigi", "tambal", "cabut", "scaling")):
            return ("inflow", treasury_code, "410010", "PRAT-GIGI")
        if any(k in d_low for k in ("hd ", "hemodialisis", "cuci darah")):
            return ("inflow", treasury_code, "410110", "ACC-HD")
        return ("inflow", treasury_code, "410010", "PRAT-UMUM")

    # 3. Outflows (Operational Expenses)
    if credit > 0:
        if any(k in d_low for k in ("riffa", "limbah")):
            return ("outflow", treasury_code, "610040", "ACC-PRATAMA")
        if any(k in d_low for k in ("omnicare", "simklinik", "lisensi")):
            return ("outflow", treasury_code, "610050", "ACC-PRATAMA")
        if any(k in d_low for k in ("toko merah", "atk", "kertas")):
            return ("outflow", treasury_code, "610060", "ACC-PRATAMA")
        if any(k in d_low for k in ("bensin", "ambulans", "bbm")):
            return ("outflow", treasury_code, "619000", "ACC-PRATAMA")
        return ("outflow", treasury_code, "619000", "ACC-PRATAMA")

    return ("skip", treasury_code, None, None)


def run_etl(env, input_path, dry_run=True, verbose=False):
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Spreadsheet file not found: {input_path}")

    Account = env["account.account"]
    Analytic = env["account.analytic.account"]
    Journal = env["account.journal"]
    Move = env["account.move"]

    misc_j = Journal.search([("code", "in", ["MISCL", "MISC"])], limit=1) or Journal.search([("type", "=", "general")], limit=1)

    total_inflow = 0.0
    total_outflow = 0.0
    total_rows = 0
    skipped_idempotent = 0
    posted_count = 0

    print("=" * 96)
    print("   KLINIK ADERA ERP - HISTORICAL DAILY SPREADSHEETS ETL PIPELINE")
    print("=" * 96)
    print(f" Source File : {input_path}")
    print(f" Mode        : {'DRY-RUN (No DB Commit)' if dry_run else 'LIVE POSTING'}")
    print("=" * 96)

    with open(input_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader, 1):
            norm = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            raw_date = norm.get("tanggal") or norm.get("date") or ""
            desc = norm.get("uraian/keterangan") or norm.get("uraian") or norm.get("keterangan") or ""
            debit = parse_idr_number(norm.get("pemasukan (debet)") or norm.get("pemasukan") or norm.get("debet") or 0)
            credit = parse_idr_number(norm.get("pengeluaran (kredit)") or norm.get("pengeluaran") or norm.get("kredit") or 0)
            method = norm.get("metode/bank") or norm.get("metode") or norm.get("bank") or "Kas"

            if not desc or (debit == 0 and credit == 0):
                continue

            total_rows += 1
            total_inflow += debit
            total_outflow += credit

            tx_date = parse_date_str(raw_date)
            checksum = hashlib.md5(f"{tx_date.isoformat()}|{debit:.2f}|{credit:.2f}|{desc}".encode("utf-8")).hexdigest()

            existing = Move.search([("ref", "=", checksum)], limit=1)
            if existing:
                skipped_idempotent += 1
                if verbose:
                    print(f"  [{idx:03d}] [SKIP-IDEMPOTENT] {tx_date} | {desc[:42]:<42} | ref={checksum[:10]}...")
                continue

            kind, acc_a_code, acc_b_code, analytic_code = classify_row(desc, debit, credit, method)
            if kind == "skip":
                continue

            if verbose:
                amt = debit if debit > 0 else credit
                print(
                    f"  [{idx:03d}] [{kind.upper():<14}] {tx_date} | {desc[:36]:<36} | "
                    f"Rp {amt:>12,.0f} | Dr/Cr={acc_a_code}/{acc_b_code} | Analytic={analytic_code or '-'}"
                )

            if not dry_run:
                acc_a = Account.search([("code", "=", acc_a_code)], limit=1)
                acc_b = Account.search([("code", "=", acc_b_code)], limit=1)
                aa = Analytic.search([("code", "=", analytic_code)], limit=1) if analytic_code else False
                dist = {str(aa.id): 100.0} if aa else False

                if acc_a and acc_b and misc_j:
                    amt = debit if debit > 0 else credit
                    if kind == "inflow":
                        lines = [
                            (0, 0, {"name": desc, "account_id": acc_a.id, "debit": amt, "credit": 0.0}),
                            (0, 0, {"name": desc, "account_id": acc_b.id, "debit": 0.0, "credit": amt, "analytic_distribution": dist}),
                        ]
                    elif kind == "outflow":
                        lines = [
                            (0, 0, {"name": desc, "account_id": acc_b.id, "debit": amt, "credit": 0.0, "analytic_distribution": dist}),
                            (0, 0, {"name": desc, "account_id": acc_a.id, "debit": 0.0, "credit": amt}),
                        ]
                    else:
                        lines = [
                            (0, 0, {"name": desc, "account_id": acc_a.id, "debit": amt, "credit": 0.0}),
                            (0, 0, {"name": desc, "account_id": acc_b.id, "debit": 0.0, "credit": amt}),
                        ]
                    move = Move.create({
                        "journal_id": misc_j.id,
                        "date": tx_date,
                        "ref": checksum,
                        "move_type": "entry",
                        "line_ids": lines,
                    })
                    move.action_post()
                    posted_count += 1

    print("-" * 96)
    print(f" Parsed Rows          : {total_rows}")
    print(f" Total Inflow (Debet) : Rp {total_inflow:,.2f}")
    print(f" Total Outflow(Kredit): Rp {total_outflow:,.2f}")
    print(f" Net Cash Movement    : Rp {(total_inflow - total_outflow):,.2f}")
    print(f" Skipped (Idempotent) : {skipped_idempotent}")
    print(f" Posted Entries       : {posted_count if not dry_run else f'0 (Dry-Run validated {total_rows - skipped_idempotent} entries)'}")
    print("=" * 96)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Klinik ADERA Historical Daily Spreadsheets ETL")
    parser.add_argument("--input", required=True, help="Path to daily CSV file")
    parser.add_argument("--config", default="/etc/odoo/odoo.conf", help="Path to odoo.conf")
    parser.add_argument("-d", "--database", default="klinik-adera", help="Target database")
    parser.add_argument("--dry-run", action="store_true", help="Parse & validate without committing")
    parser.add_argument("--verbose", action="store_true", help="Print per-row classification")
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
            ok = run_etl(env, args.input, dry_run=args.dry_run, verbose=args.verbose)
            if not args.dry_run:
                cr.commit()
            sys.exit(0 if ok else 1)
    except Exception as exc:
        print(f"ETL Error: {exc}")
        traceback.print_exc()
        sys.exit(1)

