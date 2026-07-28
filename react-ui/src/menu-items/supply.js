// Supply Sheet menu group (shown only while inside the Supply Sheet section).

import { IconClipboardList } from '@tabler/icons';

const icons = { IconClipboardList };

// ==============================|| SUPPLY SHEET MENU ITEMS ||============================== //

const supply = {
    id: 'supply',
    title: 'Supply Sheet',
    type: 'group',
    children: [
        {
            id: 'supply-sheet',
            title: 'Supply Sheet',
            type: 'item',
            url: '/warehouse/supply-sheet',
            icon: icons.IconClipboardList,
            breadcrumbs: false
        }
    ]
};

export default supply;
