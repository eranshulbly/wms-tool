// Updated MainRoutes.js file with Invoice Management routes

import React, { lazy } from 'react';
import { Route, Switch, useLocation } from 'react-router-dom';

// project imports
import MainLayout from './../layout/MainLayout';
import Loadable from '../ui-component/Loadable';
import AuthGuard from './../utils/route-guard/AuthGuard';

// warehouse management routing
const OrderUpload = Loadable(lazy(() => import('../views/warehouse/OrderUpload')));
const WarehouseDashboard = Loadable(lazy(() => import('../views/warehouse/WarehouseDashboard')));
const OrderManagement = Loadable(lazy(() => import('../views/warehouse/OrderManagement')));

// NEW: Invoice management routing
const InvoiceUpload = Loadable(lazy(() => import('../views/warehouse/InvoiceUpload')));

//-----------------------|| MAIN ROUTING ||-----------------------//

const MainRoutes = () => {
    const location = useLocation();

    return (
        <Route
            path={[
                '/dashboard/default',
                '/utils/util-typography',
                '/utils/util-color',
                '/utils/util-shadow',
                '/icons/tabler-icons',
                '/icons/material-icons',
                '/sample-page',
                '/warehouse/upload-orders',
                '/warehouse/dashboard',
                '/warehouse/manage-orders',
                // NEW: Invoice routes
                '/warehouse/upload-invoices'
            ]}
        >
            <MainLayout>
                <Switch location={location} key={location.pathname}>
                    <AuthGuard>
                        <Route path="/dashboard/default" component={WarehouseDashboard} />

                        {/* Warehouse Management Routes */}
                        <Route path="/warehouse/upload-orders" component={OrderUpload} />
                        <Route path="/warehouse/manage-orders" component={OrderManagement} />

                        {/* NEW: Invoice Management Routes */}
                        <Route path="/warehouse/upload-invoices" component={InvoiceUpload} />
                    </AuthGuard>
                </Switch>
            </MainLayout>
        </Route>
    );
};

export default MainRoutes;