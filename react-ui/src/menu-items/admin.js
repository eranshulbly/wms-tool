import { IconSettings } from '@tabler/icons';

const adminMenu = {
    id: 'admin',
    title: 'Admin',
    type: 'group',
    children: [
        {
            id: 'admin-controls',
            title: 'Admin Controls',
            type: 'item',
            url: '/admin/controls',
            icon: IconSettings,
            breadcrumbs: false,
        },
        // Future admin menu items go here.
    ],
};

export default adminMenu;
