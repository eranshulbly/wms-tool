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
const WarehouseDashboard = Loadable(lazy(() => import('../views/warehouse/WarehouseDashboard')));
const OrderManagement = Loadable(lazy(() => import('../views/warehouse/OrderManagement')));
const DownloadDmsInput = Loadable(lazy(() => import('../views/warehouse/DownloadDmsInput')));
const SupplySheetDownload = Loadable(lazy(() => import('../views/warehouse/SupplySheetDownload')));
const InvoiceUpload = Loadable(lazy(() => import('../views/warehouse/InvoiceUpload')));
const ProductUpload = Loadable(lazy(() => import('../views/warehouse/ProductUpload')));
const EwayBillGenerator = Loadable(lazy(() => import('../views/warehouse/EwayBillGenerator')));

// analytics routing
const InventoryReport = Loadable(lazy(() => import('../views/analytics/InventoryReport')));
const StockMovement = Loadable(lazy(() => import('../views/analytics/StockMovement')));
const SalesExecutives = Loadable(lazy(() => import('../views/analytics/SalesExecutives')));

// admin routing
const AdminControls = Loadable(lazy(() => import('../views/admin/AdminControls')));

// supplier document ingestion (top-level, admin only)
const InventoryIngestion = Loadable(lazy(() => import('../views/inventory/InventoryIngestion')));

//-----------------------|| MAIN ROUTING ||-----------------------//

const MainRoutes = () => {
    const location = useLocation();

    return (
        <Route
            path={[
                '/home',
                '/dashboard/default',
                '/warehouse/download-dms',
                '/warehouse/upload-orders',
                '/warehouse/manage-orders',
                '/warehouse/upload-invoices',
                '/warehouse/upload-products',
                '/warehouse/supply-sheet',
                '/warehouse/eway-bill',
                '/analytics',
                '/analytics/inventory-report',
                '/analytics/stock-movement',
                '/analytics/sales-executives',
                // Admin routes
                '/admin-controls',
                // Supplier document ingestion (top-level, admin only)
                '/inventory-ingestion',
            ]}
        >
            <MainLayout>
                <Switch location={location} key={location.pathname}>
                    {/* System launcher — the post-login landing */}
                    <Route path="/home" render={() => <AuthGuard><Launcher /></AuthGuard>} />
                    <Route path="/dashboard/default" render={() => <AuthGuard><WarehouseDashboard /></AuthGuard>} />

                    {/* Warehouse Management Routes */}
                    <Route path="/warehouse/download-dms" render={() => <AuthGuard><DownloadDmsInput /></AuthGuard>} />
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

                    {/* Analytics — /analytics lands on Batch Costing. Target Tracker
                        was removed (this deployment sets no targets). */}
                    <Route path="/analytics/inventory-report" render={() => <AuthGuard><InventoryReport /></AuthGuard>} />
                    <Route path="/analytics/stock-movement" render={() => <AuthGuard><StockMovement /></AuthGuard>} />
                    <Route path="/analytics/sales-executives" render={() => <AuthGuard><SalesExecutives /></AuthGuard>} />
                    <Route exact path="/analytics" render={() => <Redirect to="/analytics/inventory-report" />} />

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

                    {/* Inventory Ingestion — supplier GRN / credit notes, admin only */}
                    <Route
                        path="/inventory-ingestion"
                        render={() => (
                            <AuthGuard>
                                <AdminGuard>
                                    <InventoryIngestion />
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