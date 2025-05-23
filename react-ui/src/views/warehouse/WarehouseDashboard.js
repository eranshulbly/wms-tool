import React, { useState, useEffect } from 'react';
import {
  Grid,
  Card,
  CardContent,
  Typography
} from '@material-ui/core';
import { gridSpacing } from '../../store/constant';
import dashboardService from '../../services/dashboardService';

// Import separated modules
import { useWarehouseDashboardStyles } from './styles/warehouseDashboard.styles';
import { ORDER_STATUS_DATA } from './constants/warehouseDashboard.constants';
import { filterOrdersByStatus } from './utils/warehouseDashboard.utils';
import {
  FilterControls,
  StatusCard,
  OrdersTable,
  OrderDetailsDialog
} from './components/warehouseDashboard.components';

const WarehouseDashboard = () => {
  const classes = useWarehouseDashboardStyles();

  // State management
  const [warehouse, setWarehouse] = useState('');
  const [company, setCompany] = useState('');
  const [warehouses, setWarehouses] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusCounts, setStatusCounts] = useState({});
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [orderDetailsOpen, setOrderDetailsOpen] = useState(false);
  const [recentOrders, setRecentOrders] = useState([]);
  const [statusFilter, setStatusFilter] = useState('all');
  const [filteredOrders, setFilteredOrders] = useState([]);

  // Fetch warehouses and companies on component mount
  useEffect(() => {
    const fetchInitialData = async () => {
      setLoading(true);
      try {
        // Fetch warehouses
        const warehouseResponse = await dashboardService.getWarehouses();
        if (warehouseResponse.success) {
          setWarehouses(warehouseResponse.warehouses);
          // Set default warehouse selection
          if (warehouseResponse.warehouses.length > 0) {
            setWarehouse(warehouseResponse.warehouses[0].id);
          }
        }

        // Fetch companies
        const companyResponse = await dashboardService.getCompanies();
        if (companyResponse.success) {
          setCompanies(companyResponse.companies);
          // Set default company selection
          if (companyResponse.companies.length > 0) {
            setCompany(companyResponse.companies[0].id);
          }
        }
      } catch (error) {
        console.error('Error fetching initial data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchInitialData();
  }, []);

  // Fetch order data when warehouse or company changes
  useEffect(() => {
    const fetchOrderData = async () => {
      if (!warehouse || !company) return;

      setLoading(true);
      try {
        // Fetch order status counts
        const statusResponse = await dashboardService.getOrderStatusCounts(warehouse, company);
        if (statusResponse.success) {
          setStatusCounts(statusResponse.status_counts);
        }

        // Fetch recent activity
        const recentActivityResponse = await dashboardService.getRecentActivity(warehouse, company, 10);
        if (recentActivityResponse.success) {
          setRecentOrders(recentActivityResponse.recent_orders);
        }
      } catch (error) {
        console.error('Error fetching order data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchOrderData();
  }, [warehouse, company]);

  // Filter orders based on status filter
  useEffect(() => {
    setFilteredOrders(filterOrdersByStatus(recentOrders, statusFilter));
  }, [recentOrders, statusFilter]);

  // Event handlers
  const handleWarehouseChange = (event) => {
    setWarehouse(event.target.value);
  };

  const handleCompanyChange = (event) => {
    setCompany(event.target.value);
  };

  const handleStatusFilterChange = (event) => {
    setStatusFilter(event.target.value);
  };

  const handleOrderClick = async (order) => {
    try {
      const response = await dashboardService.getOrderDetails(order.order_request_id);
      if (response.success) {
        setSelectedOrder(response.order);
        setOrderDetailsOpen(true);
      }
    } catch (error) {
      console.error('Error fetching order details:', error);
    }
  };

  const handleOrderDetailsClose = () => {
    setOrderDetailsOpen(false);
  };

  return (
    <Grid container spacing={gridSpacing}>
      {/* Page Title */}
      <Grid item xs={12}>
        <Typography variant="h3">Warehouse Dashboard</Typography>
      </Grid>

      {/* Filter Controls */}
      <FilterControls
        warehouses={warehouses}
        companies={companies}
        warehouse={warehouse}
        company={company}
        statusFilter={statusFilter}
        onWarehouseChange={handleWarehouseChange}
        onCompanyChange={handleCompanyChange}
        onStatusFilterChange={handleStatusFilterChange}
        classes={classes}
      />

      {/* Order Status Cards */}
      <Grid item xs={12}>
        <Grid container spacing={gridSpacing}>
          {Object.keys(ORDER_STATUS_DATA).map((status) => (
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

      {/* Recent Activity Table */}
      <Grid item xs={12}>
        <Card>
          <CardContent>
            <Typography variant="h4" gutterBottom>
              Recent Activity
              {statusFilter !== 'all' && (
                <Typography
                  variant="subtitle1"
                  component="span"
                  className={classes.filterTitle}
                >
                  - Showing {ORDER_STATUS_DATA[statusFilter]?.label || statusFilter} ({filteredOrders.length} orders)
                </Typography>
              )}
            </Typography>

            <OrdersTable
              filteredOrders={filteredOrders}
              loading={loading}
              statusFilter={statusFilter}
              onOrderClick={handleOrderClick}
              classes={classes}
            />
          </CardContent>
        </Card>
      </Grid>

      {/* Order Details Dialog */}
      <OrderDetailsDialog
        open={orderDetailsOpen}
        order={selectedOrder}
        onClose={handleOrderDetailsClose}
        classes={classes}
      />
    </Grid>
  );
};

export default WarehouseDashboard;