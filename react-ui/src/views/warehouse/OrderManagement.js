import React, { useState, useEffect } from 'react';
import {
  Grid,
  Card,
  CardContent,
  Typography,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  CircularProgress,
  Box,
  TextField,
  IconButton,
  Chip,
  Stepper,
  Step,
  StepLabel,
  Divider,
  Tabs,
  Tab,
  Snackbar,
  Alert
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import {
  IconPackage,
  IconSearch,
  IconPlus,
  IconTrash,
} from '@tabler/icons';
import { gridSpacing } from '../../store/constant';

// Custom styles for the order management page
const useStyles = makeStyles((theme) => ({
  formControl: {
    marginBottom: theme.spacing(2),
    minWidth: 200
  },
  tableContainer: {
    maxHeight: 600,
    marginTop: theme.spacing(2)
  },
  statusChip: {
    margin: theme.spacing(0.5)
  },
  chipOpen: {
    backgroundColor: theme.palette.warning.light,
    color: theme.palette.warning.dark
  },
  chipPicking: {
    backgroundColor: theme.palette.primary.light,
    color: theme.palette.primary.dark
  },
  chipPacking: {
    backgroundColor: theme.palette.secondary.light,
    color: theme.palette.secondary.dark
  },
  chipDispatch: {
    backgroundColor: theme.palette.success.light,
    color: theme.palette.success.dark
  },
  loadingContainer: {
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    height: '100px'
  },
  statusCard: {
    height: '100%',
    cursor: 'pointer',
    transition: 'transform 0.2s ease-in-out, box-shadow 0.2s ease-in-out',
    '&:hover': {
      transform: 'translateY(-5px)',
      boxShadow: theme.shadows[10]
    }
  },
  orderDetailsContainer: {
    marginBottom: theme.spacing(3)
  },
  boxesContainer: {
    margin: theme.spacing(2, 0)
  },
  boxItem: {
    padding: theme.spacing(2),
    marginBottom: theme.spacing(2),
    backgroundColor: theme.palette.background.default,
    borderRadius: theme.shape.borderRadius,
    position: 'relative'
  },
  addBoxButton: {
    margin: theme.spacing(2, 0)
  },
  tabRoot: {
    flexGrow: 1,
    backgroundColor: theme.palette.background.paper,
    marginBottom: theme.spacing(2)
  },
  orderSummary: {
    marginBottom: theme.spacing(2)
  },
  infoGrid: {
    marginBottom: theme.spacing(1)
  },
  infoLabel: {
    fontWeight: 500,
    color: theme.palette.grey[700]
  },
  infoValue: {
    fontWeight: 400
  },
  detailsHeader: {
    display: 'flex',
    alignItems: 'center',
    marginBottom: theme.spacing(2)
  },
  orderIcon: {
    marginRight: theme.spacing(1)
  },
  boxIconContainer: {
    position: 'absolute',
    top: theme.spacing(1),
    right: theme.spacing(1)
  },
  statusButtonGroup: {
    marginTop: theme.spacing(3)
  },
  orderFilterContainer: {
    marginBottom: theme.spacing(3)
  },
  updateButton: {
    marginTop: theme.spacing(2)
  },
  productTable: {
    marginTop: theme.spacing(2)
  },
  boxIdField: {
    marginBottom: theme.spacing(1)
  }
}));

// Mock data for warehouses and companies
const mockWarehouses = [
  { warehouse_id: 1, name: 'Main Warehouse', location: 'New York' },
  { warehouse_id: 2, name: 'West Coast Facility', location: 'Los Angeles' },
  { warehouse_id: 3, name: 'Central Distribution', location: 'Chicago' }
];

const mockCompanies = [
  { company_id: 1, name: 'Acme Corporation' },
  { company_id: 2, name: 'Globex Industries' },
  { company_id: 3, name: 'Wayne Enterprises' }
];

// Mock products data
const generateMockProducts = (count) => {
  const products = [];
  for (let i = 1; i <= count; i++) {
    products.push({
      product_id: `P${Math.floor(Math.random() * 90000) + 10000}`,
      name: `Product ${i}`,
      description: `Description for Product ${i}`,
      quantity: Math.floor(Math.random() * 5) + 1,
      assigned_to_box: null // Initially not assigned to any box
    });
  }
  return products;
};

// Mock order data generator
const generateMockOrders = (status, count) => {
  const orders = [];
  for (let i = 1; i <= count; i++) {
    const orderDate = new Date();
    orderDate.setDate(orderDate.getDate() - Math.floor(Math.random() * 14));

    const numProducts = Math.floor(Math.random() * 5) + 1;
    const products = generateMockProducts(numProducts);
    const boxes = [];

    // If status is dispatch, add some boxes
    if (status === 'dispatch') {
      const numBoxes = Math.ceil(numProducts / 2); // Roughly half as many boxes as products
      for (let b = 1; b <= numBoxes; b++) {
        boxes.push({
          box_id: `B${Math.floor(Math.random() * 900) + 100}`,
          name: `Box ${b}`,
          products: []
        });
      }

      // Assign products to boxes
      products.forEach((product, index) => {
        const boxIndex = index % numBoxes;
        product.assigned_to_box = boxes[boxIndex].box_id;
        boxes[boxIndex].products.push(product.product_id);
      });
    }

    orders.push({
      order_request_id: `${status.substring(0, 1).toUpperCase()}${Math.floor(Math.random() * 90000) + 10000}`,
      original_order_id: `ORD-${Math.floor(Math.random() * 90000) + 10000}`,
      dealer_name: `Dealer ${Math.floor(Math.random() * 20) + 1}`,
      assigned_to: `User ${Math.floor(Math.random() * 5) + 1}`,
      order_date: orderDate.toISOString(),
      status: status,
      current_state_time: new Date(new Date().getTime() - Math.floor(Math.random() * 24 * 60 * 60 * 1000)).toISOString(),
      products: products,
      boxes: boxes,
      state_history: [
        {
          state_name: 'Open',
          timestamp: new Date(new Date().getTime() - Math.floor(Math.random() * 7 * 24 * 60 * 60 * 1000)).toISOString(),
          user: `User ${Math.floor(Math.random() * 5) + 1}`
        },
        ...(status !== 'open' ? [{
          state_name: 'Picking',
          timestamp: new Date(new Date().getTime() - Math.floor(Math.random() * 5 * 24 * 60 * 60 * 1000)).toISOString(),
          user: `User ${Math.floor(Math.random() * 5) + 1}`
        }] : []),
        ...(status === 'packing' || status === 'dispatch' ? [{
          state_name: 'Packing',
          timestamp: new Date(new Date().getTime() - Math.floor(Math.random() * 3 * 24 * 60 * 60 * 1000)).toISOString(),
          user: `User ${Math.floor(Math.random() * 5) + 1}`
        }] : []),
        ...(status === 'dispatch' ? [{
          state_name: 'Dispatch',
          timestamp: new Date(new Date().getTime() - Math.floor(Math.random() * 1 * 24 * 60 * 60 * 1000)).toISOString(),
          user: `User ${Math.floor(Math.random() * 5) + 1}`
        }] : [])
      ]
    });
  }
  return orders;
};

// Mock orders
const mockOrders = {
  open: generateMockOrders('open', 5),
  picking: generateMockOrders('picking', 8),
  packing: generateMockOrders('packing', 12),
  dispatch: generateMockOrders('dispatch', 7)
};

const OrderManagement = () => {
  const classes = useStyles();
  const [warehouse, setWarehouse] = useState('');
  const [company, setCompany] = useState('');
  const [warehouses, setWarehouses] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedStatus, setSelectedStatus] = useState('all');
  const [orders, setOrders] = useState([]);
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [orderDetailsOpen, setOrderDetailsOpen] = useState(false);
  const [statusUpdateDialog, setStatusUpdateDialog] = useState(false);
  const [newStatus, setNewStatus] = useState('');
  const [tabValue, setTabValue] = useState(0);
  const [boxes, setBoxes] = useState([]);
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [snackbarMessage, setSnackbarMessage] = useState('');
  const [snackbarSeverity, setSnackbarSeverity] = useState('success');

  // Fetch warehouses and companies on component mount
  useEffect(() => {
    const fetchInitialData = async () => {
      setLoading(true);
      try {
        // In a real app, you would fetch this data from your API
        // const warehouseResponse = await axios.get(`${config.API_SERVER}warehouses`);
        // const companyResponse = await axios.get(`${config.API_SERVER}companies`);

        // Using mock data for now
        setWarehouses(mockWarehouses);
        setCompanies(mockCompanies);

        // Set default selections
        if (mockWarehouses.length > 0) {
          setWarehouse(mockWarehouses[0].warehouse_id);
        }
        if (mockCompanies.length > 0) {
          setCompany(mockCompanies[0].company_id);
        }
      } catch (error) {
        console.error('Error fetching initial data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchInitialData();
  }, []);

  // Fetch orders when warehouse, company, or selectedStatus changes
  useEffect(() => {
    const fetchOrders = async () => {
      if (!warehouse || !company) return;

      setLoading(true);
      try {
        // In a real app, you would fetch this data from your API
        // const response = await axios.get(`${config.API_SERVER}orders`, {
        //   params: {
        //     warehouse_id: warehouse,
        //     company_id: company,
        //     status: selectedStatus !== 'all' ? selectedStatus : undefined
        //   }
        // });

        // Using mock data for now
        // Simulating an API delay
        await new Promise(resolve => setTimeout(resolve, 1000));

        if (selectedStatus === 'all') {
          // Combine all statuses
          setOrders([
            ...mockOrders.open,
            ...mockOrders.picking,
            ...mockOrders.packing,
            ...mockOrders.dispatch
          ]);
        } else {
          setOrders(mockOrders[selectedStatus] || []);
        }
      } catch (error) {
        console.error('Error fetching orders:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchOrders();
  }, [warehouse, company, selectedStatus]);

  // Handle warehouse selection change
  const handleWarehouseChange = (event) => {
    setWarehouse(event.target.value);
  };

  // Handle company selection change
  const handleCompanyChange = (event) => {
    setCompany(event.target.value);
  };

  // Handle status filter change
  const handleStatusChange = (event) => {
    setSelectedStatus(event.target.value);
  };

  // Handle opening order details
  const handleOrderClick = (order) => {
    setSelectedOrder(order);
    // If order is in packing status, initialize boxes array if empty
    if (order.status === 'packing' && (!order.boxes || order.boxes.length === 0)) {
      setBoxes([{
        box_id: `B${Math.floor(Math.random() * 900) + 100}`,
        name: 'Box 1',
        products: []
      }]);
    } else {
      setBoxes(order.boxes || []);
    }
    setOrderDetailsOpen(true);
  };

  // Handle closing order details
  const handleOrderDetailsClose = () => {
    setOrderDetailsOpen(false);
    setSelectedOrder(null);
    setBoxes([]);
  };

  // Handle tab change
  const handleTabChange = (event, newValue) => {
    setTabValue(newValue);
  };

  // Handle opening status update dialog
  const handleOpenStatusUpdate = (status) => {
    setNewStatus(status);
    setStatusUpdateDialog(true);
  };

  // Handle closing status update dialog
  const handleCloseStatusUpdate = () => {
    setStatusUpdateDialog(false);
  };

  // Add a new box
  const handleAddBox = () => {
    setBoxes([
      ...boxes,
      {
        box_id: `B${Math.floor(Math.random() * 900) + 100}`,
        name: `Box ${boxes.length + 1}`,
        products: []
      }
    ]);
  };

  // Remove a box
  const handleRemoveBox = (index) => {
    const updatedBoxes = [...boxes];
    // Get products that were in this box
    const productsToReassign = updatedBoxes[index].products || [];

    // Update products to show they're no longer assigned
    if (selectedOrder && productsToReassign.length > 0) {
      const updatedOrder = { ...selectedOrder };
      productsToReassign.forEach(productId => {
        const product = updatedOrder.products.find(p => p.product_id === productId);
        if (product) {
          product.assigned_to_box = null;
        }
      });
      setSelectedOrder(updatedOrder);
    }

    // Remove the box
    updatedBoxes.splice(index, 1);
    setBoxes(updatedBoxes);
  };

  // Update box ID
  const handleBoxIdChange = (index, value) => {
    const updatedBoxes = [...boxes];
    updatedBoxes[index].box_id = value;
    setBoxes(updatedBoxes);
  };

  // Update box name
  const handleBoxNameChange = (index, value) => {
    const updatedBoxes = [...boxes];
    updatedBoxes[index].name = value;
    setBoxes(updatedBoxes);
  };

  // Assign product to box
  const handleAssignProductToBox = (productId, boxId) => {
    if (!selectedOrder) return;

    // Update the product's box assignment
    const updatedOrder = { ...selectedOrder };
    const product = updatedOrder.products.find(p => p.product_id === productId);

    if (product) {
      // If product was previously assigned to a different box, remove it from that box
      if (product.assigned_to_box) {
        const oldBox = boxes.find(b => b.box_id === product.assigned_to_box);
        if (oldBox) {
          oldBox.products = oldBox.products.filter(p => p !== productId);
        }
      }

      // Assign to new box
      product.assigned_to_box = boxId;

      // Add to new box's product list
      const newBox = boxes.find(b => b.box_id === boxId);
      if (newBox && !newBox.products.includes(productId)) {
        newBox.products.push(productId);
      }

      setSelectedOrder(updatedOrder);
    }
  };

  // Update order status
  const handleUpdateStatus = async () => {
    setLoading(true);
    try {
      // Validate when moving to dispatch status
      if (newStatus === 'dispatch') {
        // Check if all products are assigned to boxes
        const unassignedProducts = selectedOrder.products.filter(p => !p.assigned_to_box);
        if (unassignedProducts.length > 0) {
          setSnackbarMessage('All products must be assigned to boxes before moving to Dispatch status');
          setSnackbarSeverity('error');
          setSnackbarOpen(true);
          setLoading(false);
          return;
        }

        // Check if any boxes are empty
        const emptyBoxes = boxes.filter(b => !b.products || b.products.length === 0);
        if (emptyBoxes.length > 0) {
          setSnackbarMessage('Empty boxes cannot be included. Please remove or add products to them.');
          setSnackbarSeverity('error');
          setSnackbarOpen(true);
          setLoading(false);
          return;
        }
      }

      // In a real app, you would update the order status via API
      // For packing to dispatch transition, include box information
      if (selectedOrder.status === 'packing' && newStatus === 'dispatch') {
        // const response = await axios.post(`${config.API_SERVER}orders/${selectedOrder.order_request_id}/status`, {
        //   new_status: newStatus,
        //   boxes: boxes
        // });

        // Mock update for now
        const updatedOrders = orders.map(order => {
          if (order.order_request_id === selectedOrder.order_request_id) {
            return {
              ...order,
              status: newStatus,
              boxes: boxes,
              state_history: [
                ...order.state_history,
                {
                  state_name: newStatus.charAt(0).toUpperCase() + newStatus.slice(1),
                  timestamp: new Date().toISOString(),
                  user: 'Current User'
                }
              ]
            };
          }
          return order;
        });

        // Update the selected order too
        const updatedSelectedOrder = {
          ...selectedOrder,
          status: newStatus,
          boxes: boxes,
          state_history: [
            ...selectedOrder.state_history,
            {
              state_name: newStatus.charAt(0).toUpperCase() + newStatus.slice(1),
              timestamp: new Date().toISOString(),
              user: 'Current User'
            }
          ]
        };

        // Update state
        setOrders(updatedOrders);
        setSelectedOrder(updatedSelectedOrder);

        // Success message
        setSnackbarMessage(`Order status updated to ${newStatus} with ${boxes.length} boxes`);
        setSnackbarSeverity('success');

      } else {
        // Simple status update without boxes
        // const response = await axios.post(`${config.API_SERVER}orders/${selectedOrder.order_request_id}/status`, {
        //   new_status: newStatus
        // });

        // Mock update for now
        const updatedOrders = orders.map(order => {
          if (order.order_request_id === selectedOrder.order_request_id) {
            return {
              ...order,
              status: newStatus,
              state_history: [
                ...order.state_history,
                {
                  state_name: newStatus.charAt(0).toUpperCase() + newStatus.slice(1),
                  timestamp: new Date().toISOString(),
                  user: 'Current User'
                }
              ]
            };
          }
          return order;
        });

        // Update the selected order too
        const updatedSelectedOrder = {
          ...selectedOrder,
          status: newStatus,
          state_history: [
            ...selectedOrder.state_history,
            {
              state_name: newStatus.charAt(0).toUpperCase() + newStatus.slice(1),
              timestamp: new Date().toISOString(),
              user: 'Current User'
            }
          ]
        };

        // Update state
        setOrders(updatedOrders);
        setSelectedOrder(updatedSelectedOrder);

        // Success message
        setSnackbarMessage(`Order status updated to ${newStatus}`);
        setSnackbarSeverity('success');
      }

      setSnackbarOpen(true);
      setStatusUpdateDialog(false);

      // Wait a bit so the user can see the updated status
      await new Promise(resolve => setTimeout(resolve, 1500));
      handleOrderDetailsClose();

    } catch (error) {
      console.error('Error updating order status:', error);
      setSnackbarMessage('Error updating order status');
      setSnackbarSeverity('error');
      setSnackbarOpen(true);
    } finally {
      setLoading(false);
    }
  };

  // Handle snackbar close
  const handleSnackbarClose = (event, reason) => {
    if (reason === 'clickaway') {
      return;
    }
    setSnackbarOpen(false);
  };

  // Format date for display
  const formatDate = (dateString) => {
    const options = { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' };
    return new Date(dateString).toLocaleString(undefined, options);
  };

  // Get status chip
  const getStatusChip = (status) => {
    let className;
    switch (status) {
      case 'open':
        className = classes.chipOpen;
        break;
      case 'picking':
        className = classes.chipPicking;
        break;
      case 'packing':
        className = classes.chipPacking;
        break;
      case 'dispatch':
        className = classes.chipDispatch;
        break;
      default:
        className = '';
    }

    return (
      <Chip
        label={status.charAt(0).toUpperCase() + status.slice(1)}
        className={`${classes.statusChip} ${className}`}
        size="small"
      />
    );
  };

  // Get next possible status based on current status
  const getNextStatus = (currentStatus) => {
    switch (currentStatus) {
      case 'open':
        return 'picking';
      case 'picking':
        return 'packing';
      case 'packing':
        return 'dispatch';
      default:
        return null;
    }
  };

  return (
    <Grid container spacing={gridSpacing}>
      <Grid item xs={12}>
        <Typography variant="h3" gutterBottom>Order Management</Typography>
      </Grid>

      {/* Filter selections */}
      <Grid item xs={12} className={classes.orderFilterContainer}>
        <Card>
          <CardContent>
            <Grid container spacing={2}>
              <Grid item xs={12} md={4} lg={3}>
                <FormControl variant="outlined" className={classes.formControl} fullWidth>
                  <InputLabel id="warehouse-select-label">Warehouse</InputLabel>
                  <Select
                    labelId="warehouse-select-label"
                    id="warehouse-select"
                    value={warehouse}
                    onChange={handleWarehouseChange}
                    label="Warehouse"
                  >
                    {warehouses.map((wh) => (
                      <MenuItem key={wh.warehouse_id} value={wh.warehouse_id}>
                        {wh.name}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} md={4} lg={3}>
                <FormControl variant="outlined" className={classes.formControl} fullWidth>
                  <InputLabel id="company-select-label">Company</InputLabel>
                  <Select
                    labelId="company-select-label"
                    id="company-select"
                    value={company}
                    onChange={handleCompanyChange}
                    label="Company"
                  >
                    {companies.map((comp) => (
                      <MenuItem key={comp.company_id} value={comp.company_id}>
                        {comp.name}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} md={4} lg={3}>
                <FormControl variant="outlined" className={classes.formControl} fullWidth>
                  <InputLabel id="status-select-label">Order Status</InputLabel>
                  <Select
                    labelId="status-select-label"
                    id="status-select"
                    value={selectedStatus}
                    onChange={handleStatusChange}
                    label="Order Status"
                  >
                    <MenuItem value="all">All Statuses</MenuItem>
                    <MenuItem value="open">Open</MenuItem>
                    <MenuItem value="picking">Picking</MenuItem>
                    <MenuItem value="packing">Packing</MenuItem>
                    <MenuItem value="dispatch">Ready for Dispatch</MenuItem>
                  </Select>
                </FormControl>
              </Grid>
            </Grid>
          </CardContent>
        </Card>
      </Grid>

      {/* Orders table */}
      <Grid item xs={12}>
        <Card>
          <CardContent>
            <Typography variant="h4" gutterBottom>Orders</Typography>

            {loading ? (
              <Box className={classes.loadingContainer}>
                <CircularProgress />
              </Box>
            ) : (
              <TableContainer className={classes.tableContainer} component={Paper}>
                <Table stickyHeader aria-label="orders table">
                  <TableHead>
                    <TableRow>
                      <TableCell>Order ID</TableCell>
                      <TableCell>Original Order ID</TableCell>
                      <TableCell>Dealer</TableCell>
                      <TableCell>Order Date</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell>Assigned To</TableCell>
                      <TableCell>Products</TableCell>
                      <TableCell>Actions</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {orders.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={8} align="center">
                          <Typography variant="subtitle1">No orders found</Typography>
                        </TableCell>
                      </TableRow>
                    ) : (
                      orders.map((order) => (
                        <TableRow key={order.order_request_id} hover onClick={() => handleOrderClick(order)} style={{ cursor: 'pointer' }}>
                          <TableCell>{order.order_request_id}</TableCell>
                          <TableCell>{order.original_order_id}</TableCell>
                          <TableCell>{order.dealer_name}</TableCell>
                          <TableCell>{formatDate(order.order_date)}</TableCell>
                          <TableCell>{getStatusChip(order.status)}</TableCell>
                          <TableCell>{order.assigned_to || 'Unassigned'}</TableCell>
                          <TableCell>{order.products.length}</TableCell>
                          <TableCell>
                            <IconButton size="small" onClick={(e) => {
                              e.stopPropagation();
                              handleOrderClick(order);
                            }}>
                              <IconSearch size={18} />
                            </IconButton>
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </CardContent>
        </Card>
      </Grid>

      {/* Order details dialog */}
      <Dialog
        open={orderDetailsOpen}
        onClose={handleOrderDetailsClose}
        maxWidth="md"
        fullWidth
      >
        {selectedOrder && (
          <>
            <DialogTitle>
              <div className={classes.detailsHeader}>
                <IconPackage className={classes.orderIcon} size={24} />
                <Typography variant="h4">
                  Order: {selectedOrder.order_request_id}
                </Typography>
              </div>
            </DialogTitle>
            <DialogContent>
              {/* Tabs for different sections */}
              <div className={classes.tabRoot}>
                <Tabs
                  value={tabValue}
                  onChange={handleTabChange}
                  indicatorColor="primary"
                  textColor="primary"
                  variant="fullWidth"
                >
                  <Tab label="Order Details" />
                  {selectedOrder.status === 'packing' && <Tab label="Box Management" />}
                  <Tab label="History" />
                </Tabs>
              </div>

              {/* Order Details Tab */}
              {tabValue === 0 && (
                <div>
                  <Box className={classes.orderSummary}>
                    <Grid container spacing={2}>
                      <Grid item xs={12} md={6} className={classes.infoGrid}>
                        <Typography variant="subtitle2" className={classes.infoLabel}>
                          Order Date:
                        </Typography>
                        <Typography variant="body1" className={classes.infoValue}>
                          {formatDate(selectedOrder.order_date)}
                        </Typography>
                      </Grid>
                      <Grid item xs={12} md={6} className={classes.infoGrid}>
                        <Typography variant="subtitle2" className={classes.infoLabel}>
                          Status:
                        </Typography>
                        <Typography variant="body1" className={classes.infoValue}>
                          {getStatusChip(selectedOrder.status)}
                        </Typography>
                      </Grid>
                      <Grid item xs={12} md={6} className={classes.infoGrid}>
                        <Typography variant="subtitle2" className={classes.infoLabel}>
                          Assigned To:
                        </Typography>
                        <Typography variant="body1" className={classes.infoValue}>
                          {selectedOrder.assigned_to || 'Unassigned'}
                        </Typography>
                      </Grid>
                      <Grid item xs={12} md={6} className={classes.infoGrid}>
                        <Typography variant="subtitle2" className={classes.infoLabel}>
                          Total Products:
                        </Typography>
                        <Typography variant="body1" className={classes.infoValue}>
                          {selectedOrder.products.length}
                        </Typography>
                      </Grid>
                    </Grid>
                  </Box>

                  <Divider />

                  <Typography variant="h5" gutterBottom style={{ marginTop: 16 }}>
                    Products
                  </Typography>

                  <TableContainer className={classes.productTable}>
                    <Table aria-label="products table">
                      <TableHead>
                        <TableRow>
                          <TableCell>Product ID</TableCell>
                          <TableCell>Name</TableCell>
                          <TableCell>Description</TableCell>
                          <TableCell>Quantity</TableCell>
                          <TableCell>Box Assignment</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {selectedOrder.products.map((product) => (
                          <TableRow key={product.product_id}>
                            <TableCell>{product.product_id}</TableCell>
                            <TableCell>{product.name}</TableCell>
                            <TableCell>{product.description}</TableCell>
                            <TableCell>{product.quantity}</TableCell>
                            <TableCell>
                              {selectedOrder.status === 'packing' || selectedOrder.status === 'dispatch' ? (
                                product.assigned_to_box ? (
                                  boxes.find(b => b.box_id === product.assigned_to_box)?.name || product.assigned_to_box
                                ) : (
                                  <Typography color="error">Not assigned</Typography>
                                )
                              ) : (
                                <Typography variant="body2" color="textSecondary">N/A</Typography>
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>

                  {/* Status update button */}
                  {getNextStatus(selectedOrder.status) && (
                    <Box className={classes.statusButtonGroup}>
                      <Button
                        variant="contained"
                        color="primary"
                        onClick={() => handleOpenStatusUpdate(getNextStatus(selectedOrder.status))}
                      >
                        Move to {getNextStatus(selectedOrder.status).charAt(0).toUpperCase() + getNextStatus(selectedOrder.status).slice(1)}
                      </Button>
                    </Box>
                  )}
                </div>
              )}

              {/* Box Management Tab */}
              {tabValue === 1 && selectedOrder.status === 'packing' && (
                <div>
                  <Typography variant="h5" gutterBottom>
                    Box Management
                  </Typography>
                  <Typography variant="body2" paragraph>
                    Assign each product to a box before marking the order as ready for dispatch.
                  </Typography>

                  {/* Boxes */}
                  <div className={classes.boxesContainer}>
                    {boxes.map((box, index) => (
                      <div key={index} className={classes.boxItem}>
                        <Grid container spacing={2}>
                          <Grid item xs={12} sm={6}>
                            <TextField
                              label="Box ID"
                              variant="outlined"
                              fullWidth
                              value={box.box_id}
                              onChange={(e) => handleBoxIdChange(index, e.target.value)}
                              className={classes.boxIdField}
                            />
                          </Grid>
                          <Grid item xs={12} sm={6}>
                            <TextField
                              label="Box Name"
                              variant="outlined"
                              fullWidth
                              value={box.name}
                              onChange={(e) => handleBoxNameChange(index, e.target.value)}
                            />
                          </Grid>
                        </Grid>

                        <Typography variant="subtitle2" style={{ marginTop: 16 }}>
                          Products in this box:
                        </Typography>

                        {box.products && box.products.length > 0 ? (
                          <ul>
                            {box.products.map(productId => {
                              const product = selectedOrder.products.find(p => p.product_id === productId);
                              return product ? (
                                <li key={productId}>
                                  {product.name} (ID: {product.product_id}) - Qty: {product.quantity}
                                </li>
                              ) : null;
                            })}
                          </ul>
                        ) : (
                          <Typography variant="body2" color="error">
                            No products assigned to this box
                          </Typography>
                        )}

                        <div className={classes.boxIconContainer}>
                          <IconButton
                            size="small"
                            color="secondary"
                            onClick={() => handleRemoveBox(index)}
                            disabled={boxes.length <= 1}
                          >
                            <IconTrash size={18} />
                          </IconButton>
                        </div>
                      </div>
                    ))}
                  </div>

                  <Button
                    variant="outlined"
                    color="primary"
                    startIcon={<IconPlus size={18} />}
                    onClick={handleAddBox}
                    className={classes.addBoxButton}
                  >
                    Add Box
                  </Button>

                  <Divider style={{ margin: '16px 0' }} />

                  <Typography variant="h6" gutterBottom>
                    Assign Products to Boxes
                  </Typography>

                  <TableContainer>
                    <Table aria-label="product assignment table">
                      <TableHead>
                        <TableRow>
                          <TableCell>Product</TableCell>
                          <TableCell>Quantity</TableCell>
                          <TableCell>Assign to Box</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {selectedOrder.products.map((product) => (
                          <TableRow key={product.product_id}>
                            <TableCell>{product.name} ({product.product_id})</TableCell>
                            <TableCell>{product.quantity}</TableCell>
                            <TableCell>
                              <FormControl variant="outlined" fullWidth>
                                <InputLabel id={`box-select-${product.product_id}`}>Box</InputLabel>
                                <Select
                                  labelId={`box-select-${product.product_id}`}
                                  value={product.assigned_to_box || ''}
                                  onChange={(e) => handleAssignProductToBox(product.product_id, e.target.value)}
                                  label="Box"
                                >
                                  <MenuItem value="">
                                    <em>None</em>
                                  </MenuItem>
                                  {boxes.map((box) => (
                                    <MenuItem key={box.box_id} value={box.box_id}>
                                      {box.name} ({box.box_id})
                                    </MenuItem>
                                  ))}
                                </Select>
                              </FormControl>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>

                  <Button
                    variant="contained"
                    color="primary"
                    onClick={() => handleOpenStatusUpdate('dispatch')}
                    className={classes.updateButton}
                    disabled={selectedOrder.products.some(p => !p.assigned_to_box)}
                  >
                    Complete Packing & Move to Dispatch
                  </Button>
                </div>
              )}

              {/* History Tab */}
              {tabValue === 2 && (
                <div>
                  <Typography variant="h5" gutterBottom>
                    Order Status History
                  </Typography>

                  <Stepper orientation="vertical" style={{ marginTop: 16 }}>
                    {selectedOrder.state_history.map((state, index) => (
                      <Step key={index} active={true} completed={true}>
                        <StepLabel>
                          <Typography variant="subtitle1">
                            {state.state_name}
                          </Typography>
                        </StepLabel>
                        <Box ml={3} mb={2}>
                          <Typography variant="body2" color="textSecondary">
                            {formatDate(state.timestamp)}
                          </Typography>
                          <Typography variant="body2">
                            Handled by: {state.user}
                          </Typography>
                        </Box>
                      </Step>
                    ))}
                  </Stepper>
                </div>
              )}
            </DialogContent>
            <DialogActions>
              <Button onClick={handleOrderDetailsClose} color="primary">
                Close
              </Button>
            </DialogActions>
          </>
        )}
      </Dialog>

      {/* Status Update Confirmation Dialog */}
      <Dialog
        open={statusUpdateDialog}
        onClose={handleCloseStatusUpdate}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          Update Order Status
        </DialogTitle>
        <DialogContent>
          <Typography variant="body1">
            Are you sure you want to update the status of order <strong>{selectedOrder?.order_request_id}</strong> from
            <strong> {selectedOrder?.status}</strong> to <strong>{newStatus}</strong>?
          </Typography>

          {selectedOrder?.status === 'packing' && newStatus === 'dispatch' && (
            <>
              <Typography variant="body1" style={{ marginTop: 16 }}>
                The order will be packed into <strong>{boxes.length}</strong> boxes:
              </Typography>
              <ul>
                {boxes.map((box, index) => (
                  <li key={index}>
                    <Typography variant="body2">
                      {box.name} ({box.box_id}): {box.products?.length || 0} products
                    </Typography>
                  </li>
                ))}
              </ul>
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseStatusUpdate} color="default">
            Cancel
          </Button>
          <Button
            onClick={handleUpdateStatus}
            color="primary"
            variant="contained"
            disabled={loading}
          >
            {loading ? <CircularProgress size={24} /> : 'Update Status'}
          </Button>
        </DialogActions>
      </Dialog>

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