# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class ClinicApprovalMixin(models.AbstractModel):
    _name = 'clinic.approval.mixin'
    _description = 'Clinical Approval Notification and Activity Hooks Mixin'

    def _notify_approvers_activity(self, summary, note, target_group_xmlid=None, deadline_days=1):
        """
        Create a To-Do mail.activity for all authorized approvers.
        This triggers real-time desktop / top-right bell counter notifications in Odoo.
        """
        todo_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not todo_type:
            todo_type = self.env['mail.activity.type'].search([('category', '=', 'default')], limit=1)
        if not todo_type:
            return

        users = self.env['res.users']
        if target_group_xmlid:
            group = self.env.ref(target_group_xmlid, raise_if_not_found=False)
            if group:
                users = group.user_ids.filtered(lambda u: u.active)

        # Fallback to administrators or current user if no explicit group members found yet
        if not users:
            admin_group = self.env.ref('base.group_erp_manager', raise_if_not_found=False)
            if admin_group:
                users = admin_group.user_ids.filtered(lambda u: u.active)
        if not users:
            users = self.env.user

        for record in self:
            if not hasattr(record, 'activity_schedule'):
                continue

            date_deadline = fields.Date.add(fields.Date.today(), days=deadline_days)
            for user in users:
                existing = self.env['mail.activity'].search([
                    ('res_model', '=', record._name),
                    ('res_id', '=', record.id),
                    ('user_id', '=', user.id),
                    ('activity_type_id', '=', todo_type.id),
                ], limit=1)
                if not existing:
                    try:
                        record.activity_schedule(
                            activity_type_id=todo_type.id,
                            summary=summary,
                            note=note,
                            user_id=user.id,
                            date_deadline=date_deadline,
                        )
                    except Exception as e:
                        _logger.warning("Could not schedule activity for user %s on %s: %s", user.name, record, e)

    def _complete_approval_activities(self):
        """Mark all pending approval activities as done on this record."""
        for record in self:
            activities = self.env['mail.activity'].search([
                ('res_model', '=', record._name),
                ('res_id', '=', record.id),
            ])
            if activities:
                activities.action_feedback(feedback=_("Otorisasi telah diproses (Disetujui/Ditolak)."))
