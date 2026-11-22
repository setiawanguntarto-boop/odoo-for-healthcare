# -*- coding: utf-8 -*-
import json
from odoo.tests.common import HttpCase, tagged


@tagged("post_install", "-at_install", "adera_clinic_bridge", "adera_accounting")
class TestClinicalEncounterETL(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.api_token = cls.env["ir.config_parameter"].sudo().get_param(
            "adera_clinic_bridge.api_token", "adera_secret_token_2026"
        )
        cls.doc = cls.env["res.partner"].create({
            "name": "dr. Test Vaksinasi ETL",
            "is_doctor": True,
            "doctor_type": "general",
            "sip_number": "DOC-004-TEST",
            "ref": "DOC-004-TEST",
        })
        cls.aa_vaksin = cls.env["account.analytic.account"].search([("code", "=", "PRAT-VAKSIN")], limit=1)
        cls.aa_umum = cls.env["account.analytic.account"].search([("code", "=", "PRAT-UMUM")], limit=1)

    def _post_encounter(self, payload):
        return self.url_open(
            "/api/v1/clinic/encounter/sync",
            data=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_token}",
            },
        )

    def test_01_multi_tender_and_analytic_and_accrual(self):
        """Verify multi-tender 50% Cash + 50% QRIS, PRAT-VAKSIN analytic segregation, doctor accrual & idempotency."""
        # Create consumable product with standard_price > 0 for Anglo-Saxon COGS check
        spuit = self.env["product.product"].search([("default_code", "=", "MED-SPOID-ETL")], limit=1)
        if not spuit:
            spuit = self.env["product.product"].create({
                "name": "Spuit 3cc Terumo ETL",
                "default_code": "MED-SPOID-ETL",
                "type": "consu",
                "is_storable": True,
                "list_price": 15000.0,
                "standard_price": 5000.0,
            })

        payload = {
            "encounter_id": "ENC-ETL-TEST-001",
            "patient_id": "RM-ETL-9812",
            "patient_name": "Ny. Siti Rahma Test",
            "date": "2026-11-20 10:15:00",
            "service_unit": "PRAT-VAKSIN",
            "doctor_id": "DOC-004-TEST",
            "items": [
                {
                    "product_code": "SRV-VAX-HPV-TEST",
                    "name": "Paket Vaksinasi HPV Gardasil 9",
                    "quantity": 1,
                    "unit_price": 985000.0,
                    "category": "service",
                    "doctor_fee_amount": 150000.0,
                },
                {
                    "product_code": "MED-SPOID-ETL",
                    "name": "Spuit 3cc Terumo ETL",
                    "quantity": 1,
                    "unit_price": 15000.0,
                    "category": "consumable",
                    "lot_id": "LOT-TER-202611",
                },
            ],
            "payments": [
                {"method": "qris_gopay", "amount": 500000.0, "ref": "GOPAY-TRX-ETL-01"},
                {"method": "cash", "amount": 500000.0, "ref": "CASH-REG-ETL-01"},
            ],
        }

        # 1. First Webhook Call -> 201 Created
        resp1 = self._post_encounter(payload)
        self.assertEqual(resp1.status_code, 201, resp1.text)
        body1 = resp1.json()
        self.assertEqual(body1.get("state"), "posted")

        encounter = self.env["clinic.encounter"].search([("external_encounter_id", "=", "ENC-ETL-TEST-001")], limit=1)
        self.assertTrue(encounter)
        invoice = encounter.account_move_id
        self.assertTrue(invoice)
        self.assertAlmostEqual(invoice.amount_total, 1000000.0, places=2)
        # Multi-tender 50% Cash + 50% QRIS -> residual == 0.00
        self.assertAlmostEqual(invoice.amount_residual, 0.0, places=2)

        # 2. Analytic Segregation: Revenue (410010) & COGS (510010) on PRAT-VAKSIN, 0 on PRAT-UMUM
        vaksin_col = self.aa_vaksin.plan_id._column_name()
        umum_col = self.aa_umum.plan_id._column_name()
        rev_analytic = self.env["account.analytic.line"].search([
            (vaksin_col, "=", self.aa_vaksin.id),
            ("move_line_id", "in", invoice.line_ids.ids),
        ])
        self.assertTrue(rev_analytic, "Revenue analytic line must exist on PRAT-VAKSIN")
        umum_analytic = self.env["account.analytic.line"].search([
            (umum_col, "=", self.aa_umum.id),
            ("move_line_id", "in", invoice.line_ids.ids),
        ])
        self.assertFalse(umum_analytic, "PRAT-UMUM must not be touched by PRAT-VAKSIN encounter")

        cogs_moves = self.env["account.move"].search([("ref", "=", "COGS ENC-ETL-TEST-001")])
        if cogs_moves:
            cogs_analytic = self.env["account.analytic.line"].search([
                (vaksin_col, "=", self.aa_vaksin.id),
                ("move_line_id", "in", cogs_moves.line_ids.ids),
            ])
            self.assertTrue(cogs_analytic, "COGS 510010 must route to PRAT-VAKSIN")

        # 3. Doctor Accrual Coupling
        accrual = self.env["medical.fee.accrual"].search([
            ("encounter_reference", "=", "ENC-ETL-TEST-001")
        ], limit=1)
        self.assertTrue(accrual)
        self.assertAlmostEqual(accrual.doctor_fee_amount, 150000.0, places=2)
        self.assertTrue(accrual.accrual_move_id)

        # 4. Idempotency Test: Sending identical payload twice -> HTTP 200 & skipped
        move_count_before = self.env["account.move"].search_count([])
        resp2 = self._post_encounter(payload)
        self.assertEqual(resp2.status_code, 200)
        body2 = resp2.json()
        self.assertIn("Record already processed - skipped", body2.get("message", ""))
        move_count_after = self.env["account.move"].search_count([])
        self.assertEqual(move_count_before, move_count_after, "Idempotent call must not create duplicate moves")
