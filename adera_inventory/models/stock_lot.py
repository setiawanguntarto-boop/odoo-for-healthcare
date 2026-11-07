# -*- coding: utf-8 -*-
from datetime import date
from odoo import models, fields, api
from odoo.exceptions import UserError


class StockLot(models.Model):
    _inherit = 'stock.lot'

    expiry_status = fields.Selection([
        ('valid', 'Valid'),
        ('near_expiry', 'Near Expiry (<90 Days)'),
        ('critical', 'Critical (<30 Days)'),
        ('expired', 'Expired'),
    ], string='Status Kadaluarsa', compute='_compute_expiry_status', store=True)

    days_to_expire = fields.Integer(
        string='Hari Menuju Kadaluarsa',
        compute='_compute_expiry_status',
        store=True,
    )

    is_quarantined = fields.Boolean(
        string='Dikarantina (Expired)',
        default=False,
        help='Otomatis true jika lot telah melewati tanggal kadaluarsa (expiration_date).'
    )

    @api.depends('expiration_date')
    def _compute_expiry_status(self):
        today = fields.Date.context_today(self)
        for lot in self:
            if not lot.expiration_date:
                lot.expiry_status = 'valid'
                lot.days_to_expire = 9999
                lot.is_quarantined = False
                continue

            exp_date = fields.Date.to_date(lot.expiration_date)
            delta = (exp_date - today).days
            lot.days_to_expire = delta

            if delta < 0:
                lot.expiry_status = 'expired'
                lot.is_quarantined = True
            elif delta <= 30:
                lot.expiry_status = 'critical'
                lot.is_quarantined = False
            elif delta <= 90:
                lot.expiry_status = 'near_expiry'
                lot.is_quarantined = False
            else:
                lot.expiry_status = 'valid'
                lot.is_quarantined = False

    @api.model
    def cron_check_expired_lots(self):
        """Cron job harian untuk menandai lot kadaluarsa dan mencegah alokasi."""
        lots = self.search([('expiration_date', '<', fields.Datetime.now())])
        lots.write({'is_quarantined': True})

