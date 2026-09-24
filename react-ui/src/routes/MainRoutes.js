// Updated MainRoutes.js file with Invoice Management routes

import React, { lazy } from 'react';
import { Route, Switch, Redirect, useLocation } from 'react-router-dom';

// project imports
import MainLayout from './../layout/MainLayout';
import Loadable from '../ui-component/Loadable';
import AuthGuard from './../utils/route-guard/AuthGuard';
import AdminGuard from './../utils/route-guard/AdminGuard';
import EwayFillingGuard from './../utils/route-guard/EwayFillingGuard';
import UploadPermissionGuard from './../utils/route-guard/UploadPermissionGuard';
import SupplySheetGuard from './../utils/route-guard/SupplySheetGuard';

// system launcher (tile home)
const Launcher = Loadable(lazy(() => import('../views/launcher/Launcher')));

// warehouse management routing
const OrderUpload = Loadable(lazy(() => import('../views/warehouse/OrderUpload')));
const PicklistUpload = Loadable(lazy(() => import('../views/warehouse/PicklistUpload')));
const WarehouseDashboard = Loadable(lazy(() => import('../views/warehouse/WarehouseDashboard')));
const OrderManagement = Loadable(lazy(() => import('../views/warehouse/OrderManagement')));
const SubmittedOrders = Loadable(lazy(() => import('../views/warehouse/SubmittedOrders')));
const DownloadDmsInput = Loadable(lazy(() => import('../views/warehouse/DownloadDmsInput')));
const SupplySheetDownload = Loadable(lazy(() => import('../views/warehouse/SupplySheetDownload')));
const InvoiceUpload = Loadable(lazy(() => import('../views/warehouse/InvoiceUpload')));
const ProductUpload = Loadable(lazy(() => import('../views/warehouse/ProductUpload')));
const EwayBillGenerator = Loadable(lazy(() => import('../views/warehouse/EwayBillGenerator')));

// analytics routing
const TargetTracker = Loadable(lazy(() => import('../views/analytics/TargetTracker')));

// admin routing
const AdminControls = Loadable(lazy(() => import('../views/admin/AdminControls')));

// monthly data upload (top-level, admin only)
const MonthlyDataUpload = Loadable(lazy(() => import('../views/monthly/MonthlyDataUpload')));

//-----------------------|| MAIN ROUTING ||-----------------------//

const MainRoutes = () => {
    const location = useLocation();

    return (
        <Route
            path={[
                '/home',
                '/dashboard/default',
                '/warehouse/submitted-orders',
                '/warehouse/download-dms',
                '/warehouse/upload-orders',
                '/warehouse/manage-orders',
                '/warehouse/upload-invoices',
                '/warehouse/upload-products',
                '/warehouse/supply-sheet',
                '/warehouse/eway-bill',
                '/analytics',
                '/analytics/target-tracker',
                // Admin routes
                '/admin-controls',
                // Monthly data upload (top-level, admin only)
                '/monthly-data-upload',
            ]}
        >
            <MainLayout>
                <Switch location={location} key={location.pathname}>
                    {/* System launcher — the post-login landing */}
                    <Route path="/home" render={() => <AuthGuard><Launcher /></AuthGuard>} />
                    <Route path="/dashboard/default" render={() => <AuthGuard><WarehouseDashboard /></AuthGuard>} />

                    {/* Warehouse Management Routes */}
                    <Route path="/warehouse/submitted-orders" render={() => <AuthGuard><SubmittedOrders /></AuthGuard>} />
                    <Route path="/warehouse/download-dms" render={() => <AuthGuard><DownloadDmsInput /></AuthGuard>} />
                    <Route path="/warehouse/upload-orders" render={() => <AuthGuard><OrderUpload /></AuthGuard>} />
                    <Route
                        path="/warehouse/upload-picklists"
                        render={() => (
                            <AuthGuard>
                                <UploadPermissionGuard uploadType="picklists">
                                    <PicklistUpload />
                                </UploadPermissionGuard>
                            </AuthGuard>
                        )}
                    />
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

                    {/* Analytics — Target Tracker is the only screen, so /analytics lands on it */}
                    <Route path="/analytics/target-tracker" render={() => <AuthGuard><TargetTracker /></AuthGuard>} />
                    <Route exact path="/analytics" render={() => <Redirect to="/analytics/target-tracker" />} />

                    {/* Admin routes */}
                    <Route
                        path="/admin-controls"
                        render={() => (
                            <AuthGuard>
                                <AdminGuard>
                                    <AdminControls />
                                </AdminGuard>
                            </AuthGuard>
                        )}
                    />

                    {/* Monthly Data Upload — top-level, admin only */}
                    <Route
                        path="/monthly-data-upload"
                        render={() => (
                            <AuthGuard>
                                <AdminGuard>
                                    <MonthlyDataUpload />
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