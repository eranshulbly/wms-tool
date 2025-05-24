import React, { useState, useEffect } from 'react';
import {
  Grid,
  Typography,
  Snackbar,
  Alert
} from '@material-ui/core';
import { gridSpacing } from '../../store/constant';

// Import separated modules
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
          // Set default warehouse selection
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
          // Set default company selection
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
          // Ensure all orders have valid status and required fields
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
      // Fetch detailed order information with products
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

  const handleStatusUpdate = async (order, newStatus, additionalData = null) => {
    setLoading(true);

    try {
      let response;

      // Handle different status transitions
      if (newStatus === 'dispatch' && additionalData) {
        // For dispatch, use the specialized endpoint
        response = await orderManagementService.finalizeDispatch(
          order.order_request_id,
          additionalData.products,
          additionalData.boxes
        );
      } else if (newStatus === 'packing' && additionalData) {
        // For packing updates, use the packing endpoint
        response = await orderManagementService.updatePackingInfo(
          order.order_request_id,
          additionalData.products,
          additionalData.boxes
        );
      } else {
        // For regular status updates
        response = await orderManagementService.updateOrderStatus(
          order.order_request_id,
          newStatus,
          additionalData
        );
      }

      if (response.success) {
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

        // Show success message with additional info if available
        let message = `Order ${order.order_request_id} status updated to ${newStatus}`;
        if (response.final_order_id) {
          message += `\nFinal Order ID: ${response.final_order_id}`;
        }
        if (response.products_dispatched !== undefined) {
          message += `\nProducts Dispatched: ${response.products_dispatched}`;
        }
        if (response.remaining_products !== undefined && response.remaining_products > 0) {
          message += `\nRemaining Products: ${response.remaining_products}`;
        }

        showSnackbar(message, 'success');

        // Close dialog if it was a successful dispatch
        if (newStatus === 'dispatch' && response.final_order_id) {
          handleOrderDetailsClose();
        }
      } else {
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
        onStatusUpdate={handleStatusUpdate}
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
  )
};

export default OrderManagement;