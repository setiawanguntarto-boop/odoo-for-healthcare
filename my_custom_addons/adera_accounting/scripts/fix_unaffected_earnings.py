# -*- coding: utf-8 -*-
"""
Fix Unaffected Earnings Account Misconfiguration for Klinik ADERA ERP.
Ensures exactly ONE account has account_type = 'equity_unaffected' per company.
"""
import logging

_logger = logging.getLogger("adera.fix.equity")


def run_fix(env):
    company = env.company
    _logger.info("Executing equity account audit for company: %s (ID: %s)", company.name, company.id)

    Account = env["account.account"]

    # 1. Search for all accounts currently marked as equity_unaffected
    unaffected_accounts = Account.search([
        ("account_type", "=", "equity_unaffected"),
        ("company_ids", "in", [company.id]),
    ])

    _logger.info("Found %d accounts marked as 'equity_unaffected': %s", 
                 len(unaffected_accounts), unaffected_accounts.mapped("code"))

    # 2. Designate standard Retained Earnings / Laba Ditahan Account (Code: 320010)
    target_retained_account = Account.search([
        ("code", "=", "320010"),
        ("company_ids", "in", [company.id]),
    ], limit=1)

    if not target_retained_account:
        target_retained_account = Account.search([
            ("code", "in", ["320010", "310010", "320000", "330000"]),
            ("company_ids", "in", [company.id]),
        ], limit=1)

    if not target_retained_account:
        target_retained_account = Account.search([
            ("name", "ilike", "Laba Ditahan"),
            ("company_ids", "in", [company.id]),
        ], limit=1)

    if not target_retained_account:
        _logger.warning("No explicit Retained Earnings account found! Creating standard Account 320010...")
        target_retained_account = Account.create({
            "code": "320010",
            "name": "Saldo Laba Ditahan (Retained Earnings)",
            "account_type": "equity_unaffected",
            "company_ids": [(4, company.id)],
        })
    else:
        target_retained_account.write({"account_type": "equity_unaffected"})
        _logger.info("Designated Primary Retained Earnings Account: [%s] %s (ID: %s)", 
                     target_retained_account.code, target_retained_account.name, target_retained_account.id)

    # 3. Demote all OTHER equity_unaffected accounts back to standard 'equity'
    for acc in unaffected_accounts:
        if acc.id != target_retained_account.id:
            _logger.info("Demoting secondary unaffected account [%s] %s -> 'equity'", acc.code, acc.name)
            acc.write({"account_type": "equity"})

    # 4. Also check any other account in DB that might have equity_unaffected
    all_other_unaffected = Account.search([
        ("account_type", "=", "equity_unaffected"),
        ("id", "!=", target_retained_account.id),
    ])
    if all_other_unaffected:
        for acc in all_other_unaffected:
            _logger.info("Demoting non-target unaffected account [%s] %s -> 'equity'", acc.code, acc.name)
            acc.write({"account_type": "equity"})

    # 5. Link company configuration field if present
    if hasattr(company, "account_retained_earnings_id"):
        company.write({"account_retained_earnings_id": target_retained_account.id})
        _logger.info("Linked company.account_retained_earnings_id -> %s", target_retained_account.code)

    env.cr.commit()

    # 6. Final verification
    final_count = Account.search_count([
        ("account_type", "=", "equity_unaffected"),
        ("company_ids", "in", [company.id]),
    ])
    _logger.info("Final equity_unaffected count for company %s: %d", company.name, final_count)
    assert final_count == 1, f"Expected exactly 1 equity_unaffected account, found {final_count}!"

    _logger.info("SUCCESS: Exactly one unaffected earnings account confirmed: [%s] %s", 
                 target_retained_account.code, target_retained_account.name)
    return True

if __name__ == "__main__":
    pass
