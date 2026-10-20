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
import { formatDate, getTimeInState, withDurations } from '../utils';
import StatusChip from './StatusChip';

/**
 * The order's state history with how long it sat in each one.
 *
 * A history row records when a state was ENTERED, so time spent in it is the
 * gap to the next row — and the last row is still running. The running one is
 * labelled rather than shown as a plain figure: "2d 4h (so far)" and "2d 4h"
 * mean different things to someone deciding whether an order is stuck.
 */
const StatusTimeline = ({ history, dense = false }) => {
  const rows = withDurations(history);
  if (!rows.length) {
    return (
      <Typography variant="body2" color="textSecondary">
        No status history recorded for this order.
      </Typography>
    );
  }

  return (
    <>
      {rows.map((state, idx) => (
        <Box
          key={`${state.state_name}-${state.timestamp}-${idx}`}
          style={{
            padding: dense ? '6px 0' : '8px 0',
            borderLeft: state.isCurrent ? '3px solid #4caf50' : '3px solid #e0e0e0',
            paddingLeft: 16,
            marginLeft: 8
          }}
        >
          <Box display="flex" alignItems="center" flexWrap="wrap" style={{ gap: 8 }}>
            <Typography variant="subtitle2" style={{ fontWeight: 700 }}>
              {state.state_name}
            </Typography>
            <Chip
              size="small"
              label={state.isCurrent ? `${state.duration} (so far)` : state.duration}
              color={state.isCurrent ? 'primary' : 'default'}
              variant={state.isCurrent ? 'default' : 'outlined'}
            />
          </Box>
          <Typography variant="body2" color="textSecondary">
            Entered {formatDate(state.timestamp)}
          </Typography>
          {state.user && <Typography variant="caption">{state.user}</Typography>}
        </Box>
      ))}
    </>
  );
};

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
              // `products` is a COUNT in the order list and an ARRAY of product objects
              // once the details have loaded. Rendered raw, the array crashed the dialog
              // to a blank page with React error #31 — objects are not valid as a child —
              // the moment the details arrived, which is why the list behind it looked fine.
              ['Total Products',
                Array.isArray(order.products) ? order.products.length : (order.products ?? 0)],
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
            <StatusTimeline history={order.state_history} />
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

            {/* The timeline used to live here, on step 0 only — so opening an
                order that was already Packed showed the step's own panel and
                nothing else, and the history was unreachable without clicking
                back. It now renders below the step content for every step. */}

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

        {/* Always visible, whatever step is selected. The stepper says where the
            order IS; this says how long each leg took to get there, which is
            the question asked when one is late. */}
        <Divider style={{ margin: '20px 0 12px' }} />
        <Typography variant="h6" gutterBottom>Time in each status</Typography>
        <StatusTimeline history={order.state_history} />
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
