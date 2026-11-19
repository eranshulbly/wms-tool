import { IconSettings, IconFileSpreadsheet, IconDiscount2 } from '@tabler/icons';

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
        // The PO Builder masters (views/po-builder/PoBuilderMasters.js).
        {
            id: 'sku-master-upload',
            title: 'SKU Master Upload',
            type: 'item',
            // Same nginx caveat as above — path avoids the '/admin/*' prefix.
            url: '/sku-master-upload',
            icon: IconFileSpreadsheet,
            breadcrumbs: false,
        },
        {
            id: 'scheme-upload',
            title: 'Scheme Upload',
            type: 'item',
            url: '/scheme-upload',
            icon: IconDiscount2,
            breadcrumbs: false,
        },
        // TAT Check's three files (inventory, dispatch & pending, GRN) are uploaded on the
        // TAT Check page itself.
        // Future admin menu items go here.
    ],
};

export default adminMenu;
