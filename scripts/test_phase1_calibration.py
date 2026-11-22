#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
KLINIK ADERA ERP (ODOO 19 CE) - PHASE 1 OPERATIONAL CALIBRATION VERIFICATION SUITE
========================================================================================
Validates:
1. Treasury & Multi-Bank Journals (BRI 569/300/561, Mandiri, BSI, BPD DIY, Petty Cash, GoPay/QRIS + MDR 610090)
2. High-Margin Clinical Sub-Analytic Accounts (PRAT-VAKSIN, PRAT-USG, PRAT-KHITAN, PRAT-HOMECARE)
3. Recurring Clinical Vendors & Loan/Equity Accounts (221010, 611010, 310020)
4. Ad-Hoc Doctor Remuneration Voucher (Rp 1,500,000 -> 50% DPP = 750,000 -> 5% PPh 21 = 37,500 -> Dr 510110 / Cr 212030, 111120)

Execution CLI:
  docker exec -i odoo_adera_clinic python3 /mnt/extra-addons/scripts/test_phase1_calibration.py
========================================================================================
"""

import sys
import os
import traceback
from datetime import date


def run_phase1_tests(env):
    print("=" * 92)
    print("   KLINIK ADERA ERP (ODOO 19 CE) - PHASE 1 CALIBRATION VERIFICATION SUITE")
    print("=" * 92)
    print(f" Database : {env.cr.dbname}")
    print("=" * 92 + "\n")

    passed = 0
    failed = 0

    def check(label, condition, detail=""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  [PASS] {label}" + (f" ({detail})" if detail else ""))
        else:
            failed += 1
            print(f"  [FAIL] {label}" + (f" ({detail})" if detail else ""))

    # ----------------------------------------------------------------------------------
    # TEST 1: MULTI-BANK, PETTY CASH & PAYMENT GATEWAY JOURNALS + ACCOUNTS
    # ----------------------------------------------------------------------------------
    print("[TEST 1] Treasury, Multi-Bank Journals, Accounts & MDR Reconciliation Rule")
    expected_accounts = [
        ("111120", "Kas di Bank - BRI 569"),
        ("111121", "Kas di Bank - BRI 300"),
        ("111122", "Kas di Bank - BRI 561"),
        ("111130", "Kas di Bank - Mandiri"),
        ("111140", "Kas di Bank - BSI 77858"),
        ("111150", "Kas di Bank - BPD DIY"),
        ("111010", "Kas Kasir"),
        ("111020", "Kas Kasir"),
        ("111220", "QRIS"),
        ("610090", "Merchant"),
        ("221010", "Pinjaman Bank Jangka Panjang"),
        ("611010", "Bunga Pinjaman Bank"),
        ("310020", "Prive"),
        ("610050", "Lisensi Perangkat Lunak"),
        ("610060", "Alat Tulis Kantor"),
    ]
    Account = env["account.account"]
    for code, _desc in expected_accounts:
        acc = Account.search([("code", "=", code)], limit=1)
        check(f"Account {code} exists", bool(acc), acc.name if acc else "Missing")

    expected_journals = [
        ("BR569", "bank", "111120"),
        ("BR300", "bank", "111121"),
        ("BR561", "bank", "111122"),
        ("BMDRI", "bank", "111130"),
        ("BSI78", "bank", "111140"),
        ("BPDIY", "bank", "111150"),
        ("KKCIL", "cash", "111020"),
        ("GOPAY", "bank", "111220"),
    ]
    Journal = env["account.journal"]
    seen_codes = set()
    for code, jtype, acc_code in expected_journals:
        j = Journal.search([("code", "=", code)], limit=1)
        no_dup = code not in seen_codes and Journal.search_count([("code", "=", code)]) == 1
        seen_codes.add(code)
        acc_ok = bool(j and j.default_account_id and j.default_account_id.code == acc_code)
        check(
            f"Journal {code} ({jtype}) -> Account {acc_code}",
            bool(j and j.type == jtype and no_dup and acc_ok),
            j.name if j else "Missing",
        )

    reconcile_model = env.ref("adera_core.reconcile_model_pg_gopay_mdr", raise_if_not_found=False)
    check(
        "Payment Gateway MDR Reconcile Rule (610090)",
        bool(reconcile_model and any(l.account_id.code == "610090" for l in reconcile_model.line_ids)),
        reconcile_model.name if reconcile_model else "Missing",
    )

    # ----------------------------------------------------------------------------------
    # TEST 2: CLINICAL SUB-ANALYTIC ACCOUNTS & ISOLATED ROUTING
    # ----------------------------------------------------------------------------------
    print("\n[TEST 2] Clinical Sub-Analytic Accounts & PRAT-VAKSIN Margin Routing")
    Analytic = env["account.analytic.account"]
    analytic_codes = [
        "PRAT-VAKSIN", "PRAT-USG", "PRAT-KHITAN", "PRAT-HOMECARE",
        "PRAT-UMUM", "PRAT-GIGI", "PRAT-KIA", "PRAT-LAB", "PRAT-FARM",
    ]
    for acode in analytic_codes:
        aa = Analytic.search([("code", "=", acode)], limit=1)
        check(f"Analytic Account {acode}", bool(aa), aa.name if aa else "Missing")

    # Test isolated analytic routing inside savepoint
    with env.cr.savepoint():
        aa_vaksin = Analytic.search([("code", "=", "PRAT-VAKSIN")], limit=1)
        aa_umum = Analytic.search([("code", "=", "PRAT-UMUM")], limit=1)
        rev_acc = Account.search([("code", "=", "410010")], limit=1)
        bank_acc = Account.search([("code", "=", "111120")], limit=1)
        misc_journal = Journal.search([("code", "=", "MISCL")], limit=1) or Journal.search([("type", "=", "general")], limit=1)

        move = env["account.move"].create({
            "journal_id": misc_journal.id,
            "date": date.today(),
            "ref": "TEST-VAKSIN-ROUTING",
            "move_type": "entry",
            "line_ids": [
                (0, 0, {
                    "name": "Penerimaan Vaksinasi HPV",
                    "account_id": bank_acc.id,
                    "debit": 1000000.0,
                    "credit": 0.0,
                }),
                (0, 0, {
                    "name": "Pendapatan Poli Vaksinasi",
                    "account_id": rev_acc.id,
                    "debit": 0.0,
                    "credit": 1000000.0,
                    "analytic_distribution": {str(aa_vaksin.id): 100.0},
                }),
            ],
        })
        move.action_post()
        plan_col = aa_vaksin.plan_id._column_name()
        vaksin_lines = env["account.analytic.line"].search([(plan_col, "=", aa_vaksin.id), ("move_line_id", "in", move.line_ids.ids)])
        umum_col = aa_umum.plan_id._column_name()
        umum_lines = env["account.analytic.line"].search([(umum_col, "=", aa_umum.id), ("move_line_id", "in", move.line_ids.ids)])
        check(
            "PRAT-VAKSIN analytic line isolation",
            len(vaksin_lines) == 1 and abs(vaksin_lines.amount - 1000000.0) < 0.01 and len(umum_lines) == 0,
            f"Vaksin={vaksin_lines.amount}, Umum={len(umum_lines)}",
        )

    # ----------------------------------------------------------------------------------
    # TEST 3: RECURRING CLINICAL VENDORS
    # ----------------------------------------------------------------------------------
    print("\n[TEST 3] Recurring Clinical Vendors")
    vendor_refs = [
        ("VEND-LIMBAH-B3", "PT Riffa Utama Mandiri"),
        ("VEND-SIMKLINIK", "Heng Sui Phin / Omnicare System"),
        ("VEND-ATK-LOGISTIK", "Toko Merah / ATK Logistik"),
    ]
    for vref, vname in vendor_refs:
        partner = env["res.partner"].search([("ref", "=", vref)], limit=1)
        check(f"Vendor '{vname}' ({vref})", bool(partner and partner.supplier_rank >= 1), partner.name if partner else "Missing")

    # ----------------------------------------------------------------------------------
    # TEST 4: AD-HOC DOCTOR REMUNERATION VOUCHER (CIRCUMCISION SPLIT Rp 1,500,000)
    # ----------------------------------------------------------------------------------
    print("\n[TEST 4] Ad-Hoc Doctor Remuneration Voucher & PPh 21 Calculation")
    with env.cr.savepoint():
        Partner = env["res.partner"]
        test_doc = Partner.create({
            "name": "dr. Test Khitan Ad-Hoc (NPWP)",
            "is_doctor": True,
            "vat": "123456789012345",
            "has_npwp": True,
        })
        bri_journal = Journal.search([("code", "=", "BR569")], limit=1)
        batch = env["medical.fee.settlement.batch"].create({
            "doctor_id": test_doc.id,
            "is_adhoc_voucher": True,
            "adhoc_description": "Bagi Hasil Tindakan Khitan",
            "adhoc_amount": 1500000.0,
            "bank_journal_id": bri_journal.id,
        })

        check("Ad-hoc gross = Rp 1,500,000", abs(batch.total_gross_fee - 1500000.0) < 0.01, f"{batch.total_gross_fee:,.0f}")
        check("Ad-hoc 50% DPP = Rp 750,000", abs(batch.dpp_amount - 750000.0) < 0.01, f"{batch.dpp_amount:,.0f}")
        check("Ad-hoc 5% PPh 21 = Rp 37,500", abs(batch.total_pph21_withheld - 37500.0) < 0.01, f"{batch.total_pph21_withheld:,.0f}")
        check("Ad-hoc Net Payable = Rp 1,462,500", abs(batch.total_net_payable - 1462500.0) < 0.01, f"{batch.total_net_payable:,.0f}")

        batch.action_post_adhoc_voucher()
        move = batch.payment_move_id
        dr_510110 = sum(move.line_ids.filtered(lambda l: l.account_id.code == "510110").mapped("debit"))
        cr_212030 = sum(move.line_ids.filtered(lambda l: l.account_id.code == "212030").mapped("credit"))
        cr_111120 = sum(move.line_ids.filtered(lambda l: l.account_id.code == "111120").mapped("credit"))

        check(
            "Ad-hoc GL Posting: Dr 510110 (1,500,000) / Cr 212030 (37,500) & 111120 (1,462,500)",
            batch.state == "paid"
            and abs(dr_510110 - 1500000.0) < 0.01
            and abs(cr_212030 - 37500.0) < 0.01
            and abs(cr_111120 - 1462500.0) < 0.01,
            f"Dr 510110={dr_510110:,.0f}, Cr 212030={cr_212030:,.0f}, Cr 111120={cr_111120:,.0f}",
        )

    print("\n" + "=" * 92)
    print(f" RESULT: {passed}/{passed + failed} CHECKS PASSED | FAILED: {failed}")
    print("=" * 92 + "\n")
    return failed == 0


if __name__ == "__main__":
    try:
        import odoo
        from odoo import api, SUPERUSER_ID
        from odoo.modules.registry import Registry

        config_file = "/etc/odoo/odoo.conf"
        if os.path.exists(config_file):
            odoo.tools.config.parse_config([
                "-c", config_file,
                "--db_host", "db_adera",
                "-r", "odoo",
                "-w", "odoo",
                "-d", "klinik-adera",
            ])
            registry = Registry("klinik-adera")
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                ok = run_phase1_tests(env)
                sys.exit(0 if ok else 1)
        else:
            print("Error: /etc/odoo/odoo.conf not found.")
            sys.exit(1)
    except Exception as exc:
        print(f"Execution Error: {exc}")
        traceback.print_exc()
        sys.exit(1)
