# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string="Unit Bisnis Analitik",
        compute="_compute_analytic_account_id",
        store=True,
        readonly=False,
        help="Penanda analitik unit bisnis otomatis berdasarkan lokasi tujuan/gudang",
    )

    @api.depends('location_dest_id', 'picking_type_id')
    def _compute_analytic_account_id(self):
        for picking in self:
            dest_code = picking.location_dest_id.complete_name or ''
            if 'HD' in dest_code:
                picking.analytic_account_id = self.env.ref('adera_core.analytic_acc_hd', raise_if_not_found=False) or self.env.ref('adera_core.analytic_account_hd_root', raise_if_not_found=False)
            elif 'Farmasi' in dest_code or 'Poli' in dest_code or 'Dental' in dest_code or 'Lab' in dest_code:
                picking.analytic_account_id = self.env.ref('adera_core.analytic_acc_pratama', raise_if_not_found=False) or self.env.ref('adera_core.analytic_account_pratama_root', raise_if_not_found=False)
            else:
                picking.analytic_account_id = self.env.ref('adera_core.analytic_acc_holding', raise_if_not_found=False) or self.env.ref('adera_core.analytic_account_holding_root', raise_if_not_found=False)

    def button_validate(self):
        # Enforce validation: cegah pengeluaran / dispense barang kadaluarsa
        for picking in self:
            if picking.picking_type_id.code in ('outgoing', 'internal'):
                for move_line in picking.move_line_ids:
                    lot = move_line.lot_id
                    if lot and (lot.is_quarantined or (lot.expiration_date and fields.Date.to_date(lot.expiration_date) < fields.Date.context_today(self))):
                        raise UserError(
                            f"VALIDASI DITOLAK: Lot '{lot.name}' pada produk '{move_line.product_id.display_name}' "
                            f"telah KADALUARSA ({lot.expiration_date.strftime('%d-%m-%Y') if lot.expiration_date else 'N/A'}). "
                            f"Produk ini masuk status KARANTINA dan tidak boleh didispense ke pasien/unit!"
                        )

            # Enforce validation pada Incoming (GRN / PO Receipt): Lot & Expiry WAJIB diisi untuk produk tracking by lot
            if picking.picking_type_id.code == 'incoming':
                for move_line in picking.move_line_ids:
                    if move_line.product_id.tracking in ('lot', 'serial'):
                        if not move_line.lot_id and not move_line.lot_name:
                            raise UserError(
                                f"VALIDASI DITOLAK: Penerimaan produk farmasi/BHP '{move_line.product_id.display_name}' "
                                f"wajib mencantumkan Nomor Lot / Batch ID!"
                            )
                        if move_line.lot_id and not move_line.lot_id.expiration_date:
                            raise UserError(
                                f"VALIDASI DITOLAK: Lot '{move_line.lot_id.name}' pada produk '{move_line.product_id.display_name}' "
                                f"wajib memiliki Tanggal Kadaluarsa (Expiration Date)!"
                            )

        return super(StockPicking, self).button_validate()

