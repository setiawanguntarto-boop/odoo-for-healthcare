# -*- coding: utf-8 -*-
{
    'name': 'Klinik ADERA - Pusat Otorisasi & Approvals Hub',
    'version': '19.0.1.0.0',
    'category': 'Healthcare/Management',
    'summary': 'Unified Executive Approval Center for Doctor Fees, Asset Disposal, Pharmacy Scrap, and POS Cash Variances',
    'author': 'Naraflow x ADERA Systems',
    'depends': [
        'base',
        'mail',
        'adera_core',
        'adera_accounting',
        'adera_doctor_remuneration',
        'adera_inventory',
        'adera_pos',
    ],
    'data': [
        'security/approval_security.xml',
        'security/ir.model.access.csv',
        'wizard/clinic_approval_reject_views.xml',
        'views/clinic_approval_inbox_views.xml',
        'views/approval_menus.xml',
    ],
    'application': True,
    'installable': True,
    'license': 'OPL-1',
}
