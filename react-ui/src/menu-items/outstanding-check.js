// Outstanding Check menu group (shown only while inside the Outstanding Check section)
// — its own standalone group, same pattern as Margin Check and Inventory Ingestion,
// rather than being bundled under Admin. Reached from its own Launcher tile.

import { IconCashBanknote } from '@tabler/icons';

const icons = { IconCashBanknote };

// ==============================|| OUTSTANDING CHECK MENU ITEMS ||============================== //

const outstandingCheck = {
    id: 'outstanding-check',
    title: 'Outstanding Check',
    type: 'group',
    children: [
        {
            id: 'outstanding-check',
            title: 'Outstanding Check',
            type: 'item',
            // NOTE: not '/admin/...' — nginx proxies ^/(health|admin)(/.*)?$ to the
            // Flask-Admin panel on the backend, which would shadow this SPA route.
            url: '/outstanding-check',
            icon: icons.IconCashBanknote,
            breadcrumbs: false
        }
    ]
};

export default outstandingCheck;
