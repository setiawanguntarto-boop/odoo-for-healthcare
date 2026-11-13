# -*- coding: utf-8 -*-
import json
import logging
from odoo import http, fields
from odoo.api import SUPERUSER_ID
from odoo.http import request

_logger = logging.getLogger(__name__)


class ClinicApiController(http.Controller):

    def _authenticate(self, raw_body=b""):
        """Verifikasi token via Authorization Bearer, X-ADERA-API-KEY, atau HMAC Signature (X-Adera-Signature)."""
        auth_header = request.httprequest.headers.get('Authorization', '')
        custom_key_header = request.httprequest.headers.get('X-ADERA-API-KEY', '')
        hmac_sig = request.httprequest.headers.get('X-Adera-Signature', '')

        token = False
        if custom_key_header:
            token = custom_key_header.strip()
        elif auth_header.startswith('Bearer '):
            token = auth_header.replace('Bearer ', '').strip()

        env = request.env(user=SUPERUSER_ID)
        sys_token = env['ir.config_parameter'].get_param('adera_clinic_bridge.api_token', 'adera_secret_token_2026')

        # 1. HMAC Verification if signature header provided
        if hmac_sig and raw_body:
            import hmac
            import hashlib
            expected_sig = hmac.new(sys_token.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()
            if hmac.compare_digest(hmac_sig.lower().strip(), expected_sig.lower().strip()):
                return True

        if not token:
            return False

        # 2. Verifikasi terhadap adera.api.config atau system parameter
        config = env['adera.api.config'].search([('api_key', '=', token), ('active', '=', True)], limit=1)
        if config:
            config.last_accessed = fields.Datetime.now()
            return True

        # Fallback default key
        return token == sys_token

    @http.route('/api/v1/clinic/encounter/sync', type='http', auth='none', methods=['POST'], csrf=False)
    def sync_clinic_encounter(self, **kwargs):
        """Inbound webhook receiver untuk kunjungan pasien dari Electronic Health Record (EHR)."""
        # 1. Parsing Payload & Raw Body
        try:
            raw_body = request.httprequest.get_data()
            raw_data = raw_body.decode('utf-8')
            payload = json.loads(raw_data)
        except Exception as e:
            return request.make_json_response({
                'status': 'error',
                'code': 400,
                'message': f"Bad Request: Format JSON tidak valid ({str(e)})."
            }, status=400)

        # 2. Autentikasi API Key / HMAC
        if not self._authenticate(raw_body=raw_body):
            return request.make_json_response({
                'status': 'error',
                'code': 401,
                'message': 'Unauthorized: API Key, Bearer Token, atau X-Adera-Signature tidak valid.'
            }, status=401)

        # Support both flat and nested 'data' payload structure
        data_block = payload.get('data') if isinstance(payload.get('data'), dict) else payload

        ext_id = (
            data_block.get('encounter_id') or
            data_block.get('external_encounter_id') or
            data_block.get('encounter_ref') or
            payload.get('external_encounter_id')
        )
        patient_block = data_block.get('patient', {})
        patient_mrn = patient_block.get('mrn') or data_block.get('patient_mrn')
        patient_name = patient_block.get('name') or data_block.get('patient_name')

        if not ext_id or not patient_mrn:
            return request.make_json_response({
                'status': 'error',
                'code': 400,
                'message': 'Bad Request: Key encounter_id (atau external_encounter_id) dan patient.mrn wajib disertakan.'
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
            # Service unit / business unit mapping
            service_unit_val = data_block.get('service_unit') or data_block.get('business_unit', '')
            unit = 'hd' if service_unit_val in ('hemodialysis', 'KLINIK_UTAMA_HD', 'hd') else 'pratama'
            
            # Poli code mapping
            poli_val = data_block.get('poli_code', 'umum').lower()
            if 'hd' in poli_val or unit == 'hd':
                poli = 'hd_special' if 'special' in poli_val or 'vip' in poli_val else 'hd_routine'
            elif 'gigi' in poli_val or 'dental' in poli_val:
                poli = 'gigi'
            elif 'kia' in poli_val:
                poli = 'kia'
            elif 'lab' in poli_val:
                poli = 'lab'
            elif 'rad' in poli_val:
                poli = 'rad'
            elif 'farm' in poli_val:
                poli = 'farmasi'
            else:
                poli = 'umum'

            # Payer type & split payment resolution
            billing_block = data_block.get('billing', {})
            payment_splits = billing_block.get('payment_split', [])
            sep = data_block.get('sep_claim_number') or data_block.get('claim_number')

            if payment_splits:
                if len(payment_splits) > 1:
                    payer = 'split'
                else:
                    pm = payment_splits[0].get('payment_method', '').lower()
                    if 'bpjs' in pm:
                        payer = 'bpjs'
                    elif 'qris' in pm or 'bank' in pm or 'transfer' in pm:
                        payer = 'qris'
                    else:
                        payer = 'cash'
                
                # Check for claim number in split payment
                for ps in payment_splits:
                    if ps.get('claim_number') and not sep:
                        sep = ps.get('claim_number')
            else:
                payer = data_block.get('payer_type', 'cash')

            # Doctor resolution
            doctor_rec = False
            doc_data = data_block.get('attending_physician') or data_block.get('doctor', {})
            doc_sip = doc_data.get('sip_number') or doc_data.get('doctor_id')
            doc_name = doc_data.get('name')
            doc_nik = doc_data.get('nik')
            doc_npwp = doc_data.get('npwp') or doc_data.get('vat')
            doc_role_raw = doc_data.get('specialty') or doc_data.get('role') or data_block.get('doctor_role', '')

            # Normalize doctor_role to clinic.encounter selection
            doc_role = 'general_practitioner'
            if 'hd' in str(doc_role_raw).lower() or unit == 'hd':
                doc_role = 'subspecialist_hd'
            elif 'dentist' in str(doc_role_raw).lower() or 'gigi' in str(doc_role_raw).lower():
                doc_role = 'dentist'
            elif 'specialist' in str(doc_role_raw).lower() or 'spesialis' in str(doc_role_raw).lower():
                doc_role = 'specialist'
            else:
                doc_role = 'general_practitioner'

            if doc_sip or doc_name:
                search_domain = []
                if doc_sip:
                    search_domain = ['|', ('sip_number', '=', doc_sip), ('ref', '=', doc_sip)]
                elif doc_name:
                    search_domain = [('name', 'ilike', doc_name.replace('dr. ', '').replace('dr.', '').strip())]

                doctor_rec = env['res.partner'].search(search_domain, limit=1) if search_domain else False
                doc_type = 'specialist_hd' if (unit == 'hd' or doc_role in ('subspecialist_hd', 'specialist_hd')) else 'general'

                if not doctor_rec and doc_name:
                    doc_vals = {
                        'name': doc_name,
                        'sip_number': doc_sip or False,
                        'is_doctor': True,
                        'doctor_type': doc_type,
                    }
                    if doc_npwp:
                        doc_vals['vat'] = doc_npwp
                    if doc_nik:
                        doc_vals['ref'] = doc_nik
                    doctor_rec = env['res.partner'].create(doc_vals)
                elif doctor_rec:
                    if doc_npwp and not doctor_rec.vat:
                        doctor_rec.vat = doc_npwp
                    if doc_nik and not doctor_rec.ref:
                        doctor_rec.ref = doc_nik

            # Safe parse ISO encounter_datetime
            raw_dt = data_block.get('encounter_date') or data_block.get('encounter_datetime')
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
                        elif len(raw_dt) == 10:  # YYYY-MM-DD
                            encounter_dt = f"{raw_dt} 00:00:00"
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
                'doctor_role': doc_role if doc_role else False,
                'payer_type': payer,
                'sep_claim_number': sep,
                'raw_payload': json.dumps(payload),
                'state': 'received',
            })

            # Line Items resolution (support both 'billing.lines' and 'billing_items')
            items = billing_block.get('lines', []) or data_block.get('billing_items', [])
            for item in items:
                item_code = item.get('item_code') or item.get('code')
                item_type = item.get('line_type') or item.get('item_type', 'procedure')
                
                # Normalize line_type to clinic.encounter.line selection
                line_type_norm = 'procedure'
                if item_type in ('medication', 'medicine', 'obat'):
                    line_type_norm = 'medication'
                elif item_type in ('consumable', 'bhp'):
                    line_type_norm = 'bhp'
                elif item_type in ('consultation', 'konsul'):
                    line_type_norm = 'consultation'
                elif item_type in ('lab', 'laboratory'):
                    line_type_norm = 'lab'
                elif item_type in ('rad', 'radiology'):
                    line_type_norm = 'rad'

                prod = env['product.product'].search([('default_code', '=', item_code)], limit=1) if item_code else False
                if not prod and item_code:
                    prod_type = 'consu' if line_type_norm in ('medication', 'bhp') else 'service'
                    is_storable = True if line_type_norm in ('medication', 'bhp') else False
                    prod = env['product.product'].create({
                        'name': item.get('item_name') or item.get('name', item_code),
                        'default_code': item_code,
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

                    # PATIENT SAFETY BLOCK: Rejection if lot is quarantined / recalled
                    if lot and lot.is_quarantined:
                        reason_dict = dict(lot._fields.get("quarantine_reason", {}).selection or []) if hasattr(lot._fields.get("quarantine_reason"), "selection") else {}
                        reason_desc = reason_dict.get(lot.quarantine_reason, lot.quarantine_reason or "Batch Recall")
                        return request.make_json_response({
                            "status": "error",
                            "code": 422,
                            "error": "MEDICAL_SAFETY_ALERT_BATCH_QUARANTINED",
                            "message": f"Ditolak: Obat/BHP '{prod.name}' dengan Nomor Batch '{lot.name}' berada dalam status KARANTINA / BATCH RECALL ({reason_desc}). Dilarang keras diberikan kepada pasien!",
                            "quarantined_lot": lot.name,
                            "product": prod.name,
                            "quarantine_reason": reason_desc,
                        }, status=422)

                analytic_acc = False
                if item.get('analytic_account_code'):
                    analytic_acc = env['account.analytic.account'].search([
                        ('code', '=', item.get('analytic_account_code'))
                    ], limit=1)

                env['clinic.encounter.line'].create({
                    'encounter_id': encounter.id,
                    'product_id': prod.id if prod else False,
                    'line_type': line_type_norm,
                    'qty': item.get('quantity') or item.get('qty', 1.0),
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
                'invoice_id': encounter.account_move_id.id if encounter.account_move_id else False,
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
