/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class ClinicalSupplyCockpit extends Component {
    static template = "adera_inventory.ClinicalSupplyCockpit";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            isLoading: true,
            metrics: null,
            criticalItems: [],
            isOrdering: false,
        });

        onWillStart(async () => {
            await this.loadCockpitData();
        });
    }

    async loadCockpitData() {
        this.state.isLoading = true;
        try {
            const metrics = await this.orm.call(
                "clinic.inventory.dashboard",
                "get_clinical_supply_metrics",
                []
            );
            const criticalItems = await this.orm.call(
                "clinic.inventory.dashboard",
                "get_critical_low_stock_items",
                []
            );
            this.state.metrics = metrics;
            this.state.criticalItems = criticalItems;
        } catch (error) {
            console.error("Failed to load clinical supply cockpit data:", error);
            this.notification.add("Gagal memuat metrik rantai pasok medis.", { type: "danger" });
        } finally {
            this.state.isLoading = false;
        }
    }

    formatCurrency(amount) {
        if (!amount && amount !== 0) return "Rp 0";
        return new Intl.NumberFormat("id-ID", {
            style: "currency",
            currency: "IDR",
            maximumFractionDigits: 0,
        }).format(amount);
    }

    // Quick Actions
    openGoodsReceipts() {
        this.action.doAction({
            name: "Penerimaan Barang PBF (GRN)",
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            views: [[false, "list"], [false, "form"]],
            domain: [["picking_type_code", "=", "incoming"]],
            context: { default_picking_type_code: "incoming" },
        });
    }

    openInternalTransfers() {
        this.action.doAction({
            name: "Transfer Antar Depo (Farmasi & HD)",
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            views: [[false, "list"], [false, "form"]],
            domain: [["picking_type_code", "=", "internal"]],
            context: { default_picking_type_code: "internal" },
        });
    }

    openCyclicAudit() {
        this.action.doAction({
            name: "Audit Stok Fisik (Stock Opname)",
            type: "ir.actions.act_window",
            res_model: "stock.quant",
            views: [[false, "list"]],
            domain: [["location_id.usage", "=", "internal"]],
            context: { search_default_internal_loc: 1 },
        });
    }

    openQuarantineLots() {
        this.action.doAction({
            name: "Karantina & Recall Batch Obat",
            type: "ir.actions.act_window",
            res_model: "stock.lot",
            views: [[false, "list"], [false, "form"]],
            domain: [["is_quarantine", "=", true]],
            context: { default_is_quarantine: true },
        });
    }

    openExpiringLots() {
        this.action.doAction({
            name: "Batch Mendekati Kadaluarsa (< 60 Hari)",
            type: "ir.actions.act_window",
            res_model: "stock.lot",
            views: [[false, "list"], [false, "form"]],
            domain: [["product_qty", ">", 0]],
            context: { search_default_expiring_soon: 1 },
        });
    }

    openDepoFarmasi() {
        this.action.doAction({
            name: "Depo Farmasi Rawat Jalan",
            type: "ir.actions.act_window",
            res_model: "stock.quant",
            views: [[false, "list"]],
            domain: [["location_id.complete_name", "ilike", "Farmasi"]],
        });
    }

    openDepoHD() {
        this.action.doAction({
            name: "Depo Logistik Hemodialisis",
            type: "ir.actions.act_window",
            res_model: "stock.quant",
            views: [[false, "list"]],
            domain: [["location_id.complete_name", "ilike", "HD"]],
        });
    }

    openCentralWarehouse() {
        this.action.doAction({
            name: "Penerimaan Gudang Pusat",
            type: "ir.actions.act_window",
            res_model: "stock.picking",
            views: [[false, "list"], [false, "form"]],
            domain: [["location_dest_id.usage", "=", "internal"]],
        });
    }

    openOpenVialWizard() {
        this.action.doAction({
            name: "Pemusnahan Sisa Obat Terbuka (Open-Vial Spoilage)",
            type: "ir.actions.act_window",
            res_model: "stock.scrap.clinic",
            views: [[false, "form"]],
            target: "new",
        });
    }

    async createExpressPO(item) {
        if (this.state.isOrdering) return;
        this.state.isOrdering = true;
        try {
            const action = await this.orm.call(
                "purchase.order",
                "action_generate_express_rfq",
                [],
                {
                    product_id: item.product_id,
                    order_qty: item.suggested_order_qty,
                    vendor_id: item.vendor_id || false,
                }
            );
            this.notification.add(
                `Draft RFQ berhasil dibuat untuk ${item.product_name} (${item.suggested_order_qty} ${item.uom_name}) ke ${item.vendor_name}.`,
                { type: "success" }
            );
            if (action && action.res_id) {
                this.action.doAction(action);
            }
        } catch (error) {
            console.error("Failed to generate express PO:", error);
            this.notification.add(`Gagal membuat RFQ: ${error.message || error}`, { type: "danger" });
        } finally {
            this.state.isOrdering = false;
        }
    }
}

registry.category("actions").add("adera_inventory.clinical_supply_cockpit", ClinicalSupplyCockpit);
