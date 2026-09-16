// Analytics menu group — dashboards and reports (built out over time).

import { IconReportAnalytics, IconUsers, IconReceipt2 } from '@tabler/icons';

const icons = { IconReportAnalytics, IconUsers, IconReceipt2 };

// ==============================|| ANALYTICS MENU ITEMS ||============================== //

// Target Tracker was removed: this deployment sets no sales targets (sales arrive as
// uploaded invoices), so there is nothing for it to track.
const analytics = {
    id: 'analytics',
    title: 'Analytics',
    type: 'group',
    children: [
        {
            id: 'analytics-inventory-report',
            title: 'Batch Costing',
            type: 'item',
            url: '/analytics/inventory-report',
            icon: icons.IconReportAnalytics,
            breadcrumbs: false
        },
        {
            id: 'analytics-stock-movement',
            title: 'Stock Movement',
            type: 'item',
            url: '/analytics/stock-movement',
            icon: icons.IconTrendingUp,
            breadcrumbs: false
        },
        {
            id: 'analytics-sales-executives',
            title: 'Sales Executive Activity',
            type: 'item',
            url: '/analytics/sales-executives',
            icon: icons.IconUsers,
            breadcrumbs: false
        },
        {
            id: 'analytics-order-margin',
            title: 'Order Margin',
            type: 'item',
            url: '/analytics/order-margin',
            icon: icons.IconReceipt2,
            breadcrumbs: false
        }
    ]
};

export default analytics;
