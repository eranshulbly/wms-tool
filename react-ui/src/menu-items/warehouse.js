// Updated menu items for warehouse management

import { IconFileUpload, IconPackage, IconTruckDelivery, IconBoxSeam, IconDashboard, IconTable } from '@tabler/icons';

// constant
const icons = {
    IconFileUpload,
    IconPackage,
    IconTruckDelivery,
    IconBoxSeam,
    IconDashboard,
    IconTable
};

// ==============================|| WAREHOUSE MENU ITEMS ||============================== //

const warehouse = {
    id: 'warehouse',
    title: 'Warehouse Management',
    type: 'group',
    children: [
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
        // {
        //     id: 'pick-tickets',
        //     title: 'Pick Tickets',
        //     type: 'item',
        //     url: '/warehouse/pick-tickets',
        //     icon: icons.IconBoxSeam,
        //     breadcrumbs: false
        // },
        // {
        //     id: 'dispatch',
        //     title: 'Dispatch',
        //     type: 'item',
        //     url: '/warehouse/dispatch',
        //     icon: icons.IconTruckDelivery,
        //     breadcrumbs: false
        // },
        {
           id: 'supply-sheet',
            title: 'Supply Sheet',
            type: 'item',
            url: '/warehouse/supply-sheet',
            icon: icons.IconTable,
            breadcrumbs: false
        }
    ]
};

export default warehouse;