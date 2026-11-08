# -*- coding: utf-8 -*-
import json
import logging
from odoo import http, fields
from odoo.api import SUPERUSER_ID
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

        env = request.env(user=SUPERUSER_ID)
        # Verifikasi terhadap adera.api.config atau system parameter
        config = env['adera.api.config'].search([('api_key', '=', token), ('active', '=', True)], limit=1)
        if config:
            config.last_accessed = fields.Datetime.now()
            return True

        # Fallback default key
        sys_token = env['ir.config_parameter'].get_param('adera_clinic_bridge.api_token', 'adera_secret_token_2026')
        return token == sys_token

    @http.route('/api/v1/clinic/encounter/sync', type='http', auth='none', methods=['POST'], csrf=False)
    def sync_clinic_encounter(self, **kwargs):
        """Inbound webhook receiver untuk kunjungan pasien dari Electronic Health Record (EHR)."""
        # 1. Autentikasi API Key
        if not self._authenticate():
            return request.make_json_response({
                'status': 'error',
                'code': 401,
                'message': 'Unauthorized: API Key atau Bearer Token tidak valid.'
            }, status=401)

        # 2. Parsing Payload
        try:
            raw_data = request.httprequest.get_data().decode('utf-8')
            payload = json.loads(raw_data)
        except Exception as e:
            return request.make_json_response({
                'status': 'error',
                'code': 400,
                'message': f"Bad Request: Format JSON tidak valid ({str(e)})."
            }, status=400)

        ext_id = payload.get('external_encounter_id') or payload.get('encounter_ref')
        patient_mrn = payload.get('patient', {}).get('mrn') or payload.get('patient_mrn')
        patient_name = payload.get('patient', {}).get('name') or payload.get('patient_name')

        if not ext_id or not patient_mrn:
            return request.make_json_response({
                'status': 'error',
                'code': 400,
                'message': 'Bad Request: Key external_encounter_id dan patient.mrn wajib disertakan.'
            }, status=400)

        env = request.env(user=SUPERUSER_ID)

        # 3. Idempotency Check: Cegah duplikasi finansial
        existing = env['clinic.encounter'].search([('external_encounter_id', '=', ext_id)], limit=1)
        if existing:
            if existing.state == 'posted':
                return request.make_json_response({
                    'status': 'success',
                    'code': 200,
                    'message': 'Idempotent: Encounter ini telah diproses dan diposting sebelumnya.',
                    'encounter_ref': existing.name,
                    'external_encounter_id': existing.external_encounter_id,
                    'state': existing.state,
                    'invoice_id': existing.account_move_id.id if existing.account_move_id else False,
                    'invoice_number': existing.account_move_id.name if existing.account_move_id else False,
                    'picking_number': existing.stock_picking_id.name if existing.stock_picking_id else False,
                }, status=200)
            elif existing.state == 'error':
                return request.make_json_response({
                    'status': 'conflict',
                    'code': 409,
                    'message': f"Conflict: Encounter sebelumnya gagal validasi ({existing.error_message}). Silakan lakukan perbaikan di Odoo Staging Dashboard.",
                    'encounter_ref': existing.name,
                }, status=409)

        # 4. Ingest ke Staging Ledger
        try:
            unit = 'hd' if payload.get('business_unit') in ('KLINIK_UTAMA_HD', 'hd') else 'pratama'
            poli = payload.get('poli_code', 'umum')
            payer = payload.get('payer_type', 'cash')
            sep = payload.get('sep_claim_number') or payload.get('claim_number')

            doctor_rec = False
            doc_data = payload.get('doctor', {})
            doc_sip = doc_data.get('sip_number')
            doc_name = doc_data.get('name')
            if doc_sip:
                doctor_rec = env['res.partner'].search([('sip_number', '=', doc_sip)], limit=1)
                doc_type = 'specialist_hd' if unit == 'hd' else 'general'
                if not doctor_rec and doc_name:
                    doctor_rec = env['res.partner'].create({
                        'name': doc_name,
                        'sip_number': doc_sip,
                        'is_doctor': True,
                        'doctor_type': doc_type,
                    })
                elif doctor_rec and doctor_rec.doctor_type != doc_type and unit == 'pratama':
                    # Ensure pratama doctor_type if practicing in pratama
                    doctor_rec.doctor_type = 'general'

            # Safe parse ISO encounter_datetime
            raw_dt = payload.get('encounter_datetime')
            encounter_dt = fields.Datetime.now()
            if raw_dt:
                try:
                    if isinstance(raw_dt, str):
                        from datetime import datetime, timezone
                        if 'T' in raw_dt:
                            dt_obj = datetime.fromisoformat(raw_dt)
                            if dt_obj.tzinfo:
                                dt_obj = dt_obj.astimezone(timezone.utc).replace(tzinfo=None)
                            encounter_dt = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            encounter_dt = raw_dt
                    else:
                        encounter_dt = raw_dt
                except Exception:
                    encounter_dt = fields.Datetime.now()

            encounter = env['clinic.encounter'].create({
                'external_encounter_id': ext_id,
                'patient_mrn': patient_mrn,
                'patient_name': patient_name or f"Pasien {patient_mrn}",
                'encounter_date': encounter_dt,
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
                prod = env['product.product'].search([('default_code', '=', item.get('code'))], limit=1)
                if not prod and item.get('code'):
                    item_type = item.get('item_type', 'procedure')
                    prod_type = 'consu' if item_type == 'medication' else 'service'
                    is_storable = True if item_type == 'medication' else False
                    prod = env['product.product'].create({
                        'name': item.get('name', item.get('code')),
                        'default_code': item.get('code'),
                        'type': prod_type,
                        'is_storable': is_storable,
                        'list_price': item.get('unit_price', 0.0),
                    })

                lot = False
                if item.get('lot_number') and prod:
                    lot = env['stock.lot'].search([
                        ('name', '=', item.get('lot_number')),
                        ('product_id', '=', prod.id)
                    ], limit=1)
                    if not lot and prod.is_storable:
                        lot = env['stock.lot'].create({
                            'name': item.get('lot_number'),
                            'product_id': prod.id,
                        })

                analytic_acc = False
                if item.get('analytic_account_code'):
                    analytic_acc = env['account.analytic.account'].search([
                        ('code', '=', item.get('analytic_account_code'))
                    ], limit=1)

                env['clinic.encounter.line'].create({
                    'encounter_id': encounter.id,
                    'product_id': prod.id,
                    'line_type': item.get('item_type', 'procedure'),
                    'qty': item.get('qty', 1.0),
                    'unit_price': item.get('unit_price', 0.0),
                    'lot_id': lot.id if lot else False,
                    'doctor_id': doctor_rec.id if doctor_rec else False,
                    'analytic_account_id': analytic_acc.id if analytic_acc else False,
                })

            encounter.state = 'staged'

            # 5. Jalankan Pipeline Otomatis
            encounter.action_process_encounter()

            return request.make_json_response({
                'status': 'success',
                'code': 201,
                'message': 'Encounter berhasil diterima, faktur dan mutasi stok telah terbentuk.',
                'encounter_ref': encounter.name,
                'external_encounter_id': encounter.external_encounter_id,
                'state': encounter.state,
                'invoice_number': encounter.account_move_id.name if encounter.account_move_id else False,
                'picking_number': encounter.stock_picking_id.name if encounter.stock_picking_id else False,
            }, status=201)

        except Exception as e:
            _logger.exception("Kesalahan sistem saat memproses webhook encounter: %s", str(e))
            return request.make_json_response({
                'status': 'error',
                'code': 500,
                'message': f"Internal Server Error: {str(e)}"
            }, status=500)
