# -*- coding: utf-8 -*-
from odoo import models, fields, api


class PosOrder(models.Model):
    _inherit = 'pos.order'

    medical_record_no = fields.Char(string='No. Rekam Medis (MRN)', index=True)
    sep_claim_number = fields.Char(string='No. SEP / Klaim Asuransi', index=True)
    encounter_reference = fields.Char(string='Referensi Kunjungan (EHR Encounter)', index=True)
    patient_id = fields.Many2one('res.partner', string='Pasien', domain="[('customer_rank', '>', 0)]")
    payer_type = fields.Selection([
        ('self_pay', 'Pasien Umum (Self-Pay)'),
        ('bpjs', 'BPJS Kesehatan'),
        ('insurance', 'Asuransi Swasta / Korporasi'),
        ('split', 'Kombinasi (Split Co-Pay + Asuransi/BPJS)'),
    ], string='Tipe Penjamin', default='self_pay', required=True)

    package_deposit_redeemed = fields.Monetary(
        string='Saldo Deposit / Paket Terpakai',
        currency_field='currency_id',
        default=0.0,
        help='Nilai rupiah paket prepaid atau voucher yang ditebus dari Akun 214010/214020.'
    )

    @api.model
    def _order_fields(self, ui_order):
        fields_dict = super(PosOrder, self)._order_fields(ui_order)
        fields_dict['medical_record_no'] = ui_order.get('medical_record_no')
        fields_dict['sep_claim_number'] = ui_order.get('sep_claim_number')
        fields_dict['encounter_reference'] = ui_order.get('encounter_reference')
        fields_dict['patient_id'] = ui_order.get('patient_id')
        fields_dict['payer_type'] = ui_order.get('payer_type', 'self_pay')
        fields_dict['package_deposit_redeemed'] = ui_order.get('package_deposit_redeemed', 0.0)
        return fields_dict


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    doctor_id = fields.Many2one('res.partner', string='Dokter Pemeriksa / Operator')
    analytic_distribution = fields.Json(
        string='Analytic Distribution',
        help='Mapping analytic account Odoo 19 misal {"<ID_PRAT_UMUM>": 100.0}'
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Auto-assign default analytic distribution jika belum diset dari POS UI
            if not vals.get('analytic_distribution'):
                product = self.env['product.product'].browse(vals.get('product_id'))
                config = self.env['pos.order'].browse(vals.get('order_id')).config_id if vals.get('order_id') else False
                
                # Check mapping dari product category atau config
                if product and product.categ_id:
                    # Kategori Hemodialisis -> HD-TREAT
                    if 'Hemodialisis' in product.categ_id.complete_name or 'HD' in product.categ_id.complete_name:
                        hd_analytic = self.env.ref('adera_core.analytic_account_hd_treat', raise_if_not_found=False)
                        if hd_analytic:
                            vals['analytic_distribution'] = {str(hd_analytic.id): 100.0}
                    # Kategori Farmasi -> PRAT-FARM
                    elif 'Farmasi' in product.categ_id.complete_name:
                        farm_analytic = self.env.ref('adera_core.analytic_account_prat_farm', raise_if_not_found=False)
                        if farm_analytic:
                            vals['analytic_distribution'] = {str(farm_analytic.id): 100.0}
                    # Default Outpatient -> PRAT-UMUM
                    else:
                        prat_analytic = self.env.ref('adera_core.analytic_account_prat_umum', raise_if_not_found=False)
                        if prat_analytic:
                            vals['analytic_distribution'] = {str(prat_analytic.id): 100.0}
        return super(PosOrderLine, self).create(vals_list)
