// E-Way Bill menu group (shown only while inside the E-Way Bill section).

import { IconFileInvoice } from '@tabler/icons';

const icons = { IconFileInvoice };

// ==============================|| E-WAY BILL MENU ITEMS ||============================== //

const eway = {
    id: 'eway',
    title: 'E-Way Bill',
    type: 'group',
    children: [
        {
            id: 'eway-bills',
            title: 'E-Way Bill',
            type: 'item',
            url: '/warehouse/eway-bill',
            icon: icons.IconFileInvoice,
            breadcrumbs: false
        }
    ]
};

export default eway;
