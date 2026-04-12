import React, { useState, useEffect } from 'react';
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Grid,
  Paper,
  Stepper,
  Step,
  StepLabel,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography
} from '@material-ui/core';
import {
  IconPackage,
  IconCalendar,
  IconUser,
  IconClock,
  IconCheck
} from '@tabler/icons';
import { formatDate, getTimeInState } from '../utils';
import StatusChip from './StatusChip';

/**
 * Order details modal used by both WarehouseDashboard (read-only) and
 * OrderManagement (with status action buttons).
 *
 * Props:
 *   open            — bool
 *   order           — order object (with products and state_history)
 *   onClose         — () => void
 *   onStatusUpdate  — (order, action, data?) => void | undefined
 *                     When undefined the dialog is read-only (dashboard mode).
 *   allowedStatuses — string[] | null
 *   classes         — makeStyles classes from the parent page
 */
const OrderDetailsDialog = ({ open, order, onClose, onStatusUpdate, classes }) => {
  const [activeStep, setActiveStep] = useState(0);
  const [numberOfBoxes, setNumberOfBoxes] = useState(1);
  const [loading, setLoading] = useState(false);
  const [isCompletingDispatch, setIsCompletingDispatch] = useState(false);

  const isManagementMode = typeof onStatusUpdate === 'function';
  const steps = ['Order Details', 'Packed', 'Invoiced', 'Dispatch Ready', 'Completed'];

  useEffect(() => {
    if (!order) return;
    setNumberOfBoxes(1);
    const slug = order.status?.toLowerCase().replace(/\s+/g, '-');
    const stepMap = {
      'open': 0, 'picking': 0,
      'packed': 1,
      'invoiced': 2,
      'dispatch-ready': 3,
      'completed': 4, 'partially-completed': 4
    };
    setActiveStep(stepMap[slug] ?? 0);
  }, [order]);

  const handleMoveToPacked = async () => {
    const boxes = parseInt(numberOfBoxes, 10);
    if (!boxes || boxes < 1) { alert('Please enter a valid number of boxes (minimum 1).'); return; }
    setLoading(true);
    try { await onStatusUpdate(order, 'packed', { number_of_boxes: boxes }); }
    catch (e) { alert('Error moving to packed: ' + e.message); }
    finally { setLoading(false); }
  };

  const handleCompleteDispatch = async () => {
    if (isCompletingDispatch) return;
    if (!window.confirm(
      'This will mark the order as completed and dispatched from the warehouse.\n\nAre you sure?'
    )) return;

    setIsCompletingDispatch(true);
    setLoading(true);
    try { await onStatusUpdate(order, 'completed'); }
    catch (e) { alert('Error completing dispatch: ' + e.message); }
    finally { setLoading(false); setIsCompletingDispatch(false); }
  };

  if (!order) return null;

  // ─── Read-only dialog (Dashboard mode) ───────────────────────────────────
  if (!isManagementMode) {
    return (
      <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth className={classes?.orderDetailsDialog}>
        <DialogTitle>
          <div className={classes?.detailsHeader}>
            <IconPackage className={classes?.orderIcon} size={24} />
            <Typography variant="h4">Order Details: {order.order_request_id}</Typography>
          </div>
        </DialogTitle>
        <DialogContent>
          <Box className={classes?.statsSummary}>
            <Grid container>
              <Grid item className={classes?.summaryItem}>
                <IconCalendar size={20} style={{ marginRight: 8 }} />
                <Typography variant="body1">{formatDate(order.order_date)}</Typography>
              </Grid>
              <Grid item className={classes?.summaryItem}>
                <IconClock size={20} style={{ marginRight: 8 }} />
                <Typography variant="body1">
                  {getTimeInState(order.current_state_time)} in{' '}
                  <StatusChip status={order.status} classes={classes} />
                </Typography>
              </Grid>
              <Grid item className={classes?.summaryItem}>
                <IconUser size={20} style={{ marginRight: 8 }} />
                <Typography variant="body1">{order.assigned_to || 'Unassigned'}</Typography>
              </Grid>
            </Grid>
          </Box>

          <Grid container spacing={2} className={classes?.infoSection}>
            {[
              ['Order ID', order.order_request_id],
              ['Original Order ID', order.original_order_id],
              ['Dealer', order.dealer_name],
              ['Total Products', order.products],
              ['Current Status', <StatusChip key="s" status={order.status} classes={classes} />],
              ['Time in Current State', getTimeInState(order.current_state_time)]
            ].map(([label, value]) => (
              <Grid item xs={12} md={6} key={label} className={classes?.infoGrid}>
                <Typography variant="subtitle2" className={classes?.infoLabel}>{label}:</Typography>
                <Typography variant="body1" className={classes?.infoValue}>{value}</Typography>
              </Grid>
            ))}
          </Grid>

          <Divider />
          <Box mt={3}>
            <Typography variant="h5" gutterBottom>Order Timeline</Typography>
            {order.state_history?.map((state, idx) => (
              <Box key={idx} className={classes?.timelineItem} mb={2}>
                <Typography variant="subtitle1">{state.state_name}</Typography>
                <Typography variant="body2" color="textSecondary">{formatDate(state.timestamp)}</Typography>
                <Typography variant="body2">Handled by: {state.user}</Typography>
              </Box>
            ))}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose} color="primary">Close</Button>
        </DialogActions>
      </Dialog>
    );
  }

  // ─── Management dialog (OrderManagement mode) ────────────────────────────
  const renderStepContent = () => {
    switch (activeStep) {
      case 0:
        return (
          <Box>
            <Grid container spacing={2}>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>Order ID:</Typography>
                <Typography variant="body1" gutterBottom>{order.order_request_id}</Typography>
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>Status:</Typography>
                <Chip label={order.status?.replace('-', ' ') || 'Unknown'} color="primary" size="small" />
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>Dealer:</Typography>
                <Typography variant="body1" gutterBottom>{order.dealer_name}</Typography>
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="subtitle2" gutterBottom>Order Date:</Typography>
                <Typography variant="body1" gutterBottom>
                  {order.order_date ? new Date(order.order_date).toLocaleDateString() : 'N/A'}
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
                  {order.products?.map((product) => (
                    <TableRow key={product.product_id}>
                      <TableCell>
                        <Typography variant="body2" fontWeight="bold">{product.name}</Typography>
                        <Typography variant="caption" color="textSecondary">{product.product_string}</Typography>
                      </TableCell>
                      <TableCell>{product.description}</TableCell>
                      <TableCell>{product.quantity_ordered}</TableCell>
                      <TableCell>${product.price}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>

            <Divider style={{ margin: '16px 0' }} />
            <Typography variant="h6" gutterBottom>Order Timeline</Typography>
            {order.state_history?.map((state, idx) => (
              <Box
                key={idx}
                style={{
                  padding: '8px 0',
                  borderLeft: idx === order.state_history.length - 1
                    ? '3px solid #4caf50' : '3px solid #e0e0e0',
                  paddingLeft: '16px',
                  marginLeft: '8px'
                }}
              >
                <Typography variant="subtitle2" fontWeight="bold">{state.state_name}</Typography>
                <Typography variant="body2" color="textSecondary">
                  {new Date(state.timestamp).toLocaleString()}
                </Typography>
                <Typography variant="caption">{state.user}</Typography>
              </Box>
            ))}

            {order.status?.toLowerCase() === 'picking' && (
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

      case 1:
        return (
          <Box p={2} bgcolor="#fff8e1" borderRadius={1} border="1px solid #fbc02d">
            <Typography variant="h6" gutterBottom>Packed</Typography>
            <Typography variant="body1">Order has been packed and is awaiting invoice upload.</Typography>
            <Typography variant="body2" color="textSecondary" style={{ marginTop: 8 }}>
              The order will automatically move to <strong>Invoiced</strong> once an invoice file is
              uploaded via the Invoice Upload page.
            </Typography>
          </Box>
        );

      case 2:
        return (
          <Box p={2} bgcolor="#e3f2fd" borderRadius={1} border="1px solid #0288d1">
            <Typography variant="h6" gutterBottom>Invoiced</Typography>
            <Typography variant="body1">Order has been invoiced and is awaiting dispatch.</Typography>
            <Typography variant="body2" color="textSecondary" style={{ marginTop: 8 }}>
              The order will automatically move to <strong>Dispatch Ready</strong> when processing is complete.
            </Typography>
          </Box>
        );

      case 3:
        return (
          <Box>
            <Typography variant="h6" gutterBottom>Dispatch Ready</Typography>
            <Box p={2} bgcolor="#e8f5e8" borderRadius={1} border="1px solid #4caf50" mb={2}>
              <Typography variant="body1">
                Order has been packed and invoice uploaded. Ready for dispatch.
              </Typography>
            </Box>
            {order.final_order && (
              <Box p={2} bgcolor="#f5f5f5" borderRadius={1}>
                <Typography variant="subtitle2" gutterBottom>Final Order Information:</Typography>
                <Typography variant="body2">Order Number: {order.final_order.order_number}</Typography>
                <Typography variant="body2">Status: {order.final_order.status}</Typography>
                <Typography variant="body2">
                  Created: {new Date(order.final_order.created_at).toLocaleString()}
                </Typography>
              </Box>
            )}
          </Box>
        );

      case 4:
        return (
          <Box textAlign="center" p={4}>
            <IconCheck size={64} color="#4caf50" style={{ marginBottom: 16 }} />
            <Typography variant="h5" gutterBottom>Order Completed</Typography>
            <Typography variant="body1" color="textSecondary">
              This order has been successfully dispatched from the warehouse.
            </Typography>
            {order.final_order?.dispatched_date && (
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

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth className={classes?.orderDetailsDialog}>
      <DialogTitle>
        <Box display="flex" alignItems="center" justifyContent="space-between">
          <Box display="flex" alignItems="center">
            <IconPackage size={24} style={{ marginRight: 8 }} />
            <Typography variant="h5">Order Management: {order.order_request_id}</Typography>
          </Box>
          <Chip label={order.status?.replace('-', ' ') || 'Unknown'} color="primary" size="small" />
        </Box>
      </DialogTitle>

      <DialogContent style={{ minHeight: '500px' }}>
        <Stepper activeStep={activeStep} style={{ marginBottom: 24 }}>
          {steps.map((label) => (
            <Step key={label}><StepLabel>{label}</StepLabel></Step>
          ))}
        </Stepper>
        {renderStepContent()}
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose} disabled={loading}>Close</Button>

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
  );
};

export default OrderDetailsDialog;
