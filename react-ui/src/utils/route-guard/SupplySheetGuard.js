import React from 'react';
import { useSelector } from 'react-redux';
import { Redirect } from 'react-router-dom';

/**
 * Guards the supply sheet route so only users whose role has the
 * supply_sheet boolean permission can access it. Admins bypass the check.
 */
const SupplySheetGuard = ({ children }) => {
    const { user, isLoggedIn } = useSelector((state) => state.account);

    if (!isLoggedIn) return <Redirect to="/login" />;

    if (user?.role !== 'admin' && !user?.permissions?.supply_sheet) {
        return <Redirect to="/dashboard/default" />;
    }

    return children;
};

export default SupplySheetGuard;
