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
        Kalkulasi dinamis KPI Eksekutif Klinik ADERA.
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
        id_to_code = {acc.id: acc.code for acc in analytic_accs if acc.code}

        target_analytic_ids = None
        if poli_code:
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

        if poli_code:
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

        # Backlog Value
        backlog_value = float(sum(
            sum(line.unit_price * line.qty for line in enc.line_ids)
            for enc in backlog_encounters
        ))

        # Unique patients in date range
        unique_mrns = set(encounters.mapped('patient_mrn'))
        unique_patients_count = len(unique_mrns)

        # Average Revenue Metrics
        arpt = float(round(total_revenue / posted_count, 2)) if posted_count > 0 else 0.0
        arpp = float(round(total_revenue / unique_patients_count, 2)) if unique_patients_count > 0 else 0.0

        # Encounter Finalization Rate
        finalization_rate = float(round((posted_count / total_inbound * 100.0), 2)) if total_inbound > 0 else 0.0
        finalization_rag = "success" if finalization_rate >= 98.0 else ("warning" if finalization_rate >= 90.0 else "danger")

        # -------------------------------------------------------------
        # 3. WORKING CAPITAL & DAYS METRICS (DSO, DPO, DIO)
        # -------------------------------------------------------------
        # Open AR on 112010 (Piutang Pasien), 112020 (Piutang BPJS), 11210010
        ar_lines = cum_lines.filtered(
            lambda l: l.account_id.code and l.account_id.code in ['112010', '112020', '11210010', '11210011']
        )
        open_ar_balance = float(sum(ar_lines.mapped('debit')) - sum(ar_lines.mapped('credit')))
        daily_rev = float(total_revenue / 30.0) if total_revenue > 0 else 0.0
        dso_days = float(round(open_ar_balance / daily_rev, 1)) if daily_rev > 0 else 0.0

        # Open AP on 211010 (Utang Pemasok & Distributor Farmasi), 21100010
        ap_lines = cum_lines.filtered(
            lambda l: l.account_id.code and l.account_id.code in ['211010', '21100010']
        )
        open_ap_balance = float(sum(ap_lines.mapped('credit')) - sum(ap_lines.mapped('debit')))
        daily_cogs = float(cogs / 30.0) if cogs > 0 else 0.0
        dpo_days = float(round(open_ap_balance / daily_cogs, 1)) if daily_cogs > 0 else 0.0

        # Stock Valuation on 114010-114040, 11300180
        stock_lines = cum_lines.filtered(
            lambda l: l.account_id.code and l.account_id.code in ['114010', '114020', '114030', '114040', '11300180']
        )
        stock_valuation = float(sum(stock_lines.mapped('debit')) - sum(stock_lines.mapped('credit')))
        inventory_days = float(round(stock_valuation / daily_cogs, 1)) if daily_cogs > 0 else 0.0

        # -------------------------------------------------------------
        # 4. SECTION B: UNIT & POLI PROFITABILITY MATRIX
        # -------------------------------------------------------------
        poli_definitions = [
            ('PRAT-UMUM', 'Poli Umum', 'Pratama'),
            ('PRAT-GIGI', 'Poli Gigi & Mulut', 'Pratama'),
            ('PRAT-KIA', 'Poli KIA & Kebidanan', 'Pratama'),
            ('PRAT-LAB', 'Laboratorium Klinik', 'Pratama'),
            ('PRAT-RAD', 'Radiologi & Diagnostik', 'Pratama'),
            ('PRAT-FARM', 'Farmasi Rawat Jalan', 'Pratama'),
            ('HD-TREAT', 'Ruang Tindakan & Mesin HD', 'Hemodialisis'),
            ('HD-PHARM', 'Dialyzer & BHP Khusus HD', 'Hemodialisis'),
            ('HD-VIP', 'Kamar Isolasi / VIP HD', 'Hemodialisis'),
        ]

        poli_matrix = []
        for p_code, p_name, p_unit in poli_definitions:
            if business_unit == 'ACC-PRATAMA' and p_unit != 'Pratama':
                continue
            if business_unit == 'ACC-HD' and p_unit != 'Hemodialisis':
                continue
            if poli_code and poli_code != p_code:
                continue

            acc = code_to_acc.get(p_code)
            p_id_str = str(acc.id) if acc else None

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

            p_gross = float(p_rev - (p_cogs + p_doc))
            p_margin = float(round((p_gross / p_rev * 100.0), 2)) if p_rev > 0 else 0.0

            if p_margin >= 40.0:
                p_rag = 'success'
            elif p_margin >= 15.0:
                p_rag = 'warning'
            else:
                p_rag = 'danger'

            poli_matrix.append({
                'poli_code': p_code,
                'poli_name': p_name,
                'unit_type': p_unit,
                'revenue': p_rev,
                'cogs': p_cogs,
                'doctor_fee': p_doc,
                'gross_profit': p_gross,
                'margin_pct': p_margin,
                'rag_badge': p_rag,
            })

        # -------------------------------------------------------------
        # 5. SECTION C: PAYER MIX BREAKDOWN
        # -------------------------------------------------------------
        # Categorize by tender accounts from period_lines
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

            # In double-entry, payments debit the liquid/receivable account
            amt = float(sum(matching_lines.mapped('debit')) - sum(matching_lines.mapped('credit')))
            if amt < 0:
                amt = 0.0
            cat['amount'] = amt
            total_payer_amount += amt

        # Fallback to revenue proportion if move lines are settled through POS or journals
        if total_payer_amount <= 0.0 and total_revenue > 0:
            # Derive from encounter payer_types in this date range
            enc_total = len(encounters)
            if enc_total > 0:
                cash_cnt = len(encounters.filtered(lambda e: e.payer_type == 'cash'))
                qris_cnt = len(encounters.filtered(lambda e: e.payer_type == 'qris'))
                bpjs_cnt = len(encounters.filtered(lambda e: e.payer_type == 'bpjs'))
                ins_cnt = len(encounters.filtered(lambda e: e.payer_type == 'insurance'))
                vouch_cnt = len(encounters.filtered(lambda e: e.payer_type == 'voucher'))

                for cat in payer_categories:
                    if cat['key'] == 'cash':
                        cat['amount'] = float(round(total_revenue * (cash_cnt / enc_total), 2))
                    elif cat['key'] == 'qris_edc':
                        cat['amount'] = float(round(total_revenue * (qris_cnt / enc_total), 2))
                    elif cat['key'] == 'bpjs':
                        cat['amount'] = float(round(total_revenue * (bpjs_cnt / enc_total), 2))
                    elif cat['key'] == 'insurance':
                        cat['amount'] = float(round(total_revenue * (ins_cnt / enc_total), 2))
                    elif cat['key'] == 'voucher':
                        cat['amount'] = float(round(total_revenue * (vouch_cnt / enc_total), 2))
                total_payer_amount = total_revenue

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
        # 6. SECTION D: PATIENT ACTIVITY & REVISIT METRICS
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
        # 7. SECTION E: AUDIT & COMPLIANCE FLAGS
        # -------------------------------------------------------------
        # 1. GR/IR Clearing 211500
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
            SELECT count(DISTINCT l.id)
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
        unsettled_doctor_fees = float(sum(doc_liab_lines.mapped('credit')) - sum(doc_liab_lines.mapped('debit')))
        unsettled_doctor_alert = unsettled_doctor_fees > 0.01

        # 5. BPJS Dispute Allowance (Account 112990)
        dispute_lines = cum_lines.filtered(lambda l: l.account_id.code == '112990')
        bpjs_dispute_allowance = float(sum(dispute_lines.mapped('credit')) - sum(dispute_lines.mapped('debit')))

        # -------------------------------------------------------------
        # 8. SECTION F: 12-MONTH CHART TIME-SERIES DATA
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

            # Monthly financial totals
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

            # Monthly encounters
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
        # RETURN AGGREGATED METRICS PAYLOAD
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
                'arpt': arpt,
                'arpp': arpp,
                'dso_days': dso_days,
                'dpo_days': dpo_days,
                'inventory_days': inventory_days,
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
            'poli_profitability_matrix': poli_matrix,
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
