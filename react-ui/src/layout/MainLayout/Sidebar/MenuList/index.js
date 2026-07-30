import React from 'react';
import { useSelector } from 'react-redux';
import { useLocation } from 'react-router-dom';

// material-ui
import { Typography } from '@material-ui/core';

// project imports
import NavGroup from './NavGroup';
import menuItem, { sectionForPath } from './../../../../menu-items';

//-----------------------|| SIDEBAR MENU LIST ||-----------------------//

// Map order-tracking upload items to the upload permission they require.
const UPLOAD_PERMISSION_MAP = {
    'upload-orders': 'orders',
    'upload-invoices': 'invoices',
    'upload-products': 'products'
};

// Filter an order-tracking group's children by the user's upload permissions.
const filterOrderTracking = (group, allowedUploads) => {
    if (!group.children || allowedUploads === null) return group;
    return {
        ...group,
        children: group.children.filter((child) => {
            const requiredPerm = UPLOAD_PERMISSION_MAP[child.id];
            if (!requiredPerm) return true; // dashboard / manage-orders always shown
            return allowedUploads.includes(requiredPerm);
        })
    };
};

const MenuList = () => {
    const user = useSelector((state) => state.account.user);
    const { pathname } = useLocation();
    const allowedUploads = user?.permissions?.uploads || null;

    // Only the current section's menu is shown (plus a Home link back to the
    // launcher). The launcher itself (/home) hides the sidebar entirely.
    const section = sectionForPath(pathname);
    const homeGroup = menuItem.items.find((g) => g.id === 'home');
    let sectionGroup = menuItem.items.find((g) => g.id === section);

    if (sectionGroup && sectionGroup.id === 'order-tracking') {
        sectionGroup = filterOrderTracking(sectionGroup, allowedUploads);
        // The part convertor is scoped to Submitted Orders only.
        if (user?.role === 'part_convertor') {
            sectionGroup = {
                ...sectionGroup,
                children: sectionGroup.children.filter((c) => c.id === 'submitted-orders')
            };
        }
    }

    const groups = [homeGroup, sectionGroup].filter(Boolean);

    return groups.map((group) => {
        if (group.type === 'group') {
            return <NavGroup key={group.id} item={group} />;
        }
        return (
            <Typography key={group.id} variant="h6" color="error" align="center">
                Menu Items Error
            </Typography>
        );
    });
};

export default MenuList;
