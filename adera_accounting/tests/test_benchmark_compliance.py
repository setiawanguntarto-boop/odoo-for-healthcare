# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo import fields
from datetime import date


class TestBenchmarkCompliance(TransactionCase):
    """Test Suite asserting compliance with Indonesian Healthcare Accounting Benchmark:
       - SAK EMKM / SAK EP Balance Sheet Balancing
       - Multi-Unit Cost Center Analytic Isolation (Pratama vs HD)
       - PMK 168/2023 & UU HPP Progressive Withholding Tax Precision
       - Automated CaLK 5-Note Disclosure Generation
    """

    def setUp(self):
        super(TestBenchmarkCompliance, self).setUp()
        self.report_model = self.env["psak.financial.report"]
        self.settlement_model = self.env["doctor.settlement"]

        # References
        self.analytic_pratama = self.env.ref("adera_core.analytic_account_pratama_root", raise_if_not_found=False)
        self.analytic_hd = self.env.ref("adera_core.analytic_account_hd_root", raise_if_not_found=False)

    def test_01_balance_sheet_equilibrium(self):
        """Uji Keseimbangan Neraca: Total Aset = Total Liabilitas + Ekuitas (Selisih = Rp 0.00)."""
        report = self.report_model.create({
            "name": "Audit Neraca Keseimbangan SAK EMKM",
            "framework_standard": "emkm",
            "report_type": "balance_sheet",
            "date_from": date(2026, 1, 1),
            "date_to": date(2026, 12, 31),
            "target_move": "posted",
        })
        report.action_recompute()

        tot_asset_line = report.line_ids.filtered(lambda l: l.name == "TOTAL ASET (TOTAL ASSETS)")
        tot_liab_eq_line = report.line_ids.filtered(lambda l: l.name == "TOTAL KEWAJIBAN & EKUITAS")

        self.assertTrue(tot_asset_line, "Baris Total Aset harus ditemukan pada neraca!")
        self.assertTrue(tot_liab_eq_line, "Baris Total Kewajiban & Ekuitas harus ditemukan pada neraca!")

        diff = abs(tot_asset_line.amount_current - tot_liab_eq_line.amount_current)
        self.assertAlmostEqual(
            diff, 0.0, places=2,
            msg=f"Neraca tidak seimbang! Aset: {tot_asset_line.amount_current}, Liabilitas & Ekuitas: {tot_liab_eq_line.amount_current}, Selisih: {diff}"
        )

    def test_02_pmk_168_progressive_withholding_tax(self):
        """Uji Presisi Perhitungan PPh 21 Tenaga Ahli Dokter (PMK 168/2023 & UU HPP Pasal 17)."""
        dummy_settlement = self.settlement_model.new({})

        # Skenario 1: Dokter Ber-NPWP, Bruto Rp 100.000.000 (DPP 50% = Rp 50.000.000)
        # Lapisan 1 (0 - 60 jt) tarif 5%: 50.000.000 x 5% = Rp 2.500.000
        tax_1 = dummy_settlement._calculate_pph21_marginal(
            prior_dpp=0.0,
            total_cum_dpp=50000000.0,
            has_npwp=True,
        )
        self.assertEqual(tax_1, 2500000.0, f"Pajak skenario 1 salah: {tax_1} != 2.500.000")

        # Skenario 2: Dokter Tidak Ber-NPWP, Bruto Rp 100.000.000 (Penalti 120%)
        # Rp 2.500.000 x 1.20 = Rp 3.000.000
        tax_2 = dummy_settlement._calculate_pph21_marginal(
            prior_dpp=0.0,
            total_cum_dpp=50000000.0,
            has_npwp=False,
        )
        self.assertEqual(tax_2, 3000000.0, f"Pajak non-NPWP salah: {tax_2} != 3.000.000")

        # Skenario 3: Transaksi Kedua Menembus Lapisan 2 (Crossing Bracket PMK 168)
        # DPP Sebelumnya: Rp 50.000.000. DPP Tambahan: Rp 25.000.000. Total DPP Kumulatif: Rp 75.000.000.
        # Lapisan 1 tersisa: 10.000.000 x 5% = 500.000
        # Lapisan 2 (60 - 250 jt): 15.000.000 x 15% = 2.250.000
        # Total pajak marginal = Rp 2.750.000
        tax_3 = dummy_settlement._calculate_pph21_marginal(
            prior_dpp=50000000.0,
            total_cum_dpp=75000000.0,
            has_npwp=True,
        )
        self.assertEqual(tax_3, 2750000.0, f"Pajak crossing bracket salah: {tax_3} != 2.750.000")

    def test_03_calk_disclosure_generation(self):
        """Uji Kelengkapan Generator Catatan Atas Laporan Keuangan (CaLK) 5 Catatan Mandatori."""
        report = self.report_model.create({
            "name": "Audit CaLK Mandatori SAK EMKM",
            "framework_standard": "emkm",
            "report_type": "calk",
            "date_from": date(2026, 1, 1),
            "date_to": date(2026, 12, 31),
            "target_move": "posted",
        })
        report.action_recompute()

        # Verifikasi 5 Catatan Mandatori terisi
        self.assertTrue(report.calk_profile_text and "PT Prosperra Medika Utama" in report.calk_profile_text, "Catatan 1 Profil Entitas kosong!")
        self.assertTrue(report.calk_policy_text and "Asumsi Kesatuan Usaha" in report.calk_policy_text, "Catatan 2 Kebijakan Akuntansi kosong!")
        self.assertTrue(report.calk_receivables_html and "112990" in report.calk_receivables_html, "Catatan 3 Aging Piutang & Dispute BPJS kosong!")
        self.assertTrue(report.calk_assets_html and "Hemodialisis" in report.calk_assets_html, "Catatan 4 Jadwal Aset Tetap kosong!")
        self.assertTrue(report.calk_tax_doc_html and "PMK 168/2023" in report.calk_tax_doc_html, "Catatan 5 Rekonsiliasi Jasa Medis & Pajak kosong!")

    def test_04_sak_ep_equity_change_and_cash_flow(self):
        """Uji Laporan Perubahan Ekuitas & Arus Kas Metode Tidak Langsung (SAK EP Roadmap)."""
        # 1. Laporan Perubahan Ekuitas
        report_eq = self.report_model.create({
            "name": "Audit Laporan Perubahan Ekuitas SAK EP",
            "framework_standard": "sak_ep",
            "report_type": "equity_change",
            "date_from": date(2026, 1, 1),
            "date_to": date(2026, 12, 31),
            "target_move": "posted",
        })
        report_eq.action_recompute()
        self.assertTrue(len(report_eq.line_ids) > 0, "Laporan Perubahan Ekuitas tidak menghasilkan baris!")

        # 2. Laporan Arus Kas Metode Tidak Langsung
        report_cf = self.report_model.create({
            "name": "Audit Laporan Arus Kas Metode Tidak Langsung SAK EP",
            "framework_standard": "sak_ep",
            "report_type": "cash_flow",
            "cash_flow_method": "indirect",
            "date_from": date(2026, 1, 1),
            "date_to": date(2026, 12, 31),
            "target_move": "posted",
        })
        report_cf.action_recompute()
        self.assertTrue(len(report_cf.line_ids) > 0, "Laporan Arus Kas Metode Tidak Langsung tidak menghasilkan baris!")

    def test_05_direct_medical_depreciation_allocation(self):
        """Uji Kemenkes 2025: Depresiasi Mesin HD Nipro langsung ke Akun 510030 & Tag Analitik ACC-HD."""
        asset_model = self.env["clinic.asset"]
        
        # 1. Test HD Medical Device (Direct COGS 510030)
        hd_asset = asset_model.create({
            "name": "Mesin Hemodialisis Nipro Surdial X Test QA",
            "asset_code": "QA-HD-001",
            "asset_category": "medical_device_hd",
            "purchase_date": date(2024, 1, 1),
            "purchase_value": 240000000.0,
            "salvage_value": 0.0,
            "useful_life_months": 60,
        })
        self.assertEqual(hd_asset.expense_account_id.code, "510030", "Akun beban aset HD harus 510030 (Direct COGS)!")
        hd_analytic = self.env["account.analytic.account"].search([("code", "=", "ACC-HD")], limit=1)
        self.assertTrue(str(hd_analytic.id) in hd_asset.analytic_distribution, "Tag analitik harus ACC-HD!")

        hd_asset.action_confirm()
        self.assertTrue(len(hd_asset.depreciation_line_ids) == 60, "Jadwal amortisasi harus 60 baris!")
        first_line = hd_asset.depreciation_line_ids[0]
        move = hd_asset.action_post_depreciation_line(first_line.id)
        
        debit_line = move.line_ids.filtered(lambda l: l.debit > 0)
        credit_line = move.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(debit_line.account_id.code, "510030", "Jurnal depresiasi harus mendebit Akun 510030!")
        self.assertTrue(str(hd_analytic.id) in debit_line.analytic_distribution, "Baris debit harus tertag analitik ACC-HD!")
        self.assertEqual(credit_line.account_id.code, "122010", "Jurnal depresiasi harus mengkredit Akun 122010!")

        # 2. Test Pratama Medical Device (OpEx 610030)
        prat_asset = asset_model.create({
            "name": "USG Mindray DC-30 Test QA",
            "asset_code": "QA-PRAT-USG",
            "asset_category": "medical_device_pratama",
            "purchase_date": date(2024, 1, 1),
            "purchase_value": 120000000.0,
            "salvage_value": 0.0,
            "useful_life_months": 60,
        })
        self.assertEqual(prat_asset.expense_account_id.code, "610030", "Akun beban aset Pratama harus 610030 (OpEx)!")
        prat_analytic = self.env["account.analytic.account"].search([("code", "=", "ACC-PRATAMA")], limit=1)
        self.assertTrue(str(prat_analytic.id) in prat_asset.analytic_distribution, "Tag analitik harus ACC-PRATAMA!")

    def test_06_bpjs_claim_dispute_writeoff(self):
        """Uji Eksekusi Single-Click Write-Off Dispute BPJS: Dr 112990 / Cr 112020."""
        wizard = self.env["bpjs.claim.dispute.writeoff"].create({
            "name": "REKON-QA-202611",
            "sep_number": "0123S0010124V009999",
            "patient_name": "Pasien Uji Rekon BPJS",
            "date": fields.Date.today(),
            "writeoff_amount": 750000.0,
            "dispute_category": "coding_dispute",
            "reason": "Koreksi tarif koding klaim INA-CBG dialisis oleh verifikator BPJS",
        })
        action = wizard.action_post_writeoff()
        move_id = action.get("res_id")
        move = self.env["account.move"].browse(move_id)
        
        self.assertTrue(move.exists() and move.state == "posted", "Jurnal write-off harus berhasil terposting!")
        dr_line = move.line_ids.filtered(lambda l: l.debit > 0)
        cr_line = move.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(dr_line.account_id.code, "112990", "Baris debit harus akun 112990 (Cadangan Dispute)!")
        self.assertEqual(cr_line.account_id.code, "112020", "Baris kredit harus akun 112020 (Piutang BPJS)!")
        self.assertEqual(dr_line.debit, 750000.0, "Nominal write-off harus sesuai!")

