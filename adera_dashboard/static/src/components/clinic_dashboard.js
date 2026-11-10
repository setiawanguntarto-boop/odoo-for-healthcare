/** @odoo-module **/

import { Component, useState, onWillStart, useEffect, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadBundle } from "@web/core/assets";

export class ClinicDashboard extends Component {
    static template = "adera_dashboard.ClinicDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        // Canvas references for Chart.js
        this.revenueChartRef = useRef("revenueChartCanvas");
        this.payerChartRef = useRef("payerChartCanvas");
        this.encounterChartRef = useRef("encounterChartCanvas");

        this.revenueChart = null;
        this.payerChart = null;
        this.encounterChart = null;

        // Reactive state
        const today = new Date();
        const yyyy = today.getFullYear();
        const mm = String(today.getMonth() + 1).padStart(2, "0");
        const dd = String(today.getDate()).padStart(2, "0");

        const firstDay = `${yyyy}-${mm}-01`;
        const currentDay = `${yyyy}-${mm}-${dd}`;

        this.state = useState({
            datePreset: "this_month",
            dateFrom: firstDay,
            dateTo: currentDay,
            businessUnit: "all",
            poliCode: "all",
            isLoading: true,
            metrics: null,
            sortColumn: "revenue",
            sortAsc: false,
        });

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.loadMetrics();
        });

        useEffect(
            () => {
                if (this.state.metrics && !this.state.isLoading) {
                    this.renderCharts();
                }
            },
            () => [this.state.metrics, this.state.isLoading]
        );
    }

    async loadMetrics() {
        this.state.isLoading = true;
        try {
            const data = await this.orm.call(
                "clinic.dashboard.kpi",
                "get_dashboard_metrics",
                [],
                {
                    date_from: this.state.dateFrom,
                    date_to: this.state.dateTo,
                    business_unit: this.state.businessUnit === "all" ? false : this.state.businessUnit,
                    poli_code: this.state.poliCode === "all" ? false : this.state.poliCode,
                }
            );
            this.state.metrics = data;
        } catch (error) {
            console.error("Failed to load clinic executive dashboard metrics:", error);
            if (this.notification) {
                this.notification.add("Gagal memuat metrik dashboard. Silakan periksa koneksi.", {
                    type: "danger",
                });
            }
        } finally {
            this.state.isLoading = false;
        }
    }

    onDatePresetChange(preset) {
        this.state.datePreset = preset;
        const now = new Date();
        const y = now.getFullYear();
        const m = now.getMonth();

        const formatDate = (d) => {
            const yy = d.getFullYear();
            const mm = String(d.getMonth() + 1).padStart(2, "0");
            const dd = String(d.getDate()).padStart(2, "0");
            return `${yy}-${mm}-${dd}`;
        };

        if (preset === "this_month") {
            const start = new Date(y, m, 1);
            const end = new Date(y, m + 1, 0);
            this.state.dateFrom = formatDate(start);
            this.state.dateTo = formatDate(end);
        } else if (preset === "last_30_days") {
            const start = new Date();
            start.setDate(now.getDate() - 30);
            this.state.dateFrom = formatDate(start);
            this.state.dateTo = formatDate(now);
        } else if (preset === "this_quarter") {
            const qMonth = Math.floor(m / 3) * 3;
            const start = new Date(y, qMonth, 1);
            const end = new Date(y, qMonth + 3, 0);
            this.state.dateFrom = formatDate(start);
            this.state.dateTo = formatDate(end);
        } else if (preset === "ytd") {
            const start = new Date(y, 0, 1);
            this.state.dateFrom = formatDate(start);
            this.state.dateTo = formatDate(now);
        } else if (preset === "all_time") {
            this.state.dateFrom = "2025-01-01";
            this.state.dateTo = formatDate(now);
        }
        this.loadMetrics();
    }

    onDateChange(event, field) {
        this.state[field] = event.target.value;
        this.state.datePreset = "custom";
        this.loadMetrics();
    }

    onBusinessUnitChange(unit) {
        this.state.businessUnit = unit;
        this.state.poliCode = "all";
        this.loadMetrics();
    }

    onPoliChange(event) {
        this.state.poliCode = event.target.value;
        this.loadMetrics();
    }

    onSortTable(column) {
        if (this.state.sortColumn === column) {
            this.state.sortAsc = !this.state.sortAsc;
        } else {
            this.state.sortColumn = column;
            this.state.sortAsc = false;
        }
    }

    get sortedPoliMatrix() {
        if (!this.state.metrics || !this.state.metrics.clinical_volume_financial_correlation) {
            return [];
        }
        const list = [...this.state.metrics.clinical_volume_financial_correlation];
        const col = this.state.sortColumn;
        const asc = this.state.sortAsc;

        list.sort((a, b) => {
            let valA = a[col];
            let valB = b[col];
            if (typeof valA === "string") {
                return asc ? valA.localeCompare(valB) : valB.localeCompare(valA);
            }
            valA = valA || 0;
            valB = valB || 0;
            return asc ? valA - valB : valB - valA;
        });
        return list;
    }

    renderCharts() {
        if (!window.Chart) {
            console.warn("Chart.js is not loaded yet.");
            return;
        }
        const timeSeries = this.state.metrics?.time_series_12m || [];
        const payerMix = this.state.metrics?.payer_mix || [];

        // -------------------------------------------------------------
        // Chart 1: 12-Month Revenue vs COGS Trend
        // -------------------------------------------------------------
        if (this.revenueChartRef.el) {
            if (this.revenueChart) {
                this.revenueChart.destroy();
            }
            const labels = timeSeries.map((t) => t.month_label);
            const revData = timeSeries.map((t) => t.revenue);
            const cogsData = timeSeries.map((t) => t.cogs);

            const ctx = this.revenueChartRef.el.getContext("2d");
            this.revenueChart = new window.Chart(ctx, {
                type: "bar",
                data: {
                    labels,
                    datasets: [
                        {
                            type: "line",
                            label: "Pendapatan Usaha (Revenue)",
                            data: revData,
                            borderColor: "#5f249f",
                            backgroundColor: "rgba(95, 36, 159, 0.15)",
                            borderWidth: 3,
                            fill: true,
                            tension: 0.35,
                            pointRadius: 4,
                            pointHoverRadius: 6,
                            order: 1,
                        },
                        {
                            type: "bar",
                            label: "Beban Pokok (HPP / COGS)",
                            data: cogsData,
                            backgroundColor: "rgba(224, 86, 253, 0.7)",
                            borderRadius: 6,
                            order: 2,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: "top" },
                        tooltip: {
                            callbacks: {
                                label: (context) => {
                                    return `${context.dataset.label}: ${this.formatCompactCurrency(context.parsed.y)}`;
                                },
                            },
                        },
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                callback: (val) => {
                                    return this.formatCompactCurrency(val);
                                },
                            },
                        },
                    },
                },
            });
        }

        // -------------------------------------------------------------
        // Chart 2: Payer Mix Donut Chart
        // -------------------------------------------------------------
        if (this.payerChartRef.el) {
            if (this.payerChart) {
                this.payerChart.destroy();
            }
            const labels = payerMix.map((p) => p.label);
            const data = payerMix.map((p) => p.amount);
            const colors = payerMix.map((p) => p.color);

            const ctx = this.payerChartRef.el.getContext("2d");
            this.payerChart = new window.Chart(ctx, {
                type: "doughnut",
                data: {
                    labels,
                    datasets: [
                        {
                            data,
                            backgroundColor: colors,
                            borderWidth: 2,
                            borderColor: "#ffffff",
                            hoverOffset: 6,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: "68%",
                    plugins: {
                        legend: { position: "bottom" },
                        tooltip: {
                            callbacks: {
                                label: (context) => {
                                    const val = context.raw || 0;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const pct = total > 0 ? ((val / total) * 100).toFixed(1) : 0;
                                    return `${context.label}: ${this.formatCompactCurrency(val)} (${pct}%)`;
                                },
                            },
                        },
                    },
                },
            });
        }

        // -------------------------------------------------------------
        // Chart 3: Finalized vs Backlog Encounters (Stacked Bar)
        // -------------------------------------------------------------
        if (this.encounterChartRef.el) {
            if (this.encounterChart) {
                this.encounterChart.destroy();
            }
            const labels = timeSeries.map((t) => t.month_label);
            const finData = timeSeries.map((t) => t.finalized_count);
            const backlogData = timeSeries.map((t) => t.backlog_count);

            const ctx = this.encounterChartRef.el.getContext("2d");
            this.encounterChart = new window.Chart(ctx, {
                type: "bar",
                data: {
                    labels,
                    datasets: [
                        {
                            label: "Selesai (Posted)",
                            data: finData,
                            backgroundColor: "#28a745",
                            stack: "enc",
                            borderRadius: { topLeft: 4, topRight: 4 },
                        },
                        {
                            label: "Antrean (Backlog)",
                            data: backlogData,
                            backgroundColor: "#ffc107",
                            stack: "enc",
                            borderRadius: { topLeft: 4, topRight: 4 },
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { position: "top" },
                    },
                    scales: {
                        x: { stacked: true },
                        y: {
                            stacked: true,
                            beginAtZero: true,
                            ticks: { precision: 0 },
                        },
                    },
                },
            });
        }
    }

    /**
     * Format Rupiah ringkas berstandar eksekutif:
     * - >= 1 Miliar: Rp X,XX M
     * - >= 1 Juta: Rp X,XX Jt
     * - < 1 Juta: Rp XXX.XXX
     */
    formatCompactCurrency(val) {
        if (val === null || val === undefined || isNaN(val)) return "Rp 0";
        const isNegative = val < 0;
        const absVal = Math.abs(val);
        let formatted = "";

        if (absVal >= 1000000000) {
            const num = (absVal / 1000000000).toLocaleString("id-ID", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
            });
            formatted = `Rp ${num} M`;
        } else if (absVal >= 1000000) {
            const num = (absVal / 1000000).toLocaleString("id-ID", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
            });
            formatted = `Rp ${num} Jt`;
        } else {
            formatted = `Rp ${Math.round(absVal).toLocaleString("id-ID")}`;
        }

        return isNegative ? `-${formatted}` : formatted;
    }

    /**
     * Format mata uang lengkap untuk tooltip dan rincian tabel
     */
    formatFullCurrency(val) {
        if (val === null || val === undefined || isNaN(val)) return "Rp 0";
        return new Intl.NumberFormat("id-ID", {
            style: "currency",
            currency: "IDR",
            minimumFractionDigits: 0,
            maximumFractionDigits: 2,
        }).format(val);
    }

    formatNumber(val) {
        if (val === null || val === undefined || isNaN(val)) return "0";
        return new Intl.NumberFormat("id-ID").format(val);
    }
}

registry.category("actions").add("adera_dashboard.main_dashboard", ClinicDashboard);
