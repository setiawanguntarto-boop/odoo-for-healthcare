# -*- coding: utf-8 -*-
"""
POS Session Management with Blind-Count Shift Closing & Cash Variance Governance
Klinik ADERA ERP (Odoo 19 CE)
"""

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class PosSession(models.Model):
    _inherit = 'pos.session'

    # 1. Blind-Count Core Fields
    is_blind_count_mode = fields.Boolean(
        string='Blind-Count Active',
        default=True,
        help='Menyembunyikan saldo teoritis sistem dari tampilan kasir saat penutupan shift.'
    )
    blind_count_physical_total = fields.Monetary(
        string='Total Fisik Kas Dihitung Kasir (Blind Count)',
        currency_field='currency_id',
        default=0.0,
        help='Nominal uang tunai fisik yang dihitung secara mandiri oleh kasir.'
    )
    blind_count_cash_counted = fields.Monetary(
        string='Fisik Kas Dihitung (Legacy)',
        currency_field='currency_id',
        compute='_compute_legacy_counted',
        store=True
    )
    cash_variance_amount = fields.Monetary(
        string='Selisih Kasir (Cash Variance)',
        currency_field='currency_id',
        compute='_compute_cash_variance_amount',
        store=True,
        help='Selisih antara uang fisik dihitung kasir dengan saldo teoritis sistem.'
    )
    cash_variance = fields.Monetary(
        string='Selisih Kasir (Legacy Alias)',
        currency_field='currency_id',
        compute='_compute_legacy_variance',
        store=True
    )

    # 2. Supervisor Governance & Override Fields
    supervisor_override_user_id = fields.Many2one(
        'res.users',
        string='Otorisasi Supervisor Kasir',
        readonly=True,
        help='Supervisor/Manager yang mengesahkan penutupan shift kasir jika terdapat selisih di luar batas toleransi.'
    )
    supervisor_override_date = fields.Datetime(
        string='Waktu Otorisasi Supervisor',
        readonly=True
    )
    discrepancy_reason = fields.Text(
        string='Alasan / Berita Acara Selisih Kasir',
        help='Wajib diisi jika selisih kasir melebihi batas toleransi Rp 50.000.'
    )
    variance_reason = fields.Text(
        string='Alasan Selisih (Legacy Alias)',
        related='discrepancy_reason',
        readonly=False
    )
    variance_tolerance_limit = fields.Monetary(
        string='Batas Toleransi Selisih Kas',
        currency_field='currency_id',
        default=50000.0,
        help='Ambang batas toleransi selisih kas (standar Klinik ADERA: Rp 50.000,00).'
    )
    variance_move_id = fields.Many2one(
        'account.move',
        string='Jurnal Selisih Kasir (619990 / 710090)',
        readonly=True
    )

    @api.depends('blind_count_physical_total')
    def _compute_legacy_counted(self):
        for session in self:
            session.blind_count_cash_counted = session.blind_count_physical_total

    @api.depends('blind_count_physical_total', 'cash_register_balance_end_real', 'cash_register_balance_end')
    def _compute_cash_variance_amount(self):
        for session in self:
            theoretical = session.cash_register_balance_end or 0.0
            counted = session.blind_count_physical_total or session.cash_register_balance_end_real or 0.0
            session.cash_variance_amount = counted - theoretical

    @api.depends('cash_variance_amount')
    def _compute_legacy_variance(self):
        for session in self:
            session.cash_variance = session.cash_variance_amount

    def action_supervisor_approve_variance(self, reason=None):
        """Supervisor authorization method to unlock major variance sessions (> Rp 50,000)."""
        self.ensure_one()
        user = self.env.user
        if not user.has_group('point_of_sale.group_pos_manager') and not user.has_group('adera_core.group_clinic_director') and not user.has_group('base.group_system'):
            raise UserError("Hanya Supervisor Kasir / Manajer Keuangan yang berhak mengesahkan selisih kasir di luar batas toleransi!")

        if reason:
            self.discrepancy_reason = reason
        elif not self.discrepancy_reason:
            raise ValidationError("Berita acara / alasan selisih kasir wajib diisi sebelum supervisor memberikan otorisasi!")

        self.write({
            'supervisor_override_user_id': user.id,
            'supervisor_override_date': fields.Datetime.now(),
        })
        self.message_post(
            body=f"Otorisasi Selisih Kasir Disetujui oleh {user.name} (Nominal: {self.currency_id.symbol} {self.cash_variance_amount:,.2f}). Alasan: {self.discrepancy_reason}"
        )
        return True

    def action_pos_session_close(self, balancing_account=False, amount_to_balance=0, bank_payment_method_diffs=None):
        """
        Enforce Blind-Count Shift Governance:
        1. Validates tolerance threshold: if |variance| > Rp 50,000, supervisor approval is mandatory.
        2. Closes POS session.
        3. Automatically posts loss/gain cash variance journal entry to Account 619990 / 710090.
        """
        for session in self:
            abs_variance = abs(session.cash_variance_amount)
            # Enforce Supervisor PIN / Override for major discrepancies
            if abs_variance > session.variance_tolerance_limit:
                if not session.supervisor_override_user_id:
                    raise ValidationError(
                        f"Peringatan Selisih Kasir Kritis!\n"
                        f"Sesi kasir '{session.name}' memiliki selisih sebesar Rp {abs_variance:,.2f} "
                        f"(melebihi batas toleransi Rp {session.variance_tolerance_limit:,.2f}).\n"
                        f"Penutupan shift DIBLOKIR hingga Supervisor Kasir menginput PIN/otorisasi dan Berita Acara Selisih!"
                    )

        res = super(PosSession, self).action_pos_session_close(
            balancing_account=balancing_account,
            amount_to_balance=amount_to_balance,
            bank_payment_method_diffs=bank_payment_method_diffs
        )

        for session in self:
            if session.cash_variance_amount != 0.0 and not session.variance_move_id:
                session._post_cashier_variance_entry()

        return res

    def _post_cashier_variance_entry(self):
        """
        Membukukan selisih fisik kasir ke:
        - Jika Kurang (variance < 0): Debit 619990 (Beban Selisih Kasir & Petty Cash) / Kredit 111010/111020 (Kas Kasir).
        - Jika Lebih  (variance > 0): Debit 111010/111020 (Kas Kasir) / Kredit 710090 (Pendapatan Lain-Lain Selisih Kasir).
        """
        self.ensure_one()
        Account = self.env['account.account']

        # 1. Resolve Accounts
        loss_acc = Account.search([('code', '=', '619990')], limit=1)
        if not loss_acc:
            loss_acc = self.env.ref('adera_core.account_619990', raise_if_not_found=False)

        gain_acc = Account.search([('code', '=', '710090')], limit=1)
        if not gain_acc:
            gain_acc = Account.search([('code', '=', '710000')], limit=1)

        is_hd = 'HD' in (self.config_id.name or '') or 'Hemodialisis' in (self.config_id.name or '')
        cash_code = '111020' if is_hd else '111010'
        cash_acc = Account.search([('code', '=', cash_code)], limit=1)
        if not cash_acc:
            cash_acc = Account.search([('code', 'in', ['111010', '111110'])], limit=1)

        # 2. Resolve Analytic Tag
        Analytic = self.env['account.analytic.account']
        analytic_code = 'ACC-HD' if is_hd else 'ACC-PRATAMA'
        analytic_acc = Analytic.search([('code', '=', analytic_code)], limit=1)
        analytic_dist = {str(analytic_acc.id): 100.0} if analytic_acc else False

        # 3. Resolve Journal
        journal = self.env['account.journal'].search([('code', 'in', ['MISCL', 'MISC'])], limit=1)
        if not journal:
            journal = self.env['account.journal'].search([('type', '=', 'general')], limit=1)

        amt = abs(self.cash_variance_amount)
        ref_desc = f"Selisih Kasir Shift {self.name} ({self.config_id.name}) - {self.discrepancy_reason or 'Blind-Count Variance'}"

        if self.cash_variance_amount < 0.0:
            # Cash Shortage: Dr. 619990 (Beban Selisih Kasir) vs Cr. 111010 (Kas Kasir)
            line_vals = [
                (0, 0, {
                    'name': ref_desc,
                    'account_id': loss_acc.id,
                    'debit': amt,
                    'credit': 0.0,
                    'analytic_distribution': analytic_dist,
                }),
                (0, 0, {
                    'name': ref_desc,
                    'account_id': cash_acc.id,
                    'debit': 0.0,
                    'credit': amt,
                    'analytic_distribution': False,
                }),
            ]
        else:
            # Cash Overage: Dr. 111010 (Kas Kasir) vs Cr. 710090 (Pendapatan Lain-lain Selisih Kasir)
            target_gain_id = gain_acc.id if gain_acc else loss_acc.id
            line_vals = [
                (0, 0, {
                    'name': ref_desc,
                    'account_id': cash_acc.id,
                    'debit': amt,
                    'credit': 0.0,
                    'analytic_distribution': False,
                }),
                (0, 0, {
                    'name': ref_desc,
                    'account_id': target_gain_id,
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
        self.message_post(body=f"Entri Penjurnalan Selisih Kasir berhasil dibukukan: {move.name} (Ref: {move.ref})")
        return move
