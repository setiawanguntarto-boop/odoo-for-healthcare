# -*- coding: utf-8 -*-
from odoo import models, fields, api, exceptions, _


class ClinicApprovalRejectWizard(models.TransientModel):
    _name = 'clinic.approval.reject.wizard'
    _description = 'Rejection Reason Wizard'

    inbox_id = fields.Many2one('clinic.approval.inbox', string='Approval Item')
    res_model = fields.Char(string='Target Model', required=True)
    res_id = fields.Integer(string='Target ID', required=True)
    document_name = fields.Char(string='Nomor Dokumen', readonly=True)

    rejection_reason = fields.Text(
        string='Alasan Penolakan / Catatan Revisi',
        required=True,
        help='Tuliskan dengan jelas poin-poin yang harus diperbaiki oleh staf pengaju.'
    )

    def action_confirm_rejection(self):
        self.ensure_one()
        if not self.rejection_reason or len(self.rejection_reason.strip()) < 5:
            raise exceptions.ValidationError(_("Harap berikan alasan penolakan yang jelas (minimal 5 karakter)."))

        target_record = self.env[self.res_model].browse(self.res_id)
        if not target_record.exists():
            raise exceptions.UserError(_("Dokumen asal sudah tidak ditemukan."))

        # 1. Log rejection note to chatter
        if hasattr(target_record, 'message_post'):
            target_record.message_post(
                body=f"<b>[OTORISASI DITOLAK OLEH {self.env.user.name}]:</b><br/>{self.rejection_reason}",
                message_type='comment',
                subtype_xmlid='mail.mt_comment'
            )

        # 2. Call specific reject action on target model
        if self.res_model == 'clinic.asset.disposal':
            target_record.action_reject(reason=self.rejection_reason)
        elif self.res_model == 'medical.fee.settlement.batch':
            target_record.write({
                'state': 'draft',
                'cancellation_reason': self.rejection_reason,
            })
        elif self.res_model == 'stock.scrap.clinic':
            target_record.write({
                'state': 'draft',
            })
        elif self.res_model == 'pos.session':
            target_record.write({
                'discrepancy_reason': f"Ditolak Supervisor: {self.rejection_reason}",
            })
        else:
            if hasattr(target_record, 'action_reject'):
                try:
                    target_record.action_reject(reason=self.rejection_reason)
                except TypeError:
                    target_record.action_reject()
            elif hasattr(target_record, 'action_cancel'):
                target_record.action_cancel()

        # 3. Complete pending To-Do activities
        activities = self.env['mail.activity'].search([
            ('res_model', '=', self.res_model),
            ('res_id', '=', self.res_id),
        ])
        if activities:
            activities.action_feedback(feedback=_("Ditolak dengan alasan: %s") % self.rejection_reason)

        return {'type': 'ir.actions.act_window_close'}
