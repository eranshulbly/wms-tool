import React from 'react';
import { useSelector } from 'react-redux';
import { Redirect } from 'react-router-dom';

/**
 * Guards the analytics routes so only roles with the analytics permission can
 * open them. Admins bypass the check.
 *
 * Hiding the launcher tile is not enough on its own: the path is guessable and
 * survives in a bookmark, and Target Tracker carries sales figures against
 * target — the kind of thing warehouse and office staff have no business seeing
 * because they happened to type a URL.
 */
const AnalyticsGuard = ({ children }) => {
    const { user, isLoggedIn } = useSelector((state) => state.account);

    if (!isLoggedIn) return <Redirect to="/login" />;

    if (user?.role !== 'admin' && !user?.permissions?.analytics) {
        return <Redirect to="/home" />;
    }

    return children;
};

export default AnalyticsGuard;
