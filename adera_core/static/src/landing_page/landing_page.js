import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class AderaLandingPage extends Component {
    static template = "adera_core.LandingPage";
    static props = { ...standardActionServiceProps };

    setup() {
        this.menuService = useService("menu");
        this.actionService = useService("action");
    }

    get apps() {
        const root = this.menuService.getMenu("root");
        if (!root || !root.children) {
            return [];
        }
        // Exclude Menu Utama itself from the grid
        return root.children
            .map((id) => this.menuService.getMenu(id))
            .filter((app) => app && app.xmlid !== "adera_core.menu_adera_landing_root" && app.name !== "Menu Utama");
    }

    async onAppClick(app) {
        if (!app) return;
        if (app.actionID) {
            await this.menuService.selectMenu(app);
            return;
        }
        // If the root menu has no direct actionID, search its children tree for the first action
        const tree = this.menuService.getMenuAsTree(app.id);
        const findFirstActionMenu = (node) => {
            if (node.actionID) return node;
            if (node.childrenTree) {
                for (const child of node.childrenTree) {
                    const found = findFirstActionMenu(child);
                    if (found) return found;
                }
            }
            return null;
        };
        const target = findFirstActionMenu(tree);
        if (target) {
            await this.menuService.selectMenu(target);
        }
    }
}

registry.category("actions").add("adera_core.landing_page", AderaLandingPage);
