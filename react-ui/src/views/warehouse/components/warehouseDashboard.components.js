import React from 'react';
import {
  Grid,
  Card,
  CardContent,
  Typography,
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
  CircularProgress,
  Box,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Divider,
  Paper
} from '@material-ui/core';
import {
  IconPackage,
  IconCalendar,
  IconUser,
  IconClock
} from '@tabler/icons';
import { ORDER_STATUS_DATA, STATUS_FILTER_OPTIONS, TABLE_COLUMNS } from '../constants/warehouseDashboard.constants';
import { formatDate, getTimeInState, getStatusChipClass } from '../utils/warehouseDashboard.utils';

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
                onChange={onWarehouseChange}
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
                onChange={onCompanyChange}
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
          <Grid item xs={12} md={6} lg={3}>
            <FormControl variant="outlined" className={classes.formControl} fullWidth>
              <InputLabel id="status-filter-label">Filter by Status</InputLabel>
              <Select
                labelId="status-filter-label"
                id="status-filter"
                value={statusFilter}
                onChange={onStatusFilterChange}
                label="Filter by Status"
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
 * Compact Status Summary Component - NEW DESIGN
 */
export const CompactStatusSummary = ({ statusCounts, loading, classes }) => (
  <Grid item xs={12}>
    <Paper className={classes.statusSummaryContainer} elevation={1}>
      <Typography variant="h6" className={classes.statusSummaryTitle}>
        Order Status Overview
      </Typography>
      <Box className={classes.statusSummaryContent}>
        {Object.keys(ORDER_STATUS_DATA).map((status) => {
          const statusData = ORDER_STATUS_DATA[status];
          const count = statusCounts[status]?.count || 0;

          return (
            <Box key={status} className={classes.compactStatusItem}>
              <Box className={classes.statusIconSmall}>
                {React.cloneElement(statusData.icon, { size: 20 })}
              </Box>
              <Box className={classes.statusInfo}>
                <Typography variant="body2" className={classes.statusLabelCompact}>
                  {statusData.label}
                </Typography>
                <Typography variant="h6" className={classes.statusCountCompact}>
                  {loading ? <CircularProgress size={16} /> : count}
                </Typography>
              </Box>
            </Box>
          );
        })}
      </Box>
    </Paper>
  </Grid>
);

/**
 * Alternative Horizontal Status Bar Component
 */
export const HorizontalStatusBar = ({ statusCounts, loading, classes }) => (
  <Grid item xs={12}>
    <Card className={classes.horizontalStatusCard}>
      <CardContent className={classes.horizontalStatusContent}>
        <Typography variant="subtitle1" className={classes.statusBarTitle}>
          Order Status Summary
        </Typography>
        <Box className={classes.horizontalStatusContainer}>
          {Object.keys(ORDER_STATUS_DATA).map((status) => {
            const statusData = ORDER_STATUS_DATA[status];
            const count = statusCounts[status]?.count || 0;

            return (
              <Box key={status} className={classes.horizontalStatusItem}>
                <Chip
                  icon={React.cloneElement(statusData.icon, { size: 16 })}
                  label={`${statusData.label}: ${loading ? '...' : count}`}
                  className={classes[statusData.chipClass]}
                  variant="outlined"
                />
              </Box>
            );
          })}
        </Box>
      </CardContent>
    </Card>
  </Grid>
);

/**
 * Legacy Status Card Component (keeping for backwards compatibility)
 */
export const StatusCard = ({ status, count, loading, classes }) => {
  const statusData = ORDER_STATUS_DATA[status];
  const cardClass = `${classes.statusCard} ${classes[`${status}Card`]}`;

  return (
    <Grid item xs={12} sm={6} md={6} lg={3}>
      <Card className={cardClass}>
        <CardContent>
          <Box display="flex" alignItems="center">
            <Box className={classes.iconContainer}>
              {statusData.icon}
            </Box>
            <Box>
              <Typography variant="h3" className={classes.orderCount}>
                {loading ? <CircularProgress size={30} /> : (count || 0)}
              </Typography>
              <Typography variant="subtitle1" className={classes.statusLabel}>
                {statusData.label}
              </Typography>
            </Box>
          </Box>
        </CardContent>
      </Card>
    </Grid>
  );
};

/**
 * Status Chip Component
 */
export const StatusChip = ({ status, classes }) => {
  const className = classes[getStatusChipClass(status)];

  return (
    <Chip
      label={status.charAt(0).toUpperCase() + status.slice(1)}
      className={className}
      size="small"
    />
  );
};

/**
 * Orders Table Component
 */
export const OrdersTable = ({
  filteredOrders,
  loading,
  statusFilter,
  onOrderClick,
  classes
}) => (
  <TableContainer className={classes.tableContainer}>
    <Table stickyHeader aria-label="recent activity table">
      <TableHead>
        <TableRow>
          {TABLE_COLUMNS.map((column) => (
            <TableCell key={column.id}>{column.label}</TableCell>
          ))}
        </TableRow>
      </TableHead>
      <TableBody>
        {loading ? (
          <TableRow>
            <TableCell colSpan={TABLE_COLUMNS.length}>
              <Box className={classes.loadingContainer}>
                <CircularProgress />
              </Box>
            </TableCell>
          </TableRow>
        ) : filteredOrders.length === 0 ? (
          <TableRow>
            <TableCell colSpan={TABLE_COLUMNS.length} align="center">
              {statusFilter === 'all'
                ? 'No recent orders found'
                : `No orders found with status: ${statusFilter}`
              }
            </TableCell>
          </TableRow>
        ) : (
          filteredOrders.map((order) => (
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
              <TableCell>{getTimeInState(order.current_state_time)}</TableCell>
              <TableCell>{order.assigned_to || 'Unassigned'}</TableCell>
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  </TableContainer>
);

/**
 * Order Details Dialog Component
 */
export const OrderDetailsDialog = ({
  open,
  order,
  onClose,
  classes
}) => (
  <Dialog
    open={open}
    onClose={onClose}
    maxWidth="md"
    fullWidth
    className={classes.orderDetailsDialog}
  >
    {order && (
      <>
        <DialogTitle>
          <div className={classes.detailsHeader}>
            <IconPackage className={classes.orderIcon} size={24} />
            <Typography variant="h4">
              Order Details: {order.order_request_id}
            </Typography>
          </div>
        </DialogTitle>
        <DialogContent>
          <Box className={classes.statsSummary}>
            <Grid container>
              <Grid item className={classes.summaryItem}>
                <IconCalendar size={20} style={{ marginRight: 8 }} />
                <Typography variant="body1">
                  {formatDate(order.order_date)}
                </Typography>
              </Grid>
              <Grid item className={classes.summaryItem}>
                <IconClock size={20} style={{ marginRight: 8 }} />
                <Typography variant="body1">
                  {getTimeInState(order.current_state_time)} in{' '}
                  <StatusChip status={order.status} classes={classes} />
                </Typography>
              </Grid>
              <Grid item className={classes.summaryItem}>
                <IconUser size={20} style={{ marginRight: 8 }} />
                <Typography variant="body1">
                  {order.assigned_to || 'Unassigned'}
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
                {order.order_request_id}
              </Typography>
            </Grid>
            <Grid item xs={12} md={6} className={classes.infoGrid}>
              <Typography variant="subtitle2" className={classes.infoLabel}>
                Original Order ID:
              </Typography>
              <Typography variant="body1" className={classes.infoValue}>
                {order.original_order_id}
              </Typography>
            </Grid>
            <Grid item xs={12} md={6} className={classes.infoGrid}>
              <Typography variant="subtitle2" className={classes.infoLabel}>
                Dealer:
              </Typography>
              <Typography variant="body1" className={classes.infoValue}>
                {order.dealer_name}
              </Typography>
            </Grid>
            <Grid item xs={12} md={6} className={classes.infoGrid}>
              <Typography variant="subtitle2" className={classes.infoLabel}>
                Total Products:
              </Typography>
              <Typography variant="body1" className={classes.infoValue}>
                {order.products}
              </Typography>
            </Grid>
            <Grid item xs={12} md={6} className={classes.infoGrid}>
              <Typography variant="subtitle2" className={classes.infoLabel}>
                Current Status:
              </Typography>
              <Typography variant="body1" className={classes.infoValue}>
                <StatusChip status={order.status} classes={classes} />
              </Typography>
            </Grid>
            <Grid item xs={12} md={6} className={classes.infoGrid}>
              <Typography variant="subtitle2" className={classes.infoLabel}>
                Time in Current State:
              </Typography>
              <Typography variant="body1" className={classes.infoValue}>
                {getTimeInState(order.current_state_time)}
              </Typography>
            </Grid>
          </Grid>

          <Divider />

          <Box mt={3}>
            <Typography variant="h5" gutterBottom>
              Order Timeline
            </Typography>

            <Box mt={2}>
              {order.state_history && order.state_history.map((state, index) => (
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
          <Button onClick={onClose} color="primary">
            Close
          </Button>
        </DialogActions>
      </>
    )}
  </Dialog>
);