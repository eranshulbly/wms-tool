import React from 'react';
import { useSelector } from 'react-redux';
import { useLocation } from 'react-router-dom';

// material-ui
import { Typography } from '@material-ui/core';

// project imports
import NavGroup from './NavGroup';
import menuItem, { sectionForPath } from './../../../../menu-items';
import { scopeForRole } from './../../../../utils/roleScope';

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

// The admin group's three items each have their own rule — Admin Controls is
// admin-only, Margin Check is also open to manager-type roles (backend:
// fulfillment/invoice/router.py::MarginCheck), Inventory Ingestion follows the
// 'ingestion' upload permission like any other upload screen.
const filterAdminGroup = (group, isAdmin, isManager, allowedUploads) => {
    if (!group.children) return group;
    return {
        ...group,
        children: group.children.filter((child) => {
            if (child.id === 'admin-controls') return isAdmin;
            if (child.id === 'margin-check') return isAdmin || isManager;
            if (child.id === 'inventory-ingestion') {
                return isAdmin || (allowedUploads !== null && allowedUploads.includes('ingestion'));
            }
            return true;
        })
    };
};

const MenuList = () => {
    const user = useSelector((state) => state.account.user);
    const { pathname } = useLocation();
    const allowedUploads = user?.permissions?.uploads || null;
    const isAdmin = user?.role === 'admin';
    const isManager = user?.role === 'manager' || user?.role === 'cadila_manager';

    // Only the current section's menu is shown (plus a Home link back to the
    // launcher). The launcher itself (/home) hides the sidebar entirely.
    const section = sectionForPath(pathname);
    const homeGroup = menuItem.items.find((g) => g.id === 'home');
    let sectionGroup = menuItem.items.find((g) => g.id === section);

    // A single-screen role sees only its own item, and no Home link — the launcher is
    // one of the places it is not allowed to go, so offering the link would just bounce.
    const scope = scopeForRole(user?.role);

    if (sectionGroup && sectionGroup.id === 'order-tracking') {
        sectionGroup = filterOrderTracking(sectionGroup, allowedUploads);
        if (scope) {
            sectionGroup = {
                ...sectionGroup,
                children: sectionGroup.children.filter((c) => c.id === scope.menuId)
            };
        }
    }

    if (sectionGroup && sectionGroup.id === 'admin') {
        sectionGroup = filterAdminGroup(sectionGroup, isAdmin, isManager, allowedUploads);
    }

    // Analytics is admin-only outright — AuthGuard also bounces a direct URL visit,
    // this is just so the sidebar itself never offers the link.
    if (sectionGroup && sectionGroup.id === 'analytics' && !isAdmin) {
        sectionGroup = null;
    }

    const groups = [scope ? null : homeGroup, sectionGroup].filter(Boolean);

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
