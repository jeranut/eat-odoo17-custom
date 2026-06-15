/** @odoo-module **/

import {
    Component,
    onWillStart,
    onWillUnmount,
    onWillUpdateProps,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class DailyBalanceDashboard extends Component {
    static template = "custom_paid_totals.DailyBalanceDashboard";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.chartRef = useRef("chart");
        this.chart = null;
        this.state = useState({
            period: "day",
            activeTab: "expenses",
            loading: true,
            error: false,
            data: {
                expenses: { labels: [], series: [] },
                sales: { labels: [], series: [] },
                currency: { symbol: "", position: "after" },
            },
        });

        onWillStart(() => this.loadData());
        onWillUpdateProps((nextProps) => {
            if (nextProps.record.resId !== this.props.record.resId) {
                return this.loadData(nextProps.record.resId);
            }
        });
        useEffect(
            () => {
                this.renderChart();
                return () => this.destroyChart();
            },
            () => [this.state.loading, this.state.error, this.state.activeTab, this.state.data]
        );
        onWillUnmount(() => this.destroyChart());
    }

    get activeData() {
        return this.state.data[this.state.activeTab];
    }

    get hasData() {
        return Boolean(this.activeData && this.activeData.series.length);
    }

    get title() {
        const section = this.state.activeTab === "expenses" ? "Décaissements" : "Encaissements";
        const period = this.state.period === "day" ? "du jour" : "du mois";
        return `${section} ${period}`;
    }

    formatAmount(value) {
        const amount = new Intl.NumberFormat().format(value);
        const currency = this.state.data.currency || {};
        if (!currency.symbol) {
            return amount;
        }
        return currency.position === "before"
            ? `${currency.symbol} ${amount}`
            : `${amount} ${currency.symbol}`;
    }

    async loadData(recordId = this.props.record.resId) {
        if (!recordId) {
            this.state.loading = false;
            return;
        }
        this.destroyChart();
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.data = await this.orm.call(
                this.props.record.resModel,
                "get_dashboard_chart_data",
                [[recordId], this.state.period]
            );
        } catch (error) {
            this.state.error = true;
            console.error("Impossible de charger le dashboard de trésorerie", error);
        } finally {
            this.state.loading = false;
        }
    }

    async setPeriod(period) {
        if (period !== this.state.period) {
            this.state.period = period;
            await this.loadData();
        }
    }

    setActiveTab(tab) {
        this.state.activeTab = tab;
    }

    async openBarLines(dataPointIndex) {
        const label = this.activeData.labels[dataPointIndex];
        if (!label) {
            return;
        }
        const action = await this.orm.call(
            this.props.record.resModel,
            "action_open_dashboard_lines",
            [[this.props.record.resId], this.state.period, this.state.activeTab, label]
        );
        await this.action.doAction(action);
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
                type: "bar",
                height: 420,
                toolbar: { show: false },
                events: {
                    dataPointSelection: (event, chartContext, config) => {
                        this.openBarLines(config.dataPointIndex);
                    },
                },
            },
            series: [{
                name: this.state.activeTab === "expenses" ? "Décaissements" : "Encaissements",
                data: this.activeData.series,
            }],
            xaxis: {
                categories: this.activeData.labels,
                labels: {
                    rotate: -45,
                    trim: true,
                    hideOverlappingLabels: false,
                    maxHeight: 120,
                },
            },
            yaxis: {
                labels: {
                    formatter: (value) => this.formatAmount(value),
                },
            },
            tooltip: {
                y: {
                    formatter: (value) => this.formatAmount(value),
                },
            },
            dataLabels: { enabled: false },
            plotOptions: {
                bar: {
                    borderRadius: 4,
                    columnWidth: "55%",
                },
            },
            colors: [this.state.activeTab === "expenses" ? "#dc3545" : "#198754"],
            noData: { text: "Aucune donnée à afficher" },
            responsive: [{
                breakpoint: 576,
                options: {
                    chart: { height: 380 },
                    plotOptions: { bar: { columnWidth: "65%" } },
                    xaxis: { labels: { rotate: -60, maxHeight: 140 } },
                },
            }],
        });
        this.chart.render();
    }
}

registry.category("fields").add("daily_balance_dashboard", {
    component: DailyBalanceDashboard,
    supportedTypes: ["boolean"],
    isEmpty: () => false,
});
