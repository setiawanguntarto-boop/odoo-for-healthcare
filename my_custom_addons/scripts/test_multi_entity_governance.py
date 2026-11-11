# -*- coding: utf-8 -*-
"""Verification test script for Multi-Entity & Multi-Branch Analytic Governance Engine."""
import sys
import logging
from datetime import date
from odoo import api, SUPERUSER_ID

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger("test_multi_entity_governance")

def run_test(env):
    _logger.info("=================================================================")
    _logger.info("STARTING CLINIC ADERA MULTI-ENTITY GOVERNANCE VERIFICATION")
    _logger.info("=================================================================")

    # 1. Verify Analytic Accounts & Plan
    plan = env.ref("adera_core.analytic_plan_adera_entities", raise_if_not_found=False) or env.ref("adera_core.analytic_plan_adera", raise_if_not_found=False)
    assert plan, "Analytic Plan ADERA not found!"
    _logger.info("PASS: Master Analytic Plan verified: %s (ID %s)", plan.name, plan.id)

    acc_holding = env.ref("adera_core.analytic_acc_holding", raise_if_not_found=False) or env.ref("adera_core.analytic_account_holding_root", raise_if_not_found=False)
    acc_pratama = env.ref("adera_core.analytic_acc_pratama", raise_if_not_found=False) or env.ref("adera_core.analytic_account_pratama_root", raise_if_not_found=False)
    acc_hd = env.ref("adera_core.analytic_acc_hd", raise_if_not_found=False) or env.ref("adera_core.analytic_account_hd_root", raise_if_not_found=False)

    assert acc_holding and acc_pratama and acc_hd, "Root Analytic accounts (HOLDING, PRATAMA, HD) missing!"
    _logger.info("PASS: Root Entities verified: HOLDING (%s), PRATAMA (%s), HD (%s)", acc_holding.code, acc_pratama.code, acc_hd.code)

    # 2. Ingest 1 Corporate HQ Bill / Expense tagged ACC-HOLDING
    journal_misc = env["account.journal"].search([("type", "=", "general")], limit=1)
    acc_hq_expense = env.ref("adera_core.account_619990", raise_if_not_found=False)
    acc_bank = env.ref("adera_core.account_111110", raise_if_not_found=False)

    test_holding_move = env["account.move"].create({
        "journal_id": journal_misc.id,
        "date": date.today(),
        "ref": "TEST-CORP-EXPENSE-001",
        "line_ids": [
            (0, 0, {
                "name": "Beban Manajemen Operasional Kantor Pusat",
                "account_id": acc_hq_expense.id,
                "debit": 10000000.0,
                "credit": 0.0,
                "analytic_distribution": {str(acc_holding.id): 100.0},
            }),
            (0, 0, {
                "name": "Kas/Bank Operasional",
                "account_id": acc_bank.id,
                "debit": 0.0,
                "credit": 10000000.0,
            }),
        ],
    })
    test_holding_move.action_post()
    _logger.info("PASS: Ingested corporate HQ bill Rp 10,000,000 tagged ACC-HOLDING: Move %s", test_holding_move.name)

    # 3. Test Shared Cost Allocation Execution (e.g. 60/40 Split)
    alloc = env["clinic.shared_cost.allocation"].create({
        "period_start": date.today().replace(day=1),
        "period_end": date.today(),
        "allocation_basis": "fixed_split",
        "pratama_share_pct": 60.0,
        "hd_share_pct": 40.0,
        "total_holding_pool": 10000000.0,
    })
    alloc.action_calculate()
    assert alloc.allocated_amount_pratama == 6000000.0, f"Expected 6M Pratama, got {alloc.allocated_amount_pratama}"
    assert alloc.allocated_amount_hd == 4000000.0, f"Expected 4M HD, got {alloc.allocated_amount_hd}"

    alloc.action_execute_allocation()
    assert alloc.state == "posted", "Allocation move posting failed!"
    _logger.info("PASS: Shared cost allocation executed successfully: Move %s", alloc.account_move_id.name)

    # 4. Verify Net Consolidated Impact is strictly Rp 0.00
    alloc_move = alloc.account_move_id
    total_debit = sum(alloc_move.line_ids.mapped("debit"))
    total_credit = sum(alloc_move.line_ids.mapped("credit"))
    assert abs(total_debit - total_credit) < 0.01, "Allocation entry does not balance!"

    clearing_line = alloc_move.line_ids.filtered(lambda l: l.account_id.code_store == "619980")
    pratama_line = alloc_move.line_ids.filtered(lambda l: l.account_id.code_store == "619981")
    hd_line = alloc_move.line_ids.filtered(lambda l: l.account_id.code_store == "619982")

    assert clearing_line.credit == 10000000.0, "Clearing credit mismatch!"
    assert pratama_line.debit == 6000000.0, "Pratama debit mismatch!"
    assert hd_line.debit == 4000000.0, "HD debit mismatch!"
    _logger.info("PASS: Net Consolidated P&L Impact verified: Clearing 619980 (-10M) + Pratama 619981 (+6M) + HD 619982 (+4M) = Rp 0.00")

    # 5. Verify Inter-Entity Related Party Balancing Trigger
    test_inter_move = env["account.move"].create({
        "journal_id": journal_misc.id,
        "date": date.today(),
        "ref": "TEST-INTER-ENTITY-TALANGAN",
        "is_inter_entity": True,
        "inter_entity_type": "holding_advance_supplier",
        "beneficiary_unit": "hd",
        "line_ids": [
            (0, 0, {
                "name": "Talangan Holding untuk Alkes HD",
                "account_id": env.ref("adera_core.account_112040").id,
                "debit": 5000000.0,
                "credit": 0.0,
                "analytic_distribution": {str(acc_holding.id): 100.0},
            }),
            (0, 0, {
                "name": "Pembayaran Bank BCA Holding",
                "account_id": acc_bank.id,
                "debit": 0.0,
                "credit": 5000000.0,
            }),
        ],
    })
    test_inter_move.action_post()
    test_inter_move.action_generate_reciprocal_entry()

    assert test_inter_move.inter_entity_clearing_move_id, "Reciprocal entry was not generated!"
    reciprocal = test_inter_move.inter_entity_clearing_move_id
    rec_debt_line = reciprocal.line_ids.filtered(lambda l: l.account_id.code_store == "214040")
    assert rec_debt_line.credit == 5000000.0, "Reciprocal debt credit mismatch!"
    _logger.info("PASS: Inter-Entity clearing verified: 112040 (Debit 5M) and 214040 (Credit 5M) net sum = Rp 0.00")

    _logger.info("=================================================================")
    _logger.info("ALL MULTI-ENTITY GOVERNANCE AUDIT TESTS PASSED SUCCESSFULLY!")
    _logger.info("=================================================================")
    return True

if __name__ == "__main__":
    pass
