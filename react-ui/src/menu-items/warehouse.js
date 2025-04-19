// Updated menu items for warehouse management

import { IconFileUpload, IconPackage, IconTruckDelivery, IconBoxSeam, IconDashboard } from '@tabler/icons';

// constant
const icons = {
    IconFileUpload,
    IconPackage,
    IconTruckDelivery,
    IconBoxSeam,
    IconDashboard
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
            id: 'manage-orders',
            title: 'Manage Orders',
            type: 'item',
            url: '/warehouse/manage-orders',
            icon: icons.IconList,
            breadcrumbs: false
        },
        {
            id: 'pick-tickets',
            title: 'Pick Tickets',
            type: 'item',
            url: '/warehouse/pick-tickets',
            icon: icons.IconBoxSeam,
            breadcrumbs: false
        },
        {
            id: 'dispatch',
            title: 'Dispatch',
            type: 'item',
            url: '/warehouse/dispatch',
            icon: icons.IconTruckDelivery,
            breadcrumbs: false
        }
    ]
};

export default warehouse;