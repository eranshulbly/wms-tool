// Dealer Payment Tracker menu group (views/dealer-payments/).

import { IconCurrencyRupee, IconPlus, IconReceipt2 } from '@tabler/icons';

// ==============================|| DEALER PAYMENTS MENU ITEMS ||============================== //

const dealerPayments = {
    id: 'dealer-payments',
    title: 'Dealer Payments',
    type: 'group',
    children: [
        {
            id: 'dealer-payments-screen',
            title: 'Dealer screen',
            type: 'item',
            url: '/dealer-payments',
            icon: IconCurrencyRupee,
            breadcrumbs: false
        },
        {
            id: 'dealer-payments-log',
            title: 'Log payment',
            type: 'item',
            url: '/dealer-payments/log',
            icon: IconPlus,
            breadcrumbs: false
        },
        {
            id: 'dealer-payments-history',
            title: 'Payment log',
            type: 'item',
            url: '/dealer-payments/payments',
            icon: IconReceipt2,
            breadcrumbs: false
        }
    ]
};

export default dealerPayments;
