// Margin Check menu group (shown only while inside the Margin Check section) — its own
// standalone group, same pattern as E-Way Bill and Supply Sheet, rather than being
// bundled under Admin. Reached from its own Launcher tile.

import { IconReceipt2 } from '@tabler/icons';

const icons = { IconReceipt2 };

// ==============================|| MARGIN CHECK MENU ITEMS ||============================== //

const marginCheck = {
    id: 'margin-check',
    title: 'Margin Check',
    type: 'group',
    children: [
        {
            id: 'margin-check',
            title: 'Margin Check',
            type: 'item',
            // NOTE: not '/admin/...' — nginx proxies ^/(health|admin)(/.*)?$ to the
            // Flask-Admin panel on the backend, which would shadow this SPA route.
            url: '/margin-check',
            icon: icons.IconReceipt2,
            breadcrumbs: false
        }
    ]
};

export default marginCheck;
