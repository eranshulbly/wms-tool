import { IconSettings, IconUpload, IconFileSpreadsheet, IconDiscount2 } from '@tabler/icons';

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
        // The three files TAT Check reads (views/dms-uploads/DmsFeedUpload.js).
        {
            id: 'dms-inventory-upload',
            title: 'DMS Inventory Upload',
            type: 'item',
            // Same nginx caveat as above — path avoids the '/admin/*' prefix.
            url: '/dms-inventory-upload',
            icon: IconUpload,
            breadcrumbs: false,
        },
        {
            id: 'dispatch-pending-upload',
            title: 'Dispatch and Pending Upload',
            type: 'item',
            url: '/dispatch-pending-upload',
            icon: IconUpload,
            breadcrumbs: false,
        },
        {
            id: 'grn-upload',
            title: 'GRN Upload',
            type: 'item',
            url: '/grn-upload',
            icon: IconUpload,
            breadcrumbs: false,
        },
        // Beat Outstanding's outlet -> beat map (views/dms-uploads/DmsFeedUpload.js). Its
        // daily Beat Plan and Outstanding Report are uploaded on the Beat Outstanding page.
        {
            id: 'outlet-master-upload',
            title: 'Outlet Master Upload',
            type: 'item',
            url: '/outlet-master-upload',
            icon: IconUpload,
            breadcrumbs: false,
        },
        // Future admin menu items go here.
    ],
};

export default adminMenu;
