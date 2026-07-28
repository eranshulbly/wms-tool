// Order Tracking menu group — order upload, invoicing, and the manage/track table.

import { IconFileUpload, IconTable, IconDashboard, IconPackage, IconClipboardList, IconFileDownload } from '@tabler/icons';

const icons = { IconFileUpload, IconTable, IconDashboard, IconPackage, IconClipboardList, IconFileDownload };

// ==============================|| ORDER TRACKING MENU ITEMS ||============================== //

const warehouse = {
    id: 'order-tracking',
    title: 'Order Tracking',
    type: 'group',
    children: [
        {
            id: 'default',
            title: 'Dashboard',
            type: 'item',
            url: '/dashboard/default',
            icon: icons.IconDashboard,
            breadcrumbs: false
        },
        {
            id: 'submitted-orders',
            title: 'Submitted Orders',
            type: 'item',
            url: '/warehouse/submitted-orders',
            icon: icons.IconClipboardList,
            breadcrumbs: false
        },
        {
            id: 'download-dms',
            title: 'Download DMS Input',
            type: 'item',
            url: '/warehouse/download-dms',
            icon: icons.IconFileDownload,
            breadcrumbs: false
        },
        {
            id: 'upload-orders',
            title: 'Upload Orders',
            type: 'item',
            url: '/warehouse/upload-orders',
            icon: icons.IconFileUpload,
            breadcrumbs: false
        },
        {
            id: 'upload-invoices',
            title: 'Upload Invoice',
            type: 'item',
            url: '/warehouse/upload-invoices',
            icon: icons.IconFileUpload,
            breadcrumbs: false
        },
        {
            id: 'manage-orders',
            title: 'Manage Orders',
            type: 'item',
            url: '/warehouse/manage-orders',
            icon: icons.IconTable,
            breadcrumbs: false
        },
        {
            id: 'upload-products',
            title: 'Upload Products',
            type: 'item',
            url: '/warehouse/upload-products',
            icon: icons.IconPackage,
            breadcrumbs: false
        }
    ]
};

export default warehouse;
