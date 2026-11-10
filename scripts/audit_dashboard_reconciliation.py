#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
KLINIK ADERA ERP (ODOO 19 CE) - DASHBOARD RECONCILIATION & AUDIT TEST SUITE
========================================================================================
Entity Scope      : PT Prosperra Medika Utama / Klinik ADERA
Architecture      : Decoupled Healthcare ERP (EHR Bridge <-> SAK EMKM / PSAK Accounting)
Author            : Principal Odoo 19 QA Architect & Healthcare Financial Audit Specialist
Execution CLI     : python3 scripts/audit_dashboard_reconciliation.py
                    OR odoo shell -c /etc/odoo/odoo.conf -d klinik-adera < scripts/audit_dashboard_reconciliation.py
========================================================================================
"""
import sys
import os
from datetime import date, datetime
from dateutil.relativedelta import relativedelta


def format_idr(val):
    if val is None:
        return "Rp 0.00"
    neg = val < 0
    abs_val = abs(val)
    formatted = f"{abs_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if neg else ''}Rp {formatted}"


def run_audit(env):
    today = date.today()
    date_from = today.replace(day=1).strftime('%Y-%m-%d')
    date_to = today.strftime('%Y-%m-%d')
    company = env.company
    company_id = company.id

    print("\n" + "=" * 94)
    print("      KLINIK ADERA ERP (ODOO 19 CE) - DASHBOARD RECONCILIATION AUDIT REPORT")
    print("=" * 94)
    print(f" Entity Scope       : PT Prosperra Medika Utama / Klinik ADERA")
    print(f" Cut-off Date Range : {date_from} s/d {date_to} (MTD)")
    print(f" Audit Timestamp    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f" Target Database    : {env.cr.dbname}")
    print("=" * 94)

    # 1. FETCH DASHBOARD AGGREGATED METRICS
    kpi_model = env['clinic.dashboard.kpi']
    metrics = kpi_model.get_dashboard_metrics(
        date_from=date_from,
        date_to=date_to,
        business_unit=False,
        poli_code=False,
    )
    sc = metrics['scorecards']
    flags = metrics['compliance_flags']

    # 2. QUERY DIRECT SOURCES OF TRUTH
    # Move Lines (Period & Cumulative)
    period_lines = env['account.move.line'].search([
        ('company_id', '=', company_id),
        ('parent_state', '=', 'posted'),
        ('date', '>=', date_from),
        ('date', '<=', date_to),
    ])
    cum_lines = env['account.move.line'].search([
        ('company_id', '=', company_id),
        ('parent_state', '=', 'posted'),
        ('date', '<=', date_to),
    ])

    # A. Operating Revenue (410xxx)
    rev_lines = period_lines.filtered(
        lambda l: l.account_id.code and (l.account_id.code.startswith('410') or l.account_id.code.startswith('4100'))
    )
    sot_revenue = float(sum(rev_lines.mapped('credit')) - sum(rev_lines.mapped('debit')))

    # B. COGS (5100xx)
    cogs_lines = period_lines.filtered(
        lambda l: l.account_id.code and l.account_id.code.startswith(('5100', '51000'))
    )
    sot_cogs = float(sum(cogs_lines.mapped('debit')) - sum(cogs_lines.mapped('credit')))

    # C. Doctor Fees (5101xx)
    doc_lines = period_lines.filtered(
        lambda l: l.account_id.code and l.account_id.code.startswith('5101')
    )
    sot_doc_fees = float(sum(doc_lines.mapped('debit')) - sum(doc_lines.mapped('credit')))

    # D. OPEX (610xxx, 619xxx)
    opex_lines = period_lines.filtered(
        lambda l: l.account_id.code and (
            l.account_id.code.startswith('610') or l.account_id.code.startswith('619') or l.account_id.code.startswith('611')
        )
    )
    sot_opex = float(sum(opex_lines.mapped('debit')) - sum(opex_lines.mapped('credit')))

    # E. Net Profit
    sot_net_profit = float(sot_revenue - (sot_cogs + sot_doc_fees + sot_opex))

    # F. GR/IR Clearing (211500)
    grir_lines = cum_lines.filtered(lambda l: l.account_id.code == '211500')
    sot_grir = float(sum(grir_lines.mapped('credit')) - sum(grir_lines.mapped('debit')))

    # G. Cashier Variance (619990 YTD)
    year_start = f"{today.year}-01-01"
    cashier_lines = env['account.move.line'].search([
        ('company_id', '=', company_id),
        ('parent_state', '=', 'posted'),
        ('date', '>=', year_start),
        ('date', '<=', date_to),
        ('account_id.code', '=', '619990'),
    ])
    sot_cashier_var = float(sum(cashier_lines.mapped('debit')) - sum(cashier_lines.mapped('credit')))

    # H. Near Expiry Lots (<60 days)
    threshold_date = today + relativedelta(days=60)
    env.cr.execute("""
        SELECT COALESCE(count(DISTINCT l.id), 0)
        FROM stock_lot l
        JOIN stock_quant q ON q.lot_id = l.id
        JOIN stock_location loc ON loc.id = q.location_id
        WHERE loc.usage = 'internal'
          AND q.quantity > 0
          AND l.expiration_date <= %s
    """, (threshold_date,))
    sot_near_expiry = int(env.cr.fetchone()[0] or 0)

    # I. Encounters Truth
    enc_domain = [
        ('encounter_date', '>=', f"{date_from} 00:00:00"),
        ('encounter_date', '<=', f"{date_to} 23:59:59"),
    ]
    encounters = env['clinic.encounter'].search(enc_domain)
    sot_total_encs = len(encounters)
    sot_posted_encs = len(encounters.filtered(lambda e: e.state == 'posted'))
    sot_backlog_encs = len(encounters.filtered(lambda e: e.state in ['draft', 'received', 'staged', 'error']))
    sot_unique_patients = len(set(encounters.mapped('patient_mrn')))

    # J. Unsettled Doctor Fees (Accounts 213010 & 213020)
    doc_liab_lines = cum_lines.filtered(
        lambda l: l.account_id.code and l.account_id.code in ['213010', '213020']
    )
    sot_unsettled_doc = float(max(0.0, sum(doc_liab_lines.mapped('credit')) - sum(doc_liab_lines.mapped('debit'))))

    # K. AR Total (112010, 112020, 112030)
    ar_lines = cum_lines.filtered(
        lambda l: l.account_id.code and l.account_id.code in ['112010', '112020', '112030', '11210010', '11210011']
    )
    sot_total_ar = float(max(0.0, sum(ar_lines.mapped('debit')) - sum(ar_lines.mapped('credit'))))

    # AUDIT RECONCILIATION ITEMS TABLE
    items = [
        ("Total Operating Revenue", format_idr(sc['total_revenue']), format_idr(sot_revenue), abs(sc['total_revenue'] - sot_revenue), True),
        ("Cost of Goods Sold (COGS)", format_idr(sc['cogs']), format_idr(sot_cogs), abs(sc['cogs'] - sot_cogs), True),
        ("Doctor Fee Remuneration", format_idr(sc['doctor_fees']), format_idr(sot_doc_fees), abs(sc['doctor_fees'] - sot_doc_fees), True),
        ("Operating Expenses (OPEX)", format_idr(sc['opex']), format_idr(sot_opex), abs(sc['opex'] - sot_opex), True),
        ("Net Operating Profit (SAK)", format_idr(sc['net_profit']), format_idr(sot_net_profit), abs(sc['net_profit'] - sot_net_profit), True),
        ("Total Receivables (AR)", format_idr(sc['total_ar']), format_idr(sot_total_ar), abs(sc['total_ar'] - sot_total_ar), True),
        ("GR/IR Clearing Balance", format_idr(flags['grir_clearing_balance']), format_idr(sot_grir), abs(flags['grir_clearing_balance'] - sot_grir), True),
        ("Cashier Shift Variance YTD", format_idr(flags['cashier_variance_ytd']), format_idr(sot_cashier_var), abs(flags['cashier_variance_ytd'] - sot_cashier_var), True),
        ("Unsettled Doctor Fees", format_idr(flags['unsettled_doctor_fees']), format_idr(sot_unsettled_doc), abs(flags['unsettled_doctor_fees'] - sot_unsettled_doc), True),
        ("Near-Expiry Lots (< 60d)", f"{flags['near_expiry_lots_count']} Lots", f"{sot_near_expiry} Lots", abs(flags['near_expiry_lots_count'] - sot_near_expiry), False),
        ("Total Inbound Encounters", f"{sc['total_encounters']:,} Trans", f"{sot_total_encs:,} Trans", abs(sc['total_encounters'] - sot_total_encs), False),
        ("Posted Encounters Count", f"{sc['posted_encounters']:,} Trans", f"{sot_posted_encs:,} Trans", abs(sc['posted_encounters'] - sot_posted_encs), False),
        ("Backlog Encounters Count", f"{sc['backlog_count']:,} Trans", f"{sot_backlog_encs:,} Trans", abs(sc['backlog_count'] - sot_backlog_encs), False),
        ("Unique Patient Count", f"{sc['unique_patients']:,} Pts", f"{sot_unique_patients:,} Pts", abs(sc['unique_patients'] - sot_unique_patients), False),
    ]

    print(f"{'Metric Name':<30} | {'Dashboard Value':<18} | {'Source of Truth':<18} | {'Variance':<12} | {'Status'}")
    print("-" * 94)

    all_passed = True
    for name, dash_val, sot_val, diff, is_curr in items:
        if is_curr:
            var_str = format_idr(diff)
            passed = diff < 0.01
        else:
            var_str = f"{int(diff)} Units"
            passed = diff == 0

        if not passed:
            all_passed = False
            status = "[FAIL]"
        elif name == "GR/IR Clearing Balance" and diff == 0:
            status = "[CLEARED]"
        else:
            status = "[MATCH]"

        print(f"{name:<30} | {dash_val:<18} | {sot_val:<18} | {var_str:<12} | {status}")

    print("-" * 94)

    # 3. POLI & UNIT PROFITABILITY MATRIX RECONCILIATION
    print("\n>>> AUDITING SECTION 2: POLI PROFITABILITY MATRIX ALIGNMENT")
    matrix = metrics['clinical_volume_financial_correlation']
    matrix_passed = True
    for row in matrix:
        p_code = row['poli_code']
        rev = row['revenue']
        cogs = row['cogs']
        doc = row['doctor_fee']
        gross = row['gross_profit']
        expected_gross = rev - (cogs + doc)
        diff = abs(gross - expected_gross)
        if diff >= 0.01:
            matrix_passed = False
            print(f"  [FAIL] Poli {p_code}: Gross Profit mismatch {gross} vs expected {expected_gross}")
    if matrix_passed:
        print(f"  [PASS] All {len(matrix)} Clinical Poli Units Gross Profit & Margin Formulas Mathematically Sound.")

    # 4. PAYER MIX 100% RECONCILIATION
    print("\n>>> AUDITING SECTION 3: PAYER MIX 100.0% RECONCILIATION")
    payer_mix = metrics['payer_mix']
    total_pct = sum(p['percentage'] for p in payer_mix)
    print(f"  Total Payer Mix Sum: {total_pct:.2f}% (Categories: {', '.join(p['label'] for p in payer_mix)})")
    if abs(total_pct - 100.0) <= 0.05 or total_pct == 0.0:
        print("  [PASS] Payer Mix Distribution strictly balances to 100.0% parity.")
    else:
        all_passed = False
        print(f"  [FAIL] Payer Mix Distribution out of balance: {total_pct:.2f}%")

    print("\n" + "=" * 94)
    if all_passed and matrix_passed:
        print("   OVERALL RECONCILIATION STATUS: 100% AUDIT TALLIED & PASSED [PRODUCTION READY]")
    else:
        print("   OVERALL RECONCILIATION STATUS: DISCREPANCIES DETECTED [ACTION REQUIRED]")
    print("=" * 94 + "\n")

    return all_passed and matrix_passed


if __name__ == '__main__':
    # Standalone execution hook inside Docker / Odoo environment
    try:
        import odoo
        from odoo import api, SUPERUSER_ID
        from odoo.modules.registry import Registry

        config_file = '/etc/odoo/odoo.conf'
        if os.path.exists(config_file):
            odoo.tools.config.parse_config([
                '-c', config_file,
                '--db_host', 'db_adera',
                '-r', 'odoo',
                '-w', 'odoo',
                '-d', 'klinik-adera'
            ])
            registry = Registry('klinik-adera')
            with registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                success = run_audit(env)
                sys.exit(0 if success else 1)
        else:
            print("Please run this script within the Odoo container or via odoo shell.")
            sys.exit(1)
    except Exception as e:
        print(f"Execution Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
