# -*- coding: utf-8 -*-
{
    'name': 'Adera Accounting - PSAK Financial Reporting & Clinical Ledgers',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Localizations',
    'summary': 'Indonesian PSAK Financial Statements (P&L, Balance Sheet, Cash Flow), Multi-Unit Analytics, and Operational Clinic Ledgers for Klinik ADERA',
    'author': 'PT Prosperra Medika Utama / Klinik ADERA',
    'website': 'https://klinikadera.co.id',
    'license': 'LGPL-3',
    'application': True,
    'installable': True,
    'auto_install': False,
    'depends': [
        'base',
        'account',
        'analytic',
        'adera_core',
        'adera_doctor_remuneration',
        'account_financial_report',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/psak_report_wizard_view.xml',
        'views/account_report_views.xml',
        'views/operational_ledger_views.xml',
        'views/specialized_accounting_views.xml',
        'views/menu_views.xml',
        'reports/psak_report_templates.xml',
    ],
}

