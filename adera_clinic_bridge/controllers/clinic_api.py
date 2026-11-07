# -*- coding: utf-8 -*-
import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class ClinicApiController(http.Controller):

    def _authenticate(self):
        """Verifikasi token via header X-ADERA-API-KEY atau Authorization Bearer."""
        auth_header = request.httprequest.headers.get('Authorization', '')
        custom_key_header = request.httprequest.headers.get('X-ADERA-API-KEY', '')

        token = False
        if custom_key_header:
            token = custom_key_header.strip()
        elif auth_header.startswith('Bearer '):
            token = auth_header.replace('Bearer ', '').strip()

        if not token:
            return False

        # Verifikasi terhadap adera.api.config atau system parameter
        config = request.env['adera.api.config'].sudo().search([('api_key', '=', token), ('active', '=', True)], limit=1)
        if config:
            config.last_accessed = fields.Datetime.now()
            return True

        # Fallback default key
        sys_token = request.env['ir.config_parameter'].sudo().get_param('adera_clinic_bridge.api_token', 'adera_secret_token_2026')
        return token == sys_token

    @http.route('/api/v1/clinic/encounter/sync', type='json', auth='none', methods=['POST'], csrf=False)
    def sync_clinic_encounter(self, **kwargs):
        """Inbound webhook receiver untuk kunjungan pasien dari Electronic Health Record (EHR)."""
        # 1. Autentikasi API Key
        if not self._authenticate():
            return {
                'status': 'error',
                'code': 401,
                'message': 'Unauthorized: API Key atau Bearer Token tidak valid.'
            }

        # 2. Parsing Payload
        try:
            raw_data = request.httprequest.get_data().decode('utf-8')
            payload = json.loads(raw_data)
        except Exception as e:
            return {
                'status': 'error',
                'code': 400,
                'message': f"Bad Request: Format JSON tidak valid ({str(e)})."
            }

        ext_id = payload.get('external_encounter_id') or payload.get('encounter_ref')
        patient_mrn = payload.get('patient', {}).get('mrn') or payload.get('patient_mrn')
        patient_name = payload.get('patient', {}).get('name') or payload.get('patient_name')

        if not ext_id or not patient_mrn:
            return {
                'status': 'error',
                'code': 400,
                'message': 'Bad Request: Key external_encounter_id dan patient.mrn wajib disertakan.'
            }

        # 3. Idempotency Check: Cegah duplikasi finansial
        existing = request.env['clinic.encounter'].sudo().search([('external_encounter_id', '=', ext_id)], limit=1)
        if existing:
            if existing.state == 'posted':
                return {
                    'status': 'success',
                    'code': 200,
                    'message': 'Idempotent: Encounter ini telah diproses dan diposting sebelumnya.',
                    'encounter_ref': existing.name,
                    'external_encounter_id': existing.external_encounter_id,
                    'invoice_id': existing.account_move_id.id if existing.account_move_id else False,
                    'invoice_number': existing.account_move_id.name if existing.account_move_id else False,
                    'picking_number': existing.stock_picking_id.name if existing.stock_picking_id else False,
                }
            elif existing.state == 'error':
                return {
                    'status': 'conflict',
                    'code': 409,
                    'message': f"Conflict: Encounter sebelumnya gagal validasi ({existing.error_message}). Silakan lakukan perbaikan di Odoo Staging Dashboard.",
                    'encounter_ref': existing.name,
                }

        # 4. Ingest ke Staging Ledger
        try:
            unit = 'hd' if payload.get('business_unit') in ('KLINIK_UTAMA_HD', 'hd') else 'pratama'
            poli = payload.get('poli_code', 'umum')
            payer = payload.get('payer_type', 'cash')
            sep = payload.get('sep_claim_number') or payload.get('claim_number')

            doctor_rec = False
            doc_sip = payload.get('doctor', {}).get('sip_number')
            if doc_sip:
                doctor_rec = request.env['res.partner'].sudo().search([('sip_number', '=', doc_sip)], limit=1)

            encounter = request.env['clinic.encounter'].sudo().create({
                'external_encounter_id': ext_id,
                'patient_mrn': patient_mrn,
                'patient_name': patient_name or f"Pasien {patient_mrn}",
                'encounter_date': payload.get('encounter_datetime', fields.Datetime.now()),
                'clinic_unit': unit,
                'poli_code': poli,
                'doctor_id': doctor_rec.id if doctor_rec else False,
                'payer_type': payer,
                'sep_claim_number': sep,
                'raw_payload': json.dumps(payload),
                'state': 'received',
            })

            # Buat Encounter Lines
            items = payload.get('billing_items', [])
            for item in items:
                prod = request.env['product.product'].sudo().search([('default_code', '=', item.get('code'))], limit=1)
                lot = False
                if item.get('lot_number'):
                    lot = request.env['stock.lot'].sudo().search([('name', '=', item.get('lot_number'))], limit=1)

                request.env['clinic.encounter.line'].sudo().create({
                    'encounter_id': encounter.id,
                    'product_id': prod.id if prod else False,
                    'line_type': item.get('item_type', 'procedure'),
                    'qty': item.get('qty', 1.0),
                    'unit_price': item.get('unit_price', 0.0),
                    'lot_id': lot.id if lot else False,
                })

            encounter.state = 'staged'

            # 5. Jalankan Pipeline Otomatis
            encounter.action_process_encounter()

            return {
                'status': 'success',
                'code': 201,
                'message': 'Encounter berhasil diterima, faktur dan mutasi stok telah terbentuk.',
                'encounter_ref': encounter.name,
                'external_encounter_id': encounter.external_encounter_id,
                'state': encounter.state,
                'invoice_number': encounter.account_move_id.name if encounter.account_move_id else False,
                'picking_number': encounter.stock_picking_id.name if encounter.stock_picking_id else False,
            }

        except Exception as e:
            _logger.exception("Kesalahan sistem saat memproses webhook encounter: %s", str(e))
            return {
                'status': 'error',
                'code': 500,
                'message': f"Internal Server Error: {str(e)}"
            }

