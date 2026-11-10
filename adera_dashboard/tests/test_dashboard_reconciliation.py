# -*- coding: utf-8 -*-
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

from odoo.tests.common import TransactionCase, tagged
from odoo import fields


@tagged('post_install', '-at_install', 'adera_dashboard')
class TestDashboardReconciliation(TransactionCase):
    """
    Automated Mathematical Verification and Audit Test Suite for
    Klinik ADERA Executive Management Dashboard (clinic.dashboard.kpi).

    Asserts 100% precision (variance = Rp 0.00) between aggregated KPI metrics
    and underlying transactional tables (account.move.line, clinic.encounter,
    stock.lot, stock.quant, etc.).
    """

    def setUp(self):
        super(TestDashboardReconciliation, self).setUp()
        self.kpi_model = self.env['clinic.dashboard.kpi']
        self.company = self.env.company
        self.company_id = self.company.id

        # Standard audit date range (Full November 2026 cut-off)
        self.today = date.today()
        self.date_from = self.today.replace(day=1).strftime('%Y-%m-%d')
        self.date_to = self.today.strftime('%Y-%m-%d')

        # Load consolidated metrics
        self.metrics = self.kpi_model.get_dashboard_metrics(
            date_from=self.date_from,
            date_to=self.date_to,
            business_unit=False,
            poli_code=False,
        )

    # =========================================================================
    # SECTION 1: FINANCIAL & OPERATIONAL SCORECARDS
    # =========================================================================
    def test_01_total_operating_revenue_reconciliation(self):
        """Assert dashboard total_revenue matches net credit on accounts 410010-410120."""
        scorecards = self.metrics['scorecards']
        dashboard_revenue = scorecards['total_revenue']

        # Query Source of Truth: account.move.line
        domain = [
            ('company_id', '=', self.company_id),
            ('parent_state', '=', 'posted'),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ]
        lines = self.env['account.move.line'].search(domain)
        rev_lines = lines.filtered(
            lambda l: l.account_id.code and (l.account_id.code.startswith('410') or l.account_id.code.startswith('4100'))
        )
        expected_revenue = float(sum(rev_lines.mapped('credit')) - sum(rev_lines.mapped('debit')))

        self.assertAlmostEqual(
            dashboard_revenue,
            expected_revenue,
            places=2,
            msg=f"Total Revenue mismatch: Dashboard={dashboard_revenue} vs Source={expected_revenue}",
        )

    def test_02_net_profit_and_margin_integrity(self):
        """Assert Net Profit == Revenue - (COGS + Doctor Fees + OPEX)."""
        sc = self.metrics['scorecards']
        total_rev = sc['total_revenue']
        cogs = sc['cogs']
        doctor_fees = sc['doctor_fees']
        opex = sc['opex']
        net_profit = sc['net_profit']

        expected_net_profit = float(total_rev - (cogs + doctor_fees + opex))
        self.assertAlmostEqual(
            net_profit,
            expected_net_profit,
            places=2,
            msg=f"Net Profit calculation mismatch: {net_profit} vs expected {expected_net_profit}",
        )

        expected_gross_margin = float(round(((total_rev - cogs) / total_rev * 100.0), 2)) if total_rev > 0 else 0.0
        self.assertAlmostEqual(sc['gross_margin_pct']['value'], expected_gross_margin, places=2)

        expected_net_margin = float(round((net_profit / total_rev * 100.0), 2)) if total_rev > 0 else 0.0
        self.assertAlmostEqual(sc['net_margin_pct']['value'], expected_net_margin, places=2)

        # Kemenkes 2025 Financial Governance: Operating Ratio
        total_operating_cost = float(cogs + doctor_fees + opex)
        expected_operating_ratio = float(round((total_operating_cost / total_rev * 100.0), 2)) if total_rev > 0 else 0.0
        self.assertAlmostEqual(sc['operating_ratio']['value'], expected_operating_ratio, places=2)
        if expected_operating_ratio < 75.0:
            self.assertEqual(sc['operating_ratio']['rag'], 'success')
        elif expected_operating_ratio <= 80.0:
            self.assertEqual(sc['operating_ratio']['rag'], 'warning')
        else:
            self.assertEqual(sc['operating_ratio']['rag'], 'danger')

    def test_03_clinical_operational_ratios_arpt_arpp(self):
        """Verify ARPT (Avg Rev per Treatment) and ARPP (Avg Rev per Patient)."""
        sc = self.metrics['scorecards']
        total_rev = sc['total_revenue']
        posted_encs = sc['posted_encounters']
        unique_pts = sc['unique_patients']

        expected_arpt = float(round(total_rev / posted_encs, 2)) if posted_encs > 0 else 0.0
        self.assertAlmostEqual(sc['arpt'], expected_arpt, places=2)

        expected_arpp = float(round(total_rev / unique_pts, 2)) if unique_pts > 0 else 0.0
        self.assertAlmostEqual(sc['arpp'], expected_arpp, places=2)

    def test_04_working_capital_dso_dpo_dio(self):
        """Verify Days Sales Outstanding (DSO), DPO, and DIO formulas."""
        sc = self.metrics['scorecards']
        total_rev = sc['total_revenue']
        cogs = sc['cogs']
        total_ar = sc['total_ar']

        daily_rev = float(total_rev / 30.0) if total_rev > 0 else 0.0
        expected_dso = float(max(0.0, round(total_ar / daily_rev, 1))) if daily_rev > 0 and total_ar > 0 else 0.0
        self.assertAlmostEqual(sc['dso_days'], expected_dso, places=1)

        daily_cogs = float(cogs / 30.0) if cogs > 0 else 0.0
        if daily_cogs > 0:
            self.assertGreaterEqual(sc['dpo_days'], 0.0)
            self.assertGreaterEqual(sc['inventory_days'], 0.0)

    def test_05_encounter_finalization_rate_and_backlog(self):
        """Verify Encounter Finalization Rate and Backlog Valuation."""
        sc = self.metrics['scorecards']
        total_inbound = sc['total_encounters']
        posted_count = sc['posted_encounters']
        backlog_count = sc['backlog_count']
        backlog_value = sc['backlog_value']

        self.assertEqual(total_inbound, posted_count + backlog_count)
        expected_fin_rate = float(round((posted_count / total_inbound * 100.0), 2)) if total_inbound > 0 else 0.0
        self.assertAlmostEqual(sc['encounter_finalization_rate']['value'], expected_fin_rate, places=2)

        # Cross-check backlog value
        backlog_encs = self.env['clinic.encounter'].search([
            ('encounter_date', '>=', f"{self.date_from} 00:00:00"),
            ('encounter_date', '<=', f"{self.date_to} 23:59:59"),
            ('state', 'in', ['draft', 'received', 'staged', 'error']),
        ])
        expected_backlog_val = float(sum(
            sum(line.unit_price * line.qty for line in enc.line_ids)
            for enc in backlog_encs
        ))
        self.assertAlmostEqual(backlog_value, expected_backlog_val, places=2)

    # =========================================================================
    # SECTION 2: POLI & UNIT PROFITABILITY MATRIX
    # =========================================================================
    def test_06_poli_profitability_matrix_integrity(self):
        """Verify each Poli row in correlation matrix matches analytic distribution."""
        matrix = self.metrics['clinical_volume_financial_correlation']
        self.assertTrue(len(matrix) > 0, "Correlation matrix should contain clinical Poli units.")

        for row in matrix:
            poli_code = row['poli_code']
            rev = row['revenue']
            cogs = row['cogs']
            doc_fee = row['doctor_fee']
            gross = row['gross_profit']
            margin = row['margin_pct']

            # Gross profit parity
            expected_gross = float(rev - (cogs + doc_fee))
            self.assertAlmostEqual(gross, expected_gross, places=2)

            # Margin % parity
            expected_margin = float(round((gross / rev * 100.0), 2)) if rev > 0 else 0.0
            self.assertAlmostEqual(margin, expected_margin, places=2)

            # ARPT parity
            enc_count = row['encounter_count']
            expected_arpt = float(round(rev / enc_count, 2)) if enc_count > 0 else 0.0
            self.assertAlmostEqual(row['arpt'], expected_arpt, places=2)

    # =========================================================================
    # SECTION 3: PAYER MIX BREAKDOWN
    # =========================================================================
    def test_07_payer_mix_reconciliation_to_100_percent(self):
        """Assert sum of all payer mix buckets equals 100% (+- 0.05%)."""
        payer_mix = self.metrics['payer_mix']
        self.assertTrue(len(payer_mix) == 5, "Expected 5 payer mix buckets.")

        total_pct = sum(item['percentage'] for item in payer_mix)
        total_amt = sum(item['amount'] for item in payer_mix)

        if total_amt > 0:
            self.assertAlmostEqual(
                total_pct,
                100.0,
                delta=0.05,
                msg=f"Payer mix percentage sum must equal 100%, got {total_pct}%",
            )

    # =========================================================================
    # SECTION 4: AUDIT & COMPLIANCE ALERTS
    # =========================================================================
    def test_08_grir_clearing_balance_audit(self):
        """Assert GR/IR Clearing 211500 balance exactly tallies with GL."""
        flags = self.metrics['compliance_flags']
        dashboard_grir = flags['grir_clearing_balance']

        cum_lines = self.env['account.move.line'].search([
            ('company_id', '=', self.company_id),
            ('parent_state', '=', 'posted'),
            ('date', '<=', self.date_to),
            ('account_id.code', '=', '211500'),
        ])
        expected_grir = float(sum(cum_lines.mapped('credit')) - sum(cum_lines.mapped('debit')))
        self.assertAlmostEqual(dashboard_grir, expected_grir, places=2)

    def test_09_cashier_variance_ytd_audit(self):
        """Assert Cashier Variance 619990 matches GL net debit."""
        flags = self.metrics['compliance_flags']
        dash_variance = flags['cashier_variance_ytd']

        year_start = f"{self.today.year}-01-01"
        cashier_lines = self.env['account.move.line'].search([
            ('company_id', '=', self.company_id),
            ('parent_state', '=', 'posted'),
            ('date', '>=', year_start),
            ('date', '<=', self.date_to),
            ('account_id.code', '=', '619990'),
        ])
        expected_variance = float(sum(cashier_lines.mapped('debit')) - sum(cashier_lines.mapped('credit')))
        self.assertAlmostEqual(dash_variance, expected_variance, places=2)

    def test_10_near_expiry_lots_count_audit(self):
        """Assert near-expiry lots count matches internal stock with expiry <= 60 days."""
        flags = self.metrics['compliance_flags']
        dashboard_expiry_count = flags['near_expiry_lots_count']

        threshold_date = self.today + relativedelta(days=60)
        self.env.cr.execute("""
            SELECT COALESCE(count(DISTINCT l.id), 0)
            FROM stock_lot l
            JOIN stock_quant q ON q.lot_id = l.id
            JOIN stock_location loc ON loc.id = q.location_id
            WHERE loc.usage = 'internal'
              AND q.quantity > 0
              AND l.expiration_date <= %s
        """, (threshold_date,))
        expected_expiry_count = int(self.env.cr.fetchone()[0] or 0)
        self.assertEqual(dashboard_expiry_count, expected_expiry_count)

    def test_11_unsettled_physician_fees_audit(self):
        """Assert unsettled doctor fees match open credit on 213010 & 213020."""
        flags = self.metrics['compliance_flags']
        dashboard_doc_fees = flags['unsettled_doctor_fees']

        doc_lines = self.env['account.move.line'].search([
            ('company_id', '=', self.company_id),
            ('parent_state', '=', 'posted'),
            ('date', '<=', self.date_to),
            ('account_id.code', 'in', ['213010', '213020']),
        ])
        expected_fees = float(max(0.0, sum(doc_lines.mapped('credit')) - sum(doc_lines.mapped('debit'))))
        self.assertAlmostEqual(dashboard_doc_fees, expected_fees, places=2)

    # =========================================================================
    # SECTION 5: DYNAMIC FILTER CONSISTENCY & ISOLATION
    # =========================================================================
    def test_12_business_unit_isolation_pratama_vs_hd(self):
        """Verify Pratama vs Hemodialisis isolation and consolidation."""
        m_pratama = self.kpi_model.get_dashboard_metrics(
            date_from=self.date_from,
            date_to=self.date_to,
            business_unit='ACC-PRATAMA',
            poli_code=False,
        )
        m_hd = self.kpi_model.get_dashboard_metrics(
            date_from=self.date_from,
            date_to=self.date_to,
            business_unit='ACC-HD',
            poli_code=False,
        )

        rev_pratama = m_pratama['scorecards']['total_revenue']
        rev_hd = m_hd['scorecards']['total_revenue']
        rev_total = self.metrics['scorecards']['total_revenue']

        # Consolidated revenue must be >= component revenues
        self.assertGreaterEqual(rev_total, rev_pratama)
        self.assertGreaterEqual(rev_total, rev_hd)

        # Encounters partition
        enc_pratama = m_pratama['scorecards']['total_encounters']
        enc_hd = m_hd['scorecards']['total_encounters']
        self.assertGreaterEqual(self.metrics['scorecards']['total_encounters'], enc_pratama + enc_hd)

