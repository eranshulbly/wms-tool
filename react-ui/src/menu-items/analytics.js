// Analytics menu group — dashboards and reports (built out over time).

import { IconTargetArrow, IconReportAnalytics } from '@tabler/icons';

const icons = { IconTargetArrow, IconReportAnalytics };

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
        },
        {
            id: 'analytics-inventory-report',
            title: 'Inventory Report',
            type: 'item',
            url: '/analytics/inventory-report',
            icon: icons.IconReportAnalytics,
            breadcrumbs: false
        }
    ]
};

export default analytics;
