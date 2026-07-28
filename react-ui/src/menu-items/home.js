// assets
import { IconHome } from '@tabler/icons';

const icons = { IconHome };

// -----------------------|| HOME (launcher) MENU ITEM ||-----------------------//

const home = {
    id: 'home',
    type: 'group',
    children: [
        {
            id: 'launcher',
            title: 'Home',
            type: 'item',
            url: '/home',
            icon: icons.IconHome,
            breadcrumbs: false
        }
    ]
};

export default home;
