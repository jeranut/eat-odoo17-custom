/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";

export class TreasuryAnalysisDashboard extends Component {
    static template = "custom_paid_totals.TreasuryAnalysisDashboard";
    static components = { Layout };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.chartRef = useRef("analysisChart");
        this.chart = null;
        this.state = useState({
            loading: true,
            error: false,
            filters: {
                period: "day",
                date_from: "",
                date_to: "",
                company_id: "",
                source_type: "",
                operator_id: "",
            },
            data: {
                labels: [],
                income: [],
                expense: [],
                totals: { income: 0, expense: 0, balance: 0 },
                companies: [],
                operators: [],
                currency: { symbol: "", position: "after" },
            },
        });

        onWillStart(() => this.loadData());
        useEffect(
            () => {
                this.renderChart();
                return () => this.destroyChart();
            },
            () => [this.state.loading, this.state.error, this.state.data]
        );
        onWillUnmount(() => this.destroyChart());
    }

    get display() {
        return { controlPanel: {} };
    }

    get hasData() {
        return Boolean(this.state.data.labels.length);
    }

    formatAmount(value) {
        const amount = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value || 0);
        const currency = this.state.data.currency || {};
        if (!currency.symbol) {
            return amount;
        }
        return currency.position === "before"
            ? `${currency.symbol} ${amount}`
            : `${amount} ${currency.symbol}`;
    }

    async loadData() {
        this.destroyChart();
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.data = await this.orm.call(
                "treasury.analysis.report",
                "get_apex_analysis_data",
                [this.state.filters]
            );
        } catch (error) {
            this.state.error = true;
            console.error("Impossible de charger l'analyse de trésorerie", error);
        } finally {
            this.state.loading = false;
        }
    }

    async resetFilters() {
        Object.assign(this.state.filters, {
            period: "day",
            date_from: "",
            date_to: "",
            company_id: "",
            source_type: "",
            operator_id: "",
        });
        await this.loadData();
    }

    openReport(viewType) {
        this.action.doAction("custom_paid_totals.action_treasury_analysis_report", {
            viewType,
            additionalContext: viewType === "pivot" ? { group_by: ["date:month"] } : {},
        });
    }

    get filtersHaveInvalidDates() {
        return Boolean(
            this.state.filters.date_from &&
            this.state.filters.date_to &&
            this.state.filters.date_from > this.state.filters.date_to
        );
    }

    async setFilter(name, value) {
        this.state.filters[name] = value;
        if (name === "company_id") {
            this.state.filters.operator_id = "";
        }
        if (!this.filtersHaveInvalidDates) {
            await this.loadData();
        } else {
            this.state.error = true;
            this.destroyChart();
        }
    }

    destroyChart() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
    }

    renderChart() {
        this.destroyChart();
        if (this.state.loading || this.state.error || !this.hasData || !this.chartRef.el) {
            return;
        }
        this.chart = new ApexCharts(this.chartRef.el, {
            chart: {
                type: "line",
                height: 540,
                fontFamily: "inherit",
                toolbar: { show: true, tools: { download: true, selection: false, zoom: true, zoomin: true, zoomout: true, pan: false, reset: true } },
                animations: { enabled: true, speed: 450 },
            },
            series: [
                { name: "Décaissements", data: this.state.data.expense },
                { name: "Encaissements", data: this.state.data.income },
            ],
            colors: ["#d84a05", "#74304d"],
            stroke: { curve: "straight", width: 5, lineCap: "round" },
            markers: { size: 0, hover: { size: 6 } },
            xaxis: {
                categories: this.state.data.labels,
                tickPlacement: "on",
                labels: { rotate: -45, trim: true, hideOverlappingLabels: true },
            },
            yaxis: {
                labels: { formatter: (value) => this.formatAmount(value) },
            },
            grid: {
                borderColor: "#ffffff",
                strokeDashArray: 0,
                row: { colors: ["#f2edef", "#ffffff"], opacity: 1 },
                padding: { left: 16, right: 16 },
            },
            legend: {
                position: "top",
                horizontalAlign: "center",
                fontSize: "16px",
                fontWeight: 700,
                markers: { width: 34, height: 6, radius: 4 },
            },
            tooltip: {
                shared: true,
                intersect: false,
                y: { formatter: (value) => this.formatAmount(value) },
            },
            dataLabels: { enabled: false },
            noData: { text: "Aucune donnée à afficher" },
            responsive: [{
                breakpoint: 768,
                options: {
                    chart: { height: 430, toolbar: { show: false } },
                    stroke: { width: 3 },
                    legend: { fontSize: "13px" },
                },
            }],
        });
        this.chart.render();
    }
}

registry.category("actions").add(
    "custom_paid_totals.treasury_analysis_dashboard",
    TreasuryAnalysisDashboard
);
