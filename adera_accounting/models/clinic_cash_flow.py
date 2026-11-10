# -*- coding: utf-8 -*-
from odoo import models, api
from dateutil.relativedelta import relativedelta
import logging

_logger = logging.getLogger(__name__)


class ClinicCashFlowEngine(models.AbstractModel):
    _name = "clinic.cash.flow.engine"
    _description = "Mesin Kalkulasi Laporan Arus Kas Metode Tidak Langsung"

    @api.model
    def compute_indirect_cash_flow(self, report):
        """
        Kalkulasi Laporan Arus Kas Metode Tidak Langsung (Indirect Method).
        Struktur standar audit klinik:
        1. Aktivitas Operasi (Laba Bersih + Pos Non-Kas + Perubahan Modal Kerja)
        2. Aktivitas Investasi (Akuisisi Aset Tetap Medis & Fasilitas)
        3. Aktivitas Pendanaan (Modal Saham, Prive, Pinjaman)
        4. Rekonsiliasi Kas Awal vs Akhir & Assertion Selisih Rp 0,00.
        """
        lines_data = []
        seq = 10

        date_from = report.date_from
        date_to = report.date_to
        date_before = date_from - relativedelta(days=1)

        # Helper to query account movement
        def get_delta_asset(code_list):
            """Untuk Aset (Piutang, Persediaan): Kenaikan = Arus Kas Keluar (-), Penurunan = Arus Kas Masuk (+)"""
            debit_total = 0.0
            credit_total = 0.0
            for code in code_list:
                d, c = report._get_account_balance(code, date_from, date_to)
                debit_total += d
                credit_total += c
            return -(debit_total - credit_total)

        def get_delta_liability(code_list):
            """Untuk Liabilitas (Utang, Akrual): Kenaikan = Arus Kas Masuk (+), Penurunan = Arus Kas Keluar (-)"""
            debit_total = 0.0
            credit_total = 0.0
            for code in code_list:
                d, c = report._get_account_balance(code, date_from, date_to)
                debit_total += d
                credit_total += c
            return credit_total - debit_total

        # =====================================================================
        # 1. ARUS KAS DARI AKTIVITAS OPERASI
        # =====================================================================
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "ARUS KAS DARI AKTIVITAS OPERASI",
            "line_type": "header",
        }))
        seq += 10

        # Laba / Rugi Bersih Periode Berjalan
        d_r, c_r = report._get_account_balance("410", date_from, date_to)
        rev = c_r - d_r
        d_c, c_c = report._get_account_balance("510", date_from, date_to)
        cogs = d_c - c_c
        d_o, c_o = report._get_account_balance("610", date_from, date_to)
        opex = d_o - c_o
        d_var, c_var = report._get_account_balance("61999", date_from, date_to)
        var_kas = d_var - c_var
        net_profit = rev - cogs - opex - var_kas

        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "Laba / (Rugi) Bersih Periode Berjalan",
            "line_type": "account",
            "amount_current": net_profit,
        }))
        seq += 10

        # Penyesuaian Pos Non-Kas (Non-Cash Adjustments)
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "Penyesuaian Pos Non-Kas:",
            "line_type": "header",
        }))
        seq += 10

        # (+) Beban Penyusutan Aset Tetap Medis & Bangunan (Akumulasi Penyusutan 122010 Credit change)
        d_dep, c_dep = report._get_account_balance("122010", date_from, date_to)
        deprec_adj = c_dep - d_dep
        if deprec_adj == 0.0:
            # Fallback to direct depreciation expense account if accumulation not posted
            d_exp, c_exp = report._get_account_balance("610030", date_from, date_to)
            deprec_adj = d_exp - c_exp

        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "(+) Beban Penyusutan Aset Tetap Medis & Fasilitas (Non-Kas)",
            "line_type": "account",
            "amount_current": deprec_adj,
        }))
        seq += 10

        # (+) Cadangan Kerugian Piutang / Dispute BPJS (112990 movement)
        d_bad, c_bad = report._get_account_balance("112990", date_from, date_to)
        bad_debt_adj = c_bad - d_bad
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "(+) Cadangan Kerugian Penurunan Nilai Piutang Klaim (112990)",
            "line_type": "account",
            "amount_current": bad_debt_adj,
        }))
        seq += 10

        # Perubahan Modal Kerja (Working Capital Changes)
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "Perubahan Modal Kerja Operasional:",
            "line_type": "header",
        }))
        seq += 10

        # (Δ) Piutang Usaha & Piutang Klaim BPJS (112010 + 112020 + 112030)
        delta_ar = get_delta_asset(["112010", "112020", "112030", "11201", "11202", "11203"])
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "(Kenaikan) / Penurunan Piutang Pasien & Klaim BPJS Kesehatan",
            "line_type": "account",
            "amount_current": delta_ar,
        }))
        seq += 10

        # (Δ) Persediaan Obat & BMHP (114010 + 114020 or 113010 + 113020)
        delta_inv = get_delta_asset(["114010", "114020", "113010", "113020", "1140", "1130"])
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "(Kenaikan) / Penurunan Persediaan Obat Farmasi & BMHP Medis",
            "line_type": "account",
            "amount_current": delta_inv,
        }))
        seq += 10

        # (Δ) Uang Muka Biaya / Beban Dibayar di Muka (115010)
        delta_prepaid = get_delta_asset(["115010", "1150"])
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "(Kenaikan) / Penurunan Uang Muka Biaya & Beban Dibayar di Muka",
            "line_type": "account",
            "amount_current": delta_prepaid,
        }))
        seq += 10

        # (Δ) Utang Usaha Distributor Obat/BHP & GR/IR (211010 + 211500)
        delta_ap = get_delta_liability(["211010", "211500", "2110", "2115"])
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "Kenaikan / (Penurunan) Utang Usaha Distributor Farmasi & GR/IR",
            "line_type": "account",
            "amount_current": delta_ap,
        }))
        seq += 10

        # (Δ) Utang Akrual Jasa Medis Dokter (213010 + 213020)
        delta_doctor_fee = get_delta_liability(["213010", "213020", "2130"])
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "Kenaikan / (Penurunan) Akrual Utang Jasa Medis Dokter",
            "line_type": "account",
            "amount_current": delta_doctor_fee,
        }))
        seq += 10

        # (Δ) Utang Pajak PPh 21 & PPN (212030 + 212010)
        delta_tax = get_delta_liability(["212030", "212010", "2120"])
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "Kenaikan / (Penurunan) Utang Pajak PPh 21 Dokter & PPN",
            "line_type": "account",
            "amount_current": delta_tax,
        }))
        seq += 10

        # (Δ) Pendapatan Diterima di Muka Paket HD & Saldo Pasien (214010 + 214020)
        delta_prepaid_hd = get_delta_liability(["214010", "214020", "2140"])
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "Kenaikan / (Penurunan) Pendapatan Diterima di Muka Paket HD & Voucher",
            "line_type": "account",
            "amount_current": delta_prepaid_hd,
        }))
        seq += 10

        net_operating = (
            net_profit
            + deprec_adj
            + bad_debt_adj
            + delta_ar
            + delta_inv
            + delta_prepaid
            + delta_ap
            + delta_doctor_fee
            + delta_tax
            + delta_prepaid_hd
        )
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "ARUS KAS BERSIH DARI AKTIVITAS OPERASI",
            "line_type": "subtotal",
            "amount_current": net_operating,
        }))
        seq += 10

        # =====================================================================
        # 2. ARUS KAS DARI AKTIVITAS INVESTASI
        # =====================================================================
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "ARUS KAS DARI AKTIVITAS INVESTASI",
            "line_type": "header",
        }))
        seq += 10

        # (-) Pembelian / Akuisisi Aset Tetap Medis & Non-Medis (121010 s/d 121040)
        d_capex, c_capex = report._get_account_balance("1210", date_from, date_to)
        capex_out = -(d_capex - c_capex)
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "Pembelian Mesin Hemodialisis, RO System & Peralatan Medis",
            "line_type": "account",
            "amount_current": capex_out,
        }))
        seq += 10

        net_investing = capex_out
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "ARUS KAS BERSIH DARI AKTIVITAS INVESTASI",
            "line_type": "subtotal",
            "amount_current": net_investing,
        }))
        seq += 10

        # =====================================================================
        # 3. ARUS KAS DARI AKTIVITAS PENDANAAN
        # =====================================================================
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "ARUS KAS DARI AKTIVITAS PENDANAAN",
            "line_type": "header",
        }))
        seq += 10

        # (Δ) Setoran Modal Saham / Ekuitas Pemilik (310010)
        d_eq, c_eq = report._get_account_balance("310010", date_from, date_to)
        delta_equity = c_eq - d_eq
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "Penerimaan dari Setoran Modal Saham Pemilik",
            "line_type": "account",
            "amount_current": delta_equity,
        }))
        seq += 10

        # (Δ) Prive / Distribusi Dividen ke Pemilik (310020)
        d_priv, c_priv = report._get_account_balance("310020", date_from, date_to)
        delta_prive = -(d_priv - c_priv)
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "Pembayaran Prive / Dividen kepada Pemegang Saham",
            "line_type": "account",
            "amount_current": delta_prive,
        }))
        seq += 10

        # (Δ) Pinjaman Bank / Liabilitas Jangka Panjang (221010)
        d_loan, c_loan = report._get_account_balance("221010", date_from, date_to)
        delta_loan = c_loan - d_loan
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "Penerimaan / (Pelunasan) Pinjaman Jangka Panjang",
            "line_type": "account",
            "amount_current": delta_loan,
        }))
        seq += 10

        net_financing = delta_equity + delta_prive + delta_loan
        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "ARUS KAS BERSIH DARI AKTIVITAS PENDANAAN",
            "line_type": "subtotal",
            "amount_current": net_financing,
        }))
        seq += 10

        # =====================================================================
        # 4. REKONSILIASI KAS & SETARA KAS
        # =====================================================================
        net_cash_flow = net_operating + net_investing + net_financing

        # Saldo Kas & Setara Kas Awal & Akhir
        cash_prefixes = ["111010", "111110", "111210", "11101", "11102", "11111", "11121", "11122"]
        # Remove duplicates while keeping order
        seen_pfx = set()
        pfx_list = []
        for p in cash_prefixes:
            if p not in seen_pfx:
                seen_pfx.add(p)
                pfx_list.append(p)

        cash_open = 0.0
        cash_close = 0.0
        for pfx in ["111010", "111110", "111210"]:
            d_o, c_o = report._get_account_balance(pfx, False, date_before, is_cumulative=True)
            cash_open += (d_o - c_o)
            d_cl, c_cl = report._get_account_balance(pfx, False, date_to, is_cumulative=True)
            cash_close += (d_cl - c_cl)

        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "KENAIKAN / (PENURUNAN) BERSIH KAS DAN SETARA KAS",
            "line_type": "total",
            "amount_current": net_cash_flow,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "SALDO KAS & SETARA KAS AWAL PERIODE",
            "line_type": "account",
            "amount_current": cash_open,
        }))
        seq += 10

        lines_data.append((0, 0, {
            "sequence": seq,
            "name": "SALDO KAS & SETARA KAS AKHIR PERIODE (KAS, KASIR & BANK BCA)",
            "line_type": "total",
            "amount_current": cash_close,
        }))
        seq += 10

        # Integrity Check
        reconciled_balance = cash_open + net_cash_flow
        recon_diff = abs(reconciled_balance - cash_close)
        if recon_diff < 0.01:
            recon_note = "Status Rekonsiliasi Kas: 100% Terekonsiliasi Sempurna (Selisih: Rp 0,00)"
        else:
            recon_note = f"Status Rekonsiliasi Kas: Perhatian Terdapat Selisih Non-Operasional (Selisih: Rp {recon_diff:,.2f})"

        lines_data.append((0, 0, {
            "sequence": seq,
            "name": recon_note,
            "line_type": "header",
        }))

        report.write({"line_ids": lines_data})
        return True

