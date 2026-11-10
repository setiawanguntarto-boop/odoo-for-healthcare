# -*- coding: utf-8 -*-
{
    'name': 'Adera Clinic Executive Management Dashboard',
    'version': '19.0.1.0.0',
    'category': 'Healthcare/Management',
    'summary': 'Executive Management & Financial KPI Dashboard for Klinik ADERA in Odoo 19 CE',
    'description': """
Executive Management & Financial KPI Dashboard for Klinik ADERA
================================================================
- Dynamic Executive Scorecards (Revenue, Net Profit, Gross/Net Margins with RAG Thresholds)
- Operating Ratios: ARPT, ARPP, DSO, DPO, DIO, Finalization Rate
- Unit & Poli Profitability Matrix across Pratama & Hemodialisis
- Multimodal Payer Mix Breakdown (Cash, QRIS/EDC, BPJS, Insurance, Voucher)
- Patient Activity & Revisit Frequency Metrics
- Audit & Compliance Flags (GR/IR Clearing 211500, Cashier Variance 619990, Near-Expiry Lots)
- Native Odoo 19 OWL + Chart.js 12-Month Financial & Encounter Visualizers
    """,
    'author': 'PT Prosperra Medika Utama',
    'website': 'https://klinikadera.com',
    'license': 'LGPL-3',
    'depends': [
        'adera_core',
        'adera_inventory',
        'adera_pos',
        'adera_doctor_remuneration',
        'adera_clinic_bridge',
        'adera_accounting',
        'spreadsheet_dashboard',
    ],
    'data': [
        'views/dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'adera_dashboard/static/src/components/clinic_dashboard.scss',
            'adera_dashboard/static/src/components/clinic_dashboard.xml',
            'adera_dashboard/static/src/components/clinic_dashboard.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
