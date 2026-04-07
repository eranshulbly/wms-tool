import React from 'react';
import { useSelector } from 'react-redux';
import { Redirect } from 'react-router-dom';

const EwayFillingGuard = ({ children }) => {
    const { user, isLoggedIn } = useSelector((state) => state.account);

    if (!isLoggedIn) return <Redirect to="/login" />;
    
    // User needs either admin or filling explicitly
    const hasFillingOrAdmin = user?.permissions?.eway_bill_filling === true || user?.permissions?.eway_bill_admin === true;
    
    // Fallback block for admins with old session
    if (!hasFillingOrAdmin && user?.role !== 'admin') {
        return <Redirect to="/dashboard/default" />;
    }

    return children;
};

export default EwayFillingGuard;
