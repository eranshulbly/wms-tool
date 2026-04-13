// Updated MainRoutes.js file with Invoice Management routes

import React, { lazy } from 'react';
import { Route, Switch, useLocation } from 'react-router-dom';

// project imports
import MainLayout from './../layout/MainLayout';
import Loadable from '../ui-component/Loadable';
import AuthGuard from './../utils/route-guard/AuthGuard';
import AdminGuard from './../utils/route-guard/AdminGuard';
import EwayFillingGuard from './../utils/route-guard/EwayFillingGuard';
import UploadPermissionGuard from './../utils/route-guard/UploadPermissionGuard';
import SupplySheetGuard from './../utils/route-guard/SupplySheetGuard';

// warehouse management routing
const OrderUpload = Loadable(lazy(() => import('../views/warehouse/OrderUpload')));
const WarehouseDashboard = Loadable(lazy(() => import('../views/warehouse/WarehouseDashboard')));
const OrderManagement = Loadable(lazy(() => import('../views/warehouse/OrderManagement')));
const SupplySheetDownload = Loadable(lazy(() => import('../views/warehouse/SupplySheetDownload')));
const InvoiceUpload = Loadable(lazy(() => import('../views/warehouse/InvoiceUpload')));
const ProductUpload = Loadable(lazy(() => import('../views/warehouse/ProductUpload')));
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
                '/warehouse/upload-products',
                '/warehouse/supply-sheet',
                '/warehouse/eway-bill',
                // Admin routes
                '/admin/controls',
            ]}
        >
            <MainLayout>
                <Switch location={location} key={location.pathname}>
                    <Route path="/dashboard/default" render={() => <AuthGuard><WarehouseDashboard /></AuthGuard>} />

                    {/* Warehouse Management Routes */}
                    <Route path="/warehouse/upload-orders" render={() => <AuthGuard><OrderUpload /></AuthGuard>} />
                    <Route path="/warehouse/manage-orders" render={() => <AuthGuard><OrderManagement /></AuthGuard>} />
                    <Route
                        path="/warehouse/upload-products"
                        render={() => (
                            <AuthGuard>
                                <UploadPermissionGuard uploadType="products">
                                    <ProductUpload />
                                </UploadPermissionGuard>
                            </AuthGuard>
                        )}
                    />
                    <Route path="/warehouse/upload-invoices" render={() => <AuthGuard><InvoiceUpload /></AuthGuard>} />
                    <Route
                        path="/warehouse/supply-sheet"
                        render={() => (
                            <AuthGuard>
                                <SupplySheetGuard>
                                    <SupplySheetDownload />
                                </SupplySheetGuard>
                            </AuthGuard>
                        )}
                    />
                    <Route
                        path="/warehouse/eway-bill"
                        render={() => (
                            <AuthGuard>
                                <EwayFillingGuard>
                                    <EwayBillGenerator />
                                </EwayFillingGuard>
                            </AuthGuard>
                        )}
                    />

                    {/* Admin routes */}
                    <Route
                        path="/admin/controls"
                        render={() => (
                            <AuthGuard>
                                <AdminGuard>
                                    <AdminControls />
                                </AdminGuard>
                            </AuthGuard>
                        )}
                    />
                </Switch>
            </MainLayout>
        </Route>
    );
};

export default MainRoutes;