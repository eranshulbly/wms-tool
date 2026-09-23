import PropTypes from 'prop-types';
import React from 'react';
import { useSelector } from 'react-redux';
import { Redirect, useLocation } from 'react-router-dom';
import { Box, Typography, Paper } from '@material-ui/core';

import { scopeForRole } from '../roleScope';

//-----------------------|| AUTH GUARD ||-----------------------//

const AuthGuard = ({ children }) => {
    const account = useSelector((state) => state.account);
    const { isLoggedIn, user } = account;
    const location = useLocation();

    if (!isLoggedIn) {
        return <Redirect to="/login" />;
    }

    // A single-screen role may only ever see its own page — any other path (including
    // the /home launcher) bounces there.
    const scope = user && scopeForRole(user.role);
    if (scope && !location.pathname.startsWith(scope.home)) {
        return <Redirect to={scope.home} />;
    }

    // Analytics and Admin Controls are admin-only (see the matching 403s in
    // inventory/router_analytics.py, sales/report/router.py, sales/analytics/router.py,
    // inventory/ingestion/router.py::IngestionReport and
    // platform/catalog/router.py::ProductMasterUpload) — bounced here too, so a
    // non-admin never lands on a page that only shows its own "Admin access required"
    // errors. Margin Check and Inventory Ingestion, the other two paths under the same
    // sidebar group, are not blocked here; they have their own, narrower rules.
    if (user && user.role !== 'admin' &&
        (location.pathname.startsWith('/analytics') || location.pathname.startsWith('/admin-controls'))) {
        return <Redirect to="/home" />;
    }

    if (user && user.status === 'pending') {
        return (
            <Box display="flex" alignItems="center" justifyContent="center" minHeight="100vh" bgcolor="#f5f5f5">
                <Paper elevation={3} style={{ padding: '48px', maxWidth: '480px', textAlign: 'center' }}>
                    <Typography variant="h4" gutterBottom>Account Pending Approval</Typography>
                    <Typography variant="body1" color="textSecondary">
                        Your account has been created and is awaiting admin approval.
                        You will have access to the portal once an admin activates your account.
                    </Typography>
                    <Box mt={3}>
                        <Typography
                            variant="body2"
                            style={{ cursor: 'pointer', color: '#1976d2' }}
                            onClick={() => { localStorage.removeItem('wms_token'); localStorage.removeItem('wms_user'); window.location.href = '/login'; }}
                        >
                            Back to Login
                        </Typography>
                    </Box>
                </Paper>
            </Box>
        );
    }

    return children;
};

AuthGuard.propTypes = {
    children: PropTypes.node
};

export default AuthGuard;
