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
        ('hd_routine', 'Tindakan HD Rutin'),
        ('hd_special', 'Tindakan HD Khusus / VIP'),
    ], string='Poli / Sub-Unit', required=True, default='umum')

    doctor_id = fields.Many2one('res.partner', string='Dokter Pemeriksa / Penanggung Jawab', domain="[('is_doctor', '=', True)]")
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
        analytic_map = {
            'umum': 'adera_core.analytic_account_prat_umum',
            'gigi': 'adera_core.analytic_account_prat_gigi',
            'kia': 'adera_core.analytic_account_prat_kia',
            'lab': 'adera_core.analytic_account_prat_lab',
            'rad': 'adera_core.analytic_account_prat_rad',
            'farmasi': 'adera_core.analytic_account_prat_farm',
            'hd_routine': 'adera_core.analytic_account_hd_treat',
            'hd_special': 'adera_core.analytic_account_hd_vip',
        }
        xml_id = analytic_map.get(poli_code)
        if xml_id:
            return self.env.ref(xml_id, raise_if_not_found=False)
        return False

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
                splits = payload.get('payment_split', [])
                for sp in splits:
                    method = sp.get('method')
                    amt = float(sp.get('amount', 0.0))
                    jcode = sp.get('journal_code', 'PGATE')
                    if method in ('qris', 'cash', 'edc', 'transfer') and amt > 0:
                        pay_journal = self.env['account.journal'].search([('code', '=', jcode)], limit=1)
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
                                'ref': f"Co-Pay QRIS/Kasir: {self.name}",
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

    def _accrue_doctor_fees(self):
        service_lines = self.line_ids.filtered(lambda l: l.line_type in ('consultation', 'procedure'))
        for line in service_lines:
            doc = line.doctor_id or self.doctor_id
            if not doc:
                continue

            # Cari fee rule
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
    currency_id = fields.Many2one('res.currency', string='Mata Uang', default=lambda self: self.env.company.currency_id)

    lot_id = fields.Many2one('stock.lot', string='Lot / Batch ID (FEFO)')
    doctor_id = fields.Many2one('res.partner', string='Dokter Operator', domain="[('is_doctor', '=', True)]")
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account')
