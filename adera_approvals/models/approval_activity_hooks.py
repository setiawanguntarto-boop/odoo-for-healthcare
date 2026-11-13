# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class PosSession(models.Model):
    _name = 'pos.session'
    _inherit = ['pos.session', 'clinic.approval.mixin']

    def action_pos_session_closing_control(self, *args, **kwargs):
        res = super().action_pos_session_closing_control(*args, **kwargs)
        for session in self:
            tolerance = session.variance_tolerance_limit or 50000.0
            variance = abs(session.cash_variance_amount or 0.0)
            if variance > tolerance and not session.supervisor_override_user_id:
                session._notify_approvers_activity(
                    summary=_("Otorisasi Selisih Kas Kasir POS: %s") % session.name,
                    note=_("Sesi %s mencatat selisih fisik kas sebesar Rp %s yang melampaui batas toleransi (Rp %s). Memerlukan otorisasi supervisor.") % (
                        session.name, f"{variance:,.2f}", f"{tolerance:,.2f}"
                    ),
                    target_group_xmlid='adera_core.group_clinic_director',
                )
        return res

    def action_supervisor_approve_variance(self):
        res = super().action_supervisor_approve_variance()
        self._complete_approval_activities()
        return res


class MedicalFeeSettlementBatch(models.Model):
    _name = 'medical.fee.settlement.batch'
    _inherit = ['medical.fee.settlement.batch', 'clinic.approval.mixin']

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.state in ['draft', 'verified']:
                rec._notify_approvers_activity(
                    summary=_("Otorisasi Remunerasi Dokter: %s") % rec.name,
                    note=_("Batch remunerasi dokter %s (Nominal: Rp %s) menunggu verifikasi & persetujuan.") % (
                        rec.name, f"{float(rec.total_net_payable or 0.0):,.2f}"
                    ),
                    target_group_xmlid='adera_doctor_remuneration.group_medical_manager' if rec.state == 'draft' else 'adera_core.group_clinic_director',
                )
        return records

    def action_submit_verification(self):
        res = super().action_submit_verification()
        for rec in self:
            rec._notify_approvers_activity(
                summary=_("Verifikasi Medis: %s") % rec.name,
                note=_("Batch remunerasi %s diajukan ke Manajer Medis untuk verifikasi klinis.").format(rec.name),
                target_group_xmlid='adera_doctor_remuneration.group_medical_manager',
            )
        return res

    def action_medical_manager_verify(self):
        res = super().action_medical_manager_verify()
        for rec in self:
            rec._complete_approval_activities()
            rec._notify_approvers_activity(
                summary=_("Persetujuan Direksi: %s") % rec.name,
                note=_("Batch %s telah diverifikasi medis. Membutuhkan persetujuan Direksi untuk pencairan.").format(rec.name),
                target_group_xmlid='adera_core.group_clinic_director',
            )
        return res

    def action_finance_approve_and_pay(self):
        res = super().action_finance_approve_and_pay()
        self._complete_approval_activities()
        return res


class ClinicAssetDisposal(models.Model):
    _name = 'clinic.asset.disposal'
    _inherit = ['clinic.asset.disposal', 'clinic.approval.mixin']

    def action_submit_for_approval(self):
        res = super().action_submit_for_approval()
        for rec in self:
            rec._notify_approvers_activity(
                summary=_("Otorisasi Pelepasan Aset Medis: %s") % rec.name,
                note=_("Usulan penghapusan/disposal aset %s membutuhkan persetujuan Direktur Utama.").format(rec.name),
                target_group_xmlid='adera_core.group_clinic_director',
            )
        return res

    def action_approve_disposal(self):
        res = super().action_approve_disposal()
        self._complete_approval_activities()
        return res

    def action_reject(self, reason=None):
        res = super().action_reject(reason=reason) if hasattr(super(), 'action_reject') else None
        self._complete_approval_activities()
        return res
