# Copyright 2020 Onestein (<https://www.onestein.eu>)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class IrActionsReport(models.Model):
    _inherit = "ir.actions.report"

    report_type = fields.Selection(
        selection_add=[("xlsx", "XLSX")],
        ondelete={"xlsx": "set default"}
    )

    @api.model
    def _prepare_account_financial_report_context(self, data):
        lang = data and data.get("account_financial_report_lang") or ""
        return dict(self.env.context or {}, lang=lang) if lang else False

    @api.model
    def _render_qweb_html(self, report_ref, docids, data=None):
        context = self._prepare_account_financial_report_context(data)
        obj = self.with_context(**context) if context else self
        return super(IrActionsReport, obj)._render_qweb_html(
            report_ref, docids, data=data
        )

    @api.model
    def _render_xlsx(self, report_ref, docids, data=None):
        context = self._prepare_account_financial_report_context(data)
        obj = self.with_context(**context) if context else self
        return super(IrActionsReport, obj)._render_xlsx(report_ref, docids, data=data)
