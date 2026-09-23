import React from 'react';
import { useSelector } from 'react-redux';
import { Redirect } from 'react-router-dom';

// allowManager: opt-in, per route — most admin-group pages (Admin Controls, Order
// Margin, Sales Report) stay strictly admin-only, but Margin Check and Inventory
// Ingestion are also open to manager-type roles. Without this prop the behaviour is
// unchanged from before: admin only.
const AdminGuard = ({ children, allowManager = false }) => {
    const { user, isLoggedIn } = useSelector((state) => state.account);

    if (!isLoggedIn) return <Redirect to="/login" />;

    const isAdmin = user?.role === 'admin';
    const isManager = allowManager && (user?.role === 'manager' || user?.role === 'cadila_manager');

    if (!user || (!isAdmin && !isManager)) return <Redirect to="/home" />;

    return children;
};

export default AdminGuard;
