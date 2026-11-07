// Beat Outstanding menu group (views/beat-outstanding/).

import { IconRoute, IconUsers } from '@tabler/icons';

// ==============================|| BEAT OUTSTANDING MENU ITEMS ||============================== //

const beatOutstanding = {
    id: 'beat-outstanding',
    title: 'Beat Outstanding',
    type: 'group',
    children: [
        {
            id: 'beat-outstanding-report',
            title: 'Outstanding',
            type: 'item',
            url: '/beat-outstanding',
            icon: IconRoute,
            breadcrumbs: false
        },
        {
            id: 'beat-outstanding-executive-beats',
            title: 'Executive Beats',
            type: 'item',
            url: '/beat-outstanding/executive-beats',
            icon: IconUsers,
            breadcrumbs: false
        }
    ]
};

export default beatOutstanding;
