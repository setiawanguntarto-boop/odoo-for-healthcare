import { Component } from "@odoo/owl";
import { useBus, useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { NavBar } from "@web/webclient/navbar/navbar";
import { patch } from "@web/core/utils/patch";

export class AderaAppSwitcher extends Component {
    static template = "adera_core.AppSwitcher";
    static props = ["*"];

    setup() {
        this.menuService = useService("menu");
        this.actionService = useService("action");
        useBus(this.env.bus, "MENUS:APP-CHANGED", () => this.render());
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
        if (app) {
            await this.menuService.selectMenu(app);
        }
    }
}

// Register as standard client action: 'adera_app_switcher'
registry.category("actions").add("adera_app_switcher", AderaAppSwitcher);

// Patch NavBar so clicking on the Apps button opens the App Switcher action
patch(NavBar.prototype, {
    onAllAppsBtnClick() {
        this.actionService.doAction("adera_app_switcher", { clearBreadcrumbs: true });
        if (super.onAllAppsBtnClick) {
            super.onAllAppsBtnClick();
        }
    },
});
