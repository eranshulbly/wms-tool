// PO Builder menu group — supplier POs and the master data behind them. The SKU master and
// scheme uploads are in the Admin group (menu-items/admin.js).

import { IconShoppingCart, IconArrowsRightLeft, IconSettings } from '@tabler/icons';

// ==============================|| PO BUILDER MENU ITEMS ||============================== //

const poBuilder = {
    id: 'po-builder',
    title: 'PO Builder',
    type: 'group',
    children: [
        {
            id: 'po-builder-build',
            title: 'Build PO',
            type: 'item',
            url: '/po-builder/build',
            icon: IconShoppingCart,
            breadcrumbs: false
        },
        {
            id: 'po-builder-sku-mapping',
            title: 'SKU → Scheme Mapping',
            type: 'item',
            url: '/po-builder/sku-mapping',
            icon: IconArrowsRightLeft,
            breadcrumbs: false
        },
        {
            id: 'po-builder-settings',
            title: 'Settings',
            type: 'item',
            url: '/po-builder/settings',
            icon: IconSettings,
            breadcrumbs: false
        }
    ]
};

export default poBuilder;
