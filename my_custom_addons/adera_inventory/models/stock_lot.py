# -*- coding: utf-8 -*-
from datetime import date
from odoo import models, fields, api
from odoo.exceptions import UserError


class StockLot(models.Model):
    _inherit = 'stock.lot'

    expiry_status = fields.Selection([
        ('valid', 'Valid'),
        ('near_expiry', 'Near Expiry (<60 Days)'),
        ('critical', 'Critical (<30 Days)'),
        ('expired', 'Expired'),
    ], string='Status Kadaluarsa', compute='_compute_expiry_status', store=True)

    days_to_expire = fields.Integer(
        string='Hari Menuju Kadaluarsa',
        compute='_compute_expiry_status',
        store=True,
    )

    is_quarantined = fields.Boolean(
        string='Dikarantina (Expired / Near Expiry)',
        default=False,
        help='Otomatis true jika lot telah melewati tanggal kadaluarsa atau masuk masa karantina (<60 hari).'
    )
    quarantine_reason = fields.Char(string='Alasan Karantina')

    # =========================================================================
    # MULTI-DOSE OPEN-VIAL & SPOILAGE TRACKING (Vaccines, EPO, Heparin)
    # =========================================================================
    is_multi_dose = fields.Boolean(
        string='Vial Multidosis / Ampul Terbuka',
        default=False,
        help='Tandai jika sediaan obat berupa vial multidosis (misal: Vaksin 5 dosis, Heparin, EPO)',
    )
    dose_capacity = fields.Integer(
        string='Kapasitas Dosis per Vial',
        default=1,
        help='Total dosis yang dapat diekstraksi dari 1 vial utuh',
    )
    doses_administered = fields.Integer(
        string='Dosis Telah Digunakan',
        default=0,
    )
    doses_remaining = fields.Integer(
        string='Sisa Dosis Tersedia',
        compute='_compute_doses_remaining',
        store=True,
    )
    is_opened = fields.Boolean(
        string='Status Vial Terbuka (Ditusuk)',
        default=False,
        tracking=True,
        help='Menandakan vial telah ditusuk jarum / dibuka segelnya.',
    )
    opened_date = fields.Datetime(
        string='Waktu Penusukan / Pembukaan Vial',
        tracking=True,
    )
    viability_hours = fields.Integer(
        string='Batas Stabilitas Pasca Buka (Jam)',
        default=24,
        help='Standar farmasi klinis: 24 jam untuk sebagian besar vial multidosis rekonsiliasi',
    )
    open_expiration_date = fields.Datetime(
        string='Batas Waktu Pakai Vial Terbuka',
        compute='_compute_open_expiration',
        store=True,
    )
    is_open_vial_expired = fields.Boolean(
        string='Vial Melewati Batas Viabilitas (Spoilage Risk)',
        compute='_compute_open_expiration',
        store=True,
    )

    @api.depends('is_multi_dose', 'dose_capacity', 'doses_administered')
    def _compute_doses_remaining(self):
        for lot in self:
            if lot.is_multi_dose:
                lot.doses_remaining = max(0, lot.dose_capacity - lot.doses_administered)
            else:
                lot.doses_remaining = 0

    @api.depends('is_opened', 'opened_date', 'viability_hours')
    def _compute_open_expiration(self):
        now = fields.Datetime.now()
        for lot in self:
            if lot.is_opened and lot.opened_date and lot.viability_hours > 0:
                from dateutil.relativedelta import relativedelta
                lot.open_expiration_date = lot.opened_date + relativedelta(hours=lot.viability_hours)
                lot.is_open_vial_expired = bool(lot.open_expiration_date < now)
            else:
                lot.open_expiration_date = False
                lot.is_open_vial_expired = False

    def action_open_vial(self):
        """Membuka segel / menusuk vial pertama kali dan memulai timer stabilitas 24 jam."""
        for lot in self:
            lot.write({
                'is_opened': True,
                'opened_date': fields.Datetime.now(),
            })
            lot.message_post(body=f"Vial multidosis dibuka pada {lot.opened_date}. Batas stabilitas in-use: {lot.viability_hours} jam.")
        return True

    def action_open_spoilage_wizard(self):
        """Membuka wizard pemusnahan sisa vial terbuka yang kadaluarsa."""
        self.ensure_one()
        return {
            'name': 'Pemusnahan Sisa Vial Terbuka (Open-Vial Spoilage)',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.scrap.clinic',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_lot_id': self.id,
                'default_product_id': self.product_id.id,
                'default_dose_scrap_quantity': self.doses_remaining,
            },
        }

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
                lot.quarantine_reason = 'Lot telah melewati tanggal kadaluarsa (Expired)'
            elif delta <= 30:
                lot.expiry_status = 'critical'
                lot.is_quarantined = True
                lot.quarantine_reason = 'Critical Near-Expiry: Kurang dari 30 hari'
            elif delta <= 60:
                lot.expiry_status = 'near_expiry'
                lot.is_quarantined = True
                lot.quarantine_reason = 'Near-Expiry Quarantine Proposal: Kurang dari 60 hari'
            else:
                lot.expiry_status = 'valid'
                lot.is_quarantined = False
                lot.quarantine_reason = False

    @api.model
    def cron_quarantine_near_expiry_lots(self):
        """Cron job harian otomatis untuk mendeteksi lot mendekati kadaluarsa (<60 hari)
           dan membuat transfer internal ke WH/Quarantine.
        """
        quarantine_loc = self.env.ref('adera_inventory.stock_location_pharma_quarantine', raise_if_not_found=False)
        if not quarantine_loc:
            return

        # Cari lot yang masa kadaluarsanya <= 60 hari
        lots = self.search([
            ('days_to_expire', '<=', 60),
            ('product_id', '!=', False),
        ])

        if not lots:
            return

        lots.write({
            'is_quarantined': True,
            'quarantine_reason': 'Otomatis Dikarantina (< 60 Hari Menuju Expired)',
        })

        # Cari quant di lokasi internal non-karantina
        quants = self.env['stock.quant'].search([
            ('lot_id', 'in', lots.ids),
            ('quantity', '>', 0),
            ('location_id.usage', '=', 'internal'),
            ('location_id', '!=', quarantine_loc.id),
        ])

        if quants:
            # Cari picking type internal
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'internal'),
                ('warehouse_id.company_id', '=', self.env.company.id)
            ], limit=1)

            if picking_type:
                picking_vals = {
                    'picking_type_id': picking_type.id,
                    'location_id': quants[0].location_id.id,
                    'location_dest_id': quarantine_loc.id,
                    'origin': 'Auto-Quarantine Near Expiry (<60 Hari)',
                }
                picking = self.env['stock.picking'].create(picking_vals)

                for q in quants:
                    self.env['stock.move'].create({
                        'name': f"Karantina {q.product_id.name}",
                        'product_id': q.product_id.id,
                        'product_uom_qty': q.quantity,
                        'product_uom': q.product_id.uom_id.id,
                        'picking_id': picking.id,
                        'location_id': q.location_id.id,
                        'location_dest_id': quarantine_loc.id,
                    })

    @api.model
    def cron_check_expired_lots(self):
        """Cron job harian untuk menandai lot kadaluarsa."""
        return self.cron_quarantine_near_expiry_lots()
