# -*- coding: utf-8 -*-
import json
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ClinicEncounter(models.Model):
    _name = 'clinic.encounter'
    _description = 'Staging Ledger Kunjungan Pasien EHR'
    _order = 'encounter_date desc, id desc'

    name = fields.Char(string='Nomor Registrasi Odoo', required=True, copy=False, default='/')
    external_encounter_id = fields.Char(string='External Encounter ID', required=True, copy=False, index=True)
    patient_mrn = fields.Char(string='Nomor Rekam Medis (MRN)', required=True, index=True)
    patient_name = fields.Char(string='Nama Pasien', required=True)
    patient_id = fields.Many2one('res.partner', string='Kontak Pasien (Odoo Partner)')

    encounter_date = fields.Datetime(string='Waktu Kunjungan Pelayanan', required=True, default=fields.Datetime.now)
    clinic_unit = fields.Selection([
        ('pratama', 'Klinik Pratama (Rawat Jalan)'),
        ('hd', 'Klinik Utama Hemodialisis'),
    ], string='Unit Bisnis', required=True, default='pratama')

    poli_code = fields.Selection([
        ('umum', 'Poli Umum'),
        ('gigi', 'Poli Gigi & Mulut'),
        ('kia', 'Poli KIA & Kebidanan'),
        ('lab', 'Laboratorium'),
        ('rad', 'Radiologi'),
        ('farmasi', 'Farmasi Rawat Jalan'),
        ('vaksin', 'Poli Vaksinasi'),
        ('usg', 'Radiologi USG'),
        ('khitan', 'Bedah Minor & Khitan'),
        ('homecare', 'Layanan Homecare'),
        ('hd_routine', 'Tindakan HD Rutin'),
        ('hd_special', 'Tindakan HD Khusus / VIP'),
    ], string='Poli / Sub-Unit', required=True, default='umum')
    service_unit_code = fields.Char(string='Kode Sub-Unit Analitik', index=True)

    doctor_id = fields.Many2one('res.partner', string='Dokter Pemeriksa / Penanggung Jawab', domain="[('is_doctor', '=', True)]")
    doctor_role = fields.Selection([
        ('general_practitioner', 'Dokter Umum (Pratama)'),
        ('specialist', 'Dokter Spesialis'),
        ('dentist', 'Dokter Gigi'),
        ('subspecialist_hd', 'Spesialis Penyakit Dalam / Konsultan Ginjal Hipertensi (HD)'),
    ], string='Peran / Spesialisasi Dokter', compute='_compute_doctor_role', store=True, readonly=False)
    payer_type = fields.Selection([
        ('cash', 'Tunai'),
        ('qris', 'QRIS / Non-Tunai'),
        ('bpjs', 'BPJS Kesehatan'),
        ('insurance', 'Asuransi Swasta'),
        ('voucher', 'Voucher / Paket'),
        ('split', 'Kombinasi / Split-Tender'),
    ], string='Tipe Penjamin', default='cash', required=True)

    sep_claim_number = fields.Char(string='Nomor SEP / Klaim BPJS', index=True)
    raw_payload = fields.Text(string='Raw Webhook Payload JSON')
    error_message = fields.Text(string='Log Catatan Error')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('received', 'Diterima Webhook'),
        ('staged', 'Terverifikasi (Staged)'),
        ('posted', 'Sukses Diproses (Posted)'),
        ('error', 'Gagal Validasi (Error)'),
    ], string='Status Integrasi', default='draft', index=True, required=True)

    line_ids = fields.One2many('clinic.encounter.line', 'encounter_id', string='Rincian Layanan & Resep')
    account_move_id = fields.Many2one('account.move', string='Faktur Tagihan (Customer Invoice)', readonly=True)
    stock_picking_id = fields.Many2one('stock.picking', string='Pengeluaran Obat & BHP (Stock Picking)', readonly=True)
    fee_accrual_ids = fields.One2many('medical.fee.accrual', compute='_compute_fee_accruals', string='Akrual Jasa Medis')

    _sql_constraints = [
        ('uniq_external_encounter_id', 'unique(external_encounter_id)', 'External Encounter ID sudah pernah diproses sebelumnya!')
    ]

    @api.depends('doctor_id', 'clinic_unit', 'poli_code')
    def _compute_doctor_role(self):
        for rec in self:
            if rec.doctor_role:
                continue
            if rec.clinic_unit == 'hd' or rec.poli_code in ('hd_routine', 'hd_special'):
                rec.doctor_role = 'subspecialist_hd'
            elif rec.poli_code == 'gigi':
                rec.doctor_role = 'dentist'
            elif rec.doctor_id and getattr(rec.doctor_id, 'doctor_type', False) == 'specialist_hd':
                rec.doctor_role = 'subspecialist_hd'
            else:
                rec.doctor_role = 'general_practitioner'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('clinic.encounter') or '/'
        return super(ClinicEncounter, self).create(vals_list)

    def _compute_fee_accruals(self):
        for rec in self:
            rec.fee_accrual_ids = self.env['medical.fee.accrual'].search([
                ('encounter_reference', '=', rec.external_encounter_id)
            ])

    def action_process_encounter(self):
        """Pipeline utama: Rollback safe dengan savepoint Odoo."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                self._ensure_patient_partner()
                self._generate_customer_invoice()
                self._generate_pharmacy_dispense()
                self._accrue_doctor_fees()
                self.write({'state': 'posted', 'error_message': False})
        except Exception as e:
            _logger.exception("Gagal memproses encounter %s", self.name)
            self.write({'state': 'error', 'error_message': str(e)})

    def _ensure_patient_partner(self):
        # Tentukan akun piutang: BPJS Claim 112020 vs Pasien Umum 112010
        if self.payer_type in ('bpjs', 'split') or self.sep_claim_number:
            rec_acc = self.env.ref('adera_core.account_112020', raise_if_not_found=False)
        else:
            rec_acc = self.env.ref('adera_core.account_112010', raise_if_not_found=False)

        if not self.patient_id:
            partner = self.env['res.partner'].search([('ref', '=', self.patient_mrn)], limit=1)
            if not partner:
                partner = self.env['res.partner'].create({
                    'name': self.patient_name,
                    'ref': self.patient_mrn,
                    'customer_rank': 1,
                    'property_account_receivable_id': rec_acc.id if rec_acc else False,
                })
            self.patient_id = partner.id

        if rec_acc and self.patient_id:
            self.patient_id.property_account_receivable_id = rec_acc.id

    def _resolve_analytic_account(self, poli_code):
        if self.service_unit_code:
            aa = self.env['account.analytic.account'].search([('code', '=', self.service_unit_code)], limit=1)
            if aa:
                return aa

        code_map = {
            'umum': 'PRAT-UMUM',
            'gigi': 'PRAT-GIGI',
            'kia': 'PRAT-KIA',
            'lab': 'PRAT-LAB',
            'rad': 'PRAT-RAD',
            'farmasi': 'PRAT-FARM',
            'vaksin': 'PRAT-VAKSIN',
            'usg': 'PRAT-USG',
            'khitan': 'PRAT-KHITAN',
            'homecare': 'PRAT-HOMECARE',
            'hd_routine': 'HD-TREAT',
            'hd_special': 'HD-VIP',
        }
        target_code = code_map.get(poli_code)
        if target_code:
            aa = self.env['account.analytic.account'].search([('code', '=', target_code)], limit=1)
            if aa:
                return aa

        analytic_map = {
            'umum': 'adera_core.analytic_account_prat_umum',
            'gigi': 'adera_core.analytic_account_prat_gigi',
            'kia': 'adera_core.analytic_account_prat_kia',
            'lab': 'adera_core.analytic_account_prat_lab',
            'rad': 'adera_core.analytic_account_prat_rad',
            'farmasi': 'adera_core.analytic_account_prat_farm',
            'vaksin': 'adera_core.analytic_sub_prat_vaksin',
            'usg': 'adera_core.analytic_sub_prat_usg',
            'khitan': 'adera_core.analytic_sub_prat_khitan',
            'homecare': 'adera_core.analytic_sub_prat_homecare',
            'hd_routine': 'adera_core.analytic_account_hd_treat',
            'hd_special': 'adera_core.analytic_account_hd_vip',
        }
        xml_id = analytic_map.get(poli_code)
        acc = self.env.ref(xml_id, raise_if_not_found=False) if xml_id else False
        if not acc:
            if self.clinic_unit == 'hd':
                acc = self.env.ref('adera_core.analytic_acc_hd', raise_if_not_found=False) or self.env.ref('adera_core.analytic_account_hd_root', raise_if_not_found=False)
            else:
                acc = self.env.ref('adera_core.analytic_acc_pratama', raise_if_not_found=False) or self.env.ref('adera_core.analytic_account_pratama_root', raise_if_not_found=False)
        return acc

    def _generate_customer_invoice(self):
        if self.account_move_id:
            return

        journal = self.env.ref('adera_core.journal_inv_hd', raise_if_not_found=False) if self.clinic_unit == 'hd' else self.env.ref('adera_core.journal_inv_out', raise_if_not_found=False)
        if not journal:
            journal = self.env['account.journal'].search([('type', '=', 'sale')], limit=1)

        inv_lines = []

        for line in self.line_ids:
            analytic_acc = line.analytic_account_id or self._resolve_analytic_account(self.poli_code)
            dist = {str(analytic_acc.id): 100.0} if analytic_acc else False

            income_acc = False
            if line.line_type == 'medication':
                income_acc = self.env.ref('adera_core.account_410060', raise_if_not_found=False)
            elif line.line_type == 'consultation':
                income_acc = self.env.ref('adera_core.account_410010', raise_if_not_found=False)
            elif self.clinic_unit == 'hd':
                income_acc = self.env.ref('adera_core.account_410110', raise_if_not_found=False)
            else:
                income_acc = self.env.ref('adera_core.account_410010', raise_if_not_found=False)

            line_vals = {
                'product_id': line.product_id.id,
                'name': line.product_id.name,
                'quantity': line.qty,
                'price_unit': line.unit_price,
                'analytic_distribution': dist,
                'tax_ids': [(5, 0, 0)],
            }
            if income_acc:
                line_vals['account_id'] = income_acc.id

            inv_lines.append((0, 0, line_vals))

        if not inv_lines:
            return

        inv_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.patient_id.id,
            'journal_id': journal.id,
            'invoice_date': fields.Date.to_date(self.encounter_date),
            'ref': f"{self.external_encounter_id} ({self.patient_mrn})",
            'invoice_line_ids': inv_lines,
        }

        invoice = self.env['account.move'].create(inv_vals)
        invoice.action_post()
        self.account_move_id = invoice.id

        # Update receivable account line to PSAK 112020/112010 if needed
        rec_acc = self.patient_id.property_account_receivable_id
        if rec_acc:
            rec_line = invoice.line_ids.filtered(lambda l: l.account_type == 'asset_receivable')
            if rec_line and rec_line.account_id != rec_acc:
                rec_line.write({'account_id': rec_acc.id})

        # Process Co-Pay / Split Payment if provided in raw_payload
        if self.raw_payload:
            try:
                payload = json.loads(self.raw_payload)
                data_node = payload.get('data') if isinstance(payload.get('data'), dict) else payload
                splits = (
                    data_node.get('payments')
                    or data_node.get('payment_split')
                    or (data_node.get('billing') or {}).get('payment_split')
                    or payload.get('payment_split')
                    or []
                )
                method_journal_map = {
                    'qris_gopay': ['GOPAY', 'QRIS', 'PGATE'],
                    'gopay': ['GOPAY', 'QRIS', 'PGATE'],
                    'qris': ['GOPAY', 'QRIS', 'PGATE'],
                    'cash': ['KKSR', 'CSH1'],
                    'tunai': ['KKSR', 'CSH1'],
                    'transfer': ['BR569', 'BMDRI', 'BBCA'],
                    'bri': ['BR569'],
                    'mandiri': ['BMDRI'],
                    'bsi': ['BSI78'],
                    'edc': ['QRIS', 'BR569', 'BBCA'],
                    'card': ['QRIS', 'BR569', 'BBCA'],
                }
                for sp in splits:
                    method = str(sp.get('method') or sp.get('payment_method') or '').lower().strip()
                    amt = float(sp.get('amount', 0.0))
                    explicit_jcode = sp.get('journal_code')
                    pay_ref = sp.get('ref') or f"Co-Pay {method.upper()}: {self.name}"
                    if amt > 0 and method not in ('bpjs', 'insurance', 'asuransi'):
                        pay_journal = False
                        candidate_codes = ([explicit_jcode] if explicit_jcode else []) + method_journal_map.get(method, ['GOPAY', 'KKSR'])
                        for jc in candidate_codes:
                            pay_journal = self.env['account.journal'].search([('code', '=', jc)], limit=1)
                            if pay_journal:
                                break
                        if not pay_journal:
                            pay_journal = self.env['account.journal'].search([('type', 'in', ('bank', 'cash'))], limit=1)
                        if pay_journal:
                            payment = self.env['account.payment'].create({
                                'partner_id': self.patient_id.id,
                                'amount': amt,
                                'journal_id': pay_journal.id,
                                'payment_type': 'inbound',
                                'partner_type': 'customer',
                                'date': invoice.invoice_date,
                                'memo': pay_ref,
                            })
                            payment.action_post()
                            lines_to_rec = (invoice.line_ids + payment.move_id.line_ids).filtered(
                                lambda l: l.account_type == 'asset_receivable' and not l.reconciled
                            )
                            if len(lines_to_rec) >= 2:
                                lines_to_rec.reconcile()
            except Exception as e:
                _logger.warning("Could not register co-pay payment for %s: %s", self.name, str(e))

    def _generate_pharmacy_dispense(self):
        if self.stock_picking_id:
            return

        med_lines = self.line_ids.filtered(lambda l: l.line_type in ('medication', 'bhp') and l.product_id.type == 'consu')
        if not med_lines:
            return

        src_location = self.env.ref('adera_inventory.stock_location_hd', raise_if_not_found=False) if self.clinic_unit == 'hd' else self.env.ref('adera_inventory.stock_location_farmasi', raise_if_not_found=False)
        if not src_location:
            src_location = self.env.ref('stock.stock_location_stock')
        cust_location = self.env.ref('stock.stock_location_customers')
        picking_type = self.env['stock.picking.type'].search([('code', '=', 'outgoing')], limit=1)
        if not picking_type:
            return

        move_lines = []
        for line in med_lines:
            move_lines.append((0, 0, {
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty,
                'product_uom': line.product_id.uom_id.id,
                'location_id': src_location.id,
                'location_dest_id': cust_location.id,
            }))

        picking = self.env['stock.picking'].create({
            'picking_type_id': picking_type.id,
            'partner_id': self.patient_id.id,
            'origin': self.external_encounter_id,
            'location_id': src_location.id,
            'location_dest_id': cust_location.id,
            'move_ids': move_lines,
        })
        picking.action_confirm()

        # Alokasi lot jika ditentukan dari resep EHR
        for move in picking.move_ids:
            matching_req = med_lines.filtered(lambda l: l.product_id == move.product_id)[:1]
            lot_id = matching_req.lot_id.id if matching_req and matching_req.lot_id else False
            if not move.move_line_ids:
                self.env['stock.move.line'].create({
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': move.product_id.id,
                    'product_uom_id': move.product_uom.id,
                    'location_id': src_location.id,
                    'location_dest_id': cust_location.id,
                    'quantity': move.product_uom_qty,
                    'lot_id': lot_id,
                })
            else:
                for ml in move.move_line_ids:
                    if lot_id:
                        ml.lot_id = lot_id
                    ml.quantity = ml.quantity_product_uom

        try:
            picking.button_validate()
        except Exception as e:
            _logger.warning("Could not immediately validate picking: %s", str(e))
        self.stock_picking_id = picking.id

        # Ensure Anglo-Saxon COGS (510010/510020) is tagged with Encounter Analytic Account
        analytic_acc = self._resolve_analytic_account(self.poli_code)
        if analytic_acc:
            dist = {str(analytic_acc.id): 100.0}
            val_moves = self.env['account.move']
            for sm in picking.move_ids:
                if hasattr(sm, 'account_move_id') and sm.account_move_id:
                    val_moves |= sm.account_move_id
                elif hasattr(sm, 'account_move_ids') and sm.account_move_ids:
                    val_moves |= sm.account_move_ids
            cogs_lines = val_moves.mapped('line_ids').filtered(
                lambda l: l.account_id.account_type == 'expense_direct_cost'
            )
            if cogs_lines:
                cogs_lines.write({'analytic_distribution': dist})
            else:
                # If real-time stock valuation move didn't fire (e.g., standard_price > 0 without automated categ),
                # post Anglo-Saxon COGS entry explicitly
                cogs_total = sum((l.product_id.standard_price or 0.0) * l.qty for l in med_lines)
                if cogs_total > 0:
                    cogs_acc = self.env.ref('adera_core.account_510010', raise_if_not_found=False)
                    inv_acc = self.env.ref('adera_core.account_113010', raise_if_not_found=False)
                    misc_j = self.env.ref('adera_core.journal_misc_clinic', raise_if_not_found=False) or self.env['account.journal'].search([('type', '=', 'general')], limit=1)
                    if cogs_acc and inv_acc and misc_j:
                        cogs_move = self.env['account.move'].create({
                            'journal_id': misc_j.id,
                            'date': fields.Date.to_date(self.encounter_date),
                            'ref': f"COGS {self.external_encounter_id}",
                            'move_type': 'entry',
                            'line_ids': [
                                (0, 0, {
                                    'name': f"HPP BHP/Farmasi: {self.external_encounter_id}",
                                    'account_id': cogs_acc.id,
                                    'debit': cogs_total,
                                    'credit': 0.0,
                                    'analytic_distribution': dist,
                                }),
                                (0, 0, {
                                    'name': f"Pengurangan Persediaan: {self.external_encounter_id}",
                                    'account_id': inv_acc.id,
                                    'debit': 0.0,
                                    'credit': cogs_total,
                                }),
                            ],
                        })
                        cogs_move.action_post()

    def _accrue_doctor_fees(self):
        service_lines = self.line_ids.filtered(lambda l: l.line_type in ('consultation', 'procedure'))
        for line in service_lines:
            doc = line.doctor_id or self.doctor_id
            if not doc:
                continue

            if line.doctor_fee_amount and line.doctor_fee_amount > 0:
                fee = line.doctor_fee_amount
            else:
                rule = self.env['medical.fee.rule'].search([
                    ('product_id', '=', line.product_id.id),
                    ('doctor_type', '=', doc.doctor_type)
                ], limit=1)

                if rule:
                    fee = (line.unit_price * line.qty * (rule.doctor_share_rate / 100.0)) if rule.doctor_share_type == 'percentage' else rule.fixed_amount
                else:
                    fee = line.unit_price * line.qty * 0.70  # Default 70% jika belum diatur

            analytic_acc = line.analytic_account_id or self._resolve_analytic_account(self.poli_code)
            dist = {str(analytic_acc.id): 100.0} if analytic_acc else False

            self.env['medical.fee.accrual'].create({
                'doctor_id': doc.id,
                'patient_id': self.patient_id.id,
                'encounter_reference': self.external_encounter_id,
                'encounter_date': fields.Date.to_date(self.encounter_date),
                'product_id': line.product_id.id,
                'billing_amount': line.unit_price * line.qty,
                'doctor_fee_amount': fee,
                'analytic_distribution': dist,
            })


class ClinicEncounterLine(models.Model):
    _name = 'clinic.encounter.line'
    _description = 'Rincian Layanan & Obat Kunjungan EHR'

    encounter_id = fields.Many2one('clinic.encounter', string='Encounter', ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Item / Layanan / Obat', required=True)
    line_type = fields.Selection([
        ('consultation', 'Konsultasi Dokter'),
        ('procedure', 'Tindakan Medis'),
        ('medication', 'Obat Farmasi'),
        ('bhp', 'BHP Medis'),
        ('lab', 'Pemeriksaan Laboratorium'),
        ('rad', 'Pemeriksaan Radiologi'),
    ], string='Tipe Layanan', default='consultation', required=True)

    qty = fields.Float(string='Jumlah (Qty)', default=1.0)
    unit_price = fields.Monetary(string='Tarif / Harga Satuan', currency_field='currency_id')
    doctor_fee_amount = fields.Monetary(string='Jasa Medis Eksplisit', currency_field='currency_id', default=0.0)
    currency_id = fields.Many2one('res.currency', string='Mata Uang', default=lambda self: self.env.company.currency_id)

    lot_id = fields.Many2one('stock.lot', string='Lot / Batch ID (FEFO)')
    doctor_id = fields.Many2one('res.partner', string='Dokter Operator', domain="[('is_doctor', '=', True)]")
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account')
