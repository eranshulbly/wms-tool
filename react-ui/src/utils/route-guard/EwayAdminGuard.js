import React from 'react';
import { useSelector } from 'react-redux';
import { Redirect } from 'react-router-dom';

const EwayAdminGuard = ({ children }) => {
    const { user, isLoggedIn } = useSelector((state) => state.account);

    if (!isLoggedIn) return <Redirect to="/login" />;
    
    // Check if user has explicit eway_bill_admin permission
    const hasAdmin = user?.permissions?.eway_bill_admin === true;
    
    // As a fallback for old sessions without permissions structure, or super admin override:
    if (!hasAdmin && user?.role !== 'admin') {
        return <Redirect to="/dashboard/default" />;
    }

    return children;
};

export default EwayAdminGuard;
