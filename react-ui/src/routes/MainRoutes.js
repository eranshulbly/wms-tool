// Updated MainRoutes.js file with Invoice Management routes

import React, { lazy } from 'react';
import { Route, Switch, useLocation } from 'react-router-dom';

// project imports
import MainLayout from './../layout/MainLayout';
import Loadable from '../ui-component/Loadable';
import AuthGuard from './../utils/route-guard/AuthGuard';
import EwayFillingGuard from './../utils/route-guard/EwayFillingGuard';

// warehouse management routing
const OrderUpload = Loadable(lazy(() => import('../views/warehouse/OrderUpload')));
const WarehouseDashboard = Loadable(lazy(() => import('../views/warehouse/WarehouseDashboard')));
const OrderManagement = Loadable(lazy(() => import('../views/warehouse/OrderManagement')));
const SupplySheetDownload = Loadable(lazy(() => import('../views/warehouse/SupplySheetDownload')));
const InvoiceUpload = Loadable(lazy(() => import('../views/warehouse/InvoiceUpload')));
const EwayBillGenerator = Loadable(lazy(() => import('../views/warehouse/EwayBillGenerator')));

// admin routing
const AdminControls = Loadable(lazy(() => import('../views/admin/AdminControls')));

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
                '/warehouse/upload-invoices',
                '/warehouse/supply-sheet',
                '/warehouse/eway-bill',
                // Admin routes
                '/admin/controls',
            ]}
        >
            <MainLayout>
                <Switch location={location} key={location.pathname}>
                    <AuthGuard>
                        <Route path="/dashboard/default" component={WarehouseDashboard} />

                        {/* Warehouse Management Routes */}
                        <Route path="/warehouse/upload-orders" component={OrderUpload} />
                        <Route path="/warehouse/manage-orders" component={OrderManagement} />
                        <Route path="/warehouse/upload-invoices" component={InvoiceUpload} />
                        <Route path="/warehouse/supply-sheet" component={SupplySheetDownload} />
                        <EwayFillingGuard>
                            <Route path="/warehouse/eway-bill" component={EwayBillGenerator} />
                        </EwayFillingGuard>

                        {/* Admin routes */}
                        <Route path="/admin/controls" component={AdminControls} />
                    </AuthGuard>
                </Switch>
            </MainLayout>
        </Route>
    );
};

export default MainRoutes;