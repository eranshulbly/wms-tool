import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useSelector } from 'react-redux';
import { Grid, Typography, Snackbar, Alert } from '@material-ui/core';
import { gridSpacing } from '../../store/constant';

import { useOrderManagementStyles } from './styles/orderManagement.styles';
import { useWarehouse } from '../../context/WarehouseContext';
import { useSnackbar } from '../../hooks/useSnackbar';
import {
  getOrders,
  getOrderDetails,
  updateOrderStatus,
  completeDispatch
} from '../../services/orderService';

import FilterControls from './components/FilterControls';
import OrdersTable from './components/OrdersTable';
import OrderDetailsDialog from './components/OrderDetailsDialog';
import BulkActionsBar from './components/BulkActionsBar';

const OrderManagement = () => {
  const classes = useOrderManagementStyles();
  const user = useSelector((state) => state.account.user);
  const { snackbar, showSnackbar, hideSnackbar } = useSnackbar();

  const allowedStatuses = useMemo(() => {
    const orderStates = user?.permissions?.order_states;
    if (!orderStates || orderStates.length === 0) return null;
    return orderStates.map((name) => name.toLowerCase().replace(/ /g, '-'));
  }, [user]);

  const {
    warehouses,
    companies,
    selectedWarehouse: warehouse,
    setSelectedWarehouse: setWarehouse,
    selectedCompany: company,
    setSelectedCompany: setCompany
  } = useWarehouse();

  const [statusFilter, setStatusFilter] = useState('all');
  const [filteredOrders, setFilteredOrders] = useState([]);
  const [totalOrders, setTotalOrders] = useState(0);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [orderDetailsOpen, setOrderDetailsOpen] = useState(false);

  const fetchOrders = useCallback(async (resetPage = false) => {
    if (!warehouse || !company) return;

    setLoading(true);
    try {
      const apiStatus = statusFilter !== 'all' ? statusFilter : null;
      const response = await getOrders(warehouse, company, apiStatus);

      if (response.success) {
        const processed = (response.orders || []).map((order) => ({
          ...order,
          status: order.status || 'open',
          current_state_time: order.current_state_time || new Date().toISOString(),
          dealer_name: order.dealer_name || 'Unknown Dealer',
          assigned_to: order.assigned_to || 'Unassigned'
        }));
        setFilteredOrders(processed);
        setTotalOrders(response.total ?? processed.length);
        if (resetPage) setPage(0);
      } else {
        showSnackbar('Error fetching orders: ' + response.msg, 'error');
        setFilteredOrders([]);
      }
    } catch (error) {
      console.error('Error fetching orders:', error);
      showSnackbar('Error fetching orders', 'error');
      setFilteredOrders([]);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [warehouse, company, statusFilter]);

  useEffect(() => { fetchOrders(true); }, [fetchOrders]);

  const handleOrderClick = async (order) => {
    setLoading(true);
    try {
      const response = await getOrderDetails(order.order_request_id);
      if (response.success) {
        setSelectedOrder(response.order);
        setOrderDetailsOpen(true);
      } else {
        showSnackbar('Error fetching order details: ' + response.msg, 'error');
      }
    } catch (error) {
      showSnackbar('Error fetching order details', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleOrderDetailsClose = () => {
    setOrderDetailsOpen(false);
    setSelectedOrder(null);
  };

  const handleStatusUpdate = async (order, action, additionalData = null) => {
    setLoading(true);
    try {
      let response;
      let successMessage = '';

      switch (action) {
        case 'open':
        case 'picking':
        case 'packed':
          response = await updateOrderStatus(order.order_request_id, action, additionalData);
          successMessage = `Order ${order.order_request_id} moved to ${action}`;
          break;

        case 'complete-dispatch':
        case 'completed':
          response = await completeDispatch(order.order_request_id);
          if (response.success) {
            successMessage = [
              'Order dispatched successfully!',
              `Order Number: ${response.final_order_number}`,
              `Dispatched: ${new Date(response.dispatched_date).toLocaleString()}`
            ].join('\n');
          }
          break;

        default:
          showSnackbar(`Unknown action: ${action}`, 'error');
          return;
      }

      if (response?.success) {
        showSnackbar(successMessage, 'success');
        if (action === 'completed' || action === 'complete-dispatch') {
          handleOrderDetailsClose();
        }
        await fetchOrders(false);
      } else if (response) {
        throw new Error(response.msg || 'Unknown error occurred');
      }
    } catch (error) {
      showSnackbar('Failed to update order status: ' + error.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleDialogStatusUpdate = async (order, action, additionalData = null) => {
    setLoading(true);
    try {
      let response;
      let successMessage = '';

      switch (action) {
        case 'completed':
        case 'complete-dispatch':
          response = await completeDispatch(order.order_request_id);
          if (response.success) {
            successMessage = [
              'Order dispatched successfully!',
              `Order Number: ${response.final_order_number}`,
              `Dispatched: ${new Date(response.dispatched_date).toLocaleString()}`
            ].join('\n');
          }
          break;

        default:
          response = await updateOrderStatus(order.order_request_id, action, additionalData);
          successMessage = `Order ${order.order_request_id} moved to ${action}`;
          break;
      }

      if (response?.success) {
        showSnackbar(successMessage, 'success');

        // Refresh the dialog with updated order data
        try {
          const updated = await getOrderDetails(order.order_request_id);
          if (updated.success) setSelectedOrder(updated.order);
        } catch {
          handleOrderDetailsClose();
        }

        await fetchOrders(false);

        if (action === 'completed' || action === 'complete-dispatch') {
          handleOrderDetailsClose();
        }
      } else if (response) {
        throw new Error(response.msg || 'Unknown error occurred');
      }
    } catch (error) {
      showSnackbar('Failed to update order status: ' + error.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const pagedOrders = filteredOrders.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage);

  const handleBulkUploadComplete = async (result) => {
    if (result.processed_count > 0 && warehouse && company) {
      await fetchOrders(true);
    }
  };

  return (
    <Grid container spacing={gridSpacing}>
      <Grid item xs={12}>
        <Typography variant="h3" gutterBottom>Order Management</Typography>
        <Typography variant="subtitle1" color="textSecondary" gutterBottom>
          Manage orders through their lifecycle: Open → Picking → Packed → Invoiced → Dispatch Ready → Completed
        </Typography>
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

      <BulkActionsBar
        warehouse={warehouse}
        company={company}
        onUploadComplete={handleBulkUploadComplete}
      />

      <OrdersTable
        orders={pagedOrders}
        totalCount={totalOrders}
        page={page}
        rowsPerPage={rowsPerPage}
        onPageChange={(e, newPage) => setPage(newPage)}
        onRowsPerPageChange={(e) => { setRowsPerPage(parseInt(e.target.value, 10)); setPage(0); }}
        loading={loading}
        statusFilter={statusFilter}
        onOrderClick={handleOrderClick}
        onStatusUpdate={handleStatusUpdate}
        allowedStatuses={allowedStatuses}
        classes={classes}
      />

      <OrderDetailsDialog
        open={orderDetailsOpen}
        order={selectedOrder}
        onClose={handleOrderDetailsClose}
        onStatusUpdate={handleDialogStatusUpdate}
        allowedStatuses={allowedStatuses}
        classes={classes}
      />

      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={hideSnackbar}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert onClose={hideSnackbar} severity={snackbar.severity}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Grid>
  );
};

export default OrderManagement;
