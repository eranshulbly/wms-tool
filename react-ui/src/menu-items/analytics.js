// Analytics menu group — dashboards and reports (built out over time).

import { IconChartBar, IconTargetArrow } from '@tabler/icons';

const icons = { IconChartBar, IconTargetArrow };

// ==============================|| ANALYTICS MENU ITEMS ||============================== //

const analytics = {
    id: 'analytics',
    title: 'Analytics',
    type: 'group',
    children: [
        {
            id: 'analytics-overview',
            title: 'Overview',
            type: 'item',
            url: '/analytics',
            icon: icons.IconChartBar,
            breadcrumbs: false
        },
        {
            id: 'analytics-target-tracker',
            title: 'Target Tracker Analytics',
            type: 'item',
            url: '/analytics/sales-executives',
            icon: icons.IconTargetArrow,
            breadcrumbs: false
        }
    ]
};

export default analytics;
