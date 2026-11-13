# STANDAR OPERASIONAL PROSEDUR (SOP)
## Penutupan Shift Kasir Mandiri (Blind-Count Protocol)
**Fasyankes:** Klinik ADERA (PT Prosperra Medika Utama)  
**Unit Terkait:** Kasir Klinik Pratama Rawat Jalan & Kasir Klinik Utama Hemodialisis  
**Versi Dokumen:** 1.0 (Odoo 19 CE Enterprise Ready)  
**Efektif Berlaku:** Cut-Over Go-Live

---

### 1. TUJUAN
1. Memastikan integritas penerimaan kas pembayaran pasien, biaya pendaftaran, resep obat, dan deposit pelayanan.
2. Mengeliminasi praktik manipulasi kas fisik (*cash manipulation/smoothing*) dengan menyembunyikan saldo kas sistem dari kasir saat penutupan shift.
3. Menegakkan kepatuhan akuntansi kas perpetual dengan pencatatan selisih kas otomatis ke Akun **`619990` (Beban Selisih Rekonsiliasi Kas Kasir & Petty Cash)**.

---

### 2. PRINSIP DASAR "BLIND-COUNT"
* **Layar Kasir Tidak Menampilkan Saldo Komputer:** Saat tombol **"Tutup Shift / Close Register"** ditekan, sistem Odoo 19 POS tidak akan menampilkan saldo kas teoritis (*Expected in Cash*).
* **Penghitungan Fisik Mandiri:** Kasir wajib menghitung uang fisik yang ada di dalam laci kasir (*cash drawer*) lembar demi lembar dan koin demi koin.
* **Toleransi Selisih:**
  - **Selisih Wajar ($\le$ Rp 50.000):** Sistem otomatis membukukan selisih ke beban operasional `619990` dan sesi kasir langsung tertutup rapi.
  - **Selisih Tidak Wajar (> Rp 50.000):** Sistem memblokir penutupan shift dan mewajibkan otorisasi Supervisor Kasir/Manajer Keuangan menggunakan PIN dan penulisan Berita Acara Selisih.

---

### 3. PROSEDUR LANGKAH DEMI LANGKAH PENUTUPAN KASIR

```text
[Kasir Selesaikan Antrean] ──> [Klik Tutup Shift] ──> [Hitung Fisik Laci Kasir]
                                                               │
                                                               ▼
[Cetak Struk Setoran Rangkap 2] <── [Kirim Hitungan] <── [Input Tabel Pecahan Uang]
```

#### Langkah 1: Penyelesaian Transaksi & Penutupan Antrean
1. Pastikan seluruh transaksi pasien rawat jalan atau hemodialisis yang telah membayar tunai/QRIS telah tercetak struknya.
2. Tidak ada order gantung (*draft orders*) pada meja kasir.

#### Langkah 2: Membuka Layar Penutupan Shift
1. Klik menu dropdown kasir di kanan atas, pilih **"Tutup Kasir / Close Shift"**.
2. Perhatikan bahwa saldo sistem disembunyikan dengan lencana informasi:  
   *"Protokol Blind-Count Aktif: Saldo sistem disembunyikan. Hitung fisik uang di laci kasir secara teliti."*

#### Langkah 3: Penghitungan Fisik Uang di Laci Kasir
1. Buka laci kasir (*cash drawer*).
2. **Pisahkan Modal Awal Kasir (*Float Cash*):**
   - Ambil uang modal awal (standar: Rp 500.000,00) dan masukkan ke amplop modal awal kasir untuk shift berikutnya.
3. **Hitung Uang Hasil Pendapatan Pasien Hari Ini:**
   - Kelompokkan uang kertas berdasarkan nominal: Rp 100.000, Rp 50.000, Rp 20.000, Rp 10.000, Rp 5.000, Rp 2.000, Rp 1.000.
   - Hitung total uang koin/receh.

#### Langkah 4: Pengisian Tabel Pecahan Uang (*Denomination Matrix*)
Pada popup penutupan kasir Odoo, masukkan jumlah lembar uang pada masing-masing kotak pecahan:
* **Rp 100.000:** ... lembar
* **Rp 50.000:** ... lembar
* **Rp 20.000:** ... lembar
* **Rp 10.000:** ... lembar
* **Rp 5.000:** ... lembar
* **Rp 2.000:** ... lembar
* **Rp 1.000:** ... lembar
* **Koin/Receh:** Total rupiah receh (misal: Rp 14.500)

Sistem akan otomatis menghitung total uang fisik kasir pada pojok kanan atas tabel pecahan.

#### Langkah 5: Konfirmasi Penutupan Shift
1. Periksa kembali total fisik yang tertera di layar apakah sudah sesuai dengan uang tunai di depan kasir.
2. Masukkan catatan kasir pada kolom *Closing note* (misal: "Shift Pagi Kasir Pratama - Aman").
3. Klik tombol **"Tutup Kasir / Close Register"**.

#### Langkah 6: Prosedur Jika Terjadi Selisih Kasir
1. **Kondisi A: Saldo Sesuai / Selisih $\le$ Rp 50.000:**
   - Sistem akan langsung menutup sesi kasir.
   - Selisih receh (kurang/lebih) otomatis terjurnal ke Akun `619990` tanpa perlu repot koreksi manual.
2. **Kondisi B: Selisih > Rp 50.000 (Peringatan Sistem):**
   - Layar akan menampilkan pesan: *"Peringatan Selisih Kasir Kritis: Memerlukan Otorisasi Supervisor"*.
   - Kasir **DILARANG** menutup paksa sistem atau memanipulasi jumlah uang.
   - Panggil **Supervisor Kasir / Manajer Keuangan**.
   - Supervisor akan menekan tombol **"Otorisasi Supervisor"**, memasukkan PIN Supervisor, melakukan hitung ulang bersama kasir, dan mengisi **Berita Acara Selisih Kasir**.

#### Langkah 7: Pencetakan Berita Acara & Setoran Kas
1. Cetak Laporan Harian Kasir (*Daily Sales / Summary Shift Report*) rangkap 2:
   - **Lembar 1:** Dimasukkan ke dalam amplop setoran uang fisik bersama bukti transaksi QRIS/Debit untuk disetor ke Rekening Bank Klinik ADERA (`111110`).
   - **Lembar 2:** Disimpan oleh kasir sebagai arsip serah terima shift.
2. Tandatangani formulir serah terima kasir shift pagi/sore.

---

### 4. SANKSI KELALAIAN & INTEGRITAS KAS
1. Segala bentuk penambahan kas pribadi ke laci kasir untuk menutupi kekurangan hitungan komputer dikategorikan sebagai pelanggaran integritas.
2. Selisih kasir berulang tanpa alasan yang sah akan dievaluasi oleh Tim Internal Audit dan Manajemen Klinik ADERA.

