import React from 'react';
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
  DialogActions
} from '@material-ui/core';
import { IconArrowRight } from '@tabler/icons';
import { STATUS_FILTER_OPTIONS, TABLE_COLUMNS } from '../constants/orderManagement.constants';
import { formatDate, getTimeInCurrentStatus, getNextStatus, getStatusChipClass } from '../utils/orderManagement.utils';

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
  classes
}) => (
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
                {STATUS_FILTER_OPTIONS.map((option) => (
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

/**
 * Status Chip Component
 */
export const StatusChip = ({ status, classes }) => {
  const normalizedStatus = String(status).toLowerCase();
  const className = classes[getStatusChipClass(status)];

  return (
    <Chip
      label={normalizedStatus.charAt(0).toUpperCase() + normalizedStatus.slice(1)}
      className={`${classes.statusChip} ${className}`}
      size="small"
    />
  );
};

/**
 * Status Action Button Component
 */
export const StatusActionButton = ({ order, onStatusUpdate, classes }) => {
  const nextStatus = getNextStatus(order.status);

  if (!nextStatus) return null;

  return (
    <Button
      variant="outlined"
      color="primary"
      size="small"
      className={classes.statusActionButton}
      onClick={(e) => {
        e.stopPropagation();
        onStatusUpdate(order, nextStatus);
      }}
      startIcon={<IconArrowRight size={16} />}
    >
      Move to {nextStatus.charAt(0).toUpperCase() + nextStatus.slice(1)}
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
 * Empty Order Details Dialog Component (placeholder)
 */
export const OrderDetailsDialog = ({
  open,
  order,
  onClose
}) => (
  <Dialog
    open={open}
    onClose={onClose}
    maxWidth="sm"
    fullWidth
  >
    <DialogTitle>
      Order Details
    </DialogTitle>
    <DialogContent>
      {order ? (
        <Box>
          <Typography variant="body1" gutterBottom>
            <strong>Order ID:</strong> {order.order_request_id}
          </Typography>
          <Typography variant="body1" gutterBottom>
            <strong>Dealer:</strong> {order.dealer_name}
          </Typography>
          <Typography variant="body1" gutterBottom>
            <strong>Status:</strong> {order.status}
          </Typography>
          <Typography variant="body1" color="textSecondary">
            Order details will be implemented here...
          </Typography>
        </Box>
      ) : (
        <Typography variant="body1">No order selected</Typography>
      )}
    </DialogContent>
    <DialogActions>
      <Button onClick={onClose} color="primary">
        Close
      </Button>
    </DialogActions>
  </Dialog>
);