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
    variance_move_id = fields.Many2one('account.move', string='Jurnal Selisih Kasir (619990)', readonly=True)

    @api.depends('blind_count_cash_counted', 'cash_register_balance_end')
    def _compute_cash_variance(self):
        for session in self:
            session.cash_variance = session.blind_count_cash_counted - session.cash_register_balance_end

    def action_pos_session_close(self, balancing_account=False, amount_to_balance=0, bank_payment_method_diffs=None):
        """Override session close untuk membukukan selisih fisik kasir ke Akun 619990 dengan tag analitik."""
        res = super(PosSession, self).action_pos_session_close(
            balancing_account=balancing_account,
            amount_to_balance=amount_to_balance,
            bank_payment_method_diffs=bank_payment_method_diffs
        )

        for session in self:
            if session.cash_variance != 0.0 and not session.variance_move_id:
                session._post_cashier_variance_entry()

        return res

    def _post_cashier_variance_entry(self):
        """Membukukan selisih kas fisik kasir ke akun Beban Selisih Kasir 619990 dengan tag analitik."""
        self.ensure_one()
        variance_acc = self.env.ref('adera_core.account_619990', raise_if_not_found=False)
        if not variance_acc:
            return

        is_hd = 'HD' in (self.config_id.name or '') or 'Hemodialisis' in (self.config_id.name or '')
        cash_acc = self.env.ref('adera_core.account_111020' if is_hd else 'adera_core.account_111010', raise_if_not_found=False)
        analytic_acc = self.env.ref('adera_core.analytic_account_hd_treat' if is_hd else 'adera_core.analytic_account_prat_farm', raise_if_not_found=False)

        if not cash_acc:
            return

        analytic_dist = {str(analytic_acc.id): 100.0} if analytic_acc else False
        journal = self.env['account.journal'].search([('type', '=', 'general')], limit=1)
        if not journal:
            return

        amt = abs(self.cash_variance)
        ref_desc = f"Selisih Kasir Shift {self.name} ({self.config_id.name}) - {self.variance_reason or 'Blind-Count Variance'}"

        if self.cash_variance < 0:
            # Fisik lebih sedikit dari sistem: Dr. 619990 (Beban Selisih) / Cr. 111010 (Kas Kasir)
            line_vals = [
                (0, 0, {
                    'name': ref_desc,
                    'account_id': variance_acc.id,
                    'debit': amt,
                    'credit': 0.0,
                    'analytic_distribution': analytic_dist,
                }),
                (0, 0, {
                    'name': ref_desc,
                    'account_id': cash_acc.id,
                    'debit': 0.0,
                    'credit': amt,
                }),
            ]
        else:
            # Fisik lebih banyak dari sistem: Dr. 111010 (Kas Kasir) / Cr. 619990
            line_vals = [
                (0, 0, {
                    'name': ref_desc,
                    'account_id': cash_acc.id,
                    'debit': amt,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': ref_desc,
                    'account_id': variance_acc.id,
                    'debit': 0.0,
                    'credit': amt,
                    'analytic_distribution': analytic_dist,
                }),
            ]

        move = self.env['account.move'].create({
            'journal_id': journal.id,
            'date': fields.Date.today(),
            'ref': ref_desc,
            'move_type': 'entry',
            'line_ids': line_vals,
        })
        move.action_post()
        self.variance_move_id = move.id
