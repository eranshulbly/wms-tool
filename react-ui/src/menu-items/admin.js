import { IconHistory } from '@tabler/icons';

const adminMenu = {
    id: 'admin',
    title: 'Admin',
    type: 'group',
    children: [
        {
            id: 'upload-history',
            title: 'Upload History',
            type: 'item',
            url: '/admin/upload-history',
            icon: IconHistory,
            breadcrumbs: false
        }
    ]
};

export default adminMenu;
