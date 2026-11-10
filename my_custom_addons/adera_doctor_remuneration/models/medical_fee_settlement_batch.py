# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class MedicalFeeSettlementBatch(models.Model):
    _name = "medical.fee.settlement.batch"
    _description = "Physician Remuneration Settlement Batch (Multi-Tier Approval)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "period_end desc, id desc"

    name = fields.Char(
        string="Nomor Batch Settlement",
        required=True,
        copy=False,
        default="/",
        tracking=True,
    )
    doctor_id = fields.Many2one(
        "res.partner",
        string="Dokter Penerima",
        required=True,
        domain="[('is_doctor', '=', True)]",
        tracking=True,
    )
    period_start = fields.Date(
        string="Periode Awal",
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
        tracking=True,
    )
    period_end = fields.Date(
        string="Periode Akhir",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )

    company_id = fields.Many2one(
        "res.company",
        string="Klinik / Perusahaan",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        string="Mata Uang",
    )

    line_ids = fields.One2many(
        "medical.fee.settlement.line",
        "batch_id",
        string="Rincian Tindakan Layanan Pasien",
    )

    total_gross_fee = fields.Monetary(
        string="Total Jasa Medis Bruto",
        currency_field="currency_id",
        compute="_compute_financial_totals",
        store=True,
        tracking=True,
    )
    dpp_amount = fields.Monetary(
        string="Dasar Pengenaan Pajak (50% Bruto)",
        currency_field="currency_id",
        compute="_compute_financial_totals",
        store=True,
    )
    total_pph21_withheld = fields.Monetary(
        string="Potongan PPh 21 Tenaga Ahli (PMK 168/2023)",
        currency_field="currency_id",
        compute="_compute_financial_totals",
        store=True,
        tracking=True,
    )
    total_net_payable = fields.Monetary(
        string="Total Net Transfer Disbursed",
        currency_field="currency_id",
        compute="_compute_financial_totals",
        store=True,
        tracking=True,
    )

    bank_journal_id = fields.Many2one(
        "account.journal",
        string="Rekening Bank Pengirim",
        domain="[('type', '=', 'bank')]",
        required=True,
        default=lambda self: self._default_bank_journal(),
        tracking=True,
    )

    claim_admin_id = fields.Many2one(
        "res.users",
        string="Disusun Oleh (Staf Klaim)",
        default=lambda self: self.env.user,
        tracking=True,
    )
    verified_by_id = fields.Many2one(
        "res.users",
        string="Diverifikasi Oleh (Manajer Medis)",
        readonly=True,
        tracking=True,
    )
    verified_datetime = fields.Datetime(
        string="Waktu Verifikasi Medis",
        readonly=True,
        tracking=True,
    )
    approved_by_id = fields.Many2one(
        "res.users",
        string="Disetujui Oleh (Direktur Keuangan)",
        readonly=True,
        tracking=True,
    )
    approved_datetime = fields.Datetime(
        string="Waktu Persetujuan Direksi",
        readonly=True,
        tracking=True,
    )

    payment_move_id = fields.Many2one(
        "account.move",
        string="Jurnal Pencairan Bank (Disbursement Move)",
        readonly=True,
        tracking=True,
    )
    cancellation_reason = fields.Text(
        string="Alasan Pembatalan / Penolakan",
        readonly=True,
        tracking=True,
    )

    state = fields.Selection(
        [
            ("draft", "Draft (Disusun Staf Klaim)"),
            ("verified", "Verified (Terverifikasi Medis)"),
            ("approved", "Approved (Disetujui Direksi)"),
            ("paid", "Paid (Dicairkan & Jurnal Terbit)"),
            ("cancelled", "Cancelled (Dibatalkan)"),
        ],
        string="Status Approval",
        default="draft",
        required=True,
        tracking=True,
    )

    def _default_bank_journal(self):
        j = self.env["account.journal"].search([("code", "in", ["BCA", "BBCA"])], limit=1)
        if not j:
            j = self.env["account.journal"].search([("type", "=", "bank")], limit=1)
        return j

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                seq_code = "medical.fee.settlement.batch"
                vals["name"] = self.env["ir.sequence"].next_by_code(seq_code) or "/"
        return super().create(vals_list)

    def action_load_fee_lines(self):
        """Menarik akrual tindakan dokter yang belum diproses."""
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Penarikan data hanya dapat dilakukan pada status Draf!"))

        self.line_ids.unlink()

        accruals = self.env["medical.fee.accrual"].search([
            ("doctor_id", "=", self.doctor_id.id),
            ("encounter_date", ">=", self.period_start),
            ("encounter_date", "<=", self.period_end),
            ("state", "=", "accrued"),
            ("settlement_id", "=", False),
        ])

        new_lines = []
        for acc in accruals:
            new_lines.append((0, 0, {
                "accrual_id": acc.id,
                "encounter_reference": acc.encounter_reference or "",
                "encounter_date": acc.encounter_date,
                "patient_id": acc.patient_id.id,
                "product_id": acc.product_id.id,
                "billing_amount": acc.billing_amount,
                "doctor_fee_amount": acc.doctor_fee_amount,
            }))

        self.write({"line_ids": new_lines})
        return True

    @api.depends("line_ids.doctor_fee_amount", "doctor_id", "period_end")
    def _compute_financial_totals(self):
        for rec in self:
            gross = sum(rec.line_ids.mapped("doctor_fee_amount"))
            rec.total_gross_fee = gross
            dpp = gross * 0.50
            rec.dpp_amount = dpp

            # Progressive tax calculation PMK 168/2023 with non-NPWP penalty logic
            target_year = (rec.period_end or fields.Date.today()).year
            prior_batches = self.search([
                ("doctor_id", "=", rec.doctor_id.id),
                ("id", "!=", rec.id or 0),
                ("state", "in", ["approved", "paid"]),
                ("period_end", ">=", f"{target_year}-01-01"),
                ("period_end", "<=", f"{target_year}-12-31"),
            ])
            # Also include legacy doctor.settlement if present
            prior_settlements = self.env["doctor.settlement"].search([
                ("doctor_id", "=", rec.doctor_id.id),
                ("state", "in", ["approved", "paid"]),
                ("date_settlement", ">=", f"{target_year}-01-01"),
                ("date_settlement", "<=", f"{target_year}-12-31"),
            ])

            prior_dpp = sum(prior_batches.mapped("dpp_amount")) + sum(prior_settlements.mapped("dpp_amount"))
            total_dpp_now = prior_dpp + dpp

            def calc_tax(cum_dpp, has_npwp):
                brackets = [
                    (60000000.0, 0.05),
                    (250000000.0, 0.15),
                    (500000000.0, 0.25),
                    (5000000000.0, 0.30),
                    (float("inf"), 0.35),
                ]
                tax = 0.0
                rem = cum_dpp
                lower = 0.0
                for upper, rate in brackets:
                    if rem <= 0:
                        break
                    tier_width = upper - lower
                    taxable = min(rem, tier_width)
                    effective_rate = rate if has_npwp else (rate * 1.20)
                    tax += taxable * effective_rate
                    rem -= taxable
                    lower = upper
                return tax

            has_npwp = bool(rec.doctor_id.vat or getattr(rec.doctor_id, "has_npwp", False))
            tax_total = calc_tax(total_dpp_now, has_npwp)
            tax_prior = calc_tax(prior_dpp, has_npwp)
            tax_period = max(0.0, round(tax_total - tax_prior, 2))

            rec.total_pph21_withheld = tax_period
            rec.total_net_payable = max(0.0, round(gross - tax_period, 2))

    # =========================================================================
    # WORKFLOW TRANSITION ENGINES
    # =========================================================================

    def compute_settlement_lines(self):
        """Alias untuk action_load_fee_lines."""
        return self.action_load_fee_lines()

    def action_submit_to_medical_manager(self):
        """Alias untuk action_submit_verification."""
        return self.action_submit_verification()

    def action_verify_medical_services(self):
        """Alias untuk action_medical_manager_verify."""
        return self.action_medical_manager_verify()

    def action_execute_bank_disbursement(self):
        """Alias untuk action_finance_approve_and_pay."""
        return self.action_finance_approve_and_pay()

    def action_submit_verification(self):
        """Tier 1: Claims Admin mengajukan ke Manajer Medis (draft -> verified)."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Tidak ada rincian jasa medis yang dimuat! Tekan 'Tarik Jasa Medis' terlebih dahulu."))
        if self.total_gross_fee <= 0:
            raise UserError(_("Total jasa medis bruto harus lebih besar dari 0!"))

        # Tandai akrual dalam proses
        accruals = self.line_ids.mapped("accrual_id")
        accruals.write({"state": "in_settlement"})

        self.write({
            "state": "verified",
            "verified_by_id": self.env.user.id,
            "verified_datetime": fields.Datetime.now(),
        })
        self.message_post(
            body=_("Batch jasa medis diajukan oleh %s untuk verifikasi klinis.") % self.env.user.name,
            subtype_xmlid="mail.mt_note",
        )
        return True

    def action_medical_manager_verify(self):
        """Tier 2: Manajer Medis memvalidasi kesesuaian klinis (verified -> approved)."""
        self.ensure_one()
        if self.state != "verified":
            raise UserError(_("Hanya batch berstatus 'Verified' yang dapat disetujui Manajer Medis!"))

        self.write({
            "state": "approved",
            "approved_by_id": self.env.user.id,
            "approved_datetime": fields.Datetime.now(),
        })
        self.message_post(
            body=_("Verifikasi klinis & tarif disetujui oleh Manajer Medis %s. Siap untuk pencairan dana.") % self.env.user.name,
            subtype_xmlid="mail.mt_note",
        )
        return True

    def action_finance_approve_and_pay(self):
        """Tier 3: Direktur Keuangan mengeksekusi pencairan bank & posting jurnal (approved -> paid)."""
        self.ensure_one()
        if self.state != "approved":
            raise UserError(_("Pencairan dana hanya dapat dilakukan setelah disetujui Manajer Medis (status Approved)!"))

        if self.payment_move_id:
            raise UserError(_("Entri jurnal pembayaran sudah pernah dibukukan!"))

        # Tentukan akun hutang berdasarkan spesialisasi dokter
        doc_type = getattr(self.doctor_id, "doctor_type", False)
        if doc_type == "specialist_hd":
            payable_acc = self.env.ref("adera_core.account_213020", raise_if_not_found=False)
            if not payable_acc:
                payable_acc = self.env["account.account"].search([("code", "=", "213020")], limit=1)
        else:
            payable_acc = self.env.ref("adera_core.account_213010", raise_if_not_found=False)
            if not payable_acc:
                payable_acc = self.env["account.account"].search([("code", "=", "213010")], limit=1)

        tax_acc = self.env.ref("adera_core.account_212030", raise_if_not_found=False)
        if not tax_acc:
            tax_acc = self.env["account.account"].search([("code", "=", "212030")], limit=1)

        bank_acc = self.bank_journal_id.default_account_id
        if not bank_acc:
            bank_acc = self.env["account.account"].search([("code", "=", "111110")], limit=1)

        if not payable_acc or not tax_acc or not bank_acc:
            raise UserError(_("Konfigurasi Akun Utang Jasa Medis (213010/213020), Utang PPh 21 (212030), atau Akun Bank belum lengkap!"))

        move_lines = [
            # 1. Debit Utang Jasa Medis (Gross)
            (0, 0, {
                "name": f"Pelunasan Akrual Jasa Medis: {self.doctor_id.name} ({self.name})",
                "account_id": payable_acc.id,
                "partner_id": self.doctor_id.id,
                "debit": self.total_gross_fee,
                "credit": 0.0,
            }),
            # 2. Credit Bank BCA Operasional (Net Disbursed)
            (0, 0, {
                "name": f"Pencairan Transfer Bank Net Fee: {self.doctor_id.name}",
                "account_id": bank_acc.id,
                "partner_id": self.doctor_id.id,
                "debit": 0.0,
                "credit": self.total_net_payable,
            }),
        ]

        # 3. Credit Utang PPh 21 Tenaga Ahli (Withheld Tax)
        if self.total_pph21_withheld > 0.0:
            move_lines.append((0, 0, {
                "name": f"Pemotongan PPh 21 Dokter Ps 17/PMK 168: {self.doctor_id.name}",
                "account_id": tax_acc.id,
                "partner_id": self.doctor_id.id,
                "debit": 0.0,
                "credit": self.total_pph21_withheld,
            }))

        move = self.env["account.move"].create({
            "journal_id": self.bank_journal_id.id,
            "date": fields.Date.context_today(self),
            "ref": f"Remunerasi Dokter Batch: {self.name} - {self.doctor_id.name}",
            "move_type": "entry",
            "line_ids": move_lines,
        })
        move.action_post()

        # Update status akrual dan encounter
        accruals = self.line_ids.mapped("accrual_id")
        accruals.write({"state": "disbursed"})

        # Notify clinic.encounter if model is present and has records
        if "clinic.encounter" in self.env:
            enc_refs = [r for r in self.line_ids.mapped("encounter_reference") if r]
            if enc_refs:
                encounters = self.env["clinic.encounter"].search([
                    "|",
                    ("external_encounter_id", "in", enc_refs),
                    ("name", "in", enc_refs),
                ])
                for enc in encounters:
                    if hasattr(enc, "message_post"):
                        try:
                            enc.message_post(body=_("Jasa Medis Dokter telah dibayarkan melalui Batch %s") % self.name)
                        except Exception:
                            pass

        self.write({
            "payment_move_id": move.id,
            "state": "paid",
        })
        self.message_post(
            body=_("Disbursement selesai dieksekusi oleh Direktur Keuangan %s. Jurnal GL: %s") % (self.env.user.name, move.name),
            subtype_xmlid="mail.mt_note",
        )
        return True

    def action_cancel(self):
        """Membatalkan batch settlement dengan mencatat alasan di chatter."""
        self.ensure_one()
        if self.state == "paid":
            raise UserError(_("Batch yang sudah dibayar tidak dapat dibatalkan! Buat entri pembalik jurnal manual jika diperlukan."))

        accruals = self.line_ids.mapped("accrual_id")
        accruals.write({"state": "accrued"})

        self.write({
            "state": "cancelled",
        })
        self.message_post(
            body=_("Batch remunerasi dibatalkan. Status akrual dikembalikan ke 'Accrued'."),
            subtype_xmlid="mail.mt_note",
        )
        return True


class MedicalFeeSettlementLine(models.Model):
    _name = "medical.fee.settlement.line"
    _description = "Rincian Tindakan Pelayanan Batch Settlement"
    _order = "encounter_date desc, id desc"

    batch_id = fields.Many2one(
        "medical.fee.settlement.batch",
        string="Batch Settlement",
        ondelete="cascade",
        required=True,
    )
    accrual_id = fields.Many2one(
        "medical.fee.accrual",
        string="Ref Akrual",
        ondelete="set null",
    )
    encounter_reference = fields.Char(
        string="Referensi Kunjungan EHR / Klinik",
        help="Nomor referensi atau ID kunjungan encounter",
    )
    encounter_date = fields.Date(
        string="Tanggal Pelayanan",
        required=True,
    )
    patient_id = fields.Many2one(
        "res.partner",
        string="Pasien",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Tindakan / Layanan Medis",
        required=True,
    )
    billing_amount = fields.Monetary(
        string="Tarif Tagihan Pasien",
        currency_field="currency_id",
    )
    doctor_fee_amount = fields.Monetary(
        string="Porsi Jasa Medis (Bruto)",
        currency_field="currency_id",
        required=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="batch_id.currency_id",
    )
