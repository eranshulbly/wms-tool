import React, { useState } from 'react';
import {
  Grid,
  Card,
  CardContent,
  Box,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  Paper,
  Typography,
  Skeleton,
  Chip,
  Tooltip
} from '@material-ui/core';
import { IconFileInvoice } from '@tabler/icons';
import {
  TABLE_COLUMNS_BASE,
  TABLE_COLUMNS_WITH_ACTIONS,
  STATUS_FILTER_OPTIONS
} from '../constants/statuses';
import { formatDate, getTimeInState } from '../utils';
import StatusChip from './StatusChip';
import StatusActionButton from './StatusActionButton';

/**
 * Paginated orders table.
 *
 * Props:
 *   orders            — current page's order array (or full array when showActions=false)
 *   totalCount        — total record count for controlled pagination
 *   page / rowsPerPage / onPageChange / onRowsPerPageChange — controlled pagination props
 *                       (when omitted the component manages pagination internally)
 *   loading           — bool
 *   statusFilter      — 'all' or a slug string
 *   onOrderClick      — (order) => void
 *   onStatusUpdate    — (order, action, data?) => void  — pass undefined to hide Actions column
 *   allowedStatuses   — string[] | null
 *   classes           — makeStyles classes
 */
const OrdersTable = ({
  orders,
  totalCount,
  page: externalPage,
  rowsPerPage: externalRowsPerPage,
  onPageChange: externalOnPageChange,
  onRowsPerPageChange: externalOnRowsPerPageChange,
  loading,
  statusFilter,
  onOrderClick,
  onStatusUpdate,
  classes
}) => {
  // Internal pagination used only when the caller does not supply page/rowsPerPage
  const [internalPage, setInternalPage] = useState(0);
  const [internalRowsPerPage, setInternalRowsPerPage] = useState(25);

  const isControlled = externalPage !== undefined;
  const page = isControlled ? externalPage : internalPage;
  const rowsPerPage = isControlled ? externalRowsPerPage : internalRowsPerPage;

  const handlePageChange = (event, newPage) => {
    if (isControlled) externalOnPageChange(event, newPage);
    else setInternalPage(newPage);
  };

  const handleRowsPerPageChange = (event) => {
    if (isControlled) {
      externalOnRowsPerPageChange(event);
    } else {
      setInternalRowsPerPage(parseInt(event.target.value, 10));
      setInternalPage(0);
    }
  };

  const showActions = typeof onStatusUpdate === 'function';
  const columns = showActions ? TABLE_COLUMNS_WITH_ACTIONS : TABLE_COLUMNS_BASE;

  // When uncontrolled, slice here; when controlled, the parent already passes paged data
  const displayOrders = isControlled
    ? orders
    : (orders || []).slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage);

  const count = totalCount !== undefined ? totalCount : (orders?.length || 0);

  const content = (
    <>
      <TableContainer className={classes?.tableContainer} component={Paper}>
        <Table stickyHeader aria-label="orders table">
          <TableHead>
            <TableRow>
              {columns.map((col) => (
                <TableCell key={col.id}>{col.label}</TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              Array.from({ length: rowsPerPage || 10 }).map((_, i) => (
                <TableRow key={i}>
                  {columns.map((col) => (
                    <TableCell key={col.id}>
                      <Skeleton variant="text" animation="wave" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : displayOrders.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columns.length} align="center">
                  <Typography variant="subtitle1">
                    {statusFilter === 'all'
                      ? 'No orders found'
                      : `No orders with status: ${statusFilter}`}
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              displayOrders.map((order) => (
                <TableRow
                  key={order.order_request_id}
                  hover
                  onClick={() => onOrderClick(order)}
                  className={classes?.tableRow}
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
                  <TableCell>{getTimeInState(order.current_state_time)}</TableCell>
                  <TableCell>{order.assigned_to || 'Unassigned'}</TableCell>
                  {showActions && (
                    <TableCell>
                      <Box display="flex" alignItems="center">
                        <StatusActionButton
                          order={order}
                          onStatusUpdate={onStatusUpdate}
                          classes={classes}
                        />
                      </Box>
                    </TableCell>
                  )}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>
      <TablePagination
        component="div"
        count={count}
        page={page}
        onPageChange={handlePageChange}
        rowsPerPage={rowsPerPage}
        onRowsPerPageChange={handleRowsPerPageChange}
        rowsPerPageOptions={[10, 25, 50, 100]}
      />
    </>
  );

  // OrderManagement wraps the table in a Card via this component;
  // WarehouseDashboard wraps it in its own Card, so we skip the wrapper when
  // the component is used in "read-only" (no actions) mode.
  if (showActions) {
    return (
      <Grid item xs={12}>
        <Card>
          <CardContent>
            <Typography variant="h4" gutterBottom>
              Orders
              {statusFilter !== 'all' && (
                <Typography
                  variant="subtitle1"
                  component="span"
                  className={classes?.filterTitle}
                >
                  {' '}— Showing {STATUS_FILTER_OPTIONS.find((o) => o.value === statusFilter)?.label} ({count} orders)
                </Typography>
              )}
            </Typography>
            {content}
          </CardContent>
        </Card>
      </Grid>
    );
  }

  return content;
};

export default OrdersTable;
