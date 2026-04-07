import React, { useState, useEffect } from 'react';
import {
  Grid,
  Card,
  CardContent,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  CircularProgress,
  Box,
  Button,
  Chip,
  Typography,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Stepper,
  Step,
  StepLabel,
  Divider,
  List,
  ListItem,
  ListItemText
} from '@material-ui/core';
import {
  IconArrowRight,
  IconPackage,
  IconCheck,
  IconTruck,
  IconDownload,
  IconUpload
} from '@tabler/icons';
import { STATUS_FILTER_OPTIONS, STATUS_LABELS, TABLE_COLUMNS } from '../constants/orderManagement.constants';
import { formatDate, getTimeInCurrentStatus, getNextStatus, getStatusChipClass } from '../utils/orderManagement.utils';
import orderManagementService from '../../../services/orderManagementService';

/**
 * Filter Controls Component
 */
export const FilterControls = ({
  warehouses,
  companies,
  warehouse,
  company,
  statusFilter,
  onWarehouseChange,
  onCompanyChange,
  onStatusFilterChange,
  allowedStatuses,
  classes
}) => {
  const visibleStatusOptions = STATUS_FILTER_OPTIONS.filter((opt) => {
    if (opt.value === 'all') return true;
    if (!allowedStatuses) return true;
    return allowedStatuses.includes(opt.value);
  });

  return (
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
                onChange={onWarehouseChange}
                label="Warehouse"
              >
                {warehouses.map((wh) => {
                  const warehouseId = wh.warehouse_id !== undefined ? wh.warehouse_id : wh.id;
                  return (
                    <MenuItem key={warehouseId} value={warehouseId}>
                      {wh.name}
                    </MenuItem>
                  );
                })}
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
                onChange={onCompanyChange}
                label="Company"
              >
                {companies.map((comp) => {
                  const companyId = comp.company_id !== undefined ? comp.company_id : comp.id;
                  return (
                    <MenuItem key={companyId} value={companyId}>
                      {comp.name}
                    </MenuItem>
                  );
                })}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} md={4} lg={3}>
            <FormControl variant="outlined" className={classes.formControl} fullWidth>
              <InputLabel id="status-select-label">Order Status</InputLabel>
              <Select
                labelId="status-select-label"
                id="status-select"
                value={statusFilter}
                onChange={onStatusFilterChange}
                label="Order Status"
              >
                {visibleStatusOptions.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
        </Grid>
      </CardContent>
    </Card>
  </Grid>
  );
};

/**
 * Status Chip Component
 */
export const StatusChip = ({ status, classes }) => {
  const normalizedStatus = String(status).toLowerCase().replace(/\s+/g, '-');
  const className = classes[getStatusChipClass(normalizedStatus)];

  return (
    <Chip
      label={STATUS_LABELS[normalizedStatus] || normalizedStatus}
      className={`${classes.statusChip} ${className}`}
      size="small"
    />
  );
};

// Correct Status Progression
const CORRECT_STATUS_PROGRESSION = {
  'open': { next: 'picking', label: 'Start Picking' },
  'picking': { next: 'packing', label: 'Start Packing' },
  'packing': { next: 'invoice-ready', label: 'Move to Invoice Ready' },
  'invoice-ready': null,   // Auto-transitions to Dispatch Ready via invoice upload
  'dispatch-ready': { next: 'completed', label: 'Complete Dispatch' },
  'completed': null,
  'partially-completed': null
};

/**
 * Status Action Button — shows next-status action for each order row.
 * Backend already filters orders to only those the user can see, so no
 * frontend allowedStatuses check is needed here.
 */
export const StatusActionButton = ({ order, onStatusUpdate, classes }) => {
  const currentStatus = order.status?.toLowerCase().replace(/\s+/g, '-');
  const nextAction = CORRECT_STATUS_PROGRESSION[currentStatus];

  if (!nextAction) return null;

  const handleClick = (e) => {
    e.stopPropagation();

    if (currentStatus === 'packing') {
      // Opens dialog to configure packing before moving to invoice-ready
      onStatusUpdate(order, 'packing-to-invoice');
    } else if (currentStatus === 'dispatch-ready') {
      // Complete dispatch directly from table
      onStatusUpdate(order, 'complete-dispatch');
    } else {
      onStatusUpdate(order, nextAction.next);
    }
  };

  return (
    <Button
      variant="outlined"
      color="primary"
      size="small"
      className={classes.statusActionButton}
      onClick={handleClick}
      startIcon={<IconArrowRight size={16} />}
    >
      {nextAction.label}
    </Button>
  );
};

/**
 * Orders Table Component
 */
export const OrdersTable = ({
  orders,
  loading,
  statusFilter,
  onOrderClick,
  onStatusUpdate,
  allowedStatuses,
  classes
}) => (
  <Grid item xs={12}>
    <Card>
      <CardContent>
        <Typography variant="h4" gutterBottom>
          Orders
          {statusFilter !== 'all' && (
            <Typography
              variant="subtitle1"
              component="span"
              className={classes.filterTitle}
            >
              - Showing {STATUS_FILTER_OPTIONS.find(opt => opt.value === statusFilter)?.label} ({orders.length} orders)
            </Typography>
          )}
        </Typography>

        {loading ? (
          <Box className={classes.loadingContainer}>
            <CircularProgress />
          </Box>
        ) : (
          <TableContainer className={classes.tableContainer} component={Paper}>
            <Table stickyHeader aria-label="orders table">
              <TableHead>
                <TableRow>
                  {TABLE_COLUMNS.map((column) => (
                    <TableCell key={column.id}>{column.label}</TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {orders.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={TABLE_COLUMNS.length} align="center">
                      <Typography variant="subtitle1">No orders found</Typography>
                    </TableCell>
                  </TableRow>
                ) : (
                  orders.map((order) => (
                    <TableRow
                      key={order.order_request_id}
                      hover
                      onClick={() => onOrderClick(order)}
                      className={classes.tableRow}
                    >
                      <TableCell>{order.dealer_name}</TableCell>
                      <TableCell>
                        <StatusChip status={order.status} classes={classes} />
                      </TableCell>
                      <TableCell>{formatDate(order.order_date)}</TableCell>
                      <TableCell>{getTimeInCurrentStatus(order.current_state_time)}</TableCell>
                      <TableCell>{order.assigned_to || 'Unassigned'}</TableCell>
                      <TableCell>
                        <Box display="flex" alignItems="center">
                          <StatusActionButton
                            order={order}
                            onStatusUpdate={onStatusUpdate}
                            classes={classes}
                          />
                        </Box>
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
);


/**
 * FIXED: Enhanced Order Details Dialog with Correct Flow and Timeline
 */
export const OrderDetailsDialog = ({
  open,
  order,
  onClose,
  onStatusUpdate,
  allowedStatuses,
  classes
}) => {
  const [activeStep, setActiveStep] = useState(0);
  const [numberOfBoxes, setNumberOfBoxes] = useState(1);
  const [loading, setLoading] = useState(false);

  // Steps based on actual flow
  const steps = ['Order Details', 'Packing', 'Invoice Ready', 'Dispatch Ready', 'Completed'];

  useEffect(() => {
    if (order) {
      setNumberOfBoxes(1);

      // Set active step based on status
      switch (order.status?.toLowerCase().replace(/\s+/g, '-')) {
        case 'open':
        case 'picking':
          setActiveStep(0);
          break;
        case 'packing':
          setActiveStep(1);
          break;
        case 'invoice-ready':
          setActiveStep(2);
          break;
        case 'dispatch-ready':
          setActiveStep(3);
          break;
        case 'completed':
        case 'partially-completed':
          setActiveStep(4);
          break;
        default:
          setActiveStep(0);
      }
    }
  }, [order]);

  // Move to Invoice Ready
  const handleMoveToInvoiceReady = async () => {
    const boxes = parseInt(numberOfBoxes, 10);
    if (!boxes || boxes < 1) {
      alert('Please enter a valid number of boxes (minimum 1).');
      return;
    }

    setLoading(true);
    try {
      await onStatusUpdate(order, 'invoice-ready', { number_of_boxes: boxes });
    } catch (error) {
      console.error('Error moving to invoice ready:', error);
      alert('Error moving to invoice ready: ' + error.message);
    } finally {
      setLoading(false);
    }
  };

  // FIXED: Complete Dispatch - prevent duplicate calls by using a flag
  const [isCompletingDispatch, setIsCompletingDispatch] = useState(false);

  const handleCompleteDispatch = async () => {
    // FIXED: Prevent duplicate calls
    if (isCompletingDispatch) {
      console.log('Complete dispatch already in progress, ignoring duplicate call');
      return;
    }

    const proceed = window.confirm(
      'This will mark the order as completed and dispatched from the warehouse.\n\n' +
      'Are you sure you want to proceed?'
    );

    if (!proceed) return;

    setIsCompletingDispatch(true);
    setLoading(true);

    try {
      // Call the status update handler from parent
      await onStatusUpdate(order, 'completed');
    } catch (error) {
      console.error('Error completing dispatch:', error);
      alert('Error completing dispatch: ' + error.message);
    } finally {
      setLoading(false);
      setIsCompletingDispatch(false);
    }
  };

  const renderStepContent = () => {
    switch (activeStep) {
      case 0: // Order Details
        return (
          <Box>
            <Grid container spacing={2}>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>Order ID:</Typography>
                <Typography variant="body1" gutterBottom>{order?.order_request_id}</Typography>
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>Status:</Typography>
                <Chip
                  label={order?.status?.replace('-', ' ') || 'Unknown'}
                  color="primary"
                  size="small"
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>Dealer:</Typography>
                <Typography variant="body1" gutterBottom>{order?.dealer_name}</Typography>
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>Order Date:</Typography>
                <Typography variant="body1" gutterBottom>
                  {order?.order_date ? new Date(order.order_date).toLocaleDateString() : 'N/A'}
                </Typography>
              </Grid>
            </Grid>

            <Divider style={{ margin: '16px 0' }} />

            <Typography variant="h6" gutterBottom>Products</Typography>
            <TableContainer component={Paper}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Product</TableCell>
                    <TableCell>Description</TableCell>
                    <TableCell>Quantity</TableCell>
                    <TableCell>Price</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {order?.products?.map((product) => (
                    <TableRow key={product.product_id}>
                      <TableCell>
                        <Typography variant="body2" fontWeight="bold">
                          {product.name}
                        </Typography>
                        <Typography variant="caption" color="textSecondary">
                          {product.product_string}
                        </Typography>
                      </TableCell>
                      <TableCell>{product.description}</TableCell>
                      <TableCell>{product.quantity_ordered}</TableCell>
                      <TableCell>${product.price}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>

            {/* FIXED: Enhanced Timeline Display */}
            <Divider style={{ margin: '16px 0' }} />
            <Typography variant="h6" gutterBottom>Order Timeline</Typography>
            <Box>
              {order?.state_history?.map((state, index) => (
                <Box key={index} style={{
                  padding: '8px 0',
                  borderLeft: index === order.state_history.length - 1 ? '3px solid #4caf50' : '3px solid #e0e0e0',
                  paddingLeft: '16px',
                  marginLeft: '8px'
                }}>
                  <Typography variant="subtitle2" fontWeight="bold">
                    {state.state_name}
                  </Typography>
                  <Typography variant="body2" color="textSecondary">
                    {new Date(state.timestamp).toLocaleString()}
                  </Typography>
                  <Typography variant="caption">
                    {state.user}
                  </Typography>
                </Box>
              ))}
            </Box>
          </Box>
        );

      case 1: // Packing
        return (
          <Box>
            <Typography variant="h6" gutterBottom>Complete Packing</Typography>
            <Typography variant="body2" color="textSecondary" style={{ marginBottom: 16 }}>
              All available products will be packed. Enter the number of boxes used for this order.
            </Typography>
            <TextField
              label="Number of Boxes"
              type="number"
              variant="outlined"
              value={numberOfBoxes}
              onChange={(e) => setNumberOfBoxes(e.target.value)}
              inputProps={{ min: 1, step: 1 }}
              style={{ width: 200 }}
            />
          </Box>
        );

      case 2: // Invoice Ready
        return (
          <Box p={2} bgcolor="#e3f2fd" borderRadius={1} border="1px solid #0288d1">
            <Typography variant="h6" gutterBottom>Invoice Ready</Typography>
            <Typography variant="body1">
              Order has been packed and is awaiting invoice upload.
            </Typography>
            <Typography variant="body2" color="textSecondary" style={{ marginTop: 8 }}>
              The order will automatically move to <strong>Dispatch Ready</strong> once invoices are uploaded via the Invoice Upload page.
            </Typography>
          </Box>
        );

      case 3: // Dispatch Ready
        return (
          <Box>
            <Typography variant="h6" gutterBottom>Dispatch Ready</Typography>
            <Box p={2} bgcolor="#e8f5e8" borderRadius={1} border="1px solid #4caf50" mb={2}>
              <Typography variant="body1">
                Order has been packed and invoice uploaded. Ready for dispatch.
              </Typography>
            </Box>
            {order?.final_order && (
              <Box p={2} bgcolor="#f5f5f5" borderRadius={1}>
                <Typography variant="subtitle2" gutterBottom>Final Order Information:</Typography>
                <Typography variant="body2">Order Number: {order.final_order.order_number}</Typography>
                <Typography variant="body2">Status: {order.final_order.status}</Typography>
                <Typography variant="body2">Created: {new Date(order.final_order.created_at).toLocaleString()}</Typography>
              </Box>
            )}
          </Box>
        );

      case 4: // Completed
        return (
          <Box textAlign="center" p={4}>
            <IconCheck size={64} color="#4caf50" style={{ marginBottom: 16 }} />
            <Typography variant="h5" gutterBottom>Order Completed</Typography>
            <Typography variant="body1" color="textSecondary">
              This order has been successfully dispatched from the warehouse.
            </Typography>
            {order?.final_order?.dispatched_date && (
              <Typography variant="body2" style={{ marginTop: 16 }}>
                Dispatched on: {new Date(order.final_order.dispatched_date).toLocaleString()}
              </Typography>
            )}
          </Box>
        );

      default:
        return null;
    }
  };

  if (!order) return null;

  return (
    <>
      <Dialog
        open={open}
        onClose={onClose}
        maxWidth="lg"
        fullWidth
        className={classes.orderDetailsDialog}
      >
        <DialogTitle>
          <Box display="flex" alignItems="center" justifyContent="space-between">
            <Box display="flex" alignItems="center">
              <IconPackage size={24} style={{ marginRight: 8 }} />
              <Typography variant="h5">Order Management: {order.order_request_id}</Typography>
            </Box>
            <Chip
              label={order.status?.replace('-', ' ') || 'Unknown'}
              color="primary"
              size="small"
            />
          </Box>
        </DialogTitle>

        <DialogContent style={{ minHeight: '500px' }}>
          <Stepper activeStep={activeStep} style={{ marginBottom: 24 }}>
            {steps.map((label) => (
              <Step key={label}>
                <StepLabel>{label}</StepLabel>
              </Step>
            ))}
          </Stepper>

          {renderStepContent()}
        </DialogContent>

        <DialogActions>
          <Button onClick={onClose} disabled={loading}>
            Close
          </Button>

          {activeStep === 0 && order.status?.toLowerCase() === 'picking' && (
            <Button
              onClick={() => setActiveStep(1)}
              color="primary"
              variant="contained"
              disabled={loading}
            >
              Start Packing
            </Button>
          )}

          {activeStep === 1 && order.status?.toLowerCase() === 'packing' && (
            <Button
              onClick={handleMoveToInvoiceReady}
              color="primary"
              variant="contained"
              disabled={loading}
              startIcon={<IconTruck size={16} />}
            >
              {loading ? <CircularProgress size={20} /> : 'Move to Invoice Ready'}
            </Button>
          )}

          {activeStep === 3 && order.status?.toLowerCase().includes('dispatch') && (
            <Button
              onClick={handleCompleteDispatch}
              color="secondary"
              variant="contained"
              disabled={loading || isCompletingDispatch}
              startIcon={<IconCheck size={16} />}
            >
              {(loading || isCompletingDispatch) ? <CircularProgress size={20} /> : 'Complete Dispatch'}
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </>
  );
};

/**
 * Bulk Actions Bar — download template and upload filled file
 */
export const BulkActionsBar = ({ statusFilter, warehouse, company, onUploadComplete, classes }) => {
  const [uploading, setUploading] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
    setDownloading(true);
    try {
      await orderManagementService.downloadBulkTemplate({
        status: statusFilter,
        warehouseId: warehouse,
        companyId: company
      });
    } catch (err) {
      alert('Failed to download template: ' + err.message);
    } finally {
      setDownloading(false);
    }
  };

  const handleFileChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    e.target.value = '';
    setUploading(true);
    try {
      const result = await orderManagementService.uploadBulkFile(file);
      onUploadComplete(result);
    } catch (err) {
      alert('Failed to upload file: ' + (err.response?.data?.msg || err.message));
    } finally {
      setUploading(false);
    }
  };

  return (
    <Grid item xs={12}>
      <Card>
        <CardContent>
          <Box display="flex" alignItems="center" justifyContent="space-between" flexWrap="wrap" style={{ gap: 8 }}>
            <Typography variant="subtitle1" style={{ fontWeight: 600 }}>
              Bulk Actions
            </Typography>
            <Box display="flex" style={{ gap: 8 }}>
              <Button
                variant="outlined"
                color="primary"
                startIcon={downloading ? <CircularProgress size={16} /> : <IconDownload size={16} />}
                onClick={handleDownload}
                disabled={downloading || uploading}
              >
                {downloading ? 'Downloading…' : 'Download Template'}
              </Button>

              <Button
                variant="contained"
                color="primary"
                component="label"
                startIcon={uploading ? <CircularProgress size={16} color="inherit" /> : <IconUpload size={16} />}
                disabled={uploading || downloading}
              >
                {uploading ? 'Uploading…' : 'Upload & Apply'}
                <input type="file" accept=".xlsx,.xls" hidden onChange={handleFileChange} />
              </Button>
            </Box>
          </Box>
          <Typography variant="caption" color="textSecondary" style={{ marginTop: 4, display: 'block' }}>
            Download orders for the current status filter, fill in "Expected Status" (and "Number of Boxes" for packing → invoice-ready), then upload to apply changes in bulk.
          </Typography>
        </CardContent>
      </Card>
    </Grid>
  );
};

/**
 * Bulk Results Dialog — shows summary after upload
 */
export const BulkResultsDialog = ({ open, results, onClose }) => {
  if (!results) return null;
  const { summary, details } = results;

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Bulk Update Results</DialogTitle>
      <DialogContent>
        {/* Summary chips */}
        <Box display="flex" style={{ gap: 12, marginBottom: 16 }}>
          <Chip label={`${summary.moved} Moved`} style={{ backgroundColor: '#4caf50', color: '#fff' }} />
          <Chip label={`${summary.skipped} Skipped`} style={{ backgroundColor: '#ff9800', color: '#fff' }} />
          <Chip label={`${summary.errors} Errors`} style={{ backgroundColor: '#f44336', color: '#fff' }} />
        </Box>

        {details.moved.length > 0 && (
          <>
            <Typography variant="subtitle2" style={{ color: '#2e7d32', marginBottom: 4 }}>
              Successfully Moved ({details.moved.length})
            </Typography>
            <TableContainer component={Paper} style={{ marginBottom: 16, maxHeight: 200 }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Order ID</TableCell>
                    <TableCell>From</TableCell>
                    <TableCell>To</TableCell>
                    <TableCell>Boxes</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {details.moved.map((r, i) => (
                    <TableRow key={i}>
                      <TableCell>{r.order_id}</TableCell>
                      <TableCell>{r.from}</TableCell>
                      <TableCell>{r.to}</TableCell>
                      <TableCell>{r.boxes || '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </>
        )}

        {details.errors.length > 0 && (
          <>
            <Typography variant="subtitle2" style={{ color: '#c62828', marginBottom: 4 }}>
              Errors ({details.errors.length})
            </Typography>
            <List dense style={{ marginBottom: 8 }}>
              {details.errors.map((e, i) => (
                <ListItem key={i} style={{ paddingTop: 2, paddingBottom: 2 }}>
                  <ListItemText
                    primary={<><strong>{e.order_id}</strong>: {e.reason}</>}
                  />
                </ListItem>
              ))}
            </List>
          </>
        )}

        {details.skipped.length > 0 && (
          <>
            <Typography variant="subtitle2" style={{ color: '#e65100', marginBottom: 4 }}>
              Skipped ({details.skipped.length})
            </Typography>
            <List dense>
              {details.skipped.map((s, i) => (
                <ListItem key={i} style={{ paddingTop: 2, paddingBottom: 2 }}>
                  <ListItemText
                    primary={<><strong>{s.order_id}</strong>: {s.reason}</>}
                  />
                </ListItem>
              ))}
            </List>
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} color="primary" variant="contained">Close</Button>
      </DialogActions>
    </Dialog>
  );
};