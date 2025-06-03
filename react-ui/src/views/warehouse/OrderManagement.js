import React, { useState, useEffect } from 'react';
import {
  Grid,
  Typography,
  Snackbar,
  Alert
} from '@material-ui/core';
import { gridSpacing } from '../../store/constant';

// Import fixed components
import { useOrderManagementStyles } from './styles/orderManagement.styles';
import { filterOrdersByStatus } from './utils/orderManagement.utils';
import {
  FilterControls,
  OrdersTable,
  OrderDetailsDialog
} from './components/orderManagement.components';
import orderManagementService from '../../services/orderManagementService';

const OrderManagement = () => {
  const classes = useOrderManagementStyles();

  // State management
  const [warehouse, setWarehouse] = useState('');
  const [company, setCompany] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [warehouses, setWarehouses] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [orders, setOrders] = useState([]);
  const [filteredOrders, setFilteredOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [orderDetailsOpen, setOrderDetailsOpen] = useState(false);

  // Snackbar state
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [snackbarMessage, setSnackbarMessage] = useState('');
  const [snackbarSeverity, setSnackbarSeverity] = useState('success');

  // Fetch warehouses and companies on component mount
  useEffect(() => {
    const fetchInitialData = async () => {
      setLoading(true);
      try {
        // Fetch warehouses
        const warehouseResponse = await orderManagementService.getWarehouses();
        if (warehouseResponse.success) {
          setWarehouses(warehouseResponse.warehouses);
          if (warehouseResponse.warehouses.length > 0) {
            const firstWarehouse = warehouseResponse.warehouses[0];
            const warehouseId = firstWarehouse.warehouse_id !== undefined ? firstWarehouse.warehouse_id : firstWarehouse.id;
            setWarehouse(warehouseId);
          }
        }

        // Fetch companies
        const companyResponse = await orderManagementService.getCompanies();
        if (companyResponse.success) {
          setCompanies(companyResponse.companies);
          if (companyResponse.companies.length > 0) {
            const firstCompany = companyResponse.companies[0];
            const companyId = firstCompany.company_id !== undefined ? firstCompany.company_id : firstCompany.id;
            setCompany(companyId);
          }
        }
      } catch (error) {
        console.error('Error fetching initial data:', error);
        showSnackbar('Error fetching initial data', 'error');
      } finally {
        setLoading(false);
      }
    };

    fetchInitialData();
  }, []);

  // Fetch orders when warehouse, company changes
  useEffect(() => {
    const fetchOrders = async () => {
      if (!warehouse || !company) return;

      setLoading(true);
      try {
        const response = await orderManagementService.getOrders(warehouse, company);

        if (response.success) {
          const processedOrders = (response.orders || []).map(order => ({
            ...order,
            status: order.status || 'open',
            current_state_time: order.current_state_time || new Date().toISOString(),
            dealer_name: order.dealer_name || 'Unknown Dealer',
            assigned_to: order.assigned_to || 'Unassigned'
          }));

          setOrders(processedOrders);
        } else {
          console.error('Error in API response:', response.msg);
          showSnackbar('Error fetching orders: ' + response.msg, 'error');
          setOrders([]);
        }
      } catch (error) {
        console.error('Error fetching orders:', error);
        showSnackbar('Error fetching orders', 'error');
        setOrders([]);
      } finally {
        setLoading(false);
      }
    };

    fetchOrders();
  }, [warehouse, company]);

  // Filter orders based on status filter
  useEffect(() => {
    setFilteredOrders(filterOrdersByStatus(orders, statusFilter));
  }, [orders, statusFilter]);

  // Helper function to show snackbar messages
  const showSnackbar = (message, severity = 'info') => {
    setSnackbarMessage(message);
    setSnackbarSeverity(severity);
    setSnackbarOpen(true);
  };

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
    setLoading(true);
    try {
      const response = await orderManagementService.getOrderDetailsWithProducts(order.order_request_id);

      if (response.success) {
        setSelectedOrder(response.order);
        setOrderDetailsOpen(true);
      } else {
        showSnackbar('Error fetching order details: ' + response.msg, 'error');
      }
    } catch (error) {
      console.error('Error fetching order details:', error);
      showSnackbar('Error fetching order details', 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleOrderDetailsClose = () => {
    setOrderDetailsOpen(false);
    setSelectedOrder(null);
  };

  // FIXED: Comprehensive status update handler
  const handleStatusUpdate = async (order, action, additionalData = null) => {
    setLoading(true);

    try {
      let response;
      let successMessage = '';

      // Handle different actions based on the correct flow
      switch (action) {
        case 'open':
        case 'picking':
        case 'packing':
          // Regular status transitions
          response = await orderManagementService.updateOrderStatus(order.order_request_id, action);
          successMessage = `Order ${order.order_request_id} moved to ${action}`;
          break;

        case 'packing-to-dispatch':
          // This should open the dialog for packing configuration
          handleOrderClick(order);
          return; // Don't proceed with API call, let dialog handle it

        case 'dispatch-ready':
          // Move from packing to dispatch ready (creates final order)
          if (!additionalData || !additionalData.products || !additionalData.boxes) {
            showSnackbar('Missing product and box data for dispatch ready', 'error');
            return;
          }

          response = await orderManagementService.moveToDispatchReady(
            order.order_request_id,
            additionalData.products,
            additionalData.boxes
          );

          if (response.success) {
            successMessage = [
              `Order moved to Dispatch Ready!`,
              `Final Order: ${response.final_order_number}`,
              `Packed: ${response.total_packed} items`,
              response.total_remaining > 0 ? `Remaining: ${response.total_remaining} items` : '',
              response.has_remaining_items ? 'Status: Partially Completed' : 'Status: Dispatch Ready'
            ].filter(Boolean).join('\n');
          }
          break;

        case 'complete-dispatch':
        case 'completed':
          // Complete dispatch (mark as dispatched from warehouse)
          response = await orderManagementService.completeDispatch(order.order_request_id);

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

      if (response && response.success) {
        // Refresh orders list
        const updatedOrders = await orderManagementService.getOrders(warehouse, company);

        if (updatedOrders.success) {
          const processedOrders = (updatedOrders.orders || []).map(ord => ({
            ...ord,
            status: ord.status || 'open',
            current_state_time: ord.current_state_time || new Date().toISOString(),
            dealer_name: ord.dealer_name || 'Unknown Dealer',
            assigned_to: ord.assigned_to || 'Unassigned'
          }));

          setOrders(processedOrders);
        }

        showSnackbar(successMessage, 'success');

        // FIXED: Close dialog and clear selected order for completed actions
        if (action === 'completed' || action === 'complete-dispatch') {
          handleOrderDetailsClose();
        }
      } else if (response) {
        throw new Error(response.msg || 'Unknown error occurred');
      }
    } catch (error) {
      console.error('Error updating order status:', error);
      showSnackbar('Failed to update order status: ' + error.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  // FIXED: Handle status updates from the order details dialog with proper refresh
  const handleDialogStatusUpdate = async (order, action, additionalData = null) => {
    setLoading(true);

    try {
      let response;
      let successMessage = '';

      // Handle the action
      switch (action) {
        case 'dispatch-ready':
          response = await orderManagementService.moveToDispatchReady(
            order.order_request_id,
            additionalData.products,
            additionalData.boxes
          );

          if (response.success) {
            successMessage = [
              `Order moved to Dispatch Ready!`,
              `Final Order: ${response.final_order_number}`,
              `Packed: ${response.total_packed} items`,
              response.total_remaining > 0 ? `Remaining: ${response.total_remaining} items` : '',
              response.has_remaining_items ? 'Status: Partially Completed' : 'Status: Dispatch Ready'
            ].filter(Boolean).join('\n');
          }
          break;

        case 'completed':
        case 'complete-dispatch':
          response = await orderManagementService.completeDispatch(order.order_request_id);

          if (response.success) {
            successMessage = [
              'Order dispatched successfully!',
              `Order Number: ${response.final_order_number}`,
              `Dispatched: ${new Date(response.dispatched_date).toLocaleString()}`
            ].join('\n');
          }
          break;

        default:
          response = await orderManagementService.updateOrderStatus(order.order_request_id, action);
          successMessage = `Order ${order.order_request_id} moved to ${action}`;
          break;
      }

      if (response && response.success) {
        // Show success message
        showSnackbar(successMessage, 'success');

        // FIXED: Refresh the order details to get updated data
        try {
          const updatedOrderResponse = await orderManagementService.getOrderDetailsWithProducts(order.order_request_id);
          if (updatedOrderResponse.success) {
            setSelectedOrder(updatedOrderResponse.order);
          }
        } catch (refreshError) {
          console.error('Error refreshing order details:', refreshError);
          // If refresh fails, close the dialog
          handleOrderDetailsClose();
        }

        // Refresh the orders list
        const updatedOrders = await orderManagementService.getOrders(warehouse, company);
        if (updatedOrders.success) {
          const processedOrders = (updatedOrders.orders || []).map(ord => ({
            ...ord,
            status: ord.status || 'open',
            current_state_time: ord.current_state_time || new Date().toISOString(),
            dealer_name: ord.dealer_name || 'Unknown Dealer',
            assigned_to: ord.assigned_to || 'Unassigned'
          }));

          setOrders(processedOrders);
        }

        // Close dialog for completed actions
        if (action === 'completed' || action === 'complete-dispatch') {
          handleOrderDetailsClose();
        }
      } else if (response) {
        throw new Error(response.msg || 'Unknown error occurred');
      }
    } catch (error) {
      console.error('Error updating order status:', error);
      showSnackbar('Failed to update order status: ' + error.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleSnackbarClose = (event, reason) => {
    if (reason === 'clickaway') {
      return;
    }
    setSnackbarOpen(false);
  };

  return (
    <Grid container spacing={gridSpacing}>
      {/* Page Title */}
      <Grid item xs={12}>
        <Typography variant="h3" gutterBottom>Order Management</Typography>
        <Typography variant="subtitle1" color="textSecondary" gutterBottom>
          Manage orders through their lifecycle: Open → Picking → Packing → Dispatch Ready → Completed
        </Typography>
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

      {/* Orders Table */}
      <OrdersTable
        orders={filteredOrders}
        loading={loading}
        statusFilter={statusFilter}
        onOrderClick={handleOrderClick}
        onStatusUpdate={handleStatusUpdate}
        classes={classes}
      />

      {/* Enhanced Order Details Dialog */}
      <OrderDetailsDialog
        open={orderDetailsOpen}
        order={selectedOrder}
        onClose={handleOrderDetailsClose}
        onStatusUpdate={handleDialogStatusUpdate}
        classes={classes}
      />

      {/* Snackbar for notifications */}
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={6000}
        onClose={handleSnackbarClose}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert onClose={handleSnackbarClose} severity={snackbarSeverity}>
          {snackbarMessage}
        </Alert>
      </Snackbar>
    </Grid>
  );
};

export default OrderManagement;