import React from 'react';
import { useSelector } from 'react-redux';
import { Redirect } from 'react-router-dom';

const AdminGuard = ({ children }) => {
    const { user, isLoggedIn } = useSelector((state) => state.account);

    if (!isLoggedIn) return <Redirect to="/login" />;
    if (!user || user.role !== 'admin') return <Redirect to="/dashboard/default" />;

    return children;
};

export default AdminGuard;
