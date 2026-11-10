# -*- coding: utf-8 -*-
from odoo import fields, models, api
from odoo.exceptions import ValidationError


class AccountMove(models.Model):
    _inherit = "account.move"

    clinic_unit = fields.Selection(
        [
            ("pratama", "Klinik Pratama (Outpatient)"),
            ("hd", "Klinik Utama Hemodialisis (HD)"),
        ],
        string="Unit Bisnis Klinik",
        help="Pemisahan unit bisnis untuk pelaporan analitik laba rugi PSAK",
    )
    is_bpjs_claim = fields.Boolean(
        string="Klaim BPJS",
        compute="_compute_is_bpjs_claim",
        store=True,
    )

    @api.depends("line_ids.account_id")
    def _compute_is_bpjs_claim(self):
        for move in self:
            move.is_bpjs_claim = any(
                line.account_id.code and line.account_id.code.startswith("112020")
                for line in move.line_ids
            )

    @api.constrains("line_ids")
    def _check_segregation_payroll_doctor_remuneration(self):
        """Audit Control: Mencegah percampuran akun gaji karyawan tetap (610010) dengan jasa medis dokter mitra (510110/510120/213010/213020)."""
        for move in self:
            account_codes = [line.account_id.code for line in move.line_ids if line.account_id and line.account_id.code]
            has_employee_payroll = any(c == "610010" or c.startswith("61001") for c in account_codes)
            has_doctor_fees = any(c in ["510110", "510120", "213010", "213020"] or c.startswith("5101") or c.startswith("2130") for c in account_codes)
            if has_employee_payroll and has_doctor_fees:
                raise ValidationError(
                    "Audit Segregation Error: Tidak diperkenankan menggabungkan Akun Gaji Karyawan Tetap (610010 - PPh 21 TER) "
                    "dengan Akun Jasa Medis Dokter Mitra Independen (510110/510120/213010/213020 - PMK 168/2023) dalam satu entri jurnal yang sama!"
                )


