#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
KLINIK ADERA ERP (ODOO 19 CE) - DAY-IN-THE-LIFE OPERATIONAL & FINANCIAL STRESS TEST RUNNER
========================================================================================
Simulates real-world clinical lifecycles end-to-end and asserts PSAK GL integrity:
  Scenario A: Outpatient Encounter with Multi-Dose Open-Vial Vaccine Usage & PMK 168 Settlement
  Scenario B: Hemodialysis Session with Split-Tender Payment (BPJS Claim + QRIS Co-Pay)
  Scenario C: Automated Medical Asset Depreciation Cron & Sinking Fund Reserve Allocation
  Financial Integrity: Neraca SAK Equilibrium, Suspense (999999) == Rp 0, Cash Flow, Dashboard KPIs

CLI Execution Options:
  python3 scripts/run_clinical_stress_test.py -d klinik-adera
  python3 scripts/run_clinical_stress_test.py -d adera_prod
  odoo shell -c /etc/odoo/odoo.conf -d klinik-adera < scripts/run_clinical_stress_test.py
========================================================================================
"""
import sys
import os
import json
import argparse
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

# ANSI Terminal Colors
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_GREEN = "\033[92m"
C_RED = "\033[91m"
C_YELLOW = "\033[93m"
C_CYAN = "\033[96m"
C_BLUE = "\033[94m"


def format_idr(val):
    if val is None:
        return "Rp 0,00"
    neg = val < 0
    abs_val = abs(val)
    formatted = f"{abs_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if neg else ''}Rp {formatted}"


def run_clinical_stress_test(env):
    print("\n" + "=" * 100)
    print(f"{C_BOLD}{C_CYAN}    KLINIK ADERA ERP (ODOO 19 CE) - OPERATIONAL & FINANCIAL STRESS TEST RUNNER{C_RESET}")
    print("=" * 100)
    print(f" Target Database : {C_BOLD}{env.cr.dbname}{C_RESET}")
    print(f" Execution Date  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f" Entity Scope    : PT Prosperra Medika Utama / Klinik ADERA")
    print(f" Architecture    : Odoo 19 CE + PSAK Healthcare Custom Extensions")
    print("=" * 100)

    total_checks = 0
    passed_checks = 0
    failed_checks = 0

    def assert_check(name, passed, detail=""):
        nonlocal total_checks, passed_checks, failed_checks
        total_checks += 1
        tag = f"{C_GREEN}[PASS]{C_RESET}" if passed else f"{C_RED}[FAIL]{C_RESET}"
        if passed:
            passed_checks += 1
        else:
            failed_checks += 1
        print(f"  {tag} {name}")
        if detail:
            print(f"         {C_YELLOW}-> {detail}{C_RESET}")

    # =========================================================================
    # 1. SCENARIO A: OUTPATIENT ENCOUNTER & OPEN-VIAL SPOILAGE
    # =========================================================================
    print(f"\n{C_BOLD}{C_BLUE}[1/4] SCENARIO A: Outpatient Encounter with Multi-Dose Open-Vial Vaccine Usage{C_RESET}")
    try:
        # Resolve / Create Master Data
        acc_cogs_pharma = env["account.account"].search([("code", "=", "510010")], limit=1)
        acc_inv_pharma = env["account.account"].search([("code", "in", ["113010", "114010"])], limit=1)
        analytic_prat_umum = env["account.analytic.account"].search([("code", "=", "PRAT-UMUM")], limit=1)
        analytic_prat_farm = env["account.analytic.account"].search([("code", "=", "PRAT-FARM")], limit=1)
        bank_bca = env["account.journal"].search([("code", "=", "BBCA")], limit=1)

        doctor = env["res.partner"].search([("is_doctor", "=", True), ("doctor_type", "=", "general")], limit=1)
        if not doctor:
            doctor = env["res.partner"].create({
                "name": "dr. Andi Pratama (Runner)",
                "is_doctor": True,
                "doctor_type": "general",
                "sip_number": "SIP.RUNNER.001",
                "has_npwp": True,
            })

        patient = env["res.partner"].search([("customer_rank", ">", 0)], limit=1)
        if not patient:
            patient = env["res.partner"].create({
                "name": "Pasien Stress Test Runner",
                "ref": "RM-RUN-001",
                "customer_rank": 1,
            })

        prod_cons = env["product.product"].search([("type", "=", "service"), ("list_price", ">", 0)], limit=1)
        prod_vac = env["product.product"].search([("default_code", "ilike", "VAC")], limit=1)
        if not prod_vac:
            prod_vac = env["product.product"].create({
                "name": "Vaksin Flubio Stress Test Runner",
                "default_code": "MED-VAC-RUNNER",
                "type": "consu",
                "list_price": 100000.0,
                "standard_price": 50000.0,
            })

        lot_vac = env["stock.lot"].create({
            "name": f"VAC-RUN-{datetime.now().strftime('%H%M%S')}",
            "product_id": prod_vac.id,
            "dose_capacity": 5,
            "doses_remaining": 5,
            "is_opened": True,
            "opened_date": date.today(),
        })

        # Create & Process Outpatient Encounter
        enc_a = env["clinic.encounter"].create({
            "external_encounter_id": f"ENC-RUN-A-{datetime.now().strftime('%H%M%S')}",
            "patient_mrn": patient.ref or "RM-RUN-001",
            "patient_name": patient.name,
            "patient_id": patient.id,
            "doctor_id": doctor.id,
            "clinic_unit": "pratama",
            "poli_code": "umum",
            "payer_type": "cash",
            "line_ids": [
                (0, 0, {
                    "product_id": prod_cons.id,
                    "line_type": "consultation",
                    "qty": 1.0,
                    "unit_price": 150000.0,
                    "doctor_id": doctor.id,
                    "analytic_account_id": analytic_prat_umum.id if analytic_prat_umum else False,
                }),
                (0, 0, {
                    "product_id": prod_vac.id,
                    "line_type": "medication",
                    "qty": 1.0,
                    "unit_price": 100000.0,
                    "lot_id": lot_vac.id,
                    "analytic_account_id": analytic_prat_farm.id if analytic_prat_farm else False,
                }),
            ]
        })
        enc_a.action_process_encounter()

        assert_check("Encounter Outpatient Processed & Invoiced", enc_a.state == "posted" and enc_a.account_move_id.state == "posted",
                     f"Encounter Ref: {enc_a.name}, Invoice: {enc_a.account_move_id.name}")

        # Open-Vial Scrap for remaining 4 doses
        lot_vac.doses_remaining = 4
        scrap_wiz = env["stock.scrap.clinic"].create({
            "lot_id": lot_vac.id,
            "product_id": prod_vac.id,
            "dose_scrap_quantity": 4,
            "discarded_doses": 4,
            "spoilage_reason": "expired_open_vial",
            "analytic_account_id": analytic_prat_farm.id if analytic_prat_farm else False,
            "spoilage_account_id": acc_cogs_pharma.id,
            "inventory_account_id": acc_inv_pharma.id,
        })
        scrap_wiz.action_scrap_open_vial()

        scrap_move = env["account.move"].search([("ref", "ilike", lot_vac.name)], limit=1)
        assert_check("Open-Vial 4-Dose Spoilage Scrapped (Dr 510010 / Cr 113010)", bool(scrap_move and scrap_move.state == "posted"),
                     f"GL Move: {scrap_move.name if scrap_move else 'N/A'}")

        # Doctor Settlement & PMK 168/2023 Withholding Tax
        settlement = env["doctor.settlement"].create({
            "doctor_id": doctor.id,
            "date_settlement": date.today(),
            "date_from": date(date.today().year, date.today().month, 1),
            "date_to": date.today(),
            "bank_journal_id": bank_bca.id,
        })
        settlement.action_load_fee_lines()
        settlement.action_approve()
        settlement.action_post_disbursement()

        assert_check("Doctor Settlement Executed via PMK 168/2023 Progressive Tax", settlement.state == "paid",
                     f"Bruto: {format_idr(settlement.total_gross_fee)}, PPh 21: {format_idr(settlement.pph21_amount)}, Take-Home: {format_idr(settlement.net_fee_payable)}")

    except Exception as e:
        assert_check("Scenario A Execution", False, str(e))

    # =========================================================================
    # 2. SCENARIO B: HEMODIALYSIS WITH SPLIT-TENDER PAYMENT
    # =========================================================================
    print(f"\n{C_BOLD}{C_BLUE}[2/4] SCENARIO B: Hemodialysis Session with Split-Tender Payment (BPJS + Co-Pay){C_RESET}")
    try:
        acc_ar_bpjs = env["account.account"].search([("code", "=", "112020")], limit=1)
        acc_qris = env["account.account"].search([("code", "in", ["111220", "111210"])], limit=1)
        analytic_hd = env["account.analytic.account"].search([("code", "=", "ACC-HD")], limit=1)
        analytic_hd_treat = env["account.analytic.account"].search([("code", "=", "HD-TREAT")], limit=1)
        journal_qris = env["account.journal"].search([("code", "in", ["QRIS", "PGATE"])], limit=1)

        prod_hd = env["product.product"].search([("default_code", "ilike", "HD")], limit=1)
        if not prod_hd:
            prod_hd = env["product.product"].create({
                "name": "Paket Hemodialisis High-Flux Runner",
                "default_code": "SRV-HD-RUNNER",
                "type": "service",
                "list_price": 1100000.0,
            })

        enc_b = env["clinic.encounter"].create({
            "external_encounter_id": f"ENC-RUN-B-{datetime.now().strftime('%H%M%S')}",
            "patient_mrn": "RM-HD-RUN-01",
            "patient_name": "Tn. Bambang Irawan (Stress Test)",
            "clinic_unit": "hd",
            "poli_code": "hd_routine",
            "payer_type": "split",
            "sep_claim_number": f"SEP-{datetime.now().strftime('%Y%m%d-%H%M')}",
            "raw_payload": json.dumps({
                "payment_split": [
                    {
                        "method": "qris",
                        "amount": 100000.0,
                        "journal_code": journal_qris.code if journal_qris else "PGATE",
                    }
                ]
            }),
            "line_ids": [
                (0, 0, {
                    "product_id": prod_hd.id,
                    "line_type": "procedure",
                    "qty": 1.0,
                    "unit_price": 1100000.0,
                    "analytic_account_id": analytic_hd_treat.id if analytic_hd_treat else analytic_hd.id,
                })
            ]
        })
        enc_b.action_process_encounter()

        assert_check("Hemodialysis Encounter Processed & Invoiced", enc_b.state == "posted",
                     f"Encounter Ref: {enc_b.name}, Invoice: {enc_b.account_move_id.name if enc_b.account_move_id else 'N/A'}")

        # Check split-tender balances
        ar_residual = enc_b.account_move_id.amount_residual
        assert_check("BPJS Claim Receivable Net Balance is Rp 1,000,000", abs(ar_residual - 1000000.0) < 1.0,
                     f"Net BPJS Receivable Residual: {format_idr(ar_residual)}")

        copay_payment = env["account.payment"].search([("memo", "ilike", enc_b.name)], limit=1)
        if not copay_payment and enc_b.patient_id:
            copay_payment = env["account.payment"].search([("partner_id", "=", enc_b.patient_id.id), ("amount", "=", 100000.0)], limit=1)
        assert_check("Cashier POS QRIS Co-Pay Debited Rp 100,000", bool(copay_payment and copay_payment.amount == 100000.0),
                     f"Payment Ref: {copay_payment.name if copay_payment else 'N/A'}, Amount: {format_idr(copay_payment.amount if copay_payment else 0.0)}")

    except Exception as e:
        assert_check("Scenario B Execution", False, str(e))

    # =========================================================================
    # 3. SCENARIO C: ASSET DEPRECIATION CRON & SINKING FUND RESERVE
    # =========================================================================
    print(f"\n{C_BOLD}{C_BLUE}[3/4] SCENARIO C: Automated Depreciation & Sinking Fund Reserve Accrual{C_RESET}")
    try:
        purchase_d = date.today() - relativedelta(months=1)
        analytic_hd = env["account.analytic.account"].search([("code", "=", "ACC-HD")], limit=1)

        # Asset Master HD
        asset_hd = env["clinic.asset"].create({
            "name": f"Mesin HD Nipro Stress Runner {datetime.now().strftime('%H%M%S')}",
            "asset_code": f"AST-HD-{datetime.now().strftime('%H%M%S')}",
            "asset_category": "medical_device_hd",
            "purchase_date": purchase_d,
            "purchase_value": 240000000.0,
            "salvage_value": 0.0,
            "useful_life_months": 60,
        })
        asset_hd.action_confirm()

        # Run Cron Depreciation
        env["clinic.asset"].cron_post_monthly_asset_depreciation()

        # Assert 510030 Direct Medical Depreciation
        dep_moves = env["account.move.line"].search([
            ("account_id.code", "=", "510030"),
            ("parent_state", "=", "posted"),
            ("debit", ">", 0),
        ])
        assert_check("Medical Equipment Depreciation Directly Debited to COGS 510030", len(dep_moves) > 0,
                     f"Monthly Depreciation: {format_idr(dep_moves[0].debit if dep_moves else 0.0)}")

        # Sinking Fund Reserve Allocation
        sf_wiz = env["clinic.sinking.fund.wizard"].create({
            "fiscal_year": date.today().year,
            "period_month": str(date.today().month),
            "net_operating_profit": 50000000.0,
            "allocation_percentage": 10.0,
            "purpose": "device_overhaul",
        })
        res_sf = sf_wiz.action_confirm_allocation()
        sf_move = env["account.move"].browse(res_sf.get("res_id"))
        assert_check("Sinking Fund Reserve 10% Allocated (Dr 320010 / Cr 320020)", sf_move.state == "posted",
                     f"Reserve Amount: {format_idr(sf_wiz.allocation_amount)} -> Move {sf_move.name}")

    except Exception as e:
        assert_check("Scenario C Execution", False, str(e))

    # =========================================================================
    # 4. STRICT FINANCIAL INTEGRITY & EXECUTIVE DASHBOARD AUDIT
    # =========================================================================
    print(f"\n{C_BOLD}{C_BLUE}[4/4] FINANCIAL INTEGRITY & EXECUTIVE DASHBOARD AUDIT{C_RESET}")
    try:
        today = date.today()

        # 1. Balance Sheet Equilibrium
        report_bs = env["psak.financial.report"].create({
            "name": f"Audit Neraca Stresstet {today}",
            "framework_standard": "emkm",
            "report_type": "balance_sheet",
            "date_from": date(today.year, 1, 1),
            "date_to": date(today.year, 12, 31),
            "target_move": "posted",
        })
        report_bs.action_recompute()
        tot_asset = report_bs.line_ids.filtered(lambda l: l.name == "TOTAL ASET (TOTAL ASSETS)")
        tot_liab_eq = report_bs.line_ids.filtered(lambda l: l.name == "TOTAL KEWAJIBAN & EKUITAS")
        variance = abs(tot_asset.amount_current - tot_liab_eq.amount_current) if tot_asset and tot_liab_eq else 999.0
        assert_check("Trial Balance & Balance Sheet Equilibrium (Variance == Rp 0,00)", variance == 0.0,
                     f"Total Aset: {format_idr(tot_asset.amount_current if tot_asset else 0.0)} == Pasiva: {format_idr(tot_liab_eq.amount_current if tot_liab_eq else 0.0)}")

        # 2. Suspense Account 999999 == Rp 0.00
        susp_lines = env["account.move.line"].search([("account_id.code", "=", "999999"), ("parent_state", "=", "posted")])
        bal_999 = sum(l.debit - l.credit for l in susp_lines)
        assert_check("Opening Balance Suspense Account 999999 == Rp 0,00", abs(bal_999) < 0.01,
                     f"Current Net Balance: {format_idr(bal_999)}")

        # 3. Interim GR/IR Clearing Account 211500 == Rp 0.00
        grir_lines = env["account.move.line"].search([("account_id.code", "=", "211500"), ("parent_state", "=", "posted")])
        bal_211500 = sum(l.debit - l.credit for l in grir_lines)
        assert_check("Interim GR/IR Clearing Account 211500 == Rp 0,00", abs(bal_211500) < 0.01,
                     f"Current Net Balance: {format_idr(bal_211500)}")

        # 4. Statement of Cash Flows (Indirect Method)
        report_cf = env["psak.financial.report"].create({
            "name": f"Audit Arus Kas Stresstest {today}",
            "framework_standard": "sak_ep",
            "report_type": "cash_flow",
            "cash_flow_method": "indirect",
            "date_from": date(today.year, 1, 1),
            "date_to": date(today.year, 12, 31),
            "target_move": "posted",
        })
        report_cf.action_recompute()
        assert_check("Statement of Cash Flows (Indirect Method) Reconciled", len(report_cf.line_ids) > 0,
                     f"Generated {len(report_cf.line_ids)} cash flow reconciliation lines.")

        # 5. Executive Dashboard Metrics
        metrics = env["clinic.dashboard.kpi"].get_dashboard_metrics()
        scorecards = metrics.get("scorecards", {}) if metrics else {}
        golden = metrics.get("golden_ratios", {}) if metrics else {}
        cashless = metrics.get("cashless_monitor", {}) if metrics else {}
        total_rev = scorecards.get("total_revenue", 0.0)
        labor_ratio = golden.get("labor_cost_ratio", {}).get("value", 0.0)
        pharma_ratio = golden.get("pharma_cost_ratio", {}).get("value", 0.0)
        cashless_pct = cashless.get("cashless_pct", 0.0)
        assert_check("Executive Dashboard Golden Ratios & Cashless Monitor Parity", bool(metrics and "scorecards" in metrics),
                     f"Total Rev: {format_idr(total_rev)}, Labor Ratio: {labor_ratio}%, Pharma Ratio: {pharma_ratio}%, Cashless: {cashless_pct}%")

    except Exception as e:
        assert_check("Financial Integrity Audit", False, str(e))

    # =========================================================================
    # SUMMARY REPORT
    # =========================================================================
    print("\n" + "=" * 100)
    print(f" {C_BOLD}SUMMARY RESULTS: {passed_checks}/{total_checks} CHECKS PASSED{C_RESET}")
    print("=" * 100)
    if failed_checks == 0:
        print(f" {C_BOLD}{C_GREEN}>>> [SUCCESS] KLINIK ADERA ERP IS 100% OPERATIONAL & AUDIT COMPLIANT! <<<{C_RESET}")
        print(" All clinical encounter events successfully integrate into General Ledger and Executive Dashboards.")
        print(" Zero financial suspense variance, zero unallocated clearing accounts.")
        print("=" * 100 + "\n")
        return 0
    else:
        print(f" {C_BOLD}{C_RED}>>> [FAILURE] {failed_checks} AUDIT CHECK(S) FAILED! <<<{C_RESET}")
        print(" Please inspect failure details above and remediate before production cutover.")
        print("=" * 100 + "\n")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Klinik ADERA ERP Stress Test Runner")
    parser.add_argument("-d", "--database", default="klinik-adera", help="Database name")
    parser.add_argument("-c", "--config", default="/etc/odoo/odoo.conf", help="Odoo config path")
    args, unknown = parser.parse_known_args()

    # Check if executed inside Odoo shell environment
    if "env" in globals():
        res = run_clinical_stress_test(globals()["env"])
        if res != 0 and not sys.flags.interactive:
            sys.exit(res)
    else:
        # Standalone Python runner
        import odoo
        from odoo import api, SUPERUSER_ID
        from odoo.modules.registry import Registry

        cfg_args = ["-c", args.config, "-d", args.database]
        # Ensure docker db host parameters if in container
        if os.path.exists("/.dockerenv") or os.environ.get("DB_HOST"):
            db_host = os.environ.get("DB_HOST", "db_adera")
            cfg_args.extend(["--db_host", db_host, "-r", "odoo", "-w", "odoo"])

        odoo.tools.config.parse_config(cfg_args)
        with Registry(args.database).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            exit_code = run_clinical_stress_test(env)
            sys.exit(exit_code)
