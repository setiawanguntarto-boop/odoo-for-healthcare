{
    'name': 'Adera Clinic POS - Revenue, Split Payments & Cashier Blind-Count',
    'version': '19.0.1.0.0',
    'category': 'Point of Sale/Healthcare',
    'summary': 'Clinical POS with Multi-Tender Split Payments, BPJS/Insurance AR Claim Routing, Blind-Count Cashier Reconciliation, and Prepaid Package Liability',
    'author': 'Klinik ADERA Solutions',
    'website': 'https://klinikadera.co.id',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'account',
        'point_of_sale',
        'adera_core',
        'adera_inventory',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/pos_payment_methods_data.xml',
        'data/pos_config_data.xml',
        'views/pos_order_views.xml',
        'views/pos_session_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

