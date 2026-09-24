// Inventory Ingestion menu group (shown only while inside the Inventory Ingestion
// section) — its own standalone group, same pattern as E-Way Bill and Supply Sheet,
// rather than being bundled under Admin. Reached from its own Launcher tile.

import { IconUpload } from '@tabler/icons';

const icons = { IconUpload };

// ==============================|| INVENTORY INGESTION MENU ITEMS ||============================== //

const inventoryIngestion = {
    id: 'inventory-ingestion',
    title: 'Inventory Ingestion',
    type: 'group',
    children: [
        {
            id: 'inventory-ingestion',
            title: 'Inventory Ingestion',
            type: 'item',
            // NOTE: not '/admin/...' — nginx proxies ^/(health|admin)(/.*)?$ to the
            // Flask-Admin panel on the backend, which would shadow this SPA route.
            url: '/inventory-ingestion',
            icon: icons.IconUpload,
            breadcrumbs: false
        }
    ]
};

export default inventoryIngestion;
