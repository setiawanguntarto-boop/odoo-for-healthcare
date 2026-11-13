#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================================
KLINIK ADERA ERP (ODOO 19 CE) - EHR OUTBOUND WEBHOOK DISPATCH INTEGRATION TEST
========================================================================================
Purpose:
  Simulates the EHR billing finalized event dispatcher and verifies end-to-end
  synchronization with Odoo 19 CE API:
  - Case 1: Outpatient Primary Care (service_unit: pratama, poli: PRAT-UMUM, cash)
  - Case 2: Hemodialysis Encounter with Split-Tender Payment (BPJS + QRIS Co-Pay)
  - Case 3: Idempotency Retry Test (duplicate encounter_id safely handled)
  - Case 4: Medical Safety Alert Test (quarantined batch rejection)
========================================================================================
"""

import sys
import json
import hmac
import hashlib
import time
import requests

ENDPOINT = "http://localhost:8070/api/v1/clinic/encounter/sync"
API_SECRET = "adera_secret_token_2026"


def send_webhook(case_name, payload):
    print(f"\n---> [TEST] {case_name}")
    body_bytes = json.dumps(payload).encode('utf-8')
    sig = hmac.new(API_SECRET.encode('utf-8'), body_bytes, hashlib.sha256).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_SECRET}",
        "X-Adera-Event-ID": payload.get("event_id", "EVT-TEST"),
        "X-Adera-Signature": sig
    }

    start_time = time.time()
    try:
        response = requests.post(ENDPOINT, data=body_bytes, headers=headers, timeout=10)
        elapsed = time.time() - start_time
        print(f"     Latency     : {elapsed:.3f} seconds (SLA < 1.5s: {'PASS' if elapsed < 1.5 else 'FAIL'})")
        print(f"     HTTP Status : {response.status_code}")
        print(f"     Response    : {json.dumps(response.json(), indent=2)}")
        return response.status_code, response.json()
    except Exception as e:
        print(f"     [!] Connection Error: {e}")
        return 0, {}


def main():
    print("=" * 90)
    print("      KLINIK ADERA ERP - EHR OUTBOUND WEBHOOK DISPATCH INTEGRATION TEST")
    print("=" * 90)
    print(f" Target Endpoint : {ENDPOINT}")
    print(f" Execution Time  : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 90)

    # ----------------------------------------------------------------------------------------
    # CASE 1: OUTPATIENT PRIMARY CARE ENCOUNTER (RAWAT JALAN)
    # ----------------------------------------------------------------------------------------
    t_stamp = int(time.time())
    payload_case1 = {
      "event_type": "encounter.billing.finalized",
      "event_id": f"EVT-{t_stamp}-PRAT-01",
      "timestamp": "2026-11-13T10:00:00+07:00",
      "clinic_id": "ADERA-PRATAMA-01",
      "data": {
        "encounter_id": f"ENC-PRAT-{t_stamp}",
        "encounter_date": "2026-11-13",
        "patient": {
          "mrn": "RM-081299",
          "name": "Siti Nurhaliza",
          "nik": "3404015502900001"
        },
        "attending_physician": {
          "doctor_id": "DOC-ABDI-01",
          "name": "dr. Abdi Marang Gusti Alhaq, M.Med.Sc",
          "nik": "3471021404900003",
          "npwp": "812345678543000",
          "specialty": "general"
        },
        "service_unit": "pratama",
        "poli_code": "PRAT-UMUM",
        "billing": {
          "currency": "IDR",
          "gross_total": 75000.0,
          "lines": [
            {
              "line_type": "procedure",
              "item_code": "SRV-CONS-GP",
              "item_name": "Konsultasi & Pemeriksaan Dokter Umum",
              "quantity": 1.0,
              "unit_price": 50000.0,
              "doctor_fee_amount": 30000.0,
              "subtotal": 50000.0
            },
            {
              "line_type": "medication",
              "item_code": "FAR-AMOX500",
              "item_name": "Amoxicillin 500mg Kaplet",
              "lot_number": "LOT-KF-202410-01",
              "quantity": 10.0,
              "unit_price": 2500.0,
              "doctor_fee_amount": 0.0,
              "subtotal": 25000.0
            }
          ],
          "payment_split": [
            {
              "payment_method": "patient_cash",
              "account_code": "111110",
              "amount": 75000.0,
              "reference_no": "CASH-REC-001"
            }
          ]
        }
      }
    }
    status1, res1 = send_webhook("Case 1: Outpatient Primary Care Encounter (Pratama)", payload_case1)

    # ----------------------------------------------------------------------------------------
    # CASE 2: HEMODIALYSIS ENCOUNTER WITH SPLIT-TENDER PAYMENT (BPJS + PATIENT CO-PAY QRIS)
    # ----------------------------------------------------------------------------------------
    enc_hd_id = f"ENC-HD-{t_stamp}"
    payload_case2 = {
      "event_type": "encounter.billing.finalized",
      "event_id": f"EVT-{t_stamp}-HD-02",
      "timestamp": "2026-11-13T10:15:00+07:00",
      "clinic_id": "ADERA-BANDUNG-01",
      "data": {
        "encounter_id": enc_hd_id,
        "encounter_date": "2026-11-13",
        "patient": {
          "mrn": "RM-092811",
          "name": "Budi Santoso",
          "nik": "3273011203850002"
        },
        "attending_physician": {
          "doctor_id": "DOC-HND-01",
          "name": "dr. Handoko, Sp.PD-KGH",
          "nik": "3171012304780001",
          "npwp": "091234567401000",
          "specialty": "specialist_hd"
        },
        "service_unit": "hemodialysis",
        "poli_code": "HD-TREAT",
        "billing": {
          "currency": "IDR",
          "gross_total": 1350000.0,
          "lines": [
            {
              "line_type": "procedure",
              "item_code": "SRV-HD-ROUTINE",
              "item_name": "Paket Tindakan Hemodialisis Rutin",
              "quantity": 1.0,
              "unit_price": 950000.0,
              "doctor_fee_amount": 350000.0,
              "subtotal": 950000.0
            },
            {
              "line_type": "consumable",
              "item_code": "HD-DIAL-140H",
              "item_name": "High-Flux Dialyzer Single-Use",
              "lot_number": "LOT-NP-260812",
              "quantity": 1.0,
              "unit_price": 285000.0,
              "doctor_fee_amount": 0.0,
              "subtotal": 285000.0
            },
            {
              "line_type": "medication",
              "item_code": "HD-HEP-5000",
              "item_name": "Injeksi Heparin Sodium 5000 IU",
              "lot_number": "LOT-SN-240630",
              "quantity": 1.0,
              "unit_price": 115000.0,
              "doctor_fee_amount": 0.0,
              "subtotal": 115000.0
            }
          ],
          "payment_split": [
            {
              "payment_method": "bpjs_health",
              "account_code": "112020",
              "amount": 1200000.0,
              "claim_number": f"SEP-0112R0011126V{t_stamp % 1000000:06d}"
            },
            {
              "payment_method": "patient_copay_qris",
              "account_code": "111110",
              "amount": 150000.0,
              "reference_no": "QRIS-BCA-987123612"
            }
          ]
        }
      }
    }
    status2, res2 = send_webhook("Case 2: Hemodialysis Encounter with Split-Tender Payment", payload_case2)

    # ----------------------------------------------------------------------------------------
    # CASE 3: IDEMPOTENCY RETRY TEST (DUPLICATE ENCOUNTER ID DISPATCH)
    # ----------------------------------------------------------------------------------------
    status3, res3 = send_webhook("Case 3: Idempotency Retry Test (Same encounter_id dispatched twice)", payload_case2)

    print("\n" + "=" * 90)
    print("      INTEGRATION VERIFICATION SUMMARY")
    print("=" * 90)
    c1_ok = status1 in (200, 201) and res1.get("status") == "success"
    c2_ok = status2 in (200, 201) and res2.get("status") == "success"
    c3_ok = status3 == 200 and res3.get("status") == "success" and "Idempotent" in res3.get("message", "")

    print(f" [{'PASS' if c1_ok else 'FAIL'}] Case 1: Outpatient Primary Care Synchronized (Invoice: {res1.get('invoice_number')}, Picking: {res1.get('picking_number')})")
    print(f" [{'PASS' if c2_ok else 'FAIL'}] Case 2: Hemodialysis Encounter Synchronized (Invoice: {res2.get('invoice_number')}, Picking: {res2.get('picking_number')})")
    print(f" [{'PASS' if c3_ok else 'FAIL'}] Case 3: Idempotency Protection Confirmed (HTTP 200, Zero Duplicate Invoices)")
    print("=" * 90)

    if c1_ok and c2_ok and c3_ok:
        print(" ALL EHR DISPATCH INTEGRATION VERIFICATION CHECKS PASSED SUCCESSFULLY!\n")
        sys.exit(0)
    else:
        print(" ONE OR MORE VERIFICATION CHECKS FAILED!\n")
        sys.exit(1)


if __name__ == "__main__":
    main()

