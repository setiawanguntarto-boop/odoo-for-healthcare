#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
KLINIK ADERA ERP (ODOO 19 CE) - HISTORICAL 2026 DAILY SPREADSHEETS ETL PIPELINE
========================================================================================
Parses daily cash/bank operational spreadsheets (.xlsx & .csv) from
01 JANUARI 2026 through 11 NOVEMBER 2026, classifies service inflows (PRAT-VAKSIN,
PRAT-USG, PRAT-KHITAN, PRAT-GIGI, ACC-HD), recurring vendor expenses (610040, 610050,
610060), and cash deposits, with MD5 idempotency checks.

Execution CLI:
  docker exec -i odoo_adera_clinic python3 /mnt/extra-addons/scripts/etl_daily_spreadsheets.py \
      --input-dir /mnt/extra-addons/adera_data \
      -d klinik-adera --dry-run --verbose
========================================================================================
"""

import argparse
import csv
import hashlib
import os
import re
import sys
import traceback
from datetime import date, datetime


LEDGER_SHEETS = (
    "KAS BESAR",
    "KAS KECIL",
    "MANDIRI",
    "BRI SLEMAN 69",
    "BRI GIRO CIK DITIRO",
    "BRI CIK DITIRO",
    "BSI",
    "BPD DIY",
)


def parse_idr_number(raw):
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s or s in ("-", "Rp", "Rp 0", "0"):
        return 0.0
    s = s.replace("Rp", "").replace("IDR", "").strip()
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


def parse_date_val(raw):
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def classify_row(desc, debit, credit, method_raw):
    d_low = desc.lower()
    m_low = (method_raw or "").lower()

    if "mandiri" in m_low:
        treasury_code = "111130"
    elif "bsi" in m_low:
        treasury_code = "111140"
    elif "bpd" in m_low:
        treasury_code = "111150"
    elif "qris" in m_low or "gopay" in m_low:
        treasury_code = "111220"
    elif "300" in m_low or "cik ditiro" in m_low:
        treasury_code = "111121"
    elif "561" in m_low or "giro" in m_low:
        treasury_code = "111122"
    elif "bri" in m_low or "sleman" in m_low or "transfer" in m_low:
        treasury_code = "111120"
    elif "kas kecil" in m_low or "petty" in m_low:
        treasury_code = "111020"
    else:
        treasury_code = "111010"

    if any(k in d_low for k in ("setoran kasir", "setor bri", "setoran tunai", "penyisihan kas kecil", "pengisian kas kecil")):
        if "kas kecil" in d_low:
            return ("petty_replenish", "111020", "111120", None)
        return ("cash_deposit", "111120", "111010", None)

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


def iter_csv_rows(filepath):
    with open(filepath, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            norm = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            tx_date = parse_date_val(norm.get("tanggal") or norm.get("date"))
            desc = norm.get("uraian/keterangan") or norm.get("uraian") or norm.get("keterangan") or ""
            debit = parse_idr_number(norm.get("pemasukan (debet)") or norm.get("pemasukan") or norm.get("debet") or 0)
            credit = parse_idr_number(norm.get("pengeluaran (kredit)") or norm.get("pengeluaran") or norm.get("kredit") or 0)
            method = norm.get("metode/bank") or norm.get("metode") or norm.get("bank") or "Kas"
            if tx_date and desc and (debit > 0 or credit > 0):
                yield (tx_date, desc, debit, credit, method)


def iter_xlsx_rows(filepath):
    import openpyxl

    wb = openpyxl.load_workbook(filepath, data_only=True, read_only=True)
    for sname in wb.sheetnames:
        s_clean = sname.strip().upper()
        if not any(s_clean.startswith(prefix) for prefix in LEDGER_SHEETS):
            continue
        ws = wb[sname]
        col_map = None
        for row in ws.iter_rows(values_only=True):
            if not row or not any(row):
                continue
            row_strs = [str(c).strip().upper() if c is not None else "" for c in row]
            if "TANGGAL" in row_strs and ("DEBET" in row_strs or "KREDIT" in row_strs):
                col_map = {name: idx for idx, name in enumerate(row_strs) if name}
                continue
            if not col_map:
                continue

            raw_dt = row[col_map["TANGGAL"]] if col_map.get("TANGGAL") is not None and col_map["TANGGAL"] < len(row) else None
            tx_date = parse_date_val(raw_dt)
            if not tx_date:
                continue

            desc_idx = col_map.get("URAIAN") if col_map.get("URAIAN") is not None else col_map.get("KETERANGAN")
            desc = str(row[desc_idx]).strip() if desc_idx is not None and desc_idx < len(row) and row[desc_idx] else ""
            if not desc:
                continue

            deb_idx = col_map.get("DEBET")
            cred_idx = col_map.get("KREDIT")
            debit = parse_idr_number(row[deb_idx] if deb_idx is not None and deb_idx < len(row) else 0)
            credit = parse_idr_number(row[cred_idx] if cred_idx is not None and cred_idx < len(row) else 0)
            if debit > 0 or credit > 0:
                yield (tx_date, desc, debit, credit, sname.strip())
    wb.close()


def run_etl(env, file_paths, dry_run=True, verbose=False):
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
    print(f" Files Queued : {len(file_paths)}")
    print(f" Mode         : {'DRY-RUN (No DB Commit)' if dry_run else 'LIVE POSTING'}")
    print("=" * 96)

    for fpath in file_paths:
        if not os.path.exists(fpath):
            raise FileNotFoundError(f"Spreadsheet file not found: {fpath}")
        fname = os.path.basename(fpath)
        row_iter = iter_xlsx_rows(fpath) if fpath.lower().endswith(".xlsx") else iter_csv_rows(fpath)
        file_rows = 0

        for tx_date, desc, debit, credit, method in row_iter:
            file_rows += 1
            total_rows += 1
            total_inflow += debit
            total_outflow += credit

            checksum = hashlib.md5(f"{tx_date.isoformat()}|{debit:.2f}|{credit:.2f}|{desc}|{method}".encode("utf-8")).hexdigest()
            if Move.search([("ref", "=", checksum)], limit=1):
                skipped_idempotent += 1
                continue

            kind, acc_a_code, acc_b_code, analytic_code = classify_row(desc, debit, credit, method)
            if kind == "skip":
                continue

            if verbose and file_rows <= 5:
                amt = debit if debit > 0 else credit
                print(
                    f"  [{fname[:15]:<15}] [{kind.upper():<14}] {tx_date} | {desc[:30]:<30} | "
                    f"Rp {amt:>12,.0f} | Dr/Cr={acc_a_code}/{acc_b_code} | {analytic_code or '-'}"
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

        print(f"  [FILE] {fname:<45} | Parsed Rows: {file_rows}")

    print("-" * 96)
    print(f" Total Parsed Rows    : {total_rows}")
    print(f" Total Inflow (Debet) : Rp {total_inflow:,.2f}")
    print(f" Total Outflow(Kredit): Rp {total_outflow:,.2f}")
    print(f" Net Cash Movement    : Rp {(total_inflow - total_outflow):,.2f}")
    print(f" Skipped (Idempotent) : {skipped_idempotent}")
    print(f" Posted Entries       : {posted_count if not dry_run else f'0 (Dry-Run validated {total_rows - skipped_idempotent} entries)'}")
    print("=" * 96)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Klinik ADERA Historical Daily Spreadsheets ETL")
    parser.add_argument("--input", help="Path to a single daily CSV/XLSX file")
    parser.add_argument("--input-dir", help="Directory containing 2026 daily LAPORAN HARIAN files")
    parser.add_argument("--config", default="/etc/odoo/odoo.conf", help="Path to odoo.conf")
    parser.add_argument("-d", "--database", default="klinik-adera", help="Target database")
    parser.add_argument("--dry-run", action="store_true", help="Parse & validate without committing")
    parser.add_argument("--verbose", action="store_true", help="Print sample per-row classification")
    args = parser.parse_args()

    if not args.input and not args.input_dir:
        parser.error("Provide either --input or --input-dir")

    files = []
    if args.input:
        files.append(args.input)
    if args.input_dir:
        for fn in sorted(os.listdir(args.input_dir)):
            if "LAPORAN HARIAN" in fn.upper() and fn.lower().endswith(".xlsx"):
                files.append(os.path.join(args.input_dir, fn))

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
            ok = run_etl(env, files, dry_run=args.dry_run, verbose=args.verbose)
            if not args.dry_run:
                cr.commit()
            sys.exit(0 if ok else 1)
    except Exception as exc:
        print(f"ETL Error: {exc}")
        traceback.print_exc()
        sys.exit(1)
