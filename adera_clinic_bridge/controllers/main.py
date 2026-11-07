# -*- coding: utf-8 -*-
import json
import logging
from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class ClinicBridgeApiController(http.Controller):

    @http.route('/api/v1/clinic/encounter/sync', type='json', auth='none', methods=['POST'], csrf=False)
    def sync_clinic_encounter(self, **kwargs):
        """Inbound webhook receiver untuk event billable dari Electronic Health Record (EHR)."""
        auth_header = request.httprequest.headers.get('Authorization', '')
        # Verifikasi Bearer Token / API Key
        expected_token = request.env['ir.config_parameter'].sudo().get_param('adera_clinic_bridge.api_token', 'adera_secret_token_2026')
        
        token = auth_header.replace('Bearer ', '').strip() if auth_header.startswith('Bearer ') else False
        if not token or token != expected_token:
            return {
                'status': 'error',
                'code': 401,
                'message': 'Unauthorized: Bearer token tidak valid atau tidak disertakan.'
            }

        try:
            raw_data = request.httprequest.get_data().decode('utf-8')
            payload = json.loads(raw_data)
        except Exception as e:
            return {
                'status': 'error',
                'code': 400,
                'message': f"Bad Request: Format JSON tidak valid ({str(e)})."
            }

        event_id = payload.get('event_id')
        encounter_ref = payload.get('encounter_ref')
        business_unit = payload.get('business_unit', 'KLINIK_PRATAMA')

        if not event_id or not encounter_ref:
            return {
                'status': 'error',
                'code': 422,
                'message': 'Unprocessable Entity: Parameter event_id dan encounter_ref wajib diisi.'
            }

        # Idempotency Check: Pastikan event_id belum pernah diproses sebelumnya
        existing_encounter = request.env['clinic.encounter'].sudo().search([('event_id', '=', event_id)], limit=1)
        if existing_encounter:
            return {
                'status': 'success',
                'code': 200,
                'message': 'Idempotent: Event ini telah diterima dan diproses sebelumnya.',
                'encounter_id': existing_encounter.id,
                'encounter_ref': existing_encounter.name,
                'state': existing_encounter.state,
                'invoice_id': existing_encounter.invoice_id.id if existing_encounter.invoice_id else False,
            }

        # Buat staging encounter dan jalankan auto-process pipeline
        try:
            encounter = request.env['clinic.encounter'].sudo().create({
                'name': encounter_ref,
                'event_id': event_id,
                'business_unit': business_unit,
                'raw_payload': json.dumps(payload),
                'state': 'draft',
            })
            encounter.action_process_encounter()

            return {
                'status': 'success',
                'code': 201,
                'message': 'Encounter berhasil disinkronisasi ke Odoo 19.',
                'encounter_id': encounter.id,
                'encounter_ref': encounter.name,
                'state': encounter.state,
                'invoice_name': encounter.invoice_id.name if encounter.invoice_id else False,
                'picking_name': encounter.picking_id.name if encounter.picking_id else False,
            }
        except Exception as e:
            _logger.exception("Error saat melakukan sync encounter dari EHR: %s", str(e))
            return {
                'status': 'error',
                'code': 500,
                'message': f"Internal Server Error: {str(e)}"
            }

