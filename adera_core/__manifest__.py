{
    'name': 'Adera Clinic Core - Foundation & CoA',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Localizations',
    'summary': 'Indonesian PSAK Chart of Accounts, Journals, and Analytic Hierarchy for Klinik ADERA',
    'author': 'Klinik ADERA Solutions',
    'website': 'https://klinikadera.co.id',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'account',
        'analytic',
        'l10n_id',
    ],
    'data': [
        'data/account_groups_data.xml',
        'data/account_accounts_data.xml',
        'data/account_journals_data.xml',
        'data/account_analytic_data.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

