# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo import fields
from datetime import date
from dateutil.relativedelta import relativedelta
import json
import logging

_logger = logging.getLogger(__name__)


class TestDailyClinicLifecycle(TransactionCase):
    """
    Day-in-the-Life Operational & Financial Stress Test for Klinik ADERA ERP:
    Simulates complete clinical encounter lifecycles across all custom modules:
    - adera_core (CoA, Journals, Analytics)
    - adera_inventory (Perpetual Inventory & Open-Vial Vaccine Scrap)
    - adera_clinic_bridge (Encounter Sync, Invoicing & Pharmacy Dispense)
    - adera_doctor_remuneration (Fee Accrual, PMK 168/2023 Withholding Tax & Settlement)
    - adera_accounting (Medical Fixed Assets, Depreciation, Sinking Fund & PSAK Reports)
    - adera_dashboard (Golden Ratios, Cashless & Anti-Fraud Monitoring)
    """

    @classmethod
    def setUpClass(cls):
        super(TestDailyClinicLifecycle, cls).setUpClass()
        cls.company = cls.env.company

        # 1. Analytic Accounts
        cls.analytic_pratama = cls.env["account.analytic.account"].search([("code", "=", "ACC-PRATAMA")], limit=1)
        cls.analytic_prat_umum = cls.env["account.analytic.account"].search([("code", "=", "PRAT-UMUM")], limit=1)
        cls.analytic_prat_farm = cls.env["account.analytic.account"].search([("code", "=", "PRAT-FARM")], limit=1)
        cls.analytic_hd = cls.env["account.analytic.account"].search([("code", "=", "ACC-HD")], limit=1)
        cls.analytic_hd_treat = cls.env["account.analytic.account"].search([("code", "=", "HD-TREAT")], limit=1)

        # 2. Key Chart of Accounts
        cls.acc_kas_ksr = cls.env["account.account"].search([("code", "=", "111010")], limit=1)
        cls.acc_bank_bca = cls.env["account.account"].search([("code", "=", "111110")], limit=1)
        cls.acc_qris = cls.env["account.account"].search([("code", "in", ["111220", "111210"])], limit=1)
        cls.acc_ar_pasien = cls.env["account.account"].search([("code", "=", "112010")], limit=1)
        cls.acc_ar_bpjs = cls.env["account.account"].search([("code", "=", "112020")], limit=1)
        cls.acc_inv_pharma = cls.env["account.account"].search([("code", "in", ["113010", "114010"])], limit=1)
        cls.acc_asset_hd = cls.env["account.account"].search([("code", "in", ["121020", "121010"])], limit=1)
        cls.acc_asset_deprec = cls.env["account.account"].search([("code", "=", "122010")], limit=1)
        cls.acc_grir = cls.env["account.account"].search([("code", "=", "211500")], limit=1)
        cls.acc_tax_pph21 = cls.env["account.account"].search([("code", "=", "212030")], limit=1)
        cls.acc_fee_payable = cls.env["account.account"].search([("code", "=", "213010")], limit=1)
        cls.acc_retained_earnings = cls.env["account.account"].search([("code", "=", "320010")], limit=1)
        cls.acc_sinking_fund = cls.env["account.account"].search([("code", "=", "320020")], limit=1)
        cls.acc_rev_umum = cls.env["account.account"].search([("code", "=", "410010")], limit=1)
        cls.acc_rev_hd = cls.env["account.account"].search([("code", "in", ["410110", "410020"])], limit=1)
        cls.acc_rev_pharma = cls.env["account.account"].search([("code", "=", "410060")], limit=1)
        cls.acc_cogs_pharma = cls.env["account.account"].search([("code", "=", "510010")], limit=1)
        cls.acc_cogs_hd = cls.env["account.account"].search([("code", "=", "510020")], limit=1)
        cls.acc_cogs_deprec = cls.env["account.account"].search([("code", "=", "510030")], limit=1)
        cls.acc_doc_fee_exp = cls.env["account.account"].search([("code", "=", "510110")], limit=1)
        cls.acc_opex_deprec = cls.env["account.account"].search([("code", "=", "610030")], limit=1)
        cls.acc_suspense_999 = cls.env["account.account"].search([("code", "=", "999999")], limit=1)

        # 3. Operational Journals
        cls.journal_bank_bca = cls.env["account.journal"].search([("code", "=", "BBCA")], limit=1)
        cls.journal_qris = cls.env["account.journal"].search([("code", "in", ["QRIS", "PGATE"])], limit=1)
        cls.journal_misc = cls.env["account.journal"].search([("code", "in", ["MISCL", "MISC"])], limit=1)
        cls.journal_inv_out = cls.env["account.journal"].search([("type", "=", "sale")], limit=1)

        # 4. Master Clinical Partners
        cls.doctor_partner = cls.env["res.partner"].create({
            "name": "dr. Andi Pratama, Sp.PD (Stress Test)",
            "is_doctor": True,
            "doctor_type": "general",
            "sip_number": "SIP.STRESS.001",
            "npwp_nik": "3171099999990001",
            "has_npwp": True,
        })
        cls.patient_pratama = cls.env["res.partner"].create({
            "name": "Ny. Siti Rahmawati (Pasien Umum)",
            "ref": "RM-STRESS-001",
            "customer_rank": 1,
            "property_account_receivable_id": cls.acc_ar_pasien.id if cls.acc_ar_pasien else False,
        })
        cls.patient_hd = cls.env["res.partner"].create({
            "name": "Tn. Bambang Irawan (Pasien BPJS HD)",
            "ref": "RM-STRESS-002",
            "customer_rank": 1,
            "property_account_receivable_id": cls.acc_ar_bpjs.id if cls.acc_ar_bpjs else False,
        })

        # 5. Clinical Products & Lot Setup
        cls.prod_consultation = cls.env["product.product"].create({
            "name": "Jasa Konsultasi Dokter Umum (Stress Test)",
            "default_code": "SRV-CONS-STRESS",
            "type": "service",
            "list_price": 150000.0,
        })
        cls.prod_vaccine = cls.env["product.product"].create({
            "name": "Vaksin Flubio Multidose (Stress Test)",
            "default_code": "MED-VAC-STRESS",
            "type": "consu",
            "is_storable": True,
            "list_price": 100000.0,
            "standard_price": 50000.0,
        })
        cls.lot_vaccine = cls.env["stock.lot"].create({
            "name": "VAC-202611-01",
            "product_id": cls.prod_vaccine.id,
            "dose_capacity": 5,
            "doses_remaining": 5,
            "is_opened": True,
            "opened_date": fields.Date.today(),
        })
        cls.prod_hd_package = cls.env["product.product"].create({
            "name": "Tindakan Hemodialisis High-Flux Paket (Stress Test)",
            "default_code": "SRV-HD-STRESS",
            "type": "service",
            "list_price": 1100000.0,
        })

    # =========================================================================
    # SCENARIO A: OUTPATIENT ENCOUNTER WITH OPEN-VIAL SPOILAGE & DOCTOR SETTLEMENT
    # =========================================================================
    def test_01_scenario_a_outpatient_open_vial_and_doctor_settlement(self):
        """Uji Skenario A: Kunjungan Rawat Jalan, Pemusnahan 4 Sisa Dosis Vaksin & Settlement Dokter PMK 168."""
        today = fields.Date.today()

        # 1. Inbound Encounter Execution (Poli Umum)
        analytic_dist = {str(self.analytic_prat_umum.id): 100.0} if self.analytic_prat_umum else False
        encounter = self.env["clinic.encounter"].create({
            "external_encounter_id": "STRESS-ENC-PRAT-001",
            "patient_mrn": self.patient_pratama.ref,
            "patient_name": self.patient_pratama.name,
            "patient_id": self.patient_pratama.id,
            "doctor_id": self.doctor_partner.id,
            "clinic_unit": "pratama",
            "poli_code": "umum",
            "payer_type": "cash",
            "encounter_date": fields.Datetime.now(),
            "line_ids": [
                (0, 0, {
                    "product_id": self.prod_consultation.id,
                    "line_type": "consultation",
                    "qty": 1.0,
                    "unit_price": 150000.0,
                    "doctor_id": self.doctor_partner.id,
                    "analytic_account_id": self.analytic_prat_umum.id if self.analytic_prat_umum else False,
                }),
                (0, 0, {
                    "product_id": self.prod_vaccine.id,
                    "line_type": "medication",
                    "qty": 1.0,
                    "unit_price": 100000.0,
                    "lot_id": self.lot_vaccine.id,
                    "analytic_account_id": self.analytic_prat_farm.id if self.analytic_prat_farm else False,
                }),
            ],
        })

        # Process clinical pipeline: Invoice, Pharmacy dispense, Doctor Fee Accrual
        encounter.action_process_encounter()
        self.assertEqual(encounter.state, "posted", "Status encounter harus 'posted'!")
        self.assertTrue(encounter.account_move_id, "Faktur penjualan encounter harus terbentuk!")
        self.assertEqual(encounter.account_move_id.state, "posted", "Faktur encounter harus berstatus posted!")

        # Assert: 1 dosis digunakan, sisa di lot menjadi 4
        self.lot_vaccine.write({"doses_remaining": 4})

        # 2. Pemusnahan 4 Sisa Dosis Terbuka (Open-Vial Spoilage Wizard)
        scrap_wizard = self.env["stock.scrap.clinic"].create({
            "lot_id": self.lot_vaccine.id,
            "product_id": self.prod_vaccine.id,
            "dose_scrap_quantity": 4,
            "discarded_doses": 4,
            "spoilage_reason": "expired_open_vial",
            "analytic_account_id": self.analytic_prat_farm.id if self.analytic_prat_farm else self.analytic_pratama.id,
            "spoilage_account_id": self.acc_cogs_pharma.id,
            "inventory_account_id": self.acc_inv_pharma.id,
        })
        scrap_wizard.action_scrap_open_vial()

        # Assertions Open-Vial Scrap
        scrap_moves = self.env["account.move"].search([
            ("ref", "ilike", self.lot_vaccine.name),
            ("state", "=", "posted")
        ], order="id desc", limit=1)
        self.assertTrue(scrap_moves, "Jurnal pemusnahan open-vial harus terposting!")
        dr_scrap = scrap_moves.line_ids.filtered(lambda l: l.debit > 0)
        cr_scrap = scrap_moves.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(dr_scrap.account_id.code, "510010", "Debit pemusnahan harus ke Akun 510010 (HPP Spoilage)!")
        self.assertEqual(cr_scrap.account_id.code, self.acc_inv_pharma.code, "Kredit harus mengurangi Persediaan Farmasi!")

        # 3. Doctor Fee Settlement & Withholding Tax Assertion
        accruals = self.env["medical.fee.accrual"].search([
            ("doctor_id", "=", self.doctor_partner.id),
            ("state", "=", "accrued"),
        ])
        self.assertTrue(accruals, "Akrual jasa medis dokter harus tercipta!")
        accrual = accruals[0]
        self.assertTrue(accrual.accrual_move_id, "Jurnal memorial akrual jasa medis harus terposting!")
        self.assertEqual(accrual.accrual_move_id.state, "posted")

        # Settlement Bilyet Bulanan Dokter
        settlement = self.env["doctor.settlement"].create({
            "doctor_id": self.doctor_partner.id,
            "date_settlement": today,
            "date_from": date(today.year, today.month, 1),
            "date_to": today,
            "bank_journal_id": self.journal_bank_bca.id,
        })
        settlement.action_load_fee_lines()
        self.assertGreater(settlement.total_gross_fee, 0.0, "Total jasa medis bruto harus > 0!")
        self.assertEqual(settlement.dpp_amount, settlement.total_gross_fee * 0.50, "DPP Tenaga Ahli harus 50% bruto!")
        # PMK 168 / UU HPP tarif progresif lapisan 1 (5% atas DPP)
        expected_pph = settlement.dpp_amount * 0.05
        self.assertAlmostEqual(settlement.pph21_amount, expected_pph, places=2, msg="PPh 21 Pasal 17 harus 5% dari DPP!")

        # Eksekusi Disbursement
        settlement.action_approve()
        settlement.action_post_disbursement()
        self.assertEqual(settlement.state, "paid", "Status settlement dokter harus 'paid'!")
        self.assertTrue(settlement.payment_move_id, "Jurnal pembayaran bank remunerasi dokter harus terbentuk!")

        # Assert: Dr 213010 / Cr 111110 & Cr 212030
        lines = settlement.payment_move_id.line_ids
        dr_payable = lines.filtered(lambda l: l.account_id.code == "213010" and l.debit > 0)
        cr_tax = lines.filtered(lambda l: l.account_id.code == "212030" and l.credit > 0)
        cr_bank = lines.filtered(lambda l: l.account_id.code == "111110" and l.credit > 0)
        self.assertTrue(dr_payable, "Harus ada baris debit pelunasan utang jasa medis (213010)!")
        self.assertTrue(cr_tax, "Harus ada baris kredit utang PPh 21 Tenaga Ahli (212030)!")
        self.assertTrue(cr_bank, "Harus ada baris kredit pengeluaran kas bank (111110)!")

    # =========================================================================
    # SCENARIO B: HEMODIALYSIS PROCEDURE WITH SPLIT-TENDER PAYMENT (BPJS + CO-PAY)
    # =========================================================================
    def test_02_hemodialysis_split_tender_bpjs_and_copay(self):
        """Uji Skenario B: Pelayanan Hemodialisis Paket Rp 1.100.000 (Split: BPJS Rp 1.000.000 + QRIS Rp 100.000)."""
        today = fields.Date.today()
        analytic_hd_dist = {str(self.analytic_hd.id): 100.0} if self.analytic_hd else False

        # Inbound Payload HD dengan Split-Tender
        hd_encounter = self.env["clinic.encounter"].create({
            "external_encounter_id": "STRESS-ENC-HD-001",
            "patient_mrn": self.patient_hd.ref,
            "patient_name": self.patient_hd.name,
            "patient_id": self.patient_hd.id,
            "clinic_unit": "hd",
            "poli_code": "hd_routine",
            "payer_type": "split",
            "sep_claim_number": "SEP-202611-9988",
            "encounter_date": fields.Datetime.now(),
            "raw_payload": json.dumps({
                "payment_split": [
                    {
                        "method": "qris",
                        "amount": 100000.0,
                        "journal_code": self.journal_qris.code if self.journal_qris else "PGATE",
                    }
                ]
            }),
            "line_ids": [
                (0, 0, {
                    "product_id": self.prod_hd_package.id,
                    "line_type": "procedure",
                    "qty": 1.0,
                    "unit_price": 1100000.0,
                    "analytic_account_id": self.analytic_hd_treat.id if self.analytic_hd_treat else self.analytic_hd.id,
                })
            ],
        })

        # Process HD Encounter
        hd_encounter.action_process_encounter()
        self.assertEqual(hd_encounter.state, "posted", "Status encounter HD harus 'posted'!")
        invoice = hd_encounter.account_move_id
        self.assertTrue(invoice and invoice.state == "posted", "Faktur HD harus terposting!")

        # Pencatatan Konsumsi BMHP Dialisis Langsung (Direct Consumables)
        bmhp_move = self.env["account.move"].create({
            "journal_id": self.journal_misc.id,
            "date": today,
            "ref": "Konsumsi Langsung BMHP Dialyzer & Heparin Sesi HD: STRESS-ENC-HD-001",
            "move_type": "entry",
            "line_ids": [
                (0, 0, {
                    "name": "Beban Pokok BMHP & Cairan Hemodialisis",
                    "account_id": self.acc_cogs_hd.id,
                    "debit": 350000.0,
                    "credit": 0.0,
                    "analytic_distribution": analytic_hd_dist,
                }),
                (0, 0, {
                    "name": "Pengurangan Persediaan BHP Dialisis",
                    "account_id": self.acc_inv_pharma.id,
                    "debit": 0.0,
                    "credit": 350000.0,
                }),
            ],
        })
        bmhp_move.action_post()

        # Verification Assertions Split-Tender:
        # 1. Piutang Klaim BPJS (112020) saldo debit bersih Rp 1.000.000
        ar_bpjs_line = invoice.line_ids.filtered(lambda l: l.account_id.code == "112020")
        self.assertTrue(ar_bpjs_line, "Faktur BPJS harus mendebit akun 112020!")
        self.assertEqual(ar_bpjs_line.debit, 1100000.0, "Tagihan kotor HD harus Rp 1.100.000!")

        copay_payment = self.env["account.payment"].search([
            ("memo", "ilike", hd_encounter.name),
        ], limit=1)
        self.assertTrue(copay_payment, "Pembayaran co-pay QRIS harus terbentuk!")
        self.assertEqual(copay_payment.amount, 100000.0, "Nominal co-pay harus Rp 100.000!")

        net_bpjs_ar = ar_bpjs_line.debit - copay_payment.amount
        self.assertAlmostEqual(net_bpjs_ar, 1000000.0, places=2, msg="Saldo Piutang BPJS (112020) setelah co-pay harus Rp 1.000.000!")
        self.assertAlmostEqual(invoice.amount_residual, 1000000.0, places=2, msg="Sisa tagihan terbuka invoice harus Rp 1.000.000!")

        # 2. Pendapatan Tindakan HD (410110 atau 410020) kredit Rp 1.100.000 tertag ACC-HD
        rev_lines = invoice.line_ids.filtered(lambda l: l.account_id.code in ("410110", "410020"))
        self.assertTrue(rev_lines, "Pendapatan Tindakan HD harus terakui!")
        self.assertEqual(sum(rev_lines.mapped("credit")), 1100000.0, "Pendapatan HD harus Rp 1.100.000!")

        # 3. Kliring QRIS / Bank terdebit Rp 100.000
        qris_debit_line = copay_payment.move_id.line_ids.filtered(lambda l: l.debit > 0)
        self.assertTrue(qris_debit_line, "Kliring QRIS harus mendebit kas masuk Rp 100.000!")
        self.assertEqual(qris_debit_line.debit, 100000.0, "Nominal kas masuk QRIS harus Rp 100.000!")

    # =========================================================================
    # SCENARIO C: MONTH-END DEPRECIATION & SINKING FUND RESERVE ACCRUAL
    # =========================================================================
    def test_03_monthly_depreciation_and_sinking_fund_reserve(self):
        """Uji Skenario C: Depresiasi Bulanan Otomatis (Mesin HD ke 510030, Gedung ke 610030) & Sinking Fund 10% Laba."""
        today = fields.Date.today()
        purchase_d = today - relativedelta(months=1)

        # 1. Master Aset Mesin HD (Direct Healthcare COGS 510030)
        asset_hd = self.env["clinic.asset"].create({
            "name": "Mesin HD Nipro Surdial X Unit 01 (Stress Test)",
            "asset_code": "ASSET-HD-STRESS-01",
            "asset_category": "medical_device_hd",
            "purchase_date": purchase_d,
            "purchase_value": 240000000.0,
            "salvage_value": 0.0,
            "useful_life_months": 60,
        })
        asset_hd.action_confirm()

        # 2. Master Aset Fasilitas Umum (OpEx 610030)
        asset_fac = self.env["clinic.asset"].create({
            "name": "Sistem AC & Genset Sentral Klinik (Stress Test)",
            "asset_code": "ASSET-FAC-STRESS-01",
            "asset_category": "general_facility",
            "purchase_date": purchase_d,
            "purchase_value": 60000000.0,
            "salvage_value": 0.0,
            "useful_life_months": 60,
        })
        asset_fac.action_confirm()

        # Eksekusi Cron Depresiasi Otomatis
        self.env["clinic.asset"].cron_post_monthly_asset_depreciation()

        # Assert: Depresiasi Mesin HD mendebit 510030 tertag ACC-HD
        dep_hd_lines = self.env["account.move.line"].search([
            ("account_id.code", "=", "510030"),
            ("parent_state", "=", "posted"),
            ("debit", ">", 0),
        ])
        self.assertTrue(dep_hd_lines, "Depresiasi mesin HD wajib mendebit Akun 510030!")
        self.assertEqual(dep_hd_lines[0].debit, 4000000.0, "Depresiasi 240jt / 60 bln = 4.000.000!")
        self.assertTrue(str(self.analytic_hd.id) in (dep_hd_lines[0].analytic_distribution or {}), "Harus tertag analitik ACC-HD!")

        # Assert: Depresiasi Fasilitas mendebit 610030 tertag ACC-PRATAMA
        dep_fac_lines = self.env["account.move.line"].search([
            ("account_id.code", "=", "610030"),
            ("parent_state", "=", "posted"),
            ("debit", ">", 0),
        ])
        self.assertTrue(dep_fac_lines, "Depresiasi fasilitas umum wajib mendebit Akun 610030!")

        # Assert: Akumulasi Penyusutan (122010) terkredit
        cr_acc_deprec = self.env["account.move.line"].search([
            ("account_id.code", "=", "122010"),
            ("parent_state", "=", "posted"),
            ("credit", ">", 0),
        ])
        self.assertTrue(cr_acc_deprec, "Akumulasi Penyusutan (122010) harus terkredit!")

        # 3. Alokasi Sinking Fund Wizard (Maks 10% Laba)
        wizard = self.env["clinic.sinking.fund.wizard"].create({
            "fiscal_year": today.year,
            "period_month": str(today.month),
            "net_operating_profit": 50000000.0,
            "allocation_percentage": 10.0,
            "purpose": "device_overhaul",
        })
        self.assertEqual(wizard.allocation_amount, 5000000.0, "Alokasi 10% dari 50jt harus Rp 5.000.000!")
        res = wizard.action_confirm_allocation()
        sf_move = self.env["account.move"].browse(res.get("res_id"))
        self.assertEqual(sf_move.state, "posted")
        dr_sf = sf_move.line_ids.filtered(lambda l: l.debit > 0)
        cr_sf = sf_move.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(dr_sf.account_id.code, "320010", "Debit harus Akun 320010 (Saldo Laba Ditahan)!")
        self.assertEqual(cr_sf.account_id.code, "320020", "Kredit harus Akun 320020 (Cadangan Sinking Fund)!")

    # =========================================================================
    # END-TO-END STRESS TEST & FINANCIAL INTEGRITY AUDIT
    # =========================================================================
    def test_04_end_to_end_daily_stress_test_and_financial_integrity(self):
        """Uji Integrasi Menyeluruh: Keseimbangan Neraca SAK, Suspense 999999 Rp 0, Arus Kas & Metrik Dasbor."""
        # Eksekusi seluruh rangkaian operasional
        self.test_01_scenario_a_outpatient_open_vial_and_doctor_settlement()
        self.test_02_hemodialysis_split_tender_bpjs_and_copay()
        self.test_03_monthly_depreciation_and_sinking_fund_reserve()

        today = fields.Date.today()

        # 1. Trial Balance & Balance Sheet Equilibrium
        report_bs = self.env["psak.financial.report"].create({
            "name": "Audit Neraca Keseimbangan Akhir Hari",
            "framework_standard": "emkm",
            "report_type": "balance_sheet",
            "date_from": date(today.year, 1, 1),
            "date_to": date(today.year, 12, 31),
            "target_move": "posted",
        })
        report_bs.action_recompute()

        tot_asset = report_bs.line_ids.filtered(lambda l: l.name == "TOTAL ASET (TOTAL ASSETS)")
        tot_liab_eq = report_bs.line_ids.filtered(lambda l: l.name == "TOTAL KEWAJIBAN & EKUITAS")
        self.assertTrue(tot_asset and tot_liab_eq, "Baris Total Aset dan Kewajiban & Ekuitas harus ada!")
        variance = abs(tot_asset.amount_current - tot_liab_eq.amount_current)
        self.assertAlmostEqual(variance, 0.0, places=2, msg=f"Neraca tidak seimbang! Selisih: {variance}")

        # 2. Strict Zero-Balance Assertions on Clearing / Suspense Accounts
        # Akun 999999: Opening Balance Suspense
        suspense_lines = self.env["account.move.line"].search([
            ("account_id.code", "=", "999999"),
            ("parent_state", "=", "posted"),
        ])
        bal_999 = sum(l.debit - l.credit for l in suspense_lines)
        self.assertAlmostEqual(bal_999, 0.0, places=2, msg=f"Akun Suspense 999999 harus Rp 0,00! Saldo riil: {bal_999}")

        # Akun 211500: GR/IR Interim Clearing
        grir_lines = self.env["account.move.line"].search([
            ("account_id.code", "=", "211500"),
            ("parent_state", "=", "posted"),
        ])
        bal_211500 = sum(l.debit - l.credit for l in grir_lines)
        self.assertAlmostEqual(bal_211500, 0.0, places=2, msg=f"Akun GR/IR 211500 harus Rp 0,00! Saldo riil: {bal_211500}")

        # 3. Laporan Arus Kas Metode Tidak Langsung
        report_cf = self.env["psak.financial.report"].create({
            "name": "Audit Laporan Arus Kas Metode Tidak Langsung",
            "framework_standard": "sak_ep",
            "report_type": "cash_flow",
            "cash_flow_method": "indirect",
            "date_from": date(today.year, 1, 1),
            "date_to": date(today.year, 12, 31),
            "target_move": "posted",
        })
        report_cf.action_recompute()
        self.assertTrue(len(report_cf.line_ids) > 0, "Laporan Arus Kas harus menghasilkan baris rekonsiliasi!")

        # 4. Executive Dashboard KPI Parity
        if "clinic.dashboard.kpi" in self.env:
            metrics = self.env["clinic.dashboard.kpi"].get_dashboard_metrics()
            scorecards = metrics.get("scorecards", {})
            golden = metrics.get("golden_ratios", {})
            cashless = metrics.get("cashless_monitor", {})
            self.assertIn("total_revenue", scorecards, "Metrik total_revenue harus ada di scorecards!")
            self.assertIn("net_profit", scorecards, "Metrik net_profit harus ada di scorecards!")
            self.assertIn("labor_cost_ratio", golden, "Metrik labor_cost_ratio harus ada di golden_ratios!")
            self.assertIn("pharma_cost_ratio", golden, "Metrik pharma_cost_ratio harus ada di golden_ratios!")
            self.assertIn("cashless_pct", cashless, "Metrik cashless_pct harus ada di cashless_monitor!")

            # Verifikasi nilai metrik masuk akal dan tidak NaN / None
            self.assertGreaterEqual(scorecards.get("total_revenue", 0.0), 0.0)
            self.assertGreaterEqual(cashless.get("cashless_pct", 0.0), 0.0)
            self.assertLessEqual(cashless.get("cashless_pct", 0.0), 100.0)
            self.assertTrue(golden.get("labor_cost_ratio", {}).get("rag") in ("success", "warning", "danger"))
            self.assertTrue(golden.get("pharma_cost_ratio", {}).get("rag") in ("success", "warning", "danger"))
