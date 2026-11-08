# -*- coding: utf-8 -*-
from odoo import models


class ReportXlsxAbstract(models.AbstractModel):
    _name = "report.report_xlsx.abstract"
    _description = "Abstract XLSX Report"

    def _get_objs_for_report(self, docids, data):
        if docids:
            return self.env[self.env.context.get("active_model")].browse(docids)
        elif data and "docids" in data:
            return self.env[self.env.context.get("active_model")].browse(data["docids"])
        return []

