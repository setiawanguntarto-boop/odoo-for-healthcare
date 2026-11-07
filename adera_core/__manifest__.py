{
    'name': 'Adera Clinic Core - Foundation, CoA & Enterprise UI',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Localizations',
    'summary': 'Indonesian PSAK Chart of Accounts, Journals, Analytic Hierarchy and Responsive App Switcher for Klinik ADERA',
    'author': 'Klinik ADERA Solutions',
    'website': 'https://klinikadera.co.id',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'web',
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
    'assets': {
        'web.assets_backend': [
            'adera_core/static/src/app_switcher/app_switcher.scss',
            'adera_core/static/src/app_switcher/app_switcher.xml',
            'adera_core/static/src/app_switcher/navbar_patch.xml',
            'adera_core/static/src/app_switcher/app_switcher.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
