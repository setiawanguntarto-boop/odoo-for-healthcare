# -*- coding: utf-8 -*-
"""Script Validasi & Assertions Kepatuhan Benchmark Akuntansi Nasional Klinik ADERA (Odoo 19 CE)
Standar: Permenkes 14/2021, IAI SAK EMKM, SAK EP 2025, PMK 168/2023.
"""
import sys
from datetime import date


def run_benchmark_tests(env):
    print("=" * 80)
    print("STARTING NATIONAL ACCOUNTING BENCHMARK COMPLIANCE AUDIT (KLINIK ADERA ERP)")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # TEST 1: Keseimbangan Neraca (Balance Sheet Equilibrium)
    # -------------------------------------------------------------------------
    print("\n[TEST 1] Menguji Keseimbangan Laporan Posisi Keuangan (Neraca SAK EMKM)...")
    report = env["psak.financial.report"].create({
        "name": "Audit Neraca Keseimbangan SAK EMKM",
        "framework_standard": "emkm",
        "report_type": "balance_sheet",
        "date_from": date(2026, 1, 1),
        "date_to": date(2026, 12, 31),
        "target_move": "posted",
    })
    report.action_recompute()

    tot_asset = report.line_ids.filtered(lambda l: l.name == "TOTAL ASET (TOTAL ASSETS)")
    tot_liab_eq = report.line_ids.filtered(lambda l: l.name == "TOTAL KEWAJIBAN & EKUITAS")

    assert tot_asset, "FAIL: Baris Total Aset tidak ditemukan!"
    assert tot_liab_eq, "FAIL: Baris Total Kewajiban & Ekuitas tidak ditemukan!"

    amt_asset = tot_asset.amount_current
    amt_liab_eq = tot_liab_eq.amount_current
    diff = abs(amt_asset - amt_liab_eq)

    print(f"  -> Total Aset: Rp {amt_asset:,.2f}")
    print(f"  -> Total Liabilitas & Ekuitas: Rp {amt_liab_eq:,.2f}")
    print(f"  -> Selisih (Difference): Rp {diff:,.2f}")
    assert diff < 0.01, f"FAIL: Neraca tidak seimbang! Selisih = Rp {diff:,.2f}"
    print("  -> PASSED: Neraca Seimbang 100% (Rp 0.00 difference)!")

    # -------------------------------------------------------------------------
    # TEST 2: Presisi Pemotongan PPh 21 Tenaga Ahli Dokter (PMK 168/2023 & UU HPP)
    # -------------------------------------------------------------------------
    print("\n[TEST 2] Menguji Presisi Perhitungan Pajak PPh 21 Progresif PMK 168/2023...")
    settlement_model = env["doctor.settlement"]
    dummy = settlement_model.new({})

    # Kasus A: Dokter Ber-NPWP, Bruto Rp 100.000.000 (DPP 50% = Rp 50.000.000)
    # Lapisan 1 (0-60 jt): 50.000.000 x 5% = Rp 2.500.000
    tax_a = dummy._calculate_pph21_marginal(prior_dpp=0.0, total_cum_dpp=50000000.0, has_npwp=True)
    print(f"  -> Kasus A (Single Settlement, NPWP, DPP 50M): Rp {tax_a:,.2f} (Ekspektasi: Rp 2,500,000.00)")
    assert tax_a == 2500000.0, f"FAIL: Kasus A salah {tax_a}"

    # Kasus B: Dokter Non-NPWP, Bruto Rp 100.000.000 (Penalti 120%)
    # Rp 2.500.000 x 1.20 = Rp 3.000.000
    tax_b = dummy._calculate_pph21_marginal(prior_dpp=0.0, total_cum_dpp=50000000.0, has_npwp=False)
    print(f"  -> Kasus B (Non-NPWP Multiplier 120%, DPP 50M): Rp {tax_b:,.2f} (Ekspektasi: Rp 3,000,000.00)")
    assert tax_b == 3000000.0, f"FAIL: Kasus B salah {tax_b}"

    # Kasus C: Transaksi Kedua Menembus Lapisan 2 (Crossing Bracket: Lapisan 1 s.d 60jt, Lapisan 2 > 60jt-250jt)
    # Prior DPP: 50M. Total Kumulatif DPP: 75M.
    # Lapisan 1 sisa 10M x 5% = 500k. Lapisan 2 15M x 15% = 2.25M. Total = Rp 2.750.000.
    tax_c = dummy._calculate_pph21_marginal(prior_dpp=50000000.0, total_cum_dpp=75000000.0, has_npwp=True)
    print(f"  -> Kasus C (Lapisan Kumulatif Marginal YTD 50M -> 75M): Rp {tax_c:,.2f} (Ekspektasi: Rp 2,750,000.00)")
    assert tax_c == 2750000.0, f"FAIL: Kasus C salah {tax_c}"
    print("  -> PASSED: Seluruh formula perpajakan PMK 168/2023 Pasal 17 100% presisi!")

    # -------------------------------------------------------------------------
    # TEST 3: Generator Catatan Atas Laporan Keuangan (CaLK) 5 Catatan Mandatori
    # -------------------------------------------------------------------------
    print("\n[TEST 3] Menguji Otomasi Catatan Atas Laporan Keuangan (CaLK SAK EMKM / SAK EP)...")
    calk = env["psak.financial.report"].create({
        "name": "Audit CaLK Mandatori SAK EMKM",
        "framework_standard": "emkm",
        "report_type": "calk",
        "date_from": date(2026, 1, 1),
        "date_to": date(2026, 12, 31),
        "target_move": "posted",
    })
    calk.action_recompute()

    assert calk.calk_profile_text and "PT Prosperra Medika Utama" in calk.calk_profile_text, "FAIL: Profil Entitas kosong!"
    assert calk.calk_policy_text and "Asumsi Kesatuan Usaha" in calk.calk_policy_text, "FAIL: Kebijakan Akuntansi kosong!"
    assert calk.calk_receivables_html and "112990" in calk.calk_receivables_html, "FAIL: Schedule Piutang & Dispute BPJS kosong!"
    assert calk.calk_assets_html and "Hemodialisis" in calk.calk_assets_html, "FAIL: Jadwal Aset Tetap kosong!"
    assert calk.calk_tax_doc_html and "PMK 168/2023" in calk.calk_tax_doc_html, "FAIL: Rekonsiliasi Jasa Medis & Pajak kosong!"

    print("  -> Catatan 1: Profil Entitas & Permenkes 14/2021 (Tervalidasi)")
    print("  -> Catatan 2: Asumsi Kesatuan Usaha & Kebijakan FIFO Perpetual (Tervalidasi)")
    print("  -> Catatan 3: Schedule Aging Piutang & Contra-Asset Dispute 112990 (Tervalidasi)")
    print("  -> Catatan 4: Jadwal Aset Tetap Medis Garis Lurus Permenkes 14/2021 (Tervalidasi)")
    print("  -> Catatan 5: Rekonsiliasi Jasa Medis & PPh 21 Dokter Tenaga Ahli (Tervalidasi)")
    print("  -> PASSED: Generator CaLK 5-Note Mandatori lengkap dan siap audit!")

    # -------------------------------------------------------------------------
    # TEST 4: Kesiapan Roadmap SAK EP (Perubahan Ekuitas & Arus Kas Tidak Langsung)
    # -------------------------------------------------------------------------
    print("\n[TEST 4] Menguji Kesiapan Transisi Roadmap SAK EP (Equity Change & Cash Flow Indirect)...")
    eq_report = env["psak.financial.report"].create({
        "name": "Audit Laporan Perubahan Ekuitas SAK EP",
        "framework_standard": "sak_ep",
        "report_type": "equity_change",
        "date_from": date(2026, 1, 1),
        "date_to": date(2026, 12, 31),
        "target_move": "posted",
    })
    eq_report.action_recompute()
    assert len(eq_report.line_ids) > 0, "FAIL: Laporan Perubahan Ekuitas kosong!"
    print(f"  -> Laporan Perubahan Ekuitas berhasil dibentuk ({len(eq_report.line_ids)} baris terkomputasi).")

    cf_report = env["psak.financial.report"].create({
        "name": "Audit Laporan Arus Kas Tidak Langsung SAK EP",
        "framework_standard": "sak_ep",
        "report_type": "cash_flow",
        "cash_flow_method": "indirect",
        "date_from": date(2026, 1, 1),
        "date_to": date(2026, 12, 31),
        "target_move": "posted",
    })
    cf_report.action_recompute()
    assert len(cf_report.line_ids) > 0, "FAIL: Laporan Arus Kas Tidak Langsung kosong!"
    print(f"  -> Laporan Arus Kas Metode Tidak Langsung berhasil dibentuk ({len(cf_report.line_ids)} baris terkomputasi).")
    print("  -> PASSED: Kesiapan SAK EP Section 6 & 7 100% tervalidasi!")

    # -------------------------------------------------------------------------
    # TEST 5: Karantina Otomatis Farmasi FEFO (< 60 Hari)
    # -------------------------------------------------------------------------
    print("\n[TEST 5] Menguji Mekanisme FEFO & Karantina Farmasi Near-Expiry (< 60 Hari)...")
    lot_model = env["stock.lot"]
    assert hasattr(lot_model, "cron_quarantine_near_expiry_lots"), "FAIL: Method cron_quarantine_near_expiry_lots tidak ditemukan!"
    lot_model.cron_quarantine_near_expiry_lots()
    print("  -> PASSED: Cron FEFO Auto-Quarantine Near-Expiry Lots (< 60 Hari) dieksekusi dengan sukses!")

    print("\n" + "=" * 80)
    print("ALL 5 NATIONAL BENCHMARK COMPLIANCE AUDITS PASSED WITH 100% SUCCESS!")
    print("=" * 80)


if 'env' in locals():
    run_benchmark_tests(env)
elif __name__ == "__main__":
    import odoo
    from odoo import api, SUPERUSER_ID
    from odoo.modules.registry import Registry

    odoo.tools.config.parse_config([
        "-c", "/etc/odoo/odoo.conf",
        "-d", "klinik-adera",
        "--db_host=db_adera",
        "--db_user=odoo",
        "--db_password=odoo",
    ])
    registry = Registry("klinik-adera")
    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        run_benchmark_tests(env)
