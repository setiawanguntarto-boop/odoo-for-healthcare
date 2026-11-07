import { Component, useState, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { WebClient } from "@web/webclient/webclient";
import { NavBar } from "@web/webclient/navbar/navbar";

export class AderaAppSwitcher extends Component {
    static template = "adera_core.AppSwitcher";
    static props = {};

    setup() {
        this.menuService = useService("menu");
        this.actionService = useService("action");
        this.state = useState({
            isOpen: false,
        });

        this.env.bus.addEventListener("ADERA:TOGGLE_APPSWITCHER", (ev) => {
            if (ev?.detail && typeof ev.detail.open === "boolean") {
                this.state.isOpen = ev.detail.open;
            } else {
                this.state.isOpen = !this.state.isOpen;
            }
        });

        onMounted(() => {
            // If user arrives at root path or has no controller, open app switcher
            const hash = window.location.hash;
            if (!hash || hash === "#" || hash === "#home") {
                this.state.isOpen = true;
            }
        });
    }

    get apps() {
        const root = this.menuService.getMenu("root");
        if (!root || !root.children) {
            return [];
        }
        return root.children
            .map((id) => this.menuService.getMenu(id))
            .filter((app) => app && app.name !== "Tests");
    }

    async onAppClick(app) {
        this.state.isOpen = false;
        if (app) {
            await this.menuService.selectMenu(app);
        }
    }

    close() {
        this.state.isOpen = false;
    }
}

// Add AderaAppSwitcher as a top-level persistent main component
registry.category("main_components").add("AderaAppSwitcher", {
    Component: AderaAppSwitcher,
});

// Patch WebClient to open App Switcher instead of silently auto-redirecting when no action in URL
patch(WebClient.prototype, {
    async _loadDefaultApp() {
        this.env.bus.trigger("ADERA:TOGGLE_APPSWITCHER", { open: true });
    },
});

// Patch NavBar to toggle our full app switcher when the home menu / app button is clicked
patch(NavBar.prototype, {
    setup() {
        super.setup();
        // Listen to toggle requests
    },
    onAllAppsBtnClick() {
        this.env.bus.trigger("ADERA:TOGGLE_APPSWITCHER", { open: true });
        if (super.onAllAppsBtnClick) {
            super.onAllAppsBtnClick();
        }
    },
});
