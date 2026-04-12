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
  TablePagination,
  Paper,
  CircularProgress,
  Skeleton,
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
  Tooltip
} from '@material-ui/core';
import {
  IconArrowRight,
  IconPackage,
  IconCheck,
  IconUpload,
  IconFileInvoice
} from '@tabler/icons';
import { STATUS_FILTER_OPTIONS, STATUS_LABELS, TABLE_COLUMNS, BULK_TARGET_STATUSES } from '../constants/orderManagement.constants';
import UploadResultCard from '../../../components/UploadResultCard';
import { formatDate, getTimeInCurrentStatus, getStatusChipClass } from '../utils/orderManagement.utils';
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
  'picking': { next: 'packed', label: 'Move to Packed' },
  'packed': null,          // No manual step — only via invoice upload
  'invoiced': null,
  'dispatch-ready': { next: 'completed', label: 'Complete Dispatch' },
  'completed': null,
  'partially-completed': null
};

/**
 * Status Action Button — shows next-status action for each order row.
 * Picking → Packed prompts for number of boxes before proceeding.
 */
export const StatusActionButton = ({ order, onStatusUpdate, classes }) => {
  const [boxDialogOpen, setBoxDialogOpen] = useState(false);
  const [boxCount, setBoxCount] = useState(1);

  const currentStatus = order.status?.toLowerCase().replace(/\s+/g, '-');
  const nextAction = CORRECT_STATUS_PROGRESSION[currentStatus];

  if (!nextAction) return null;

  const handleClick = (e) => {
    e.stopPropagation();
    if (currentStatus === 'picking') {
      setBoxCount(1);
      setBoxDialogOpen(true);
    } else if (currentStatus === 'dispatch-ready') {
      onStatusUpdate(order, 'complete-dispatch');
    } else {
      onStatusUpdate(order, nextAction.next);
    }
  };

  const handleBoxConfirm = (e) => {
    e.stopPropagation();
    const boxes = parseInt(boxCount, 10);
    // Bug 33 fix: show error instead of silently returning on invalid input
    if (!boxes || boxes < 1) {
      alert('Please enter a valid number of boxes (minimum 1).');
      return;
    }
    setBoxDialogOpen(false);
    onStatusUpdate(order, 'packed', { number_of_boxes: boxes });
  };

  return (
    <>
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

      <Dialog open={boxDialogOpen} onClose={(e) => { e.stopPropagation(); setBoxDialogOpen(false); }} maxWidth="xs" fullWidth>
        <DialogTitle>Number of Boxes</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="textSecondary" style={{ marginBottom: 12 }}>
            Enter the number of boxes for packing order <strong>{order.order_request_id}</strong>.
          </Typography>
          <TextField
            label="Number of Boxes"
            type="number"
            variant="outlined"
            fullWidth
            value={boxCount}
            onChange={(e) => setBoxCount(e.target.value)}
            inputProps={{ min: 1, step: 1 }}
            autoFocus
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={(e) => { e.stopPropagation(); setBoxDialogOpen(false); }}>Cancel</Button>
          <Button onClick={handleBoxConfirm} color="primary" variant="contained">
            Move to Packed
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
};

/**
 * Orders Table Component
 */
export const OrdersTable = ({
  orders,
  totalCount,
  page,
  rowsPerPage,
  onPageChange,
  onRowsPerPageChange,
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
              - Showing {STATUS_FILTER_OPTIONS.find(opt => opt.value === statusFilter)?.label} ({totalCount} orders)
            </Typography>
          )}
        </Typography>

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
              {loading ? (
                Array.from({ length: rowsPerPage || 10 }).map((_, i) => (
                  <TableRow key={i}>
                    {TABLE_COLUMNS.map((col) => (
                      <TableCell key={col.id}>
                        <Skeleton variant="text" animation="wave" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : orders.length === 0 ? (
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
                        <Box display="flex" alignItems="center" style={{ gap: '6px', flexWrap: 'wrap' }}>
                          <StatusChip status={order.status} classes={classes} />
                          {order.invoice_submitted && (
                            <Tooltip title="Invoice uploaded but order is not yet Packed. Will auto-transition to Invoiced when moved to Packed.">
                              <Chip
                                icon={<IconFileInvoice size={12} />}
                                label="Invoice Submitted"
                                size="small"
                                style={{
                                  backgroundColor: '#e65100',
                                  color: '#fff',
                                  fontSize: '0.6rem',
                                  height: '20px',
                                  cursor: 'default'
                                }}
                              />
                            </Tooltip>
                          )}
                        </Box>
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
          <TablePagination
            component="div"
            count={totalCount || 0}
            page={page}
            onPageChange={onPageChange}
            rowsPerPage={rowsPerPage}
            onRowsPerPageChange={onRowsPerPageChange}
            rowsPerPageOptions={[10, 25, 50, 100]}
          />
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
  const steps = ['Order Details', 'Packed', 'Invoiced', 'Dispatch Ready', 'Completed'];

  useEffect(() => {
    if (order) {
      setNumberOfBoxes(1);
      // Reset to step 0 — correct step is set by status below

      // Set active step based on status
      switch (order.status?.toLowerCase().replace(/\s+/g, '-')) {
        case 'open':
        case 'picking':
          setActiveStep(0);
          break;
        case 'packed':
          setActiveStep(1);
          break;
        case 'invoiced':
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

  // Move to Packed (from Picking state in dialog)
  const handleMoveToPacked = async () => {
    const boxes = parseInt(numberOfBoxes, 10);
    if (!boxes || boxes < 1) {
      alert('Please enter a valid number of boxes (minimum 1).');
      return;
    }

    setLoading(true);
    try {
      await onStatusUpdate(order, 'packed', { number_of_boxes: boxes });
    } catch (error) {
      console.error('Error moving to packed:', error);
      alert('Error moving to packed: ' + error.message);
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

            {/* Timeline */}
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

            {/* Box count input shown only when order is currently in Picking */}
            {order?.status?.toLowerCase() === 'picking' && (
              <>
                <Divider style={{ margin: '16px 0' }} />
                <Typography variant="h6" gutterBottom>Move to Packed</Typography>
                <Typography variant="body2" color="textSecondary" style={{ marginBottom: 12 }}>
                  Enter the number of boxes for packing this order.
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
              </>
            )}
          </Box>
        );

      case 1: // Packed
        return (
          <Box p={2} bgcolor="#fff8e1" borderRadius={1} border="1px solid #fbc02d">
            <Typography variant="h6" gutterBottom>Packed</Typography>
            <Typography variant="body1">
              Order has been packed and is awaiting invoice upload.
            </Typography>
            <Typography variant="body2" color="textSecondary" style={{ marginTop: 8 }}>
              The order will automatically move to <strong>Invoiced</strong> once an invoice file is
              uploaded via the Invoice Upload page.
            </Typography>
          </Box>
        );

      case 2: // Invoiced
        return (
          <Box p={2} bgcolor="#e3f2fd" borderRadius={1} border="1px solid #0288d1">
            <Typography variant="h6" gutterBottom>Invoiced</Typography>
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
              onClick={handleMoveToPacked}
              color="primary"
              variant="contained"
              disabled={loading}
              startIcon={<IconPackage size={16} />}
            >
              {loading ? <CircularProgress size={20} /> : 'Move to Packed'}
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
 * Bulk Actions Bar — target status dropdown + Excel file upload.
 * Excel must have an 'Order ID' column. For Packed target, also 'Number of Boxes'.
 */
export const BulkActionsBar = ({ warehouse, company, onUploadComplete, classes }) => {
  const [targetStatus, setTargetStatus] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);

  const selectedConfig = BULK_TARGET_STATUSES.find(s => s.value === targetStatus);

  const handleFileChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    e.target.value = '';

    if (!targetStatus) {
      alert('Please select a target status before uploading.');
      return;
    }

    setUploading(true);
    try {
      const result = await orderManagementService.bulkStatusUpdate(file, targetStatus, warehouse, company);
      setUploadResult(result);
      if (result.processed_count > 0) {
        onUploadComplete(result);
      }
    } catch (err) {
      alert('Failed to upload file: ' + (err.response?.data?.msg || err.message));
    } finally {
      setUploading(false);
    }
  };

  const handleReset = () => {
    setUploadResult(null);
    setTargetStatus('');
  };

  if (uploadResult) {
    return (
      <Grid item xs={12}>
        <UploadResultCard
          result={uploadResult}
          onReset={handleReset}
          successLabel="Orders Moved"
          errorFilename={`bulk_status_errors_${new Date().toISOString().slice(0, 10)}.xlsx`}
        />
      </Grid>
    );
  }

  return (
    <Grid item xs={12}>
      <Card>
        <CardContent>
          <Typography variant="subtitle1" style={{ fontWeight: 600, marginBottom: 12 }}>
            Bulk Status Update
          </Typography>
          <Box display="flex" alignItems="center" flexWrap="wrap" style={{ gap: 12 }}>
            <FormControl variant="outlined" style={{ minWidth: 200 }}>
              <InputLabel id="bulk-target-label">Target Status</InputLabel>
              <Select
                labelId="bulk-target-label"
                value={targetStatus}
                onChange={(e) => setTargetStatus(e.target.value)}
                label="Target Status"
              >
                {BULK_TARGET_STATUSES.map((s) => (
                  <MenuItem key={s.value} value={s.value}>{s.label}</MenuItem>
                ))}
              </Select>
            </FormControl>

            <Button
              variant="contained"
              color="primary"
              component="label"
              startIcon={uploading ? <CircularProgress size={16} color="inherit" /> : <IconUpload size={16} />}
              disabled={uploading || !targetStatus}
            >
              {uploading ? 'Uploading…' : 'Upload Excel'}
              <input type="file" accept=".xlsx,.xls,.csv" hidden onChange={handleFileChange} />
            </Button>
          </Box>

          <Typography variant="caption" color="textSecondary" style={{ marginTop: 8, display: 'block' }}>
            Upload an Excel with an <strong>Order ID</strong> column
            {selectedConfig?.requiresBoxes && (
              <> and a <strong>Number of Boxes</strong> column (required for Packed)</>
            )}.
            Only orders in the correct preceding state will be moved.
          </Typography>
        </CardContent>
      </Card>
    </Grid>
  );
};

/**
 * BulkResultsDialog is no longer used — results are shown inline in BulkActionsBar.
 * Kept as a no-op export for compatibility until OrderManagement.js is updated.
 */
export const BulkResultsDialog = () => null;