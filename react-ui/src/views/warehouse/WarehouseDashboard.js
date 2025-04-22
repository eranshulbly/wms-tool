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
  IconButton,
  Chip,
  Divider
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import {
  IconPackage,
  IconTruckDelivery,
  IconBoxSeam,
  IconClipboardList,
  IconSearch,
  IconCalendar,
  IconUser,
  IconClock
} from '@tabler/icons';
import { gridSpacing } from '../../store/constant';
import dashboardService from '../../services/dashboardService';

// Custom styles for the dashboard
const useStyles = makeStyles((theme) => ({
  statusCard: {
    height: '100%',
    cursor: 'pointer',
    transition: 'transform 0.2s ease-in-out, box-shadow 0.2s ease-in-out',
    '&:hover': {
      transform: 'translateY(-5px)',
      boxShadow: theme.shadows[10]
    }
  },
  openCard: {
    borderTop: `5px solid ${theme.palette.warning.main}`
  },
  pickingCard: {
    borderTop: `5px solid ${theme.palette.primary.main}`
  },
  packingCard: {
    borderTop: `5px solid ${theme.palette.secondary.main}`
  },
  dispatchCard: {
    borderTop: `5px solid ${theme.palette.success.main}`
  },
  iconContainer: {
    backgroundColor: theme.palette.background.default,
    padding: theme.spacing(2),
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: theme.spacing(2)
  },
  orderCount: {
    fontSize: '2rem',
    fontWeight: 600,
    marginBottom: theme.spacing(1)
  },
  statusLabel: {
    fontSize: '1.25rem',
    fontWeight: 500
  },
  formControl: {
    marginBottom: theme.spacing(2),
    minWidth: 200
  },
  orderDetailsDialog: {
    minWidth: 600
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
  tableContainer: {
    maxHeight: 440,
    overflowX: 'auto'
  },
  loadingContainer: {
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    height: '100px'
  },
  statsSummary: {
    marginBottom: theme.spacing(3),
    padding: theme.spacing(2),
    backgroundColor: theme.palette.background.default,
    borderRadius: theme.shape.borderRadius
  },
  summaryItem: {
    display: 'flex',
    alignItems: 'center',
    marginRight: theme.spacing(3)
  },
  detailsHeader: {
    display: 'flex',
    alignItems: 'center',
    marginBottom: theme.spacing(2)
  },
  orderIcon: {
    marginRight: theme.spacing(1)
  },
  infoSection: {
    marginTop: theme.spacing(2),
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
  timelineItem: {
    padding: theme.spacing(2),
    borderLeft: `2px solid ${theme.palette.primary.main}`,
    marginLeft: theme.spacing(2),
    position: 'relative',
    '&:before': {
      content: '""',
      position: 'absolute',
      left: -8,
      top: 24,
      width: 14,
      height: 14,
      borderRadius: '50%',
      backgroundColor: theme.palette.primary.main
    }
  }
}));

// Define order status data
const orderStatusData = {
  open: {
    icon: <IconClipboardList size={42} color="#ed6c02" />,
    label: 'Open Orders',
    chipClass: 'chipOpen'
  },
  picking: {
    icon: <IconPackage size={42} color="#1976d2" />,
    label: 'Picking',
    chipClass: 'chipPicking'
  },
  packing: {
    icon: <IconBoxSeam size={42} color="#9c27b0" />,
    label: 'Packing',
    chipClass: 'chipPacking'
  },
  dispatch: {
    icon: <IconTruckDelivery size={42} color="#2e7d32" />,
    label: 'Dispatch Ready',
    chipClass: 'chipDispatch'
  }
};

const WarehouseDashboard = () => {
  const classes = useStyles();
  const [warehouse, setWarehouse] = useState('');
  const [company, setCompany] = useState('');
  const [warehouses, setWarehouses] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusCounts, setStatusCounts] = useState({});
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedStatus, setSelectedStatus] = useState('');
  const [selectedOrders, setSelectedOrders] = useState([]);
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [orderDetailsOpen, setOrderDetailsOpen] = useState(false);
  const [recentOrders, setRecentOrders] = useState([]);
  const [loadingOrders, setLoadingOrders] = useState(false);

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

  // Handle warehouse selection change
  const handleWarehouseChange = (event) => {
    setWarehouse(event.target.value);
  };

  // Handle company selection change
  const handleCompanyChange = (event) => {
    setCompany(event.target.value);
  };

  // Handle card click to show orders in that status
  const handleStatusCardClick = async (status) => {
    setSelectedStatus(status);
    setLoadingOrders(true);

    try {
      const response = await dashboardService.getOrdersByStatus(status, warehouse, company);
      if (response.success) {
        setSelectedOrders(response.orders);
      } else {
        setSelectedOrders([]);
      }
    } catch (error) {
      console.error(`Error fetching ${status} orders:`, error);
      setSelectedOrders([]);
    } finally {
      setLoadingOrders(false);
      setDialogOpen(true);
    }
  };

  // Handle dialog close
  const handleDialogClose = () => {
    setDialogOpen(false);
  };

  // Handle opening order details
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

  // Handle closing order details
  const handleOrderDetailsClose = () => {
    setOrderDetailsOpen(false);
  };

  // Format date for display
  const formatDate = (dateString) => {
    const options = { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' };
    return new Date(dateString).toLocaleString(undefined, options);
  };

  // Calculate time in state
  const getTimeInState = (dateString) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    const diffHours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));

    if (diffDays > 0) {
      return `${diffDays}d ${diffHours}h`;
    }
    return `${diffHours}h`;
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
        className={className}
        size="small"
      />
    );
  };

  return (
    <Grid container spacing={gridSpacing}>
      <Grid item xs={12}>
        <Typography variant="h3">Warehouse Dashboard</Typography>
      </Grid>

      {/* Filter selections */}
      <Grid item xs={12}>
        <Card>
          <CardContent>
            <Grid container spacing={2}>
              <Grid item xs={12} md={6} lg={3}>
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
                      <MenuItem key={wh.id} value={wh.id}>
                        {wh.name}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} md={6} lg={3}>
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
                      <MenuItem key={comp.id} value={comp.id}>
                        {comp.name}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
            </Grid>
          </CardContent>
        </Card>
      </Grid>

      {/* Order status cards */}
      <Grid item xs={12}>
        <Grid container spacing={gridSpacing}>
          {/* Open Orders Card */}
          <Grid item xs={12} sm={6} md={6} lg={3}>
            <Card className={`${classes.statusCard} ${classes.openCard}`} onClick={() => handleStatusCardClick('open')}>
              <CardContent>
                <Box display="flex" alignItems="center">
                  <Box className={classes.iconContainer}>
                    {orderStatusData.open.icon}
                  </Box>
                  <Box>
                    <Typography variant="h3" className={classes.orderCount}>
                      {loading ? <CircularProgress size={30} /> : (statusCounts.open?.count || 0)}
                    </Typography>
                    <Typography variant="subtitle1" className={classes.statusLabel}>
                      {orderStatusData.open.label}
                    </Typography>
                  </Box>
                </Box>
              </CardContent>
            </Card>
          </Grid>

          {/* Picking Card */}
          <Grid item xs={12} sm={6} md={6} lg={3}>
            <Card className={`${classes.statusCard} ${classes.pickingCard}`} onClick={() => handleStatusCardClick('picking')}>
              <CardContent>
                <Box display="flex" alignItems="center">
                  <Box className={classes.iconContainer}>
                    {orderStatusData.picking.icon}
                  </Box>
                  <Box>
                    <Typography variant="h3" className={classes.orderCount}>
                      {loading ? <CircularProgress size={30} /> : (statusCounts.picking?.count || 0)}
                    </Typography>
                    <Typography variant="subtitle1" className={classes.statusLabel}>
                      {orderStatusData.picking.label}
                    </Typography>
                  </Box>
                </Box>
              </CardContent>
            </Card>
          </Grid>

          {/* Packing Card */}
          <Grid item xs={12} sm={6} md={6} lg={3}>
            <Card className={`${classes.statusCard} ${classes.packingCard}`} onClick={() => handleStatusCardClick('packing')}>
              <CardContent>
                <Box display="flex" alignItems="center">
                  <Box className={classes.iconContainer}>
                    {orderStatusData.packing.icon}
                  </Box>
                  <Box>
                    <Typography variant="h3" className={classes.orderCount}>
                      {loading ? <CircularProgress size={30} /> : (statusCounts.packing?.count || 0)}
                    </Typography>
                    <Typography variant="subtitle1" className={classes.statusLabel}>
                      {orderStatusData.packing.label}
                    </Typography>
                  </Box>
                </Box>
              </CardContent>
            </Card>
          </Grid>

          {/* Dispatch Card */}
          <Grid item xs={12} sm={6} md={6} lg={3}>
            <Card className={`${classes.statusCard} ${classes.dispatchCard}`} onClick={() => handleStatusCardClick('dispatch')}>
              <CardContent>
                <Box display="flex" alignItems="center">
                  <Box className={classes.iconContainer}>
                    {orderStatusData.dispatch.icon}
                  </Box>
                  <Box>
                    <Typography variant="h3" className={classes.orderCount}>
                      {loading ? <CircularProgress size={30} /> : (statusCounts.dispatch?.count || 0)}
                    </Typography>
                    <Typography variant="subtitle1" className={classes.statusLabel}>
                      {orderStatusData.dispatch.label}
                    </Typography>
                  </Box>
                </Box>
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      </Grid>

      {/* Recent activity */}
      <Grid item xs={12}>
        <Card>
          <CardContent>
            <Typography variant="h4" gutterBottom>Recent Activity</Typography>
            <TableContainer className={classes.tableContainer}>
              <Table stickyHeader aria-label="recent activity table">
                <TableHead>
                  <TableRow>
                    <TableCell>Order ID</TableCell>
                    <TableCell>Dealer</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell>Date</TableCell>
                    <TableCell>Assigned To</TableCell>
                    <TableCell>Actions</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {loading ? (
                    <TableRow>
                      <TableCell colSpan={6}>
                        <Box className={classes.loadingContainer}>
                          <CircularProgress />
                        </Box>
                      </TableCell>
                    </TableRow>
                  ) : recentOrders.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={6} align="center">No recent orders found</TableCell>
                    </TableRow>
                  ) : (
                    recentOrders.map((order) => (
                      <TableRow key={order.order_request_id} hover onClick={() => handleOrderClick(order)} style={{ cursor: 'pointer' }}>
                        <TableCell>{order.order_request_id}</TableCell>
                        <TableCell>{order.dealer_name}</TableCell>
                        <TableCell>{getStatusChip(order.status)}</TableCell>
                        <TableCell>{formatDate(order.order_date)}</TableCell>
                        <TableCell>{order.assigned_to || 'Unassigned'}</TableCell>
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
          </CardContent>
        </Card>
      </Grid>

      {/* Orders list dialog */}
      <Dialog
        open={dialogOpen}
        onClose={handleDialogClose}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>
          {selectedStatus && orderStatusData[selectedStatus]?.label} ({selectedOrders.length})
        </DialogTitle>
        <DialogContent>
          <TableContainer className={classes.tableContainer}>
            <Table stickyHeader aria-label="orders table">
              <TableHead>
                <TableRow>
                  <TableCell>Order ID</TableCell>
                  <TableCell>Original Order ID</TableCell>
                  <TableCell>Dealer</TableCell>
                  <TableCell>Order Date</TableCell>
                  <TableCell>Time in State</TableCell>
                  <TableCell>Assigned To</TableCell>
                  <TableCell>Products</TableCell>
                  <TableCell>Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {loadingOrders ? (
                  <TableRow>
                    <TableCell colSpan={8}>
                      <Box className={classes.loadingContainer}>
                        <CircularProgress />
                      </Box>
                    </TableCell>
                  </TableRow>
                ) : selectedOrders.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} align="center">No orders found</TableCell>
                  </TableRow>
                ) : (
                  selectedOrders.map((order) => (
                    <TableRow key={order.order_request_id} hover onClick={() => handleOrderClick(order)} style={{ cursor: 'pointer' }}>
                      <TableCell>{order.order_request_id}</TableCell>
                      <TableCell>{order.original_order_id}</TableCell>
                      <TableCell>{order.dealer_name}</TableCell>
                      <TableCell>{formatDate(order.order_date)}</TableCell>
                      <TableCell>{getTimeInState(order.current_state_time)}</TableCell>
                      <TableCell>{order.assigned_to || 'Unassigned'}</TableCell>
                      <TableCell>{order.products}</TableCell>
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
        </DialogContent>
        <DialogActions>
          <Button onClick={handleDialogClose} color="primary">
            Close
          </Button>
        </DialogActions>
      </Dialog>

      {/* Order details dialog */}
      <Dialog
        open={orderDetailsOpen}
        onClose={handleOrderDetailsClose}
        maxWidth="md"
        fullWidth
        className={classes.orderDetailsDialog}
      >
        {selectedOrder && (
          <>
            <DialogTitle>
              <div className={classes.detailsHeader}>
                <IconPackage className={classes.orderIcon} size={24} />
                <Typography variant="h4">
                  Order Details: {selectedOrder.order_request_id}
                </Typography>
              </div>
            </DialogTitle>
            <DialogContent>
              <Box className={classes.statsSummary}>
                <Grid container>
                  <Grid item className={classes.summaryItem}>
                    <IconCalendar size={20} style={{ marginRight: 8 }} />
                    <Typography variant="body1">
                      {formatDate(selectedOrder.order_date)}
                    </Typography>
                  </Grid>
                  <Grid item className={classes.summaryItem}>
                    <IconClock size={20} style={{ marginRight: 8 }} />
                    <Typography variant="body1">
                      {getTimeInState(selectedOrder.current_state_time)} in {getStatusChip(selectedOrder.status)}
                    </Typography>
                  </Grid>
                  <Grid item className={classes.summaryItem}>
                    <IconUser size={20} style={{ marginRight: 8 }} />
                    <Typography variant="body1">
                      {selectedOrder.assigned_to || 'Unassigned'}
                    </Typography>
                  </Grid>
                </Grid>
              </Box>

              <Grid container spacing={2} className={classes.infoSection}>
                <Grid item xs={12} md={6} className={classes.infoGrid}>
                  <Typography variant="subtitle2" className={classes.infoLabel}>
                    Order ID:
                  </Typography>
                  <Typography variant="body1" className={classes.infoValue}>
                    {selectedOrder.order_request_id}
                  </Typography>
                </Grid>
                <Grid item xs={12} md={6} className={classes.infoGrid}>
                  <Typography variant="subtitle2" className={classes.infoLabel}>
                    Original Order ID:
                  </Typography>
                  <Typography variant="body1" className={classes.infoValue}>
                    {selectedOrder.original_order_id}
                  </Typography>
                </Grid>
                <Grid item xs={12} md={6} className={classes.infoGrid}>
                  <Typography variant="subtitle2" className={classes.infoLabel}>
                    Dealer:
                  </Typography>
                  <Typography variant="body1" className={classes.infoValue}>
                    {selectedOrder.dealer_name}
                  </Typography>
                </Grid>
                <Grid item xs={12} md={6} className={classes.infoGrid}>
                  <Typography variant="subtitle2" className={classes.infoLabel}>
                    Total Products:
                  </Typography>
                  <Typography variant="body1" className={classes.infoValue}>
                    {selectedOrder.products}
                  </Typography>
                </Grid>
                <Grid item xs={12} md={6} className={classes.infoGrid}>
                  <Typography variant="subtitle2" className={classes.infoLabel}>
                    Current Status:
                  </Typography>
                  <Typography variant="body1" className={classes.infoValue}>
                    {getStatusChip(selectedOrder.status)}
                  </Typography>
                </Grid>
                <Grid item xs={12} md={6} className={classes.infoGrid}>
                  <Typography variant="subtitle2" className={classes.infoLabel}>
                    Time in Current State:
                  </Typography>
                  <Typography variant="body1" className={classes.infoValue}>
                    {getTimeInState(selectedOrder.current_state_time)}
                  </Typography>
                </Grid>
              </Grid>

              <Divider />

              <Box mt={3}>
                <Typography variant="h5" gutterBottom>
                  Order Timeline
                </Typography>

                <Box mt={2}>
                  {selectedOrder.state_history && selectedOrder.state_history.map((state, index) => (
                    <Box key={index} className={classes.timelineItem} mb={2}>
                      <Typography variant="subtitle1">
                        {state.state_name}
                      </Typography>
                      <Typography variant="body2" color="textSecondary">
                        {formatDate(state.timestamp)}
                      </Typography>
                      <Typography variant="body2">
                        Handled by: {state.user}
                      </Typography>
                    </Box>
                  ))}
                </Box>
              </Box>
            </DialogContent>
            <DialogActions>
              <Button onClick={handleOrderDetailsClose} color="primary">
                Close
              </Button>
            </DialogActions>
          </>
        )}
      </Dialog>
    </Grid>
  );
};

export default WarehouseDashboard;