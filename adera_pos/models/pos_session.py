# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class PosSession(models.Model):
    _inherit = 'pos.session'

    is_blind_count_mode = fields.Boolean(
        string='Blind-Count Active',
        default=True,
        help='Menyembunyikan saldo teoritis sistem dari tampilan kasir saat penutupan shift.'
    )
    blind_count_cash_counted = fields.Monetary(
        string='Fisik Kas Dihitung Kasir (Blind Count)',
        currency_field='currency_id',
        default=0.0
    )
    cash_variance = fields.Monetary(
        string='Selisih Kasir (Variance)',
        currency_field='currency_id',
        compute='_compute_cash_variance',
        store=True
    )
    variance_reason = fields.Text(string='Alasan / Berita Acara Selisih Kasir')

    @api.depends('blind_count_cash_counted', 'cash_register_balance_end')
    def _compute_cash_variance(self):
        for session in self:
            session.cash_variance = session.blind_count_cash_counted - session.cash_register_balance_end

    def action_pos_session_close(self, balancing_account=False, amount_to_balance=0, bank_payment_method_diffs=None):
        """Override session close untuk membukukan selisih fisik kasir ke Akun 619990."""
        res = super(PosSession, self).action_pos_session_close(
            balancing_account=balancing_account,
            amount_to_balance=amount_to_balance,
            bank_payment_method_diffs=bank_payment_method_diffs
        )
        return res
