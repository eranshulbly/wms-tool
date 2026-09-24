import { IconSettings } from '@tabler/icons';

// Admin Controls only — Inventory Ingestion and Margin Check moved out to their own
// standalone menu groups (menu-items/inventory-ingestion.js, menu-items/margin-check.js),
// same pattern as E-Way Bill and Supply Sheet, each reached from its own Launcher tile
// rather than being bundled under Admin.
const adminMenu = {
    id: 'admin',
    title: 'Admin',
    type: 'group',
    children: [
        {
            id: 'admin-controls',
            title: 'Admin Controls',
            type: 'item',
            // NOTE: not '/admin/controls' — nginx proxies ^/(health|admin)(/.*)?$ to the
            // Flask-Admin panel on the backend, which would shadow this SPA route on any
            // direct load or refresh. '/admin-controls' falls through to the React app.
            url: '/admin-controls',
            icon: IconSettings,
            breadcrumbs: false,
        },
        // Future admin-only menu items go here.
    ],
};

export default adminMenu;
