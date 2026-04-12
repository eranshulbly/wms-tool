import React, { useState, useEffect, useCallback } from 'react';
import {
  Grid,
  Card,
  CardContent,
  Typography,
  IconButton,
  Tooltip
} from '@material-ui/core';
import RefreshIcon from '@material-ui/icons/Refresh';
import { gridSpacing } from '../../store/constant';

import { useWarehouseDashboardStyles } from './styles/warehouseDashboard.styles';
import { ORDER_STATUS_DATA } from './constants/statuses';
import { filterOrdersByStatus } from './utils';
import { useWarehouse } from '../../context/WarehouseContext';
import { getOrderStatusCounts, getOrderDetails, getRecentActivity } from '../../services/orderService';

import FilterControls from './components/FilterControls';
import CompactStatusSummary from './components/CompactStatusSummary';
import StatusCard from './components/StatusCard';
import OrdersTable from './components/OrdersTable';
import OrderDetailsDialog from './components/OrderDetailsDialog';

import { useSelector } from 'react-redux';

// Convert backend state names ("Dispatch Ready") to frontend slugs ("dispatch-ready")
const stateNameToKey = (name) => name.toLowerCase().replace(/ /g, '-');

const WarehouseDashboard = () => {
  const classes = useWarehouseDashboardStyles();
  const user = useSelector((state) => state.account.user);

  const allowedStatuses = React.useMemo(() => {
    const orderStates = user?.permissions?.order_states;
    if (!orderStates || orderStates.length === 0) return null;
    return orderStates.map(stateNameToKey);
  }, [user]);

  const {
    warehouses,
    companies,
    selectedWarehouse: warehouse,
    setSelectedWarehouse: setWarehouse,
    selectedCompany: company,
    setSelectedCompany: setCompany
  } = useWarehouse();

  const [loading, setLoading] = useState(false);
  const [statusCounts, setStatusCounts] = useState({});
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [orderDetailsOpen, setOrderDetailsOpen] = useState(false);
  const [recentOrders, setRecentOrders] = useState([]);
  const [statusFilter, setStatusFilter] = useState('all');
  const [filteredOrders, setFilteredOrders] = useState([]);
  const [compactView] = useState(true);
  const [refreshTick, setRefreshTick] = useState(0);

  const handleRefresh = useCallback(() => setRefreshTick((t) => t + 1), []);

  // Fetch order data when warehouse, company, or refreshTick changes
  useEffect(() => {
    if (!warehouse || !company) return;

    let mounted = true;
    const fetchOrderData = async () => {
      setLoading(true);
      try {
        const [statusData, recentData] = await Promise.all([
          getOrderStatusCounts(warehouse, company),
          getRecentActivity(warehouse, company)
        ]);
        if (!mounted) return;
        if (statusData.success) setStatusCounts(statusData.status_counts);
        if (recentData.success) setRecentOrders(recentData.recent_orders);
      } catch (error) {
        console.error('Error fetching order data:', error);
      } finally {
        if (mounted) setLoading(false);
      }
    };

    fetchOrderData();
    return () => { mounted = false; };
  }, [warehouse, company, refreshTick]);

  // Client-side filter for the recent orders table
  useEffect(() => {
    setFilteredOrders(filterOrdersByStatus(recentOrders, statusFilter));
  }, [recentOrders, statusFilter]);

  const handleOrderClick = async (order) => {
    try {
      const response = await getOrderDetails(order.order_request_id);
      if (response.success) {
        setSelectedOrder(response.order);
        setOrderDetailsOpen(true);
      }
    } catch (error) {
      console.error('Error fetching order details:', error);
    }
  };

  const renderStatusCounts = () => {
    if (compactView) {
      return (
        <CompactStatusSummary
          statusCounts={statusCounts}
          loading={loading}
          classes={classes}
          allowedStatuses={allowedStatuses}
        />
      );
    }
    const statusKeys = allowedStatuses
      ? Object.keys(ORDER_STATUS_DATA).filter((s) => allowedStatuses.includes(s))
      : Object.keys(ORDER_STATUS_DATA);
    return (
      <Grid item xs={12}>
        <Grid container spacing={gridSpacing}>
          {statusKeys.map((status) => (
            <StatusCard
              key={status}
              status={status}
              count={statusCounts[status]?.count}
              loading={loading}
              classes={classes}
            />
          ))}
        </Grid>
      </Grid>
    );
  };

  return (
    <Grid container spacing={gridSpacing}>
      <Grid item xs={12}>
        <Typography variant="h3">Warehouse Dashboard</Typography>
      </Grid>

      <FilterControls
        warehouses={warehouses}
        companies={companies}
        warehouse={warehouse}
        company={company}
        statusFilter={statusFilter}
        onWarehouseChange={(e) => setWarehouse(e.target.value)}
        onCompanyChange={(e) => setCompany(e.target.value)}
        onStatusFilterChange={(e) => setStatusFilter(e.target.value)}
        allowedStatuses={allowedStatuses}
        classes={classes}
      />

      {renderStatusCounts()}

      <Grid item xs={12}>
        <Card>
          <CardContent style={{ padding: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
              <Typography variant="h4">
                Recent Activity
                {statusFilter !== 'all' && (
                  <Typography variant="subtitle1" component="span" className={classes.filterTitle}>
                    &nbsp;— Showing {ORDER_STATUS_DATA[statusFilter]?.label || statusFilter} ({filteredOrders.length} orders)
                  </Typography>
                )}
              </Typography>
              <Tooltip title="Refresh data">
                <span>
                  <IconButton size="small" onClick={handleRefresh} disabled={loading}>
                    <RefreshIcon />
                  </IconButton>
                </span>
              </Tooltip>
            </div>

            <OrdersTable
              orders={filteredOrders}
              loading={loading}
              statusFilter={statusFilter}
              onOrderClick={handleOrderClick}
              classes={classes}
            />
          </CardContent>
        </Card>
      </Grid>

      <OrderDetailsDialog
        open={orderDetailsOpen}
        order={selectedOrder}
        onClose={() => setOrderDetailsOpen(false)}
        classes={classes}
      />
    </Grid>
  );
};

export default WarehouseDashboard;
