// Analytics menu group — dashboards and reports (built out over time).

import { IconTargetArrow } from '@tabler/icons';

const icons = { IconTargetArrow };

// ==============================|| ANALYTICS MENU ITEMS ||============================== //

const analytics = {
    id: 'analytics',
    title: 'Analytics',
    type: 'group',
    children: [
        {
            id: 'analytics-target-tracker',
            title: 'Target Tracker',
            type: 'item',
            url: '/analytics/target-tracker',
            icon: icons.IconTargetArrow,
            breadcrumbs: false
        }
    ]
};

export default analytics;
