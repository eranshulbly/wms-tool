import React from 'react';
import { useSelector } from 'react-redux';
import { Redirect } from 'react-router-dom';

/**
 * Guards a route so only users whose role has the given upload permission
 * can access it. Admins bypass the check.
 *
 * Usage:
 *   <UploadPermissionGuard uploadType="products">
 *     <Route path="/warehouse/upload-products" component={ProductUpload} />
 *   </UploadPermissionGuard>
 */
const UploadPermissionGuard = ({ uploadType, children }) => {
    const { user, isLoggedIn } = useSelector((state) => state.account);

    if (!isLoggedIn) return <Redirect to="/login" />;

    const allowedUploads = user?.permissions?.uploads || [];
    if (user?.role !== 'admin' && !allowedUploads.includes(uploadType)) {
        return <Redirect to="/dashboard/default" />;
    }

    return children;
};

export default UploadPermissionGuard;
