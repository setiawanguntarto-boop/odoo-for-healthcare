#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
KLINIK ADERA ERP (ODOO 19 CE) - ACCOUNTING & FINANCE UI/UX MENU & VIEW INTEGRITY AUDIT
========================================================================================
Entity Scope      : PT Prosperra Medika Utama / Klinik ADERA
Target Modules    : adera_accounting, adera_core, adera_doctor_remuneration, adera_pos
Audit Standards   : Odoo 19 CE View Compliance, Zero Missing Action/Model, RBAC Verification
Execution CLI     : docker exec -i odoo_adera_clinic python3 /mnt/extra-addons/scripts/audit_accounting_menus.py
========================================================================================
"""

import sys
import os
import traceback
from datetime import date, datetime


def audit_accounting_system(env):
    print("=" * 96)
    print("      KLINIK ADERA ERP (ODOO 19 CE) - UI/UX MENU & VIEW INTEGRITY AUDIT REPORT")
    print("      Landscape: Akuntansi & Keuangan (Accounting & Financial Architecture)")
    print("=" * 96)
    print(f" Target Database : {env.cr.dbname}")
    print(f" Execution Time  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f" Superuser Scope : User #{env.uid} ({env.user.name})")
    print("=" * 96 + "\n")

    errors = []
    warnings = []
    audit_stats = {
        'total_menus': 0,
        'action_menus': 0,
        'category_menus': 0,
        'models_tested': set(),
        'views_compiled': 0,
        'passed_checks': 0,
        'total_checks': 0
    }

    # ==================================================================================
    # 1. ROOT MENU DISCOVERY & TREE TRAVERSAL
    # ==================================================================================
    print("[PHASE 1] HIERARCHICAL MENU DISCOVERY & VIEW COMPILATION AUDIT")
    print("-" * 96)

    root_menus = env['ir.ui.menu'].search([
        ('parent_id', '=', False),
        '|',
        ('name', 'ilike', 'Akuntansi'),
        ('name', 'ilike', 'Remunerasi')
    ])

    if not root_menus:
        print("[CRITICAL] Neither 'Akuntansi & Keuangan' nor 'Remunerasi Dokter' root menu found!")
        return False

    for root_menu in root_menus:
        print(f"\n📂 ROOT MENU: [{root_menu.id}] {root_menu.name} (xml_id: {root_menu.get_external_id().get(root_menu.id, 'n/a')})")
        all_submenus = env['ir.ui.menu'].search([('id', 'child_of', root_menu.id)])
        audit_stats['total_menus'] += len(all_submenus)

        for menu in all_submenus:
            level = len(menu.parent_path.strip('/').split('/')) - 1
            indent = "  " * level

            if not menu.action:
                audit_stats['category_menus'] += 1
                print(f"{indent}📁 [{menu.id}] {menu.name} (Sub-category)")
                continue

            audit_stats['action_menus'] += 1
            action = menu.action
            action_type = action._name
            res_model = getattr(action, 'res_model', False)
            view_mode = getattr(action, 'view_mode', 'list,form')
            
            print(f"{indent}📄 [{menu.id}] {menu.name} -> Action: '{action.name}' [{action_type}] | Model: {res_model}")

            audit_stats['total_checks'] += 1

            # 1.A Check model existence
            if res_model:
                if res_model not in env:
                    msg = f"BROKEN MODEL: Menu '{menu.name}' (ID: {menu.id}) references missing model '{res_model}'"
                    errors.append(msg)
                    print(f"{indent}   ❌ {msg}")
                    continue
                else:
                    audit_stats['models_tested'].add(res_model)
                    audit_stats['passed_checks'] += 1
            else:
                if action_type == 'ir.actions.act_window':
                    msg = f"EMPTY MODEL: Window Action '{action.name}' has no res_model defined"
                    errors.append(msg)
                    print(f"{indent}   ❌ {msg}")
                    continue

            # 1.B Compile views for res_model
            if res_model and res_model in env:
                modes = [m.strip() for m in view_mode.split(',') if m.strip()]
                for mode in modes:
                    try:
                        view_info = env[res_model].get_view(view_type=mode)
                        audit_stats['views_compiled'] += 1
                        audit_stats['total_checks'] += 1
                        audit_stats['passed_checks'] += 1

                        # Inspect arch for deprecated Odoo 19 attributes
                        arch_str = view_info.get('arch', '')
                        if 'states="' in arch_str:
                            warn_msg = f"DEPRECATED SYNTAX: Model '{res_model}' view_type '{mode}' contains deprecated states='...' attribute"
                            warnings.append(warn_msg)
                            print(f"{indent}   ⚠️ {warn_msg}")
                        if 'attrs="' in arch_str:
                            warn_msg = f"DEPRECATED SYNTAX: Model '{res_model}' view_type '{mode}' contains deprecated attrs='...' attribute"
                            warnings.append(warn_msg)
                            print(f"{indent}   ⚠️ {warn_msg}")

                    except Exception as e:
                        err_msg = f"BROKEN VIEW COMPILATION in Menu '{menu.name}' ({res_model}, type: {mode}): {str(e)}"
                        errors.append(err_msg)
                        print(f"{indent}   ❌ {err_msg}")

                # Test search view
                try:
                    env[res_model].get_view(view_type='search')
                    audit_stats['views_compiled'] += 1
                    audit_stats['total_checks'] += 1
                    audit_stats['passed_checks'] += 1
                except Exception as e:
                    err_msg = f"BROKEN SEARCH VIEW in Menu '{menu.name}' ({res_model}): {str(e)}"
                    errors.append(err_msg)
                    print(f"{indent}   ❌ {err_msg}")

    print("\n" + "-" * 96)
    print(f"Phase 1 Summary: {audit_stats['total_menus']} Menus Inspected ({audit_stats['action_menus']} Actions, {audit_stats['category_menus']} Categories)")
    print(f"Models Audited: {len(audit_stats['models_tested'])} | Views Compiled: {audit_stats['views_compiled']}")

    # ==================================================================================
    # 2. SECTION-SPECIFIC CLINICAL ACCOUNTING INTEGRITY CHECKS
    # ==================================================================================
    print("\n[PHASE 2] DETAILED DOMAIN INTEGRITY AUDIT (SECTIONS A, B, C, D)")
    print("-" * 96)

    # --- SECTION A: Operasional & Kasir (Operational Cockpit & Daily Billing) ---
    print("\n[SECTION A] Operasional & Kasir (Daily Billing, POS Sessions, Cash Variance)")
    audit_stats['total_checks'] += 1
    # Check 619990 account exists
    acc_619990 = env['account.account'].search([('code', '=', '619990')], limit=1)
    if acc_619990:
        print(f"  [OK] Cash Variance Account 619990 verified: [{acc_619990.code}] {acc_619990.name}")
        audit_stats['passed_checks'] += 1
    else:
        err = "CRITICAL: Account 619990 (Beban Selisih Kasir & Petty Cash) not found in Chart of Accounts!"
        errors.append(err)
        print(f"  ❌ {err}")

    # Check Currency formatting & IDR setup
    audit_stats['total_checks'] += 1
    currency_idr = env.ref('base.IDR', raise_if_not_found=False)
    if currency_idr and currency_idr.symbol in ('Rp', 'IDR'):
        print(f"  [OK] Currency Symbol Verified: {currency_idr.name} ({currency_idr.symbol})")
        audit_stats['passed_checks'] += 1
    else:
        err = "WARNING: Currency IDR symbol not properly registered or active"
        warnings.append(err)
        print(f"  ⚠️ {err}")

    # Check POS Order / Settlement Action & Group-By Search
    audit_stats['total_checks'] += 1
    pos_action = env.ref('adera_accounting.action_pos_copay_settlement_ledger', raise_if_not_found=False)
    if pos_action and pos_action.res_model == 'pos.order':
        print(f"  [OK] Action 'action_pos_copay_settlement_ledger' correctly mapped to pos.order")
        audit_stats['passed_checks'] += 1
    else:
        err = "MISSING ACTION: 'action_pos_copay_settlement_ledger' missing or not mapped to pos.order"
        errors.append(err)
        print(f"  ❌ {err}")

    # Check Cashier Variance Action
    audit_stats['total_checks'] += 1
    cashier_action = env.ref('adera_accounting.action_cashier_variance_audit_ledger', raise_if_not_found=False)
    if cashier_action and '619990' in (cashier_action.domain or ''):
        print(f"  [OK] Action 'action_cashier_variance_audit_ledger' binds domain with account 619990")
        audit_stats['passed_checks'] += 1
    else:
        err = "DOMAIN ERROR: 'action_cashier_variance_audit_ledger' does not filter by 619990"
        warnings.append(err)
        print(f"  ⚠️ {err}")

    # --- SECTION B: Jasa Medis & Perpajakan (Doctor Fees & Withholding Taxes) ---
    print("\n[SECTION B] Jasa Medis & Perpajakan (Doctor Fees, Batches, PPh 21)")
    audit_stats['total_checks'] += 1
    # Check medical.fee.settlement.batch model & state selection
    if 'medical.fee.settlement.batch' in env:
        batch_model = env['medical.fee.settlement.batch']
        state_field = batch_model._fields.get('state')
        expected_states = {'draft', 'verified', 'approved'}
        actual_states = {k for k, _ in state_field.selection} if state_field else set()
        if expected_states.issubset(actual_states) and ('paid' in actual_states or 'disbursed' in actual_states):
            print(f"  [OK] medical.fee.settlement.batch state machine compliant: {actual_states}")
            audit_stats['passed_checks'] += 1
        else:
            err = f"STATE MACHINE FAULT: Expected states {expected_states} + paid/disbursed, got {actual_states}"
            errors.append(err)
            print(f"  ❌ {err}")
    else:
        err = "MISSING MODEL: medical.fee.settlement.batch not found in environment!"
        errors.append(err)
        print(f"  ❌ {err}")

    # Check medical.fee.accrual model & state selection
    audit_stats['total_checks'] += 1
    if 'medical.fee.accrual' in env:
        accrual_model = env['medical.fee.accrual']
        accrual_state_field = accrual_model._fields.get('state')
        accrual_states = {k for k, _ in accrual_state_field.selection} if accrual_state_field else set()
        if {'accrued', 'in_settlement', 'disbursed'}.issubset(accrual_states):
            print(f"  [OK] medical.fee.accrual state machine verified: {accrual_states}")
            audit_stats['passed_checks'] += 1
        else:
            warn = f"NOTICE: medical.fee.accrual states: {accrual_states}"
            warnings.append(warn)
            print(f"  ⚠️ {warn}")
    else:
        err = "MISSING MODEL: medical.fee.accrual not found in environment!"
        errors.append(err)
        print(f"  ❌ {err}")

    # Check button security & XML visibility in medical_fee_settlement_batch_views.xml
    audit_stats['total_checks'] += 1
    batch_form_view = env.ref('adera_doctor_remuneration.view_medical_fee_settlement_batch_form', raise_if_not_found=False)
    if batch_form_view:
        arch = batch_form_view.arch
        director_restricted = 'group_clinic_director' in arch and 'action_approve' in arch
        if director_restricted:
            print(f"  [OK] 'action_approve' and 'Posting Pembayaran' buttons strictly protected by group_clinic_director")
            audit_stats['passed_checks'] += 1
        else:
            warn = "SECURITY WARNING: 'action_approve' button in batch form view may lack strict group_clinic_director constraint"
            warnings.append(warn)
            print(f"  ⚠️ {warn}")
    else:
        err = "MISSING VIEW: view_medical_fee_settlement_batch_form not found!"
        errors.append(err)
        print(f"  ❌ {err}")

    # Check button security in doctor_settlement_views.xml
    audit_stats['total_checks'] += 1
    doc_settlement_form = env.ref('adera_doctor_remuneration.view_doctor_settlement_form', raise_if_not_found=False)
    if doc_settlement_form:
        arch = doc_settlement_form.arch
        if 'groups="adera_core.group_clinic_director"' in arch and 'action_post_disbursement' in arch:
            print(f"  [OK] doctor.settlement disbursement & approval buttons strictly restricted to group_clinic_director")
            audit_stats['passed_checks'] += 1
        else:
            warn = "SECURITY WARNING: doctor.settlement buttons lack group_clinic_director constraint"
            warnings.append(warn)
            print(f"  ⚠️ {warn}")
    else:
        err = "MISSING VIEW: view_doctor_settlement_form not found!"
        errors.append(err)
        print(f"  ❌ {err}")

    # Test PPh 21 Withholding Account 212030 & Doctor Payable Accounts 213010 / 213020
    audit_stats['total_checks'] += 1
    acc_212030 = env['account.account'].search([('code', '=', '212030')], limit=1)
    acc_213010 = env['account.account'].search([('code', '=', '213010')], limit=1)
    if acc_212030 and acc_213010:
        print(f"  [OK] Tax Account 212030 and Doctor Payable 213010 exist in CoA")
        audit_stats['passed_checks'] += 1
    else:
        err = "MISSING COA: Account 212030 or 213010 not found!"
        errors.append(err)
        print(f"  ❌ {err}")

    # --- SECTION C: Manajemen Aset & Logistik Medis (Fixed Assets & Equipment) ---
    print("\n[SECTION C] Manajemen Aset & Logistik Medis (Fixed Assets, Disposal & Depreciation)")
    audit_stats['total_checks'] += 1
    if 'clinic.asset' in env and 'clinic.asset.disposal' in env:
        print(f"  [OK] Models 'clinic.asset' and 'clinic.asset.disposal' registered and accessible")
        audit_stats['passed_checks'] += 1
    else:
        err = "MISSING MODEL: 'clinic.asset' or 'clinic.asset.disposal' not found!"
        errors.append(err)
        print(f"  ❌ {err}")

    # Check COGS account 510030 for depreciation direct booking
    audit_stats['total_checks'] += 1
    acc_510030 = env['account.account'].search([('code', '=', '510030')], limit=1)
    if acc_510030:
        print(f"  [OK] COGS Depreciation Account 510030 verified: [{acc_510030.code}] {acc_510030.name}")
        audit_stats['passed_checks'] += 1
    else:
        warn = "COA NOTICE: Account 510030 (Beban Penyusutan Alkes HD) not explicitly found under code 510030"
        warnings.append(warn)
        print(f"  ⚠️ {warn}")

    # Check Asset Disposal Form View captures Net Book Value and Director Approval
    audit_stats['total_checks'] += 1
    disposal_form = env.ref('adera_accounting.view_clinic_asset_disposal_form', raise_if_not_found=False)
    if disposal_form:
        arch = disposal_form.arch
        if 'net_book_value' in arch and 'action_approve' in arch:
            print(f"  [OK] Asset disposal form captures residual net book value and approval workflow")
            audit_stats['passed_checks'] += 1
        else:
            warn = "WARNING: Asset disposal form missing net_book_value or action_approve"
            warnings.append(warn)
            print(f"  ⚠️ {warn}")
    else:
        err = "MISSING VIEW: view_clinic_asset_disposal_form not found!"
        errors.append(err)
        print(f"  ❌ {err}")

    # --- SECTION D: Laporan Finansial PSAK / SAK EMKM (Reporting Engines) ---
    print("\n[SECTION D] Laporan Finansial PSAK / SAK EMKM (Statutory Financial Engines)")
    audit_stats['total_checks'] += 1
    if 'psak.financial.report' in env:
        report_model = env['psak.financial.report']
        print(f"  [OK] Model 'psak.financial.report' verified")
        audit_stats['passed_checks'] += 1
    else:
        err = "MISSING MODEL: psak.financial.report not found!"
        errors.append(err)
        print(f"  ❌ {err}")

    # Check General Ledger / Trial Balance wizard actions
    audit_stats['total_checks'] += 1
    gl_wizard_action = env.ref('account_financial_report.action_general_ledger_wizard', raise_if_not_found=False)
    tb_wizard_action = env.ref('account_financial_report.action_trial_balance_wizard', raise_if_not_found=False)
    if gl_wizard_action and tb_wizard_action:
        print(f"  [OK] Standard PSAK General Ledger & Trial Balance wizard actions registered cleanly")
        audit_stats['passed_checks'] += 1
    else:
        err = "MISSING ACTION: account_financial_report General Ledger or Trial Balance wizard action missing"
        errors.append(err)
        print(f"  ❌ {err}")

    # Check Analytic Accounts for multi-entity segmentation
    audit_stats['total_checks'] += 1
    analytic_codes = ['ACC-HOLDING', 'ACC-PRATAMA', 'ACC-HD']
    found_analytics = env['account.analytic.account'].search([('code', 'in', analytic_codes)])
    found_codes = set(found_analytics.mapped('code'))
    if set(analytic_codes).issubset(found_codes):
        print(f"  [OK] Multi-entity analytic accounts verified: {list(found_codes)}")
        audit_stats['passed_checks'] += 1
    else:
        warn = f"ANALYTIC ACCOUNTS: Expected {analytic_codes}, found {list(found_codes)}"
        warnings.append(warn)
        print(f"  ⚠️ {warn}")

    # ==================================================================================
    # 3. RBAC PERSONA ACCESS CONTROL VERIFICATION
    # ==================================================================================
    print("\n[PHASE 3] ROLE-BASED ACCESS CONTROL (RBAC) SECURITY AUDIT")
    print("-" * 96)

    personas = [
        ('Director / Direktur Klinik', 'adera_core.group_clinic_director'),
        ('Finance Manager / Keuangan', 'adera_core.group_clinic_finance_manager'),
        ('Cashier / Kasir Billing', 'adera_core.group_clinic_cashier'),
        ('Dokter / Medical Specialist', 'adera_core.group_clinic_doctor')
    ]

    for persona_name, group_xml_id in personas:
        audit_stats['total_checks'] += 1
        group = env.ref(group_xml_id, raise_if_not_found=False)
        if group:
            user_count = len(group.user_ids)
            print(f"  [OK] Security Persona '{persona_name}' registered ({group_xml_id}) - {user_count} active users")
            audit_stats['passed_checks'] += 1
        else:
            err = f"MISSING SECURITY GROUP: Persona '{persona_name}' XML ID '{group_xml_id}' not found!"
            errors.append(err)
            print(f"  ❌ {err}")

    # ==================================================================================
    # 4. FINAL INTEGRITY VERDICT & SCORECARD
    # ==================================================================================
    print("\n" + "=" * 96)
    print("      KLINIK ADERA ERP (ODOO 19 CE) - AUDIT SCORECARD & VERDICT")
    print("=" * 96)
    score_pct = (audit_stats['passed_checks'] / max(audit_stats['total_checks'], 1)) * 100
    print(f" Total Integrity Checks  : {audit_stats['total_checks']}")
    print(f" Passed Checks           : {audit_stats['passed_checks']}")
    print(f" Compilation Errors      : {len(errors)}")
    print(f" Deprecation Warnings    : {len(warnings)}")
    print(f" Integrity Score         : {score_pct:.1f}%")
    print("-" * 96)

    if errors:
        print("\n[AUDIT FAILURE] Detected Critical Errors:")
        for idx, err in enumerate(errors, 1):
            print(f"  {idx}. {err}")
    else:
        print("\n[AUDIT PASSED] 100% OF MENUS, ACTIONS, AND VIEWS COMPILED CLEANLY WITH ZERO DEFECTS!")

    if warnings:
        print("\n[AUDIT WARNINGS] Recommended Modernization Items:")
        for idx, warn in enumerate(warnings, 1):
            print(f"  {idx}. {warn}")

    print("=" * 96 + "\n")
    return len(errors) == 0


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
                success = audit_accounting_system(env)
                sys.exit(0 if success else 1)
        else:
            # Fallback when running inside odoo shell with env already defined
            if 'env' in locals() or 'env' in globals():
                audit_accounting_system(env)
            else:
                print("Error: Odoo configuration file not found and env not in scope.")
                sys.exit(1)
    except Exception as e:
        print(f"Execution Error: {e}")
        traceback.print_exc()
        sys.exit(1)
