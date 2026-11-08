# -*- coding: utf-8 -*-
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class ClinicDashboardKPI(models.AbstractModel):
    _name = 'clinic.dashboard.kpi'
    _description = 'Klinik ADERA Executive Management KPI Aggregator'

    @api.model
    def get_dashboard_metrics(self, date_from=False, date_to=False, business_unit=False, poli_code=False):
        """
        Kalkulasi dinamis KPI Eksekutif Klinik ADERA berstandar SAK EMKM / PSAK.
        Strictly zero mutations (Read-Only Analytical Aggregator).
        """
        today = date.today()
        if not date_from:
            date_from = today.replace(day=1).strftime('%Y-%m-%d')
        if not date_to:
            date_to = today.strftime('%Y-%m-%d')

        company = self.env.company
        company_id = company.id

        # Mapping Analytic Accounts
        analytic_accs = self.env['account.analytic.account'].search([])
        code_to_acc = {acc.code: acc for acc in analytic_accs if acc.code}

        target_analytic_ids = None
        if poli_code and poli_code != 'all':
            target_acc = code_to_acc.get(poli_code)
            if target_acc:
                target_analytic_ids = {target_acc.id}
        elif business_unit == 'ACC-PRATAMA':
            prat_codes = ['ACC-PRATAMA', 'PRAT-UMUM', 'PRAT-GIGI', 'PRAT-KIA', 'PRAT-LAB', 'PRAT-RAD', 'PRAT-FARM']
            target_analytic_ids = {code_to_acc[c].id for c in prat_codes if c in code_to_acc}
        elif business_unit == 'ACC-HD':
            hd_codes = ['ACC-HD', 'HD-TREAT', 'HD-PHARM', 'HD-VIP']
            target_analytic_ids = {code_to_acc[c].id for c in hd_codes if c in code_to_acc}

        # Helper: Analytic filter for move lines
        def _matches_analytic(l):
            if not target_analytic_ids:
                return True
            if not l.analytic_distribution:
                return False
            return any(str(aid) in l.analytic_distribution for aid in target_analytic_ids)

        # -------------------------------------------------------------
        # 1. MOVE LINES QUERY (Period & Cumulative)
        # -------------------------------------------------------------
        period_domain = [
            ('company_id', '=', company_id),
            ('parent_state', '=', 'posted'),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ]
        period_lines = self.env['account.move.line'].search(period_domain)

        cum_domain = [
            ('company_id', '=', company_id),
            ('parent_state', '=', 'posted'),
            ('date', '<=', date_to),
        ]
        cum_lines = self.env['account.move.line'].search(cum_domain)

        # Operating Revenue (410010 - 410120, 41000010)
        rev_lines = period_lines.filtered(
            lambda l: l.account_id.code and (l.account_id.code.startswith('410') or l.account_id.code.startswith('4100'))
        )
        if target_analytic_ids:
            rev_lines = rev_lines.filtered(_matches_analytic)
        total_revenue = float(sum(rev_lines.mapped('credit')) - sum(rev_lines.mapped('debit')))

        # COGS (510010 - 510040, 51000010, 51000020)
        cogs_lines = period_lines.filtered(
            lambda l: l.account_id.code and l.account_id.code.startswith(('5100', '51000'))
        )
        if target_analytic_ids:
            cogs_lines = cogs_lines.filtered(_matches_analytic)
        cogs = float(sum(cogs_lines.mapped('debit')) - sum(cogs_lines.mapped('credit')))

        # Doctor Fees (510110 - 510130)
        doc_fee_lines = period_lines.filtered(
            lambda l: l.account_id.code and l.account_id.code.startswith('5101')
        )
        if target_analytic_ids:
            doc_fee_lines = doc_fee_lines.filtered(_matches_analytic)
        doctor_fees = float(sum(doc_fee_lines.mapped('debit')) - sum(doc_fee_lines.mapped('credit')))

        # OPEX (610010 - 619990, 61100010)
        opex_lines = period_lines.filtered(
            lambda l: l.account_id.code and (
                l.account_id.code.startswith('610') or l.account_id.code.startswith('619') or l.account_id.code.startswith('611')
            )
        )
        if target_analytic_ids:
            opex_lines = opex_lines.filtered(_matches_analytic)
        opex = float(sum(opex_lines.mapped('debit')) - sum(opex_lines.mapped('credit')))

        net_profit = float(total_revenue - (cogs + doctor_fees + opex))

        gross_margin_pct = float(round(((total_revenue - cogs) / total_revenue * 100.0), 2)) if total_revenue > 0 else 0.0
        net_margin_pct = float(round((net_profit / total_revenue * 100.0), 2)) if total_revenue > 0 else 0.0

        # RAG Rules
        gross_margin_rag = "success" if gross_margin_pct >= 55.0 else ("warning" if gross_margin_pct >= 40.0 else "danger")
        net_margin_rag = "success" if net_margin_pct >= 20.0 else ("warning" if net_margin_pct >= 10.0 else "danger")

        # -------------------------------------------------------------
        # 2. ENCOUNTERS QUERY
        # -------------------------------------------------------------
        enc_domain = [
            ('encounter_date', '>=', f"{date_from} 00:00:00"),
            ('encounter_date', '<=', f"{date_to} 23:59:59"),
        ]
        if business_unit == 'ACC-PRATAMA':
            enc_domain.append(('clinic_unit', '=', 'pratama'))
        elif business_unit == 'ACC-HD':
            enc_domain.append(('clinic_unit', '=', 'hd'))

        if poli_code and poli_code != 'all':
            code_to_poli = {
                'PRAT-UMUM': 'umum',
                'PRAT-GIGI': 'gigi',
                'PRAT-KIA': 'kia',
                'PRAT-LAB': 'lab',
                'PRAT-RAD': 'rad',
                'PRAT-FARM': 'farmasi',
                'HD-TREAT': 'hd_routine',
                'HD-VIP': 'hd_special',
                'HD-PHARM': 'hd_special',
            }
            mapped_poli = code_to_poli.get(poli_code)
            if mapped_poli:
                enc_domain.append(('poli_code', '=', mapped_poli))

        encounters = self.env['clinic.encounter'].search(enc_domain)
        total_inbound = len(encounters)
        posted_encounters = encounters.filtered(lambda e: e.state == 'posted')
        posted_count = len(posted_encounters)
        backlog_encounters = encounters.filtered(lambda e: e.state in ['draft', 'received', 'staged', 'error'])
        backlog_count = len(backlog_encounters)

        # Backlog Value (Sum of encounter line price * qty)
        backlog_value = float(sum(
            sum(line.unit_price * line.qty for line in enc.line_ids)
            for enc in backlog_encounters
        ))

        # Unique patients in date range
        unique_mrns = set(encounters.mapped('patient_mrn'))
        unique_patients_count = len(unique_mrns)

        # Average Revenue Metrics (ARPT & ARPP)
        arpt = float(round(total_revenue / posted_count, 2)) if posted_count > 0 else 0.0
        arpp = float(round(total_revenue / unique_patients_count, 2)) if unique_patients_count > 0 else 0.0

        # Encounter Finalization Rate
        finalization_rate = float(round((posted_count / total_inbound * 100.0), 2)) if total_inbound > 0 else 0.0
        finalization_rag = "success" if finalization_rate >= 98.0 else ("warning" if finalization_rate >= 90.0 else "danger")

        # -------------------------------------------------------------
        # 3. WORKING CAPITAL & DAYS METRICS (DSO, DPO, DIO, TOTAL AR)
        # -------------------------------------------------------------
        # Balance of Accounts 112010 (Self-Pay), 112020 (BPJS Claim), 112030 (Private Insurance)
        ar_bpjs_lines = cum_lines.filtered(lambda l: l.account_id.code == '112020')
        ar_bpjs = float(sum(ar_bpjs_lines.mapped('debit')) - sum(ar_bpjs_lines.mapped('credit')))

        ar_self_pay_lines = cum_lines.filtered(lambda l: l.account_id.code in ['112010', '11210010', '11210011'])
        ar_self_pay = float(sum(ar_self_pay_lines.mapped('debit')) - sum(ar_self_pay_lines.mapped('credit')))

        ar_insurance_lines = cum_lines.filtered(lambda l: l.account_id.code == '112030')
        ar_insurance = float(sum(ar_insurance_lines.mapped('debit')) - sum(ar_insurance_lines.mapped('credit')))

        total_ar = float(max(0.0, ar_bpjs + ar_self_pay + ar_insurance))

        # DSO: Total AR / (Total Operating Revenue / 30)
        daily_rev = float(total_revenue / 30.0) if total_revenue > 0 else 0.0
        dso_days = float(max(0.0, round(total_ar / daily_rev, 1))) if daily_rev > 0 and total_ar > 0 else 0.0

        # DPO: Accounts Payable 211010 / (COGS / 30)
        ap_lines = cum_lines.filtered(lambda l: l.account_id.code in ['211010', '21100010'])
        open_ap_balance = float(max(0.0, sum(ap_lines.mapped('credit')) - sum(ap_lines.mapped('debit'))))
        daily_cogs = float(cogs / 30.0) if cogs > 0 else 0.0
        dpo_days = float(max(0.0, round(open_ap_balance / daily_cogs, 1))) if daily_cogs > 0 and open_ap_balance > 0 else 0.0

        # DIO: Stock Valuation 114010-114040, 11300180 / (COGS / 30)
        stock_lines = cum_lines.filtered(
            lambda l: l.account_id.code and l.account_id.code in ['114010', '114020', '114030', '114040', '11300180']
        )
        stock_valuation = float(max(0.0, sum(stock_lines.mapped('debit')) - sum(stock_lines.mapped('credit'))))
        inventory_days = float(max(0.0, round(stock_valuation / daily_cogs, 1))) if daily_cogs > 0 and stock_valuation > 0 else 0.0

        # -------------------------------------------------------------
        # 4. HEALTHCARE WIDGET: TOP 5 CLINICAL SERVICES & PROCEDURES
        # -------------------------------------------------------------
        enc_ids = encounters.ids
        top_services = []
        if enc_ids:
            query_services = """
                SELECT COALESCE(p.name->>'en_US', 'Layanan Medis') as name,
                       el.line_type,
                       COALESCE(SUM(el.qty), 0) as total_qty,
                       COALESCE(SUM(el.unit_price * el.qty), 0) as total_rev
                FROM clinic_encounter_line el
                JOIN product_product pp ON pp.id = el.product_id
                JOIN product_template p ON p.id = pp.product_tmpl_id
                WHERE el.encounter_id IN %s
                  AND el.line_type IN ('consultation', 'procedure', 'lab', 'rad')
                GROUP BY COALESCE(p.name->>'en_US', 'Layanan Medis'), el.line_type
                ORDER BY total_rev DESC
                LIMIT 5
            """
            self.env.cr.execute(query_services, (tuple(enc_ids),))
            type_label_map = {
                'consultation': 'Konsultasi Dokter',
                'procedure': 'Tindakan Medis',
                'lab': 'Laboratorium Medis',
                'rad': 'Radiologi / Diagnostik',
            }
            for row in self.env.cr.fetchall():
                top_services.append({
                    'name': row[0],
                    'type_label': type_label_map.get(row[1], 'Prosedur Medis'),
                    'qty': float(row[2]),
                    'revenue': float(row[3]),
                })

        # -------------------------------------------------------------
        # 5. HEALTHCARE WIDGET: TOP 5 DISPENSED PHARMACY & CONSUMABLES
        # -------------------------------------------------------------
        top_pharmacy = []
        if enc_ids:
            query_pharmacy = """
                SELECT COALESCE(p.name->>'en_US', 'Farmasi / Obat') as name,
                       COALESCE(SUM(el.qty), 0) as total_qty,
                       COALESCE(SUM(el.unit_price * el.qty), 0) as total_val
                FROM clinic_encounter_line el
                JOIN product_product pp ON pp.id = el.product_id
                JOIN product_template p ON p.id = pp.product_tmpl_id
                WHERE el.encounter_id IN %s
                  AND el.line_type = 'medication'
                GROUP BY COALESCE(p.name->>'en_US', 'Farmasi / Obat')
                ORDER BY total_val DESC
                LIMIT 5
            """
            self.env.cr.execute(query_pharmacy, (tuple(enc_ids),))
            for row in self.env.cr.fetchall():
                top_pharmacy.append({
                    'name': row[0],
                    'qty': float(row[1]),
                    'total_value': float(row[2]),
                })

        if len(top_pharmacy) < 5:
            move_query = """
                SELECT COALESCE(p.name->>'en_US', 'Obat & BHP') as name,
                       COALESCE(SUM(sm.product_uom_qty), 0) as total_qty,
                       COALESCE(SUM(sm.product_uom_qty * COALESCE(pp.standard_price, 0)), 0) as total_val
                FROM stock_move sm
                JOIN product_product pp ON pp.id = sm.product_id
                JOIN product_template p ON p.id = pp.product_tmpl_id
                WHERE sm.state = 'done'
                  AND sm.date >= %s AND sm.date <= %s
                GROUP BY COALESCE(p.name->>'en_US', 'Obat & BHP')
                ORDER BY total_qty DESC
                LIMIT 5
            """
            self.env.cr.execute(move_query, (f"{date_from} 00:00:00", f"{date_to} 23:59:59"))
            existing_names = {x['name'] for x in top_pharmacy}
            for row in self.env.cr.fetchall():
                if row[0] not in existing_names and len(top_pharmacy) < 5:
                    top_pharmacy.append({
                        'name': row[0],
                        'qty': float(row[1]),
                        'total_value': float(row[2]),
                    })

        # -------------------------------------------------------------
        # 6. CLINICAL VOLUME VS. FINANCIAL REVENUE CORRELATION MATRIX
        # -------------------------------------------------------------
        poli_definitions = [
            ('PRAT-UMUM', 'Poli Umum', 'Pratama', 'umum'),
            ('PRAT-GIGI', 'Poli Gigi & Mulut', 'Pratama', 'gigi'),
            ('PRAT-KIA', 'Poli KIA & Kebidanan', 'Pratama', 'kia'),
            ('PRAT-LAB', 'Laboratorium Klinik', 'Pratama', 'lab'),
            ('PRAT-RAD', 'Radiologi & Diagnostik', 'Pratama', 'rad'),
            ('PRAT-FARM', 'Farmasi Rawat Jalan', 'Pratama', 'farmasi'),
            ('HD-TREAT', 'Ruang Tindakan & Mesin HD', 'Hemodialisis', 'hd_routine'),
            ('HD-PHARM', 'Dialyzer & BHP Khusus HD', 'Hemodialisis', 'hd_special'),
            ('HD-VIP', 'Kamar Isolasi / VIP HD', 'Hemodialisis', 'hd_special'),
        ]

        correlation_matrix = []
        for p_code, p_name, p_unit, p_enum in poli_definitions:
            if business_unit == 'ACC-PRATAMA' and p_unit != 'Pratama':
                continue
            if business_unit == 'ACC-HD' and p_unit != 'Hemodialisis':
                continue
            if poli_code and poli_code != 'all' and poli_code != p_code:
                continue

            acc = code_to_acc.get(p_code)
            p_id_str = str(acc.id) if acc else None

            # 1. Clinical Volume (Encounters count in date range)
            p_encs = encounters.filtered(lambda e: e.poli_code == p_enum)
            p_enc_count = len(p_encs)

            # 2. Invoiced Revenue & Expenses
            p_rev = 0.0
            p_cogs = 0.0
            p_doc = 0.0

            if p_id_str:
                for l in period_lines:
                    if l.analytic_distribution and p_id_str in l.analytic_distribution:
                        code = l.account_id.code or ''
                        if code.startswith('410') or code.startswith('4100'):
                            p_rev += float(l.credit - l.debit)
                        elif code.startswith(('5100', '51000')):
                            p_cogs += float(l.debit - l.credit)
                        elif code.startswith('5101'):
                            p_doc += float(l.debit - l.credit)

            # Fallback revenue from encounter lines if move lines not yet fully closed
            if p_rev <= 0.0 and p_enc_count > 0:
                p_rev = float(sum(
                    sum(line.unit_price * line.qty for line in enc.line_ids)
                    for enc in p_encs
                ))

            p_gross = float(p_rev - (p_cogs + p_doc))
            p_margin = float(round((p_gross / p_rev * 100.0), 2)) if p_rev > 0 else 0.0
            p_arpt = float(round(p_rev / p_enc_count, 2)) if p_enc_count > 0 else 0.0

            if p_margin >= 40.0:
                p_rag = 'success'
            elif p_margin >= 15.0:
                p_rag = 'warning'
            else:
                p_rag = 'danger'

            correlation_matrix.append({
                'poli_code': p_code,
                'poli_name': p_name,
                'unit_type': p_unit,
                'encounter_count': p_enc_count,
                'revenue': p_rev,
                'cogs': p_cogs,
                'doctor_fee': p_doc,
                'gross_profit': p_gross,
                'margin_pct': p_margin,
                'arpt': p_arpt,
                'rag_badge': p_rag,
            })

        # -------------------------------------------------------------
        # 7. SECTION C: PAYER MIX BREAKDOWN
        # -------------------------------------------------------------
        payer_categories = [
            {
                'key': 'cash',
                'label': 'Tunai / Kas Kasir',
                'accounts': ['111010', '111020', '11110001', '11110010'],
                'color': '#28a745',
            },
            {
                'key': 'qris_edc',
                'label': 'QRIS & EDC Electronic',
                'accounts': ['111220', '111210', '11120001'],
                'color': '#17a2b8',
            },
            {
                'key': 'bpjs',
                'label': 'Piutang Klaim BPJS (SEP)',
                'accounts': ['112020'],
                'color': '#007bff',
            },
            {
                'key': 'insurance',
                'label': 'Asuransi Swasta & Korporasi',
                'accounts': ['112030'],
                'color': '#6f42c1',
            },
            {
                'key': 'voucher',
                'label': 'Voucher / Deposit Dimuka',
                'accounts': ['214010', '214020'],
                'color': '#fd7e14',
            },
        ]

        payer_mix = []
        total_payer_amount = 0.0

        for cat in payer_categories:
            matching_lines = period_lines.filtered(
                lambda l: l.account_id.code and l.account_id.code in cat['accounts']
            )
            if target_analytic_ids:
                matching_lines = matching_lines.filtered(_matches_analytic)

            amt = float(max(0.0, sum(matching_lines.mapped('debit')) - sum(matching_lines.mapped('credit'))))
            cat['amount'] = amt
            total_payer_amount += amt

        # Fallback to encounter distribution if payment move lines are pending batch posting
        if total_payer_amount <= 0.0 and len(encounters) > 0:
            enc_total = len(encounters)
            cash_cnt = len(encounters.filtered(lambda e: e.payer_type == 'cash'))
            qris_cnt = len(encounters.filtered(lambda e: e.payer_type == 'qris'))
            bpjs_cnt = len(encounters.filtered(lambda e: e.payer_type == 'bpjs'))
            ins_cnt = len(encounters.filtered(lambda e: e.payer_type == 'insurance'))
            vouch_cnt = len(encounters.filtered(lambda e: e.payer_type == 'voucher'))

            ref_vol = total_revenue if total_revenue > 0 else sum(sum(l.unit_price * l.qty for l in e.line_ids) for e in encounters)
            if ref_vol > 0 and enc_total > 0:
                for cat in payer_categories:
                    if cat['key'] == 'cash':
                        cat['amount'] = float(round(ref_vol * (cash_cnt / enc_total), 2))
                    elif cat['key'] == 'qris_edc':
                        cat['amount'] = float(round(ref_vol * (qris_cnt / enc_total), 2))
                    elif cat['key'] == 'bpjs':
                        cat['amount'] = float(round(ref_vol * (bpjs_cnt / enc_total), 2))
                    elif cat['key'] == 'insurance':
                        cat['amount'] = float(round(ref_vol * (ins_cnt / enc_total), 2))
                    elif cat['key'] == 'voucher':
                        cat['amount'] = float(round(ref_vol * (vouch_cnt / enc_total), 2))
                total_payer_amount = ref_vol

        for cat in payer_categories:
            pct = float(round((cat['amount'] / total_payer_amount * 100.0), 2)) if total_payer_amount > 0 else 0.0
            payer_mix.append({
                'key': cat['key'],
                'label': cat['label'],
                'amount': cat['amount'],
                'percentage': pct,
                'color': cat['color'],
            })

        # -------------------------------------------------------------
        # 8. SECTION D: PATIENT ACTIVITY & REVISIT METRICS
        # -------------------------------------------------------------
        prior_mrns = set(self.env['clinic.encounter'].search([
            ('encounter_date', '<', f"{date_from} 00:00:00")
        ]).mapped('patient_mrn'))

        new_encounters = 0
        returning_encounters = 0
        for enc in encounters:
            if enc.patient_mrn in prior_mrns:
                returning_encounters += 1
            else:
                new_encounters += 1

        revisit_rate_pct = float(round((returning_encounters / total_inbound * 100.0), 2)) if total_inbound > 0 else 0.0

        # -------------------------------------------------------------
        # 9. SECTION E: AUDIT & COMPLIANCE WARNING FLAGS
        # -------------------------------------------------------------
        # 1. GR/IR Clearing 211500 (Alert if non-zero != 0.00)
        grir_lines = cum_lines.filtered(lambda l: l.account_id.code == '211500')
        grir_clearing_balance = float(sum(grir_lines.mapped('credit')) - sum(grir_lines.mapped('debit')))
        grir_alert = abs(grir_clearing_balance) > 0.01

        # 2. Cashier Variance YTD (619990)
        year_start = f"{today.year}-01-01"
        cashier_lines = self.env['account.move.line'].search([
            ('company_id', '=', company_id),
            ('parent_state', '=', 'posted'),
            ('date', '>=', year_start),
            ('date', '<=', date_to),
            ('account_id.code', '=', '619990'),
        ])
        cashier_variance_ytd = float(sum(cashier_lines.mapped('debit')) - sum(cashier_lines.mapped('credit')))
        cashier_alert = cashier_variance_ytd > 1000000.0

        # 3. Near-Expiry Lots Count (<= today + 60 days in internal locations)
        threshold_date = today + relativedelta(days=60)
        self.env.cr.execute("""
            SELECT COALESCE(count(DISTINCT l.id), 0)
            FROM stock_lot l
            JOIN stock_quant q ON q.lot_id = l.id
            JOIN stock_location loc ON loc.id = q.location_id
            WHERE loc.usage = 'internal'
              AND q.quantity > 0
              AND l.expiration_date <= %s
        """, (threshold_date,))
        near_expiry_lots_count = int(self.env.cr.fetchone()[0] or 0)
        near_expiry_alert = near_expiry_lots_count > 0

        # 4. Unsettled Doctor Fees (Accounts 213010 & 213020)
        doc_liab_lines = cum_lines.filtered(
            lambda l: l.account_id.code and l.account_id.code in ['213010', '213020']
        )
        unsettled_doctor_fees = float(max(0.0, sum(doc_liab_lines.mapped('credit')) - sum(doc_liab_lines.mapped('debit'))))
        unsettled_doctor_alert = unsettled_doctor_fees > 0.01

        # 5. BPJS Dispute Allowance (Account 112990)
        dispute_lines = cum_lines.filtered(lambda l: l.account_id.code == '112990')
        bpjs_dispute_allowance = float(max(0.0, sum(dispute_lines.mapped('credit')) - sum(dispute_lines.mapped('debit'))))

        # -------------------------------------------------------------
        # 10. SECTION F: 12-MONTH TIME-SERIES DATA (SQL COALESCE & NULLIF)
        # -------------------------------------------------------------
        twelve_months_data = []
        month_cursor = today.replace(day=1) - relativedelta(months=11)
        end_month = today.replace(day=1)

        indonesian_months = {
            1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mei", 6: "Jun",
            7: "Jul", 8: "Agu", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Des"
        }

        while month_cursor <= end_month:
            m_start = month_cursor.strftime('%Y-%m-%d')
            m_end = ((month_cursor + relativedelta(months=1)) - relativedelta(days=1)).strftime('%Y-%m-%d')
            m_label = f"{indonesian_months[month_cursor.month]} {month_cursor.year}"
            m_key = month_cursor.strftime('%Y-%m')

            # Financial query with COALESCE
            m_rev_lines = self.env['account.move.line'].search([
                ('company_id', '=', company_id),
                ('parent_state', '=', 'posted'),
                ('date', '>=', m_start),
                ('date', '<=', m_end),
                ('account_id.code', '=like', '410%'),
            ])
            if target_analytic_ids:
                m_rev_lines = m_rev_lines.filtered(_matches_analytic)
            m_rev = float(sum(m_rev_lines.mapped('credit')) - sum(m_rev_lines.mapped('debit')))

            m_cogs_lines = self.env['account.move.line'].search([
                ('company_id', '=', company_id),
                ('parent_state', '=', 'posted'),
                ('date', '>=', m_start),
                ('date', '<=', m_end),
                ('account_id.code', '=like', '5100%'),
            ])
            if target_analytic_ids:
                m_cogs_lines = m_cogs_lines.filtered(_matches_analytic)
            m_cogs = float(sum(m_cogs_lines.mapped('debit')) - sum(m_cogs_lines.mapped('credit')))

            # Encounters count
            m_enc_domain = [
                ('encounter_date', '>=', f"{m_start} 00:00:00"),
                ('encounter_date', '<=', f"{m_end} 23:59:59"),
            ]
            if business_unit == 'ACC-PRATAMA':
                m_enc_domain.append(('clinic_unit', '=', 'pratama'))
            elif business_unit == 'ACC-HD':
                m_enc_domain.append(('clinic_unit', '=', 'hd'))

            m_encs = self.env['clinic.encounter'].search(m_enc_domain)
            m_finalized = len(m_encs.filtered(lambda e: e.state == 'posted'))
            m_backlog = len(m_encs.filtered(lambda e: e.state in ['draft', 'received', 'staged', 'error']))

            twelve_months_data.append({
                'month_key': m_key,
                'month_label': m_label,
                'revenue': m_rev,
                'cogs': m_cogs,
                'finalized_count': m_finalized,
                'backlog_count': m_backlog,
            })

            month_cursor += relativedelta(months=1)

        # -------------------------------------------------------------
        # RETURN STRUCTURED EXECUTIVE PAYLOAD
        # -------------------------------------------------------------
        return {
            'date_from': date_from,
            'date_to': date_to,
            'business_unit': business_unit or 'all',
            'poli_code': poli_code or 'all',
            'currency_symbol': company.currency_id.symbol or 'Rp',
            'scorecards': {
                'total_revenue': total_revenue,
                'net_profit': net_profit,
                'cogs': cogs,
                'doctor_fees': doctor_fees,
                'opex': opex,
                'gross_margin_pct': {
                    'value': gross_margin_pct,
                    'rag': gross_margin_rag,
                },
                'net_margin_pct': {
                    'value': net_margin_pct,
                    'rag': net_margin_rag,
                },
                'total_ar': total_ar,
                'ar_breakdown': {
                    'bpjs': ar_bpjs,
                    'self_pay': ar_self_pay,
                    'insurance': ar_insurance,
                },
                'dso_days': dso_days,
                'dpo_days': dpo_days,
                'inventory_days': inventory_days,
                'arpt': arpt,
                'arpp': arpp,
                'encounter_finalization_rate': {
                    'value': finalization_rate,
                    'rag': finalization_rag,
                },
                'posted_encounters': posted_count,
                'total_encounters': total_inbound,
                'backlog_count': backlog_count,
                'backlog_value': backlog_value,
                'unique_patients': unique_patients_count,
            },
            'top_clinical_services': top_services,
            'top_pharmacy_items': top_pharmacy,
            'clinical_volume_financial_correlation': correlation_matrix,
            'poli_profitability_matrix': correlation_matrix,
            'payer_mix': payer_mix,
            'patient_activity': {
                'new_encounters': new_encounters,
                'returning_encounters': returning_encounters,
                'total_encounters': total_inbound,
                'revisit_rate_pct': revisit_rate_pct,
            },
            'compliance_flags': {
                'grir_clearing_balance': grir_clearing_balance,
                'grir_alert': grir_alert,
                'cashier_variance_ytd': cashier_variance_ytd,
                'cashier_alert': cashier_alert,
                'near_expiry_lots_count': near_expiry_lots_count,
                'near_expiry_alert': near_expiry_alert,
                'unsettled_doctor_fees': unsettled_doctor_fees,
                'unsettled_doctor_alert': unsettled_doctor_alert,
                'bpjs_dispute_allowance': bpjs_dispute_allowance,
            },
            'time_series_12m': twelve_months_data,
        }
