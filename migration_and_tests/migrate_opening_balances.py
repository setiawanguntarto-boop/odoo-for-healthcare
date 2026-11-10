# -*- coding: utf-8 -*-
"""
Cut-Over Migration Script: Opening Balances for Klinik ADERA ERP (Odoo 19 CE)
Executes within Odoo shell or standalone odoo-bin shell environment:
python odoo-bin shell -c odoo.conf -d <DB_NAME> < migrate_opening_balances.py
"""

import csv
import os
import logging
from datetime import datetime

_logger = logging.getLogger("adera.migration")

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else '/mnt/extra-addons/migration_and_tests'
OPEN_AP_CSV = os.path.join(BASE_DIR, "open_ap.csv")
OPEN_AR_CSV = os.path.join(BASE_DIR, "open_ar.csv")
OPEN_STOCK_CSV = os.path.join(BASE_DIR, "open_stock.csv")


def get_or_create_suspense_account(env):
    """Mendapatkan atau membuat akun perantara saldo awal (Opening Balance Suspense: 999999)."""
    acc = env['account.account'].search([('code', '=', '999999')], limit=1)
    if not acc:
        acc = env['account.account'].create({
            'code': '999999',
            'name': 'Saldo Awal Migrasi (Opening Balance Suspense / Equity)',
            'account_type': 'equity_unaffected',
        })
    return acc


def get_or_create_opening_journal(env):
    """Mendapatkan atau membuat jurnal memorial saldo awal (MISC-OPEN)."""
    journal = env['account.journal'].search([('code', '=', 'MOPEN')], limit=1)
    if not journal:
        journal = env['account.journal'].create({
            'name': 'Jurnal Saldo Awal Migrasi',
            'code': 'MOPEN',
            'type': 'general',
        })
    return journal


def migrate_open_ap(env):
    print("\n--- [1/3] Migrating Open Vendor Bills (AP) ---")
    if not os.path.exists(OPEN_AP_CSV):
        print(f"Skipping: {OPEN_AP_CSV} not found.")
        return

    suspense_acc = get_or_create_suspense_account(env)
    ap_acc = env.ref('adera_core.account_211010')
    bill_journal = env.ref('adera_core.journal_bill_med')

    with open(OPEN_AP_CSV, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            vendor_name = row['Vendor Name'].strip()
            partner = env['res.partner'].search([('name', '=', vendor_name)], limit=1)
            if not partner:
                partner = env['res.partner'].create({
                    'name': vendor_name,
                    'supplier_rank': 1,
                    'property_account_payable_id': ap_acc.id,
                })
            else:
                partner.property_account_payable_id = ap_acc.id

            existing_bill = env['account.move'].search([
                ('ref', '=', f"SALDO AWAL: {row['Bill Reference']}"),
            ], limit=1)
            if existing_bill:
                pay_line = existing_bill.line_ids.filtered(lambda l: l.account_id.account_type == 'liability_payable')
                if pay_line and pay_line.account_id.id != ap_acc.id:
                    existing_bill.button_draft()
                    pay_line.account_id = ap_acc.id
                    existing_bill.action_post()
                print(f"  [=] Updated/Verified Opening Bill: {existing_bill.name} | Vendor: {vendor_name} | Account: 211010")
                continue

            amount = float(row['Untaxed Amount'])
            bill_vals = {
                'move_type': 'in_invoice',
                'partner_id': partner.id,
                'journal_id': bill_journal.id,
                'invoice_date': row['Bill Date'],
                'invoice_date_due': row['Due Date'],
                'ref': f"SALDO AWAL: {row['Bill Reference']}",
                'invoice_line_ids': [
                    (0, 0, {
                        'name': f"Saldo Awal Utang: {row['Bill Reference']}",
                        'account_id': suspense_acc.id,
                        'price_unit': amount,
                        'quantity': 1.0,
                    })
                ]
            }
            bill = env['account.move'].create(bill_vals)
            bill.action_post()
            print(f"  [+] Created Opening Bill: {bill.name} | Vendor: {vendor_name} | Rp {amount:,.2f}")


def migrate_open_ar(env):
    print("\n--- [2/3] Migrating Open Patient & BPJS Receivables (AR) ---")
    if not os.path.exists(OPEN_AR_CSV):
        print(f"Skipping: {OPEN_AR_CSV} not found.")
        return

    suspense_acc = get_or_create_suspense_account(env)
    inv_journal = env.ref('adera_core.journal_inv_out')

    with open(OPEN_AR_CSV, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            debtor_name = row['Debtor Name'].strip()
            target_ar_acc = None
            acc_code = row.get('Account Code', '').strip()
            if acc_code:
                target_ar_acc = env['account.account'].search([('code', '=', acc_code)], limit=1)
            if not target_ar_acc:
                target_ar_acc = env['account.account'].search([('code', '=', '112010')], limit=1)

            partner = env['res.partner'].search([('name', '=', debtor_name)], limit=1)
            if not partner:
                partner = env['res.partner'].create({
                    'name': debtor_name,
                    'customer_rank': 1,
                    'property_account_receivable_id': target_ar_acc.id,
                })
            else:
                partner.property_account_receivable_id = target_ar_acc.id

            existing_inv = env['account.move'].search([
                ('ref', '=', f"SALDO AWAL: {row['Claim / Invoice Reference']}"),
            ], limit=1)
            if existing_inv:
                rec_line = existing_inv.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable')
                if rec_line and rec_line.account_id.id != target_ar_acc.id:
                    existing_inv.button_draft()
                    rec_line.account_id = target_ar_acc.id
                    existing_inv.action_post()
                print(f"  [=] Updated/Verified Opening Invoice: {existing_inv.name} | Debtor: {debtor_name} | Account: {target_ar_acc.code}")
                continue

            amount = float(row['Amount'])
            inv_vals = {
                'move_type': 'out_invoice',
                'partner_id': partner.id,
                'journal_id': inv_journal.id,
                'invoice_date': row['Date'],
                'invoice_date_due': row['Due Date'],
                'ref': f"SALDO AWAL: {row['Claim / Invoice Reference']}",
                'invoice_line_ids': [
                    (0, 0, {
                        'name': f"Saldo Awal Piutang: {row['Claim / Invoice Reference']}",
                        'account_id': suspense_acc.id,
                        'price_unit': amount,
                        'quantity': 1.0,
                    })
                ]
            }
            invoice = env['account.move'].create(inv_vals)
            invoice.action_post()
            print(f"  [+] Created Opening Claim/Invoice: {invoice.name} | Debtor: {debtor_name} | Rp {amount:,.2f}")


def migrate_open_stock(env):
    print("\n--- [3/3] Migrating Physical Stock with FEFO Lots & Expiry ---")
    if not os.path.exists(OPEN_STOCK_CSV):
        print(f"Skipping: {OPEN_STOCK_CSV} not found.")
        return

    with open(OPEN_STOCK_CSV, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            prod_code = row['Product Code'].strip()
            product = env['product.product'].search([('default_code', '=', prod_code)], limit=1)
            if not product:
                print(f"  [-] Warning: Product code {prod_code} not found in database. Skipping.")
                continue

            # Resolve Location
            loc_name = row['Location'].strip()
            location = env['stock.location'].search([('complete_name', 'ilike', loc_name)], limit=1)
            if not location:
                location = env.ref('adera_inventory.stock_location_farmasi', raise_if_not_found=False) or env.ref('stock.stock_location_stock')

            lot_name = row['Lot Number'].strip()
            exp_date = row['Expiration Date'].strip()
            qty = float(row['Counted Quantity'])
            cost = float(row['Unit Cost'])

            # Create or update Lot
            lot = env['stock.lot'].search([('name', '=', lot_name), ('product_id', '=', product.id)], limit=1)
            if not lot:
                lot = env['stock.lot'].create({
                    'name': lot_name,
                    'product_id': product.id,
                    'expiration_date': f"{exp_date} 00:00:00",
                })

            # Create Quant inventory adjustment
            quant = env['stock.quant'].create({
                'product_id': product.id,
                'location_id': location.id,
                'lot_id': lot.id,
                'inventory_quantity': qty,
            })
            quant.action_apply_inventory()

            # Update standard price if needed
            product.standard_price = cost
            print(f"  [+] Adjusted Stock: {product.name} ({prod_code}) | Qty: {qty} | Lot: {lot_name} (Exp: {exp_date})")


    # Post Perpetual Inventory Valuation GL Entry
    suspense_acc = get_or_create_suspense_account(env)
    misc_journal = env.ref('adera_core.journal_misc_clinic', raise_if_not_found=False) or get_or_create_opening_journal(env)
    inv_farm_acc = env['account.account'].search([('code', 'in', ['114010', '113010'])], limit=1)
    inv_bhp_acc = env['account.account'].search([('code', 'in', ['114020', '114030', '113020'])], limit=1)

    with open(OPEN_STOCK_CSV, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        valuation_lines = []
        tot_val = 0.0
        for row in reader:
            qty = float(row['Counted Quantity'])
            cost = float(row['Unit Cost'])
            line_val = round(qty * cost, 2)
            tot_val += line_val
            prod_code = row['Product Code'].strip()
            target_acc = inv_farm_acc if prod_code.startswith('MED-') else inv_bhp_acc
            valuation_lines.append((0, 0, {
                'name': f"Saldo Awal Persediaan: {row['Product Code']} (Lot: {row['Lot Number']})",
                'account_id': target_acc.id,
                'debit': line_val,
                'credit': 0.0,
            }))

        existing_stock_move = env['account.move'].search([
            ('ref', '=', 'SALDO AWAL: Penilaian Fisik Persediaan (Cutover)'),
        ], limit=1)
        if not existing_stock_move and valuation_lines:
            valuation_lines.append((0, 0, {
                'name': "Saldo Awal Persediaan Fisik (Opening Suspense)",
                'account_id': suspense_acc.id,
                'debit': 0.0,
                'credit': tot_val,
            }))
            stock_move = env['account.move'].create({
                'journal_id': misc_journal.id,
                'date': '2026-10-31',
                'ref': 'SALDO AWAL: Penilaian Fisik Persediaan (Cutover)',
                'line_ids': valuation_lines,
            })
            stock_move.action_post()
            print(f"  [+] Created Opening Stock Valuation Journal: {stock_move.name} | Rp {tot_val:,.2f}")
        elif existing_stock_move:
            print(f"  [=] Verified Opening Stock Valuation Journal: {existing_stock_move.name} | Rp {tot_val:,.2f}")


def balance_suspense_account(env):
    """Menyeimbangkan akun perantara migrasi (999999) ke Ekuitas Pemilik (310010) agar saldo bersih Rp 0,00."""
    print("\n--- [4/4] Balancing Opening Suspense (999999) to Equity (310010) ---")
    suspense_acc = get_or_create_suspense_account(env)
    equity_acc = env['account.account'].search([('code', '=', '310010')], limit=1)
    misc_journal = env.ref('adera_core.journal_misc_clinic', raise_if_not_found=False) or get_or_create_opening_journal(env)

    # Clean previous balancing moves if recalculating
    old_bal_moves = env['account.move'].search([
        ('ref', '=', 'SALDO AWAL: Eliminasi Akun Perantara Migrasi 999999 ke Ekuitas'),
    ])
    for obm in old_bal_moves:
        obm.button_draft()
        obm.unlink()

    # Re-verify Bulaksumur finding #3 move parent_state
    bulaksumur_move = env['account.move'].search([('ref', 'ilike', 'Bulaksumur')], limit=1)
    if bulaksumur_move and any(l.parent_state != 'posted' for l in bulaksumur_move.line_ids):
        bulaksumur_move.button_draft()
        bulaksumur_move.action_post()

    # Compute net balance of 999999
    lines = env['account.move.line'].search([
        ('account_id', '=', suspense_acc.id),
        ('parent_state', '=', 'posted'),
    ])
    total_debit = sum(lines.mapped('debit'))
    total_credit = sum(lines.mapped('credit'))
    net_diff = total_debit - total_credit

    if abs(net_diff) > 0.001:
        if net_diff > 0:
            # Debit exceeds credit, need credit to suspense and debit to equity
            bal_lines = [
                (0, 0, {
                    'name': 'Penyeimbang Saldo Awal Migrasi ke Ekuitas',
                    'account_id': equity_acc.id,
                    'debit': net_diff,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': 'Nol-kan Saldo Perantara Migrasi 999999',
                    'account_id': suspense_acc.id,
                    'debit': 0.0,
                    'credit': net_diff,
                }),
            ]
        else:
            # Credit exceeds debit, need debit to suspense and credit to equity
            diff_abs = abs(net_diff)
            bal_lines = [
                (0, 0, {
                    'name': 'Nol-kan Saldo Perantara Migrasi 999999',
                    'account_id': suspense_acc.id,
                    'debit': diff_abs,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': 'Penyeimbang Saldo Awal Migrasi ke Ekuitas Pemilik',
                    'account_id': equity_acc.id,
                    'debit': 0.0,
                    'credit': diff_abs,
                }),
            ]

        bal_move = env['account.move'].create({
            'journal_id': misc_journal.id,
            'date': '2026-10-31',
            'ref': 'SALDO AWAL: Eliminasi Akun Perantara Migrasi 999999 ke Ekuitas',
            'line_ids': bal_lines,
        })
        bal_move.action_post()
        print(f"  [+] Balanced Suspense Account to Equity: {bal_move.name} | Rp {abs(net_diff):,.2f}")
    else:
        print("  [+] Suspense Account 999999 already zero-balanced.")


def run_migration(env):
    print("=" * 70)
    print("KLINIK ADERA - OPENING BALANCE CUT-OVER MIGRATION SUITE")
    print("=" * 70)
    migrate_open_ap(env)
    migrate_open_ar(env)
    migrate_open_stock(env)
    balance_suspense_account(env)
    env.cr.commit()
    print("\n" + "=" * 70)
    print("MIGRATION COMPLETED SUCCESSFULLY.")
    print("=" * 70)


# If executed in Odoo shell where `env` is automatically provided:
if 'env' in locals():
    run_migration(env)

