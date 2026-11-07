# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


class TestClinicBridge(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super(TestClinicBridge, cls).setUpClass()
        cls.doctor = cls.env['res.partner'].create({
            'name': 'dr. Test Sp.PD-KGH',
            'is_doctor': True,
            'doctor_type': 'specialist_hd',
            'sip_number': 'SIP.TEST.001',
            'npwp_nik': '3171000000000001',
            'has_npwp': True,
        })
        cls.patient = cls.env['res.partner'].create({
            'name': 'Pasien Test Sutrisno',
            'ref': 'RM-TEST-99',
            'customer_rank': 1,
        })

    def test_01_encounter_staging_and_idempotency(self):
        """Test staging creation and idempotency constraint."""
        enc1 = self.env['clinic.encounter'].create({
            'external_encounter_id': 'TEST-ENC-001',
            'patient_mrn': 'RM-TEST-99',
            'patient_name': 'Pasien Test Sutrisno',
            'clinic_unit': 'pratama',
            'poli_code': 'umum',
            'state': 'draft',
        })
        self.assertTrue(enc1.id)

        # Idempotency constraint should block duplicate external_encounter_id
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.env['clinic.encounter'].create({
                    'external_encounter_id': 'TEST-ENC-001',
                    'patient_mrn': 'RM-TEST-99',
                    'patient_name': 'Pasien Test Sutrisno Duplikat',
                    'clinic_unit': 'pratama',
                    'poli_code': 'umum',
                })

    def test_02_pph21_progressive_calculation(self):
        """Test PPh 21 calculation for Tenaga Ahli Dokter."""
        settlement = self.env['doctor.settlement'].new({
            'doctor_id': self.doctor.id,
            'date_from': '2026-11-01',
            'date_to': '2026-11-30',
        })
        # Rp 20.000.000 Gross -> DPP (50%) = Rp 10.000.000 -> PPh 21 (5%) = Rp 500.000
        dpp = 10000000.0
        tax = settlement._calculate_pph21_progressive(dpp, has_npwp=True)
        self.assertEqual(tax, 500000.0, "PPh 21 progressive 5% on 10jt DPP must be 500,000")

        # Test Non-NPWP 120% penalty
        tax_non_npwp = settlement._calculate_pph21_progressive(dpp, has_npwp=False)
        self.assertEqual(tax_non_npwp, 600000.0, "Non-NPWP tariff must be 120% (600,000)")

