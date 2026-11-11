# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)


class ClinicSharedCostAllocation(models.Model):
    _name = "clinic.shared_cost.allocation"
    _description = "Alokasi Biaya Bersama Holding PT Prosperra Medika Utama"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "period_end desc, id desc"

    name = fields.Char(
        string="Nomor Referensi Alokasi",
        required=True,
        copy=False,
        readonly=True,
        default="/",
    )
    period_start = fields.Date(
        string="Periode Awal",
        required=True,
        default=lambda self: fields.Date.context_today(self).replace(day=1),
    )
    period_end = fields.Date(
        string="Periode Akhir",
        required=True,
        default=fields.Date.context_today,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Entitas Legal",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        string="Mata Uang",
    )

    holding_expense_account_ids = fields.Many2many(
        "account.account",
        string="Akun Beban Operasional Holding (Pool)",
        domain="[('account_type', '=', 'expense'), ('code_store', '=like', '%61%')]",
        help="Akun-akun beban operasional kantor pusat (610010–619990) yang dialokasikan ke cabang",
    )

    total_holding_pool = fields.Monetary(
        string="Total Beban Holding Terhimpun",
        compute="_compute_total_holding_pool",
        store=True,
        readonly=False,
        currency_field="currency_id",
        tracking=True,
    )

    allocation_basis = fields.Selection(
        [
            ("revenue_ratio", "Proporsional Pendapatan Usaha (Gross Revenue Ratio)"),
            ("fixed_split", "Persentase Tetap (Custom Fixed Split)"),
            ("headcount_ratio", "Rasio Jumlah SDM & Tenaga Medis (Headcount)"),
        ],
        string="Dasar Alokasi Biaya",
        default="revenue_ratio",
        required=True,
        tracking=True,
    )

    pratama_share_pct = fields.Float(
        string="Porsi Pratama (%)",
        default=50.0,
        digits=(5, 2),
    )
    hd_share_pct = fields.Float(
        string="Porsi Hemodialisis (%)",
        default=50.0,
        digits=(5, 2),
    )

    allocated_amount_pratama = fields.Monetary(
        string="Beban Dialokasikan ke Pratama",
        compute="_compute_allocation_shares",
        store=True,
        currency_field="currency_id",
    )
    allocated_amount_hd = fields.Monetary(
        string="Beban Dialokasikan ke Hemodialisis",
        compute="_compute_allocation_shares",
        store=True,
        currency_field="currency_id",
    )

    account_move_id = fields.Many2one(
        "account.move",
        string="Entri Jurnal Alokasi Biaya",
        readonly=True,
        copy=False,
    )
    state = fields.Selection(
        [
            ("draft", "Draf"),
            ("calculated", "Terkalkulasi"),
            ("posted", "Selesai Dialokasikan"),
            ("cancelled", "Dibatalkan"),
        ],
        string="Status",
        default="draft",
        tracking=True,
    )

    notes = fields.Text(string="Catatan Audit / Justifikasi Alokasi")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("clinic.shared_cost.allocation") or "/"
        return super(ClinicSharedCostAllocation, self).create(vals_list)

    @api.depends("period_start", "period_end", "holding_expense_account_ids")
    def _compute_total_holding_pool(self):
        for rec in self:
            if not rec.period_start or not rec.period_end:
                rec.total_holding_pool = 0.0
                continue

            holding_acc = self.env.ref("adera_core.analytic_acc_holding", raise_if_not_found=False) or self.env.ref("adera_core.analytic_account_holding_root", raise_if_not_found=False)
            domain = [
                ("move_id.state", "=", "posted"),
                ("date", ">=", rec.period_start),
                ("date", "<=", rec.period_end),
                ("account_id.account_type", "=", "expense"),
            ]
            if rec.holding_expense_account_ids:
                domain.append(("account_id", "in", rec.holding_expense_account_ids.ids))
            else:
                # Default 61xxxx excluding clearing accounts 619980-619982
                domain.append(("account_id.code_store", "=like", "%61%"))

            lines = self.env["account.move.line"].search(domain)
            # Filter tagged ACC-HOLDING
            if holding_acc:
                holding_tag = str(holding_acc.id)
                lines = lines.filtered(
                    lambda l: l.analytic_distribution and holding_tag in l.analytic_distribution and not l.account_id.code_store.startswith("61998")
                )

            total_pool = sum(lines.mapped("debit")) - sum(lines.mapped("credit"))
            rec.total_holding_pool = max(0.0, total_pool)

    @api.depends("total_holding_pool", "allocation_basis", "pratama_share_pct", "hd_share_pct", "period_start", "period_end")
    def _compute_allocation_shares(self):
        for rec in self:
            if rec.total_holding_pool <= 0:
                rec.allocated_amount_pratama = 0.0
                rec.allocated_amount_hd = 0.0
                continue

            if rec.allocation_basis == "revenue_ratio":
                # Compute revenue of Pratama vs HD in the period
                pratama_acc = self.env.ref("adera_core.analytic_acc_pratama", raise_if_not_found=False) or self.env.ref("adera_core.analytic_account_pratama_root", raise_if_not_found=False)
                hd_acc = self.env.ref("adera_core.analytic_acc_hd", raise_if_not_found=False) or self.env.ref("adera_core.analytic_account_hd_root", raise_if_not_found=False)

                rev_lines = self.env["account.move.line"].search([
                    ("move_id.state", "=", "posted"),
                    ("date", ">=", rec.period_start),
                    ("date", "<=", rec.period_end),
                    ("account_id.account_type", "=", "income"),
                ])

                rev_pratama = 0.0
                rev_hd = 0.0
                for l in rev_lines:
                    dist = l.analytic_distribution or {}
                    credit_net = l.credit - l.debit
                    if pratama_acc and str(pratama_acc.id) in dist:
                        rev_pratama += credit_net
                    elif hd_acc and str(hd_acc.id) in dist:
                        rev_hd += credit_net

                total_rev = rev_pratama + rev_hd
                if total_rev > 0:
                    pct_p = (rev_pratama / total_rev) * 100.0
                    pct_h = 100.0 - pct_p
                    rec.pratama_share_pct = round(pct_p, 2)
                    rec.hd_share_pct = round(pct_h, 2)
                else:
                    rec.pratama_share_pct = 50.0
                    rec.hd_share_pct = 50.0

            amt_pratama = round(rec.total_holding_pool * (rec.pratama_share_pct / 100.0), 2)
            amt_hd = round(rec.total_holding_pool - amt_pratama, 2)
            rec.allocated_amount_pratama = amt_pratama
            rec.allocated_amount_hd = amt_hd

    def action_calculate(self):
        self._compute_total_holding_pool()
        self._compute_allocation_shares()
        self.state = "calculated"

    def action_execute_allocation(self):
        """Generates internal journal entry in MISCL:
        Credit: 619980 (Alokasi Biaya Bersama Holding) with ACC-HOLDING
        Debit: 619981 (Beban Alokasi Manajemen Holding - Pratama) with ACC-PRATAMA
        Debit: 619982 (Beban Alokasi Manajemen Holding - HD) with ACC-HD
        Net consolidated P&L impact = Rp 0.00
        """
        self.ensure_one()
        if self.total_holding_pool <= 0:
            raise UserError(_("Total beban holding pool bernilai Rp 0.00. Tidak ada beban yang perlu dialokasikan."))

        journal = self.env["account.journal"].search([("type", "=", "general")], limit=1)
        if not journal:
            journal = self.env.ref("adera_core.journal_misc", raise_if_not_found=False)
        if not journal:
            raise UserError(_("Jurnal Umum (MISCL) tidak ditemukan."))

        acc_clearing = self.env.ref("adera_core.account_619980", raise_if_not_found=False)
        acc_pratama = self.env.ref("adera_core.account_619981", raise_if_not_found=False)
        acc_hd = self.env.ref("adera_core.account_619982", raise_if_not_found=False)

        if not acc_clearing or not acc_pratama or not acc_hd:
            raise UserError(_("Akun alokasi biaya bersama (619980, 619981, 619982) belum terkonfigurasi di Chart of Accounts."))

        analytic_holding = self.env.ref("adera_core.analytic_acc_holding", raise_if_not_found=False) or self.env.ref("adera_core.analytic_account_holding_root", raise_if_not_found=False)
        analytic_pratama = self.env.ref("adera_core.analytic_acc_pratama", raise_if_not_found=False) or self.env.ref("adera_core.analytic_account_pratama_root", raise_if_not_found=False)
        analytic_hd = self.env.ref("adera_core.analytic_acc_hd", raise_if_not_found=False) or self.env.ref("adera_core.analytic_account_hd_root", raise_if_not_found=False)

        holding_dist = {str(analytic_holding.id): 100.0} if analytic_holding else False
        pratama_dist = {str(analytic_pratama.id): 100.0} if analytic_pratama else False
        hd_dist = {str(analytic_hd.id): 100.0} if analytic_hd else False

        lines = [
            # Credit: Holding Clearing Account
            (0, 0, {
                "name": f"Alokasi Biaya Bersama Holding ({self.name}): Pengalihan ke Cabang",
                "account_id": acc_clearing.id,
                "debit": 0.0,
                "credit": self.total_holding_pool,
                "analytic_distribution": holding_dist,
            }),
            # Debit: Pratama Shared Overhead
            (0, 0, {
                "name": f"Alokasi Biaya Holding ({self.name}): Beban Operasional Manajemen Pratama ({self.pratama_share_pct}%)",
                "account_id": acc_pratama.id,
                "debit": self.allocated_amount_pratama,
                "credit": 0.0,
                "analytic_distribution": pratama_dist,
            }),
            # Debit: HD Shared Overhead
            (0, 0, {
                "name": f"Alokasi Biaya Holding ({self.name}): Beban Operasional Manajemen Hemodialisis ({self.hd_share_pct}%)",
                "account_id": acc_hd.id,
                "debit": self.allocated_amount_hd,
                "credit": 0.0,
                "analytic_distribution": hd_dist,
            }),
        ]

        move = self.env["account.move"].create({
            "journal_id": journal.id,
            "date": self.period_end,
            "ref": f"Alokasi Biaya Bersama Holding {self.name} ({self.period_start} s/d {self.period_end})",
            "line_ids": lines,
        })
        move.action_post()

        self.write({
            "account_move_id": move.id,
            "state": "posted",
        })
        self.message_post(body=f"Alokasi Biaya Bersama Holding berhasil dieksekusi dengan entri jurnal {move.name}.")
        return True

    def action_cancel(self):
        for rec in self:
            if rec.account_move_id and rec.account_move_id.state == "posted":
                rec.account_move_id.button_draft()
                rec.account_move_id.button_cancel()
            rec.state = "cancelled"
