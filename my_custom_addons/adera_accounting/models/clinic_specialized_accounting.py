# -*- coding: utf-8 -*-
from odoo import fields, models, api
from odoo.exceptions import UserError
from datetime import date


class BpjsCapitationRecognition(models.TransientModel):
    _name = "bpjs.capitation.recognition"
    _description = "Pengakuan Akrual Pendapatan Kapitasi BPJS Kesehatan FKTP"

    name = fields.Char(string="Keterangan Pengakuan", required=True, default="Penerimaan Dana Kapitasi BPJS Kesehatan FKTP")
    period_month = fields.Selection(
        [
            ("1", "Januari"), ("2", "Februari"), ("3", "Maret"),
            ("4", "April"), ("5", "Mei"), ("6", "Juni"),
            ("7", "Juli"), ("8", "Agustus"), ("9", "September"),
            ("10", "Oktober"), ("11", "November"), ("12", "Desember"),
        ],
        string="Bulan Cakupan",
        required=True,
        default=str(date.today().month),
    )
    period_year = fields.Integer(string="Tahun Pajak / Cakupan", required=True, default=date.today().year)
    recognition_date = fields.Date(string="Tanggal Pembukuan", required=True, default=fields.Date.today)

    registered_participants = fields.Integer(string="Jumlah Peserta Terdaftar FKTP", required=True, default=10000)
    rate_per_participant = fields.Monetary(string="Norma Tarif Kapitasi per Peserta (Rp)", required=True, default=10000.0, currency_field="currency_id")
    total_amount = fields.Monetary(string="Total Dana Kapitasi Diterima", compute="_compute_total_amount", store=True, currency_field="currency_id")

    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")

    bank_journal_id = fields.Many2one("account.journal", string="Rekening Bank Penampung", domain="[('type', '=', 'bank')]", required=True)
    income_account_id = fields.Many2one(
        "account.account",
        string="Akun Pendapatan Kapitasi",
        required=True,
        default=lambda self: self.env.ref("adera_core.account_410040", raise_if_not_found=False),
    )
    analytic_account_id = fields.Many2one(
        "account.analytic.account",
        string="Unit Bisnis Analitik",
        default=lambda self: self.env.ref("adera_core.analytic_account_pratama_root", raise_if_not_found=False),
    )

    @api.depends("registered_participants", "rate_per_participant")
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = rec.registered_participants * rec.rate_per_participant

    def action_post_capitation(self):
        """Membukukan Pendapatan Kapitasi: Dr. Bank Penampung (111110) / Cr. Pendapatan Kapitasi BPJS (410040)."""
        self.ensure_one()
        if self.total_amount <= 0:
            raise UserError("Jumlah dana kapitasi harus lebih besar dari Rp 0.00!")

        bank_acc = self.bank_journal_id.default_account_id
        if not bank_acc:
            raise UserError(f"Akun default pada jurnal '{self.bank_journal_id.name}' belum dikonfigurasi!")

        analytic_dist = {str(self.analytic_account_id.id): 100.0} if self.analytic_account_id else False

        ref_desc = f"Dana Kapitasi BPJS FKTP {self.period_month}/{self.period_year} ({self.registered_participants:,} Peserta)"
        move_vals = {
            "journal_id": self.bank_journal_id.id,
            "date": self.recognition_date,
            "ref": ref_desc,
            "move_type": "entry",
            "line_ids": [
                (0, 0, {
                    "name": ref_desc,
                    "account_id": bank_acc.id,
                    "debit": self.total_amount,
                    "credit": 0.0,
                }),
                (0, 0, {
                    "name": ref_desc,
                    "account_id": self.income_account_id.id,
                    "debit": 0.0,
                    "credit": self.total_amount,
                    "analytic_distribution": analytic_dist,
                }),
            ],
        }

        move = self.env["account.move"].create(move_vals)
        move.action_post()

        return {
            "name": "Jurnal Pendapatan Kapitasi BPJS",
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": move.id,
            "view_mode": "form",
            "target": "current",
        }


class BpjsDisputeProvision(models.TransientModel):
    _name = "bpjs.dispute.provision"
    _description = "Pembentukan Cadangan Dispute & Penolakan Klaim BPJS (Contra-Asset 112990)"

    name = fields.Char(string="Nomor Berita Acara Rekon / SEP", required=True)
    date = fields.Date(string="Tanggal Pembentukan Cadangan", required=True, default=fields.Date.today)
    dispute_amount = fields.Monetary(string="Nominal Potensi Dispute (Rp)", required=True, currency_field="currency_id")
    reason = fields.Text(string="Alasan Dispute / Feedback Verifikator BPJS", required=True)

    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")

    expense_account_id = fields.Many2one(
        "account.account",
        string="Akun Beban Dispute / Penurunan Nilai",
        required=True,
        default=lambda self: self.env.ref("adera_core.account_619000", raise_if_not_found=False),
    )
    allowance_account_id = fields.Many2one(
        "account.account",
        string="Akun Cadangan Kerugian Klaim BPJS (Contra-Asset)",
        required=True,
        default=lambda self: self.env.ref("adera_core.account_112990", raise_if_not_found=False),
    )
    analytic_account_id = fields.Many2one(
        "account.analytic.account",
        string="Unit Bisnis Analitik",
        default=lambda self: self.env.ref("adera_core.analytic_account_hd_root", raise_if_not_found=False),
    )

    def action_post_provision(self):
        """Membukukan Cadangan Dispute BPJS: Dr. 619000 (Beban Dispute) / Cr. 112990 (Cadangan Penolakan)."""
        self.ensure_one()
        journal = self.env["account.journal"].search([("type", "=", "general")], limit=1)
        if not journal:
            raise UserError("Jurnal operasional umum belum tersedia!")

        analytic_dist = {str(self.analytic_account_id.id): 100.0} if self.analytic_account_id else False

        ref_desc = f"Cadangan Dispute Klaim BPJS: {self.name} - {self.reason[:60]}"
        move_vals = {
            "journal_id": journal.id,
            "date": self.date,
            "ref": ref_desc,
            "move_type": "entry",
            "line_ids": [
                (0, 0, {
                    "name": ref_desc,
                    "account_id": self.expense_account_id.id,
                    "debit": self.dispute_amount,
                    "credit": 0.0,
                    "analytic_distribution": analytic_dist,
                }),
                (0, 0, {
                    "name": ref_desc,
                    "account_id": self.allowance_account_id.id,
                    "debit": 0.0,
                    "credit": self.dispute_amount,
                }),
            ],
        }

        move = self.env["account.move"].create(move_vals)
        move.action_post()

        return {
            "name": "Jurnal Cadangan Dispute BPJS",
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": move.id,
            "view_mode": "form",
            "target": "current",
        }


class BpjsClaimDisputeWriteoff(models.TransientModel):
    _name = "bpjs.claim.dispute.writeoff"
    _description = "Rekonsiliasi & Penghapusan Piutang Dispute Klaim BPJS (Dr 112990 / Cr 112020)"

    name = fields.Char(string="Nomor Berita Acara Rekonsiliasi", required=True, default=lambda self: f"REKON-BPJS-{fields.Date.today().strftime('%Y%m')}")
    sep_number = fields.Char(string="Nomor SEP Klaim BPJS", required=True, help="Nomor Surat Eligibilitas Peserta (SEP) yang disengketakan/dipotong")
    patient_name = fields.Char(string="Nama Pasien", help="Identitas pasien pemilik berkas klaim")
    date = fields.Date(string="Tanggal Rekonsiliasi / Pemotongan", required=True, default=fields.Date.today)
    writeoff_amount = fields.Monetary(string="Nominal Pemotongan Klaim (Rp)", required=True, currency_field="currency_id")

    dispute_category = fields.Selection(
        [
            ("coding_dispute", "Dispute Koding INA-CBG (Penurunan Tarif/Grouper)"),
            ("administrative", "Ketidaklengkapan Berkas / Resep / Resume Medis"),
            ("medical_audit", "Audit Pasca Bayar / Dispute Medis Tim Pencegahan Fraud"),
            ("claim_deduction", "Pemotongan Selisih Bayar / Denda Administrasi"),
            ("other", "Lainnya / Sengketa Berkas"),
        ],
        string="Kategori Dispute",
        default="coding_dispute",
        required=True,
    )
    reason = fields.Text(string="Keterangan Verifikator BPJS / Berita Acara", required=True)

    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")

    allowance_account_id = fields.Many2one(
        "account.account",
        string="Akun Cadangan Dispute BPJS (Dr 112990)",
        required=True,
        default=lambda self: self.env["account.account"].search([("code", "=", "112990")], limit=1),
    )
    bpjs_receivable_account_id = fields.Many2one(
        "account.account",
        string="Akun Piutang Klaim BPJS (Cr 112020)",
        required=True,
        default=lambda self: self.env["account.account"].search([("code", "=", "112020")], limit=1),
    )
    analytic_account_id = fields.Many2one(
        "account.analytic.account",
        string="Unit Bisnis Analitik",
        default=lambda self: self.env["account.analytic.account"].search([("code", "in", ["ACC-HD", "ACC-PRATAMA"])], limit=1),
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Jurnal Operasional",
        required=True,
        default=lambda self: self.env["account.journal"].search([("type", "=", "general")], limit=1),
    )

    def action_post_writeoff(self):
        """Membukukan Single-Click Write-off Dispute Klaim: Dr 112990 (Cadangan Dispute) / Cr 112020 (Piutang BPJS)."""
        self.ensure_one()
        if self.writeoff_amount <= 0:
            raise UserError("Nominal pemotongan klaim harus lebih besar dari Rp 0,00!")

        analytic_dist = {str(self.analytic_account_id.id): 100.0} if self.analytic_account_id else False
        cat_label = dict(self._fields["dispute_category"].selection).get(self.dispute_category, self.dispute_category)
        ref_desc = f"Write-off Dispute BPJS (SEP: {self.sep_number}) - {cat_label}"

        move_vals = {
            "journal_id": self.journal_id.id,
            "date": self.date,
            "ref": ref_desc,
            "move_type": "entry",
            "line_ids": [
                (0, 0, {
                    "name": f"Pengurangan Cadangan Dispute (SEP: {self.sep_number})",
                    "account_id": self.allowance_account_id.id,
                    "debit": self.writeoff_amount,
                    "credit": 0.0,
                    "analytic_distribution": analytic_dist,
                }),
                (0, 0, {
                    "name": f"Penyelesaian Piutang Klaim BPJS (SEP: {self.sep_number} - {self.patient_name or ''})",
                    "account_id": self.bpjs_receivable_account_id.id,
                    "debit": 0.0,
                    "credit": self.writeoff_amount,
                }),
            ],
        }

        move = self.env["account.move"].create(move_vals)
        move.action_post()

        return {
            "name": "Jurnal Write-Off Dispute Klaim BPJS",
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": move.id,
            "view_mode": "form",
            "target": "current",
        }


class ClinicPrepaidDialysisPackage(models.Model):
    _name = "clinic.prepaid.dialysis.package"
    _description = "Pengelolaan Deposit & Voucher Paket Terapi Hemodialisis (PSAK 72)"
    _order = "purchase_date desc, id desc"

    name = fields.Char(string="Nomor Voucher Paket", required=True, copy=False, default="/")
    partner_id = fields.Many2one("res.partner", string="Pasien", required=True)
    purchase_date = fields.Date(string="Tanggal Pembelian Paket", required=True, default=fields.Date.today)
    package_type = fields.Selection(
        [
            ("hd_5", "Paket Hemodialisis 5x Terapi"),
            ("hd_10", "Paket Hemodialisis 10x Terapi"),
            ("hd_vip_5", "Paket Hemodialisis VIP 5x Terapi"),
        ],
        string="Jenis Paket Terapi",
        required=True,
        default="hd_10",
    )

    total_sessions = fields.Integer(string="Total Sesi Terapi", required=True, default=10)
    sessions_used = fields.Integer(string="Sesi Terpakai", default=0, readonly=True)
    sessions_remaining = fields.Integer(string="Sisa Sesi Terapi", compute="_compute_remaining_sessions", store=True)

    package_price = fields.Monetary(string="Harga Total Paket (Rp)", required=True, currency_field="currency_id")
    price_per_session = fields.Monetary(string="Harga per Sesi Terapi", compute="_compute_session_price", store=True, currency_field="currency_id")

    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id")

    deferred_revenue_account_id = fields.Many2one(
        "account.account",
        string="Akun Pendapatan Diterima Dimuka (PSAK 72)",
        required=True,
        default=lambda self: self.env.ref("adera_core.account_214020", raise_if_not_found=False),
    )
    earned_income_account_id = fields.Many2one(
        "account.account",
        string="Akun Pendapatan Terakui (Earned)",
        required=True,
        default=lambda self: self.env.ref("adera_core.account_410120", raise_if_not_found=False),
    )
    payment_journal_id = fields.Many2one("account.journal", string="Jurnal Pembayaran Kasir", required=True)

    state = fields.Selection(
        [
            ("draft", "Draf"),
            ("active", "Aktif (Uang Diterima Dimuka)"),
            ("depleted", "Tuntas (Semua Sesi Ditebus)"),
            ("cancelled", "Dibatalkan / Refund"),
        ],
        string="Status Paket",
        default="draft",
        required=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = f"PKT-HD-{fields.Date.today().strftime('%Y%m')}-{self.env['ir.sequence'].next_by_code('clinic.prepaid.package') or '001'}"
        return super(ClinicPrepaidDialysisPackage, self).create(vals_list)

    @api.depends("total_sessions", "sessions_used")
    def _compute_remaining_sessions(self):
        for rec in self:
            rec.sessions_remaining = rec.total_sessions - rec.sessions_used

    @api.depends("package_price", "total_sessions")
    def _compute_session_price(self):
        for rec in self:
            rec.price_per_session = rec.package_price / rec.total_sessions if rec.total_sessions > 0 else 0.0

    def action_confirm_payment(self):
        """Saat pembayaran diterima: Dr. Kas/Bank (111020/111110) / Cr. Liabilitas Kontrak 214020."""
        self.ensure_one()
        cash_bank_acc = self.payment_journal_id.default_account_id
        if not cash_bank_acc:
            raise UserError("Akun default pada jurnal pembayaran belum dikonfigurasi!")

        ref_desc = f"Penerimaan Paket Dialisis PSAK 72: {self.name} - {self.partner_id.name}"
        move_vals = {
            "journal_id": self.payment_journal_id.id,
            "date": self.purchase_date,
            "ref": ref_desc,
            "move_type": "entry",
            "line_ids": [
                (0, 0, {
                    "name": ref_desc,
                    "account_id": cash_bank_acc.id,
                    "debit": self.package_price,
                    "credit": 0.0,
                }),
                (0, 0, {
                    "name": ref_desc,
                    "account_id": self.deferred_revenue_account_id.id,
                    "debit": 0.0,
                    "credit": self.package_price,
                }),
            ],
        }

        move = self.env["account.move"].create(move_vals)
        move.action_post()
        self.write({"state": "active"})

    def action_redeem_single_session(self):
        """Saat pasien menjalani 1 sesi terapi: Dr. 214020 / Cr. 410120."""
        self.ensure_one()
        if self.sessions_remaining <= 0:
            raise UserError("Semua kuota sesi pada paket ini telah habis digunakan!")

        journal = self.env["account.journal"].search([("type", "=", "general")], limit=1)
        analytic_hd = self.env.ref("adera_core.analytic_account_hd_treat", raise_if_not_found=False)
        analytic_dist = {str(analytic_hd.id): 100.0} if analytic_hd else False

        ref_desc = f"Penebusan Sesi HD ({self.sessions_used + 1}/{self.total_sessions}) - {self.name} - {self.partner_id.name}"
        move_vals = {
            "journal_id": journal.id,
            "date": fields.Date.today(),
            "ref": ref_desc,
            "move_type": "entry",
            "line_ids": [
                (0, 0, {
                    "name": ref_desc,
                    "account_id": self.deferred_revenue_account_id.id,
                    "debit": self.price_per_session,
                    "credit": 0.0,
                }),
                (0, 0, {
                    "name": ref_desc,
                    "account_id": self.earned_income_account_id.id,
                    "debit": 0.0,
                    "credit": self.price_per_session,
                    "analytic_distribution": analytic_dist,
                }),
            ],
        }

        move = self.env["account.move"].create(move_vals)
        move.action_post()

        new_used = self.sessions_used + 1
        new_state = "depleted" if new_used >= self.total_sessions else "active"
        self.write({"sessions_used": new_used, "state": new_state})

