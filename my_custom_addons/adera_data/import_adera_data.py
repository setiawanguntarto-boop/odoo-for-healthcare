#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
KLINIK ADERA ERP - CLINICAL DATA MIGRATION ENGINE (ODOO 19 CE)
=============================================================================
ETL script for importing:
1. Patient Registry (res.partner) from 'Klinik ADERA - DAFTAR PASIEN.csv'
2. Practitioner Registry (res.partner - Doctors/Midwives) from 'Klinik ADERA - DAFTAR PEMERIKSAAN TENAGA MEDIS.csv'
3. Historical Clinical Encounters (clinic.encounter & clinic.encounter.line) in 'staged' state

Standards:
- Idempotent: Can be run multiple times without duplicating records.
- Indonesian GAAPs (PSAK) & Permenkes 24/2022 compliant.
- Safe Staging: Historical encounters are staged without triggering financial posting.
=============================================================================
"""

import os
import sys
import csv
import json
import logging
import re
from datetime import datetime, timedelta

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("AderaDataMigration")

# Determine base paths
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
PATIENT_CSV = os.path.join(DATA_DIR, "Klinik ADERA - DAFTAR PASIEN.csv")
ENCOUNTER_CSV = os.path.join(DATA_DIR, "Klinik ADERA - DAFTAR PEMERIKSAAN TENAGA MEDIS.csv")
REPORT_FILE = os.path.join(DATA_DIR, "MIGRATION_ANOMALY_REPORT.json")

# Clean Practitioner Catalog
DOCTOR_METADATA = {
    'Heru Prasanto, Sp.pd-kgh, Finasim': {
        'name': 'dr. Heru Prasanto, Sp.PD-KGH, FINASIM',
        'doctor_type': 'specialist_hd',
        'is_doctor': True,
        'title': 'Spesialis Penyakit Dalam - Konsultan Ginjal Hipertensi (Hemodialisis)',
    },
    'Abdi Marang Gusti Alhaq  M.med.sc tes': {
        'name': 'dr. Abdi Marang Gusti Alhaq, M.Med.Sc',
        'doctor_type': 'general',
        'is_doctor': True,
        'title': 'Dokter Umum / Konsultan Medis',
    },
    'Antonius Janottama Saga': {
        'name': 'dr. Antonius Janottama Saga',
        'doctor_type': 'general',
        'is_doctor': True,
        'title': 'Dokter Umum & Akupunktur Klinis',
    },
    'Dedy Sukmo Anggoro': {
        'name': 'dr. Dedy Sukmo Anggoro',
        'doctor_type': 'general',
        'is_doctor': True,
        'title': 'Dokter Pelayanan Medik Dasar',
    },
    'Farah Dina': {
        'name': 'dr. Farah Dina',
        'doctor_type': 'general',
        'is_doctor': True,
        'title': 'Dokter Umum',
    },
    'Imam Khoirul Fajri': {
        'name': 'dr. Imam Khoirul Fajri',
        'doctor_type': 'general',
        'is_doctor': True,
        'title': 'Dokter Umum',
    },
    'Janet Bins': {
        'name': 'dr. Janet Bins',
        'doctor_type': 'general',
        'is_doctor': True,
        'title': 'Praktisi Akupunktur & Komplementer',
    },
    'Nareswari Dyah Wisesaningrum': {
        'name': 'dr. Nareswari Dyah Wisesaningrum',
        'doctor_type': 'general',
        'is_doctor': True,
        'title': 'Dokter Umum',
    },
    'Raudi Akmal': {
        'name': 'dr. Raudi Akmal',
        'doctor_type': 'general',
        'is_doctor': True,
        'title': 'Dokter Konsultan',
    },
    'Rosyida Avicennianing Tyas , M.hpm': {
        'name': 'dr. Rosyida Avicennianing Tyas, M.HPM',
        'doctor_type': 'general',
        'is_doctor': True,
        'title': 'Dokter Umum / Magister Kebijakan & Manajemen Kesehatan',
    },
    'Tamara Dewi Setyowati, A.md.keb': {
        'name': 'Bd. Tamara Dewi Setyowati, A.Md.Keb',
        'doctor_type': 'general',
        'is_doctor': True,
        'title': 'Bidan Pelaksana KIA & Vaksinasi',
    },
    'Bidan etika': {
        'name': 'Bd. Etika',
        'doctor_type': 'general',
        'is_doctor': True,
        'title': 'Bidan Praktisi KIA & Kandungan',
    },
}

def clean_patient_name(name_raw):
    """Clean patient name: remove emojis, special characters, and title case."""
    if not name_raw:
        return ""
    # Remove emojis and unprintable characters
    cleaned = re.sub(r'[^\w\s\.,\-\']', '', name_raw)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned.title()

def clean_phone(phone_raw):
    """Format Indonesian phone number."""
    if not phone_raw:
        return False
    digits = re.sub(r'[^\d+]', '', phone_raw.strip())
    if len(digits) < 8 or digits in ['08', '081298765432', '123']:
        return False
    if digits.startswith('62'):
        digits = '+' + digits
    elif digits.startswith('8'):
        digits = '+62' + digits
    elif digits.startswith('08'):
        digits = '+62' + digits[1:]
    return digits

def clean_street(street_raw):
    """Validate address string."""
    if not street_raw:
        return False
    s = street_raw.strip()
    if len(s) < 3 or s.lower() in ['[]', '-', 'alamat yang muncul merupakan alamat lengkap', 'none', 'null']:
        return False
    return s

def sanitize_xml_id(raw_str):
    """Generate safe XML ID string."""
    return re.sub(r'[^a-zA-Z0-9_]', '_', str(raw_str).strip())

def parse_wib_datetime_to_utc(tanggal_str, reg_str):
    """Convert DD/MM/YYYY and HH:MM in WIB (UTC+7) to Odoo UTC string."""
    if not tanggal_str:
        return False
    try:
        t_clean = tanggal_str.strip()
        r_clean = (reg_str or '08:00').strip()
        dt_local = datetime.strptime(f"{t_clean} {r_clean}", "%d/%m/%Y %H:%M")
        # Subtract 7 hours for UTC
        dt_utc = dt_local - timedelta(hours=7)
        return dt_utc.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        logger.warning(f"Failed to parse datetime '{tanggal_str} {reg_str}': {e}")
        return False

def parse_amount(amt_raw):
    """Parse amount formatted with commas and decimals."""
    if not amt_raw:
        return 0.0
    try:
        clean_str = str(amt_raw).replace(',', '').strip()
        return float(clean_str)
    except Exception:
        return 0.0


class AderaDataMigrator:
    def __init__(self, env, force_update=False):
        self.env = env
        self.force_update = force_update
        self.stats = {
            'patients': {'total_rows': 0, 'valid': 0, 'discarded': 0, 'created': 0, 'updated': 0, 'skipped': 0},
            'doctors': {'total_raw': len(DOCTOR_METADATA), 'registered': 0},
            'encounters': {'total_rows': 0, 'valid': 0, 'discarded': 0, 'staged': 0, 'lines_created': 0, 'skipped': 0},
        }
        self.anomalies = {
            'discarded_patients': [],
            'discarded_encounters': [],
        }
        self.doctor_map = {}
        self.analytic_map = {}
        self.service_product_map = {}

    def ensure_service_products(self):
        """Ensure necessary service products exist for encounter lines."""
        logger.info("Ensuring service products and analytic accounts...")
        Product = self.env['product.product']
        Analytic = self.env['account.analytic.account']

        # Cache Analytic Accounts
        for code in ['ACC-PRATAMA', 'ACC-HD', 'PRAT-UMUM', 'PRAT-GIGI', 'PRAT-KIA', 'HD-TREAT']:
            acc = Analytic.search([('code', '=', code)], limit=1)
            if acc:
                self.analytic_map[code] = acc.id

        # Service Products mapping
        services = [
            ('SRV-CONS-GP', 'Konsultasi & Pemeriksaan Dokter Umum', 150000.0),
            ('SRV-HD-ROUTINE', 'Pelayanan Hemodialisis Rutin (Sp.PD-KGH)', 850000.0),
            ('SRV-CONS-DENTAL', 'Pemeriksaan & Tindakan Gigi & Mulut', 120000.0),
            ('SRV-CONS-KIA', 'Pelayanan KIA & Pemeriksaan Kebidanan', 90000.0),
            ('SRV-CONS-SPEC', 'Konsultasi Spesialis / Akupunktur Medis', 200000.0),
        ]

        for code, name, price in services:
            prod = Product.search([('default_code', '=', code)], limit=1)
            if not prod:
                prod = Product.create({
                    'name': name,
                    'default_code': code,
                    'type': 'service',
                    'list_price': price,
                })
                logger.info(f"Created Service Product: [{code}] {name}")
            self.service_product_map[code] = prod.id

    def migrate_doctors(self):
        """Extract and upsert practitioners into res.partner."""
        logger.info("--- Step 1: Ingesting Practitioners (Doctors & Midwives) ---")
        Partner = self.env['res.partner']
        for raw_key, meta in DOCTOR_METADATA.items():
            # Check by name or sip
            partner = Partner.search([('name', '=', meta['name'])], limit=1)
            if not partner:
                # Check without titles
                clean_short = meta['name'].replace('dr. ', '').replace('Bd. ', '').split(',')[0].strip()
                partner = Partner.search([('name', 'ilike', clean_short), ('is_doctor', '=', True)], limit=1)

            vals = {
                'name': meta['name'],
                'is_doctor': True,
                'doctor_type': meta['doctor_type'],
                'is_company': False,
                'comment': f"Legacy Medical Staff: {meta['title']}",
            }

            if partner:
                partner.write(vals)
                logger.info(f"Updated existing practitioner: {meta['name']} (ID: {partner.id})")
            else:
                partner = Partner.create(vals)
                logger.info(f"Created new practitioner: {meta['name']} (ID: {partner.id})")

            self.doctor_map[raw_key] = partner.id
            self.stats['doctors']['registered'] += 1

    def migrate_patients(self, batch_size=1000):
        """Ingest patients from DAFTAR PASIEN.csv with idempotency and batching."""
        logger.info(f"--- Step 2: Ingesting Patients from {PATIENT_CSV} ---")
        if not os.path.exists(PATIENT_CSV):
            logger.error(f"Patient CSV file not found: {PATIENT_CSV}")
            return

        Partner = self.env['res.partner']
        ModelData = self.env['ir.model.data']

        # Pre-cache existing patients by ref (MRN)
        logger.info("Pre-indexing existing patient MRNs...")
        existing_partners = Partner.search_read([('ref', '!=', False)], ['id', 'ref'])
        existing_mrn_map = {p['ref'].strip(): p['id'] for p in existing_partners if p['ref']}
        logger.info(f"Found {len(existing_mrn_map)} existing patient records in database.")

        batch_create = []
        batch_xmlids = []
        batch_updates = []

        with open(PATIENT_CSV, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f)
            # Skip 3 title rows + 1 header row
            for _ in range(4):
                next(reader, None)

            for row_idx, row in enumerate(reader, start=5):
                if not row or not any(row):
                    continue
                self.stats['patients']['total_rows'] += 1

                no_id = row[0].strip() if len(row) > 0 else ""
                nama_raw = row[1].strip() if len(row) > 1 else ""
                gender_raw = row[2].strip() if len(row) > 2 else ""
                alamat_raw = row[3].strip() if len(row) > 3 else ""
                tempat_lahir = row[4].strip() if len(row) > 4 else ""
                tgl_lahir = row[5].strip() if len(row) > 5 else ""
                phone_raw = row[6].strip() if len(row) > 6 else ""
                email_raw = row[7].strip() if len(row) > 7 else ""
                asuransi_raw = row[8].strip() if len(row) > 8 else ""

                # Cleansing & Test Detection
                discard_reasons = []
                if not no_id:
                    discard_reasons.append("Missing NO ID / MRN")
                if not nama_raw or len(nama_raw) < 2:
                    discard_reasons.append("Invalid or Empty Name")
                if re.search(r'test|testing|contoh|coba|dummy|pemarah', nama_raw, re.IGNORECASE):
                    discard_reasons.append(f"Test / Dummy Patient Name ('{nama_raw}')")
                if re.search(r'test|dummy', no_id, re.IGNORECASE):
                    discard_reasons.append(f"Test MRN ('{no_id}')")

                if discard_reasons:
                    self.stats['patients']['discarded'] += 1
                    self.anomalies['discarded_patients'].append({
                        'row': row_idx,
                        'mrn': no_id,
                        'name': nama_raw,
                        'reasons': discard_reasons,
                    })
                    continue

                self.stats['patients']['valid'] += 1
                clean_name = clean_patient_name(nama_raw)
                clean_ph = clean_phone(phone_raw)
                clean_addr = clean_street(alamat_raw)
                clean_email = email_raw if '@' in email_raw else False

                comment_parts = [
                    f"Legacy MRN: {no_id}",
                    f"Gender: {gender_raw}" if gender_raw else None,
                    f"Birth: {tempat_lahir}, {tgl_lahir}" if (tempat_lahir or tgl_lahir) else None,
                    f"Insurance: {asuransi_raw}" if asuransi_raw else None,
                ]
                comment_str = " | ".join([p for p in comment_parts if p])

                vals = {
                    'name': clean_name,
                    'ref': no_id,
                    'is_company': False,
                    'customer_rank': 1,
                    'street': clean_addr,
                    'phone': clean_ph,
                    'email': clean_email,
                    'comment': comment_str,
                }

                if no_id in existing_mrn_map:
                    if self.force_update:
                        batch_updates.append((existing_mrn_map[no_id], vals))
                    else:
                        self.stats['patients']['skipped'] += 1
                else:
                    batch_create.append((no_id, vals))

                # Flush creation batch
                if len(batch_create) >= batch_size:
                    self._flush_patient_create_batch(batch_create, existing_mrn_map)
                    batch_create = []

                # Flush update batch
                if len(batch_updates) >= batch_size:
                    self._flush_patient_update_batch(batch_updates)
                    batch_updates = []

            # Final flushes
            if batch_create:
                self._flush_patient_create_batch(batch_create, existing_mrn_map)
            if batch_updates:
                self._flush_patient_update_batch(batch_updates)

        logger.info(
            f"Patients Migration Complete: Total={self.stats['patients']['total_rows']}, "
            f"Valid={self.stats['patients']['valid']}, Created={self.stats['patients']['created']}, "
            f"Updated={self.stats['patients']['updated']}, Discarded={self.stats['patients']['discarded']}"
        )

    def _flush_patient_create_batch(self, batch_create, existing_mrn_map):
        Partner = self.env['res.partner']
        ModelData = self.env['ir.model.data']
        vals_list = [item[1] for item in batch_create]
        partners = Partner.create(vals_list)

        xmlid_vals = []
        for (no_id, _), partner in zip(batch_create, partners):
            existing_mrn_map[no_id] = partner.id
            sanitized = sanitize_xml_id(no_id)
            xmlid_vals.append({
                'module': 'adera_data',
                'name': f'adera_patient_{sanitized}',
                'model': 'res.partner',
                'res_id': partner.id,
            })
        ModelData.create(xmlid_vals)
        self.stats['patients']['created'] += len(partners)
        logger.info(f"Batched created {len(partners)} patients (Total Created: {self.stats['patients']['created']}).")

    def _flush_patient_update_batch(self, batch_updates):
        Partner = self.env['res.partner']
        for partner_id, vals in batch_updates:
            partner = Partner.browse(partner_id)
            partner.write(vals)
        self.stats['patients']['updated'] += len(batch_updates)
        logger.info(f"Batched updated {len(batch_updates)} existing patients.")

    def migrate_encounters(self):
        """Ingest historical clinical encounters into clinic.encounter staging."""
        logger.info(f"--- Step 3: Ingesting Clinical Encounters from {ENCOUNTER_CSV} ---")
        if not os.path.exists(ENCOUNTER_CSV):
            logger.error(f"Encounter CSV file not found: {ENCOUNTER_CSV}")
            return

        Encounter = self.env['clinic.encounter']
        EncounterLine = self.env['clinic.encounter.line']
        Partner = self.env['res.partner']

        # Pre-cache patients by MRN
        patient_mrn_map = {p['ref'].strip(): p['id'] for p in Partner.search_read([('ref', '!=', False)], ['id', 'ref'])}

        # Pre-cache existing encounters by external_encounter_id
        existing_enc_records = Encounter.search_read([], ['external_encounter_id'])
        existing_enc_set = {e['external_encounter_id'] for e in existing_enc_records if e.get('external_encounter_id')}
        logger.info(f"Found {len(existing_enc_set)} existing staged encounters in database.")

        with open(ENCOUNTER_CSV, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.reader(f)
            # Skip 3 title rows + 1 header row
            for _ in range(4):
                next(reader, None)

            for row_idx, row in enumerate(reader, start=5):
                if not row or len(row) < 28:
                    continue

                faktur = row[27].strip()
                if faktur.upper() == 'TOTAL' or not row[9].strip():
                    continue

                self.stats['encounters']['total_rows'] += 1

                tgl_str = row[1].strip()
                reg_str = row[2].strip()
                kode_book = row[6].strip()
                layanan = row[7].strip()
                no_id = row[8].strip()
                pasien = row[9].strip()
                nik = row[10].strip()
                doc_raw = row[14].strip()
                poli_raw = row[15].strip()
                diagnosa = row[17].strip()
                asuransi = row[18].strip()
                no_peserta = row[19].strip()
                total_amt = parse_amount(row[28])
                status = row[29].strip()

                # Anomaly & Test Filtering
                discard_reasons = []
                if status == 'Batal':
                    discard_reasons.append("Status 'Batal'")
                if not pasien or len(pasien) < 2:
                    discard_reasons.append("Empty Patient Name")
                if re.search(r'test|testing|contoh|coba|dummy|pemarah|nam depan', pasien, re.IGNORECASE):
                    discard_reasons.append(f"Test Patient Name ('{pasien}')")
                if re.search(r'test|noidentiassass|dummy', nik, re.IGNORECASE) or nik in ['123', '212312312', '21231243']:
                    discard_reasons.append(f"Dummy NIK ('{nik}')")
                if re.search(r'test', asuransi, re.IGNORECASE):
                    discard_reasons.append(f"Test Insurance ('{asuransi}')")

                if discard_reasons:
                    self.stats['encounters']['discarded'] += 1
                    self.anomalies['discarded_encounters'].append({
                        'row': row_idx,
                        'faktur': faktur,
                        'patient': pasien,
                        'doctor': doc_raw,
                        'total_amount': total_amt,
                        'reasons': discard_reasons,
                    })
                    continue

                self.stats['encounters']['valid'] += 1

                # Construct Unique External Encounter ID
                if faktur and faktur != '-':
                    external_id = faktur
                else:
                    external_id = f"ENC-HIST-{kode_book}-{no_id}"

                # Idempotency check
                if external_id in existing_enc_set:
                    self.stats['encounters']['skipped'] += 1
                    logger.debug(f"Skipping existing encounter: {external_id}")
                    continue

                # Parse DateTime
                dt_utc_str = parse_wib_datetime_to_utc(tgl_str, reg_str)

                # Clinical Unit & Poli Mapping
                is_hd = ('Heru Prasanto' in doc_raw) or ('N18' in diagnosa)
                if is_hd:
                    clinic_unit = 'hd'
                    poli_code = 'hd_routine'
                    analytic_code = 'ACC-HD'
                    service_product = self.service_product_map.get('SRV-HD-ROUTINE')
                    line_type = 'procedure'
                elif 'Gigi' in poli_raw:
                    clinic_unit = 'pratama'
                    poli_code = 'gigi'
                    analytic_code = 'PRAT-GIGI'
                    service_product = self.service_product_map.get('SRV-CONS-DENTAL')
                    line_type = 'consultation'
                elif 'Kandungan' in poli_raw or 'Bidan' in doc_raw:
                    clinic_unit = 'pratama'
                    poli_code = 'kia'
                    analytic_code = 'PRAT-KIA'
                    service_product = self.service_product_map.get('SRV-CONS-KIA')
                    line_type = 'consultation'
                elif 'Akupunktur' in poli_raw:
                    clinic_unit = 'pratama'
                    poli_code = 'umum'
                    analytic_code = 'PRAT-UMUM'
                    service_product = self.service_product_map.get('SRV-CONS-SPEC')
                    line_type = 'consultation'
                else:
                    clinic_unit = 'pratama'
                    poli_code = 'umum'
                    analytic_code = 'PRAT-UMUM'
                    service_product = self.service_product_map.get('SRV-CONS-GP')
                    line_type = 'consultation'

                # Fallback to general consultation if specific service missing
                if not service_product:
                    service_product = self.service_product_map.get('SRV-CONS-GP')

                # Payer Type Mapping
                asur_lower = asuransi.lower()
                if 'bpjs' in asur_lower:
                    payer_type = 'bpjs'
                elif asur_lower in ['', '-', 'none', 'tunai', 'cash']:
                    payer_type = 'cash'
                else:
                    payer_type = 'insurance'

                # Doctor resolution
                doctor_id = self.doctor_map.get(doc_raw)
                if not doctor_id and doc_raw:
                    # Try partial match
                    for k, d_id in self.doctor_map.items():
                        if doc_raw.lower() in k.lower() or k.lower() in doc_raw.lower():
                            doctor_id = d_id
                            break

                # Patient Partner resolution
                patient_id = patient_mrn_map.get(no_id)

                # Raw payload for audit trail
                raw_payload_dict = {
                    'csv_row': row_idx,
                    'tanggal': tgl_str,
                    'reg': reg_str,
                    'kode_book': kode_book,
                    'layanan': layanan,
                    'mrn': no_id,
                    'pasien': pasien,
                    'nik': nik,
                    'dokter': doc_raw,
                    'poliklinik': poli_raw,
                    'diagnosa': diagnosa,
                    'asuransi': asuransi,
                    'no_faktur': faktur,
                    'total_biaya': total_amt,
                    'status': status,
                }

                encounter_vals = {
                    'external_encounter_id': external_id,
                    'patient_mrn': no_id,
                    'patient_name': clean_patient_name(pasien),
                    'patient_id': patient_id,
                    'encounter_date': dt_utc_str or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    'clinic_unit': clinic_unit,
                    'poli_code': poli_code,
                    'doctor_id': doctor_id,
                    'payer_type': payer_type,
                    'sep_claim_number': no_peserta if payer_type == 'bpjs' else False,
                    'state': 'staged',  # Staged safely, without auto-posting invoices
                    'raw_payload': json.dumps(raw_payload_dict, ensure_ascii=False),
                }

                encounter = Encounter.create(encounter_vals)
                existing_enc_set.add(external_id)
                self.stats['encounters']['staged'] += 1

                # Create Encounter Line
                line_vals = {
                    'encounter_id': encounter.id,
                    'product_id': service_product,
                    'line_type': line_type,
                    'qty': 1.0,
                    'unit_price': total_amt,
                    'doctor_id': doctor_id,
                    'analytic_account_id': self.analytic_map.get(analytic_code) or self.analytic_map.get('ACC-PRATAMA'),
                }
                EncounterLine.create(line_vals)
                self.stats['encounters']['lines_created'] += 1

        logger.info(
            f"Encounters Migration Complete: Total={self.stats['encounters']['total_rows']}, "
            f"Valid={self.stats['encounters']['valid']}, Staged={self.stats['encounters']['staged']}, "
            f"Lines={self.stats['encounters']['lines_created']}, Discarded={self.stats['encounters']['discarded']}"
        )

    def generate_report(self):
        """Export comprehensive JSON anomaly & summary report."""
        report_data = {
            'timestamp': datetime.now().isoformat(),
            'statistics': self.stats,
            'anomalies_summary': {
                'total_discarded_patients': len(self.anomalies['discarded_patients']),
                'total_discarded_encounters': len(self.anomalies['discarded_encounters']),
            },
            'sample_discarded_patients': self.anomalies['discarded_patients'][:20],
            'sample_discarded_encounters': self.anomalies['discarded_encounters'][:20],
        }
        with open(REPORT_FILE, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
        logger.info(f"Anomaly report generated at: {REPORT_FILE}")


def run_migration(db_name='klinik-adera', force_update=False):
    """Main execution entry point."""
    logger.info("Initializing Odoo ORM environment...")
    import odoo
    import odoo.tools

    odoo.tools.config.parse_config([
        '-c', '/etc/odoo/odoo.conf',
        '-d', db_name,
        '--db_host', os.environ.get('HOST', 'db_adera'),
        '--db_user', os.environ.get('USER', 'odoo'),
        '--db_password', os.environ.get('PASSWORD', 'odoo'),
    ])

    from odoo.modules.registry import Registry
    registry = Registry(db_name)

    with registry.cursor() as cr:
        env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
        migrator = AderaDataMigrator(env, force_update=force_update)

        t_start = datetime.now()
        logger.info(f"Starting Clinical Data Migration for database: {db_name} (force_update={force_update})")

        try:
            migrator.ensure_service_products()
            migrator.migrate_doctors()
            migrator.migrate_patients(batch_size=1000)
            migrator.migrate_encounters()
            migrator.generate_report()

            cr.commit()
            t_end = datetime.now()
            logger.info(f"=== MIGRATION COMPLETED SUCCESSFULLY IN {(t_end - t_start).total_seconds():.2f} SECONDS ===")

        except Exception as e:
            cr.rollback()
            logger.exception(f"CRITICAL ERROR during migration. Rolled back changes: {e}")
            raise


if __name__ == '__main__':
    db = 'klinik-adera'
    force = '--force-update' in sys.argv
    for arg in sys.argv[1:]:
        if not arg.startswith('--'):
            db = arg
    run_migration(db, force_update=force)
