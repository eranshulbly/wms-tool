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
const SubmittedOrders = Loadable(lazy(() => import('../views/warehouse/SubmittedOrders')));
const DownloadDmsInput = Loadable(lazy(() => import('../views/warehouse/DownloadDmsInput')));
const DownloadPicklist = Loadable(lazy(() => import('../views/warehouse/DownloadPicklist')));
const SupplySheetDownload = Loadable(lazy(() => import('../views/warehouse/SupplySheetDownload')));
const InvoiceUpload = Loadable(lazy(() => import('../views/warehouse/InvoiceUpload')));
const ProductUpload = Loadable(lazy(() => import('../views/warehouse/ProductUpload')));
const EwayBillGenerator = Loadable(lazy(() => import('../views/warehouse/EwayBillGenerator')));

// analytics routing
const TargetTracker = Loadable(lazy(() => import('../views/analytics/TargetTracker')));
const InventoryReport = Loadable(lazy(() => import('../views/analytics/InventoryReport')));

// admin routing
const AdminControls = Loadable(lazy(() => import('../views/admin/AdminControls')));

// PO Builder (top-level, admin only) — draft supplier POs with live scheme slabs
const BuildPo = Loadable(lazy(() => import('../views/po-builder/BuildPo')));
const PoBuilderMasters = Loadable(lazy(() => import('../views/po-builder/PoBuilderMasters')));
const TatCheck = Loadable(lazy(() => import('../views/tat-check/TatCheck')));
const DmsFeedUpload = Loadable(lazy(() => import('../views/dms-uploads/DmsFeedUpload')));
const BeatOutstanding = Loadable(lazy(() => import('../views/beat-outstanding/BeatOutstanding')));

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
                '/warehouse/download-picklist',
                '/warehouse/upload-orders',
                '/warehouse/manage-orders',
                '/warehouse/upload-invoices',
                '/warehouse/upload-products',
                '/warehouse/supply-sheet',
                '/warehouse/eway-bill',
                '/analytics',
                '/analytics/target-tracker',
                '/analytics/inventory-report',
                // Admin routes
                '/admin-controls',
                '/sku-master-upload',
                '/scheme-upload',
                '/outlet-master-upload',
                '/beat-outstanding',
                '/po-builder',
                '/tat-check',
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
                    <Route path="/warehouse/download-picklist" render={() => <AuthGuard><DownloadPicklist /></AuthGuard>} />
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

                    {/* Analytics — /analytics lands on Target Tracker */}
                    <Route path="/analytics/target-tracker" render={() => <AuthGuard><TargetTracker /></AuthGuard>} />
                    <Route path="/analytics/inventory-report" render={() => <AuthGuard><InventoryReport /></AuthGuard>} />
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

                    {/* Outlet Master Upload — read by Beat Outstanding, admin only */}
                    <Route
                        path="/outlet-master-upload"
                        render={() => (
                            <AuthGuard>
                                <AdminGuard>
                                    <DmsFeedUpload key="outlets" feed="outlets" />
                                </AdminGuard>
                            </AuthGuard>
                        )}
                    />
                    {/* Beat Outstanding — each executive's dealers' outstanding for the day, admin only */}
                    <Route
                        path="/beat-outstanding"
                        render={() => (
                            <AuthGuard>
                                <AdminGuard>
                                    <BeatOutstanding />
                                </AdminGuard>
                            </AuthGuard>
                        )}
                    />

                    {/* PO Builder masters that live in the Admin menu (menu-items/admin.js). */}
                    <Route
                        path="/sku-master-upload"
                        render={() => (
                            <AuthGuard>
                                <AdminGuard>
                                    <PoBuilderMasters key="sku-master" section="sku-master" />
                                </AdminGuard>
                            </AuthGuard>
                        )}
                    />
                    <Route
                        path="/scheme-upload"
                        render={() => (
                            <AuthGuard>
                                <AdminGuard>
                                    <PoBuilderMasters key="schemes" section="schemes" />
                                </AdminGuard>
                            </AuthGuard>
                        )}
                    />
                    <Redirect exact from="/po-builder/sku-master" to="/sku-master-upload" />
                    <Redirect exact from="/po-builder/schemes" to="/scheme-upload" />

                    {/* PO Builder — supplier POs with live scheme slabs, admin only.
                        Each master-data page is its own sidebar item (menu-items/poBuilder.js). */}
                    <Redirect exact from="/po-builder" to="/po-builder/build" />
                    <Route
                        path="/po-builder/build"
                        render={() => (
                            <AuthGuard>
                                <AdminGuard>
                                    <BuildPo />
                                </AdminGuard>
                            </AuthGuard>
                        )}
                    />
                    <Route
                        path="/po-builder/:section(sku-mapping|settings)"
                        render={() => (
                            <AuthGuard>
                                <AdminGuard>
                                    <PoBuilderMasters />
                                </AdminGuard>
                            </AuthGuard>
                        )}
                    />

                    {/* TAT Check — stock / in transit / in PO for a SKU. Any logged-in user
                        can check; the files it reads are uploaded from the Admin menu. */}
                    <Route path="/tat-check" render={() => <AuthGuard><TatCheck /></AuthGuard>} />
                </Switch>
            </MainLayout>
        </Route>
    );
};

export default MainRoutes;