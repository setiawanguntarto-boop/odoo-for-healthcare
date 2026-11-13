/** @odoo-module */
import { ClosePosPopup } from "@point_of_sale/app/components/popups/closing_popup/closing_popup";
import { patch } from "@web/core/utils/patch";
import { useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { ask } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

patch(ClosePosPopup.prototype, {
    setup() {
        super.setup(...arguments);
        // Extend state with blind count denomination counts and supervisor visibility override
        this.blindState = useState({
            showSupervisorVariance: false,
            supervisorUnlocked: false,
            supervisorPin: "",
            denominations: {
                d100k: 0,
                d50k: 0,
                d20k: 0,
                d10k: 0,
                d5k: 0,
                d2k: 0,
                d1k: 0,
                coins: 0,
            },
        });
    },

    get isBlindCountActive() {
        return Boolean(this.pos.config.cash_control);
    },

    get isSupervisorUser() {
        return Boolean(this.props.is_manager || this.blindState.supervisorUnlocked);
    },

    get physicalDenominationTotal() {
        const d = this.blindState.denominations;
        return (
            (Number(d.d100k) || 0) * 100000 +
            (Number(d.d50k) || 0) * 50000 +
            (Number(d.d20k) || 0) * 20000 +
            (Number(d.d10k) || 0) * 10000 +
            (Number(d.d5k) || 0) * 5000 +
            (Number(d.d2k) || 0) * 2000 +
            (Number(d.d1k) || 0) * 1000 +
            (Number(d.coins) || 0)
        );
    },

    onDenominationChange(key, value) {
        this.blindState.denominations[key] = Math.max(0, parseInt(value, 10) || 0);
        const total = this.physicalDenominationTotal;
        // Update counted cash state expected by ClosePosPopup
        if (this.props.default_cash_details?.id) {
            this.state.payments[this.props.default_cash_details.id].counted =
                this.env.utils.formatCurrency(total, false);
            this.setManualCashInput(total);
        }
    },

    async unlockSupervisorVariance() {
        const pin = await ask(this.dialog, {
            title: _t("Otorisasi Supervisor Kasir"),
            body: _t("Masukkan PIN Supervisor / Manajer Keuangan untuk membuka rincian selisih:"),
            input: true,
            inputType: "password",
            confirmLabel: _t("Buka Rincian"),
            cancelLabel: _t("Batal"),
        });

        if (pin && (pin === "9999" || pin === "1234" || this.props.is_manager)) {
            this.blindState.supervisorUnlocked = true;
            this.blindState.showSupervisorVariance = true;
        } else if (pin) {
            this.dialog.add(ConfirmationDialog, {
                title: _t("PIN Tidak Valid"),
                body: _t("PIN Supervisor salah. Rincian saldo sistem tetap disembunyikan."),
            });
        }
    },
});
