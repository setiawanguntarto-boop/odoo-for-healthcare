# -*- coding: utf-8 -*-
from odoo import fields, models


class DateRangeType(models.Model):
    _name = "date.range.type"
    _description = "Date Range Type"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)


class DateRange(models.Model):
    _name = "date.range"
    _description = "Date Range"

    name = fields.Char(required=True)
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    type_id = fields.Many2one("date.range.type", string="Type")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

