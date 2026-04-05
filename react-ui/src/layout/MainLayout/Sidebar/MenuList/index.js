import React from 'react';
import { useSelector } from 'react-redux';

// material-ui
import { Typography } from '@material-ui/core';

// project imports
import NavGroup from './NavGroup';
import menuItem from './../../../../menu-items';

//-----------------------|| SIDEBAR MENU LIST ||-----------------------//

// Map menu item id to the upload permission name it requires
const UPLOAD_PERMISSION_MAP = {
    'upload-orders': 'orders',
    'upload-invoices': 'invoices',
};

const MenuList = () => {
    const user = useSelector((state) => state.account.user);
    const allowedUploads = user?.permissions?.uploads || null;

    const navItems = menuItem.items.map((item) => {
        // Hide the entire admin menu group from non-admins
        if (item.id === 'admin' && user?.role !== 'admin') return null;

        // Filter upload menu items based on permissions
        let filteredItem = item;
        if (item.id === 'warehouse' && item.children && allowedUploads !== null) {
            filteredItem = {
                ...item,
                children: item.children.filter((child) => {
                    const requiredPerm = UPLOAD_PERMISSION_MAP[child.id];
                    // If item doesn't require an upload permission, always show it
                    if (!requiredPerm) return true;
                    return allowedUploads.includes(requiredPerm);
                })
            };
        }

        switch (filteredItem.type) {
            case 'group':
                return <NavGroup key={filteredItem.id} item={filteredItem} />;
            default:
                return (
                    <Typography key={filteredItem.id} variant="h6" color="error" align="center">
                        Menu Items Error
                    </Typography>
                );
        }
    });

    return navItems;
};

export default MenuList;
