import { IconSettings, IconUpload, IconReceipt2 } from '@tabler/icons';

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
        {
            id: 'inventory-ingestion',
            title: 'Inventory Ingestion',
            type: 'item',
            // Same nginx caveat as above — path avoids the '/admin/*' prefix.
            url: '/inventory-ingestion',
            icon: IconUpload,
            breadcrumbs: false,
        },
        {
            id: 'margin-check',
            title: 'Margin Check',
            type: 'item',
            // Same nginx caveat as above — path avoids the '/admin/*' prefix.
            url: '/margin-check',
            icon: IconReceipt2,
            breadcrumbs: false,
        },
        // Future admin menu items go here.
    ],
};

export default adminMenu;
