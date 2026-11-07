# -*- coding: utf-8 -*-
from odoo import models, fields


class AderaApiConfig(models.Model):
    _name = 'adera.api.config'
    _description = 'Konfigurasi Autentikasi REST API EHR'

    name = fields.Char(string='Deskripsi Kredensial', required=True, default='EHR Production API Key')
    api_key = fields.Char(string='API Key / Token Rahasia', required=True, default='adera_secret_token_2026')
    active = fields.Boolean(default=True)
    ip_whitelist = fields.Char(string='IP Whitelist (Opsional, pisahkan koma)')
    last_accessed = fields.Datetime(string='Terakhir Diakses', readonly=True)

