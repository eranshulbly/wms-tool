import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Grid,
  Box,
  Stack,
  Typography,
  Card,
  CardContent,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  TextField,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  Paper,
  Chip,
  CircularProgress,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  IconButton,
  Snackbar,
  Alert
} from '@material-ui/core';
import { IconPhoto, IconX, IconDownload, IconBan } from '@tabler/icons';

import MainCard from '../../ui-component/cards/MainCard';
import { gridSpacing } from '../../store/constant';
import { useWarehouse } from '../../context/WarehouseContext';
import {
  getSubmittedOrders,
  fetchSubmittedOrderPhoto,
  downloadDmsFile,
  rejectSubmittedOrder,
  readBlobError
} from '../../services/orderService';

// Download DMS input file — stage 2 of the DMS pipeline. Orders whose parts are ready
// (itemised orders, or photo orders whose part convertor was uploaded). A user downloads
// the company's DMS input file here (which marks the order Done, but it stays so it can
// still be rejected), or rejects it with a note — sending it back to Submitted Orders.

const STATUS_LABELS = { ready: 'Ready', done: 'Done' };

const DownloadDmsInput = () => {
  const { warehouses, companies } = useWarehouse();

  const [companyFilter, setCompanyFilter] = useState('all');
  const [warehouseFilter, setWarehouseFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [dealerFilter, setDealerFilter] = useState('all');
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);

  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' });
  const [busyId, setBusyId] = useState(null);
  const notify = (message, severity = 'success') => setSnackbar({ open: true, message, severity });

  // Photo viewer.
  const [photo, setPhoto] = useState(null);
  const [photoLoading, setPhotoLoading] = useState(false);
  const [photoError, setPhotoError] = useState(null);
  const [photoOpen, setPhotoOpen] = useState(false);

  // Reject dialog.
  const [rejectOrder, setRejectOrder] = useState(null);
  const [rejectNote, setRejectNote] = useState('');
  const [rejecting, setRejecting] = useState(false);

  const fetchOrders = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const wh = warehouseFilter !== 'all' ? warehouseFilter : null;
      const co = companyFilter !== 'all' ? companyFilter : null;
      const data = await getSubmittedOrders(wh, co, 'download');
      if (data.success) {
        setOrders(data.orders || []);
      } else {
        setError(data.msg || 'Failed to load orders');
      }
    } catch (e) {
      setError(e?.response?.data?.msg || 'Failed to load orders');
    } finally {
      setLoading(false);
    }
  }, [warehouseFilter, companyFilter]);

  useEffect(() => {
    fetchOrders();
  }, [fetchOrders]);

  useEffect(() => {
    setPage(0);
  }, [warehouseFilter, companyFilter, statusFilter, dealerFilter]);

  const dealerOptions = useMemo(() => {
    const seen = new Map();
    orders.forEach((o) => {
      if (o.dealer_id != null && !seen.has(o.dealer_id)) {
        seen.set(o.dealer_id, o.dealer_name || `Dealer ${o.dealer_id}`);
      }
    });
    return Array.from(seen, ([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name));
  }, [orders]);

  const filteredOrders = useMemo(
    () =>
      orders.filter(
        (o) =>
          (statusFilter === 'all' || o.dms_status === statusFilter) &&
          (dealerFilter === 'all' || o.dealer_id === dealerFilter)
      ),
    [orders, statusFilter, dealerFilter]
  );

  const handleDownload = useCallback(
    async (order) => {
      setBusyId(order.order_id);
      try {
        const { blob, filename } = await downloadDmsFile(order.order_id);
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        notify(`Downloaded ${filename} — order marked Done`);
        await fetchOrders();
      } catch (e) {
        const msg = await readBlobError(e);
        notify(msg || 'Could not generate the DMS file.', 'error');
      } finally {
        setBusyId(null);
      }
    },
    [fetchOrders]
  );

  const submitReject = async () => {
    if (!rejectOrder || !rejectNote.trim()) return;
    setRejecting(true);
    try {
      const data = await rejectSubmittedOrder(rejectOrder.order_id, rejectNote.trim());
      if (data.success) {
        notify(`${rejectOrder.order_number || `#${rejectOrder.order_id}`} rejected — back in Submitted Orders`);
        setRejectOrder(null);
        setRejectNote('');
        await fetchOrders();
      } else {
        notify(data.msg || 'Could not reject the order.', 'error');
      }
    } catch (e) {
      notify(e?.response?.data?.msg || 'Could not reject the order.', 'error');
    } finally {
      setRejecting(false);
    }
  };

  const openPhoto = useCallback(async (order) => {
    const attachment = order.attachments?.[0];
    if (!attachment) return;
    setPhotoOpen(true);
    setPhotoLoading(true);
    setPhotoError(null);
    setPhoto(null);
    try {
      const blob = await fetchSubmittedOrderPhoto(order.order_id, attachment.attachment_id);
      setPhoto({ url: URL.createObjectURL(blob), order });
    } catch (e) {
      setPhotoError('Could not load the photo.');
    } finally {
      setPhotoLoading(false);
    }
  }, []);

  const closePhoto = useCallback(() => {
    setPhotoOpen(false);
    setPhoto((p) => {
      if (p?.url) URL.revokeObjectURL(p.url);
      return null;
    });
    setPhotoError(null);
  }, []);

  const pagedOrders = filteredOrders.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage);

  return (
    <Grid container spacing={gridSpacing}>
      <Grid item xs={12}>
        <Card>
          <CardContent>
            <Grid container spacing={gridSpacing} alignItems="center">
              <Grid item xs={12} sm={6} md={3}>
                <FormControl fullWidth size="small">
                  <InputLabel>Company</InputLabel>
                  <Select value={companyFilter} label="Company" onChange={(e) => setCompanyFilter(e.target.value)}>
                    <MenuItem value="all">All Companies</MenuItem>
                    {companies.map((c) => (
                      <MenuItem key={c.id} value={c.id}>
                        {c.name}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <FormControl fullWidth size="small">
                  <InputLabel>Warehouse</InputLabel>
                  <Select value={warehouseFilter} label="Warehouse" onChange={(e) => setWarehouseFilter(e.target.value)}>
                    <MenuItem value="all">All Warehouses</MenuItem>
                    {warehouses.map((w) => (
                      <MenuItem key={w.id} value={w.id}>
                        {w.name}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <FormControl fullWidth size="small">
                  <InputLabel>Status</InputLabel>
                  <Select value={statusFilter} label="Status" onChange={(e) => setStatusFilter(e.target.value)}>
                    <MenuItem value="all">All Statuses</MenuItem>
                    <MenuItem value="ready">Ready</MenuItem>
                    <MenuItem value="done">Done</MenuItem>
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <FormControl fullWidth size="small">
                  <InputLabel>Dealer</InputLabel>
                  <Select value={dealerFilter} label="Dealer" onChange={(e) => setDealerFilter(e.target.value)}>
                    <MenuItem value="all">All Dealers</MenuItem>
                    {dealerOptions.map((d) => (
                      <MenuItem key={d.id} value={d.id}>
                        {d.name}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
            </Grid>
          </CardContent>
        </Card>
      </Grid>

      <Grid item xs={12}>
        <MainCard
          title={`Download DMS Input${filteredOrders.length ? ` (${filteredOrders.length})` : ''}`}
          content={false}
        >
          {loading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', p: 5 }}>
              <CircularProgress />
            </Box>
          ) : error ? (
            <Box sx={{ p: 3 }}>
              <Typography color="error">{error}</Typography>
            </Box>
          ) : filteredOrders.length === 0 ? (
            <Box sx={{ p: 3 }}>
              <Typography color="textSecondary">
                {orders.length === 0 ? 'No orders ready for DMS download.' : 'No orders match the filters.'}
              </Typography>
            </Box>
          ) : (
            <>
              <TableContainer component={Paper} elevation={0}>
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableCell>Order #</TableCell>
                      <TableCell>Dealer</TableCell>
                      <TableCell>Company</TableCell>
                      <TableCell>Warehouse</TableCell>
                      <TableCell align="right">Parts</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell>Photo</TableCell>
                      <TableCell>Actions</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {pagedOrders.map((o) => (
                      <TableRow key={o.order_id} hover>
                        <TableCell>{o.order_number || `#${o.order_id}`}</TableCell>
                        <TableCell>{o.dealer_name}</TableCell>
                        <TableCell>{o.company_name || '—'}</TableCell>
                        <TableCell>{o.warehouse_name || '—'}</TableCell>
                        <TableCell align="right">{o.item_count}</TableCell>
                        <TableCell>
                          <Chip
                            size="small"
                            color={o.dms_status === 'done' ? 'success' : 'info'}
                            label={STATUS_LABELS[o.dms_status] || o.dms_status}
                          />
                        </TableCell>
                        <TableCell>
                          {o.attachments && o.attachments.length > 0 ? (
                            <Button
                              size="small"
                              variant="outlined"
                              startIcon={<IconPhoto size={16} />}
                              onClick={() => openPhoto(o)}
                            >
                              View
                            </Button>
                          ) : (
                            <Typography variant="body2" color="textSecondary">
                              —
                            </Typography>
                          )}
                        </TableCell>
                        <TableCell>
                          <Stack direction="row" spacing={1} alignItems="center">
                            {o.dms_available ? (
                              <Button
                                size="small"
                                variant="contained"
                                disabled={busyId === o.order_id}
                                startIcon={<IconDownload size={16} />}
                                onClick={() => handleDownload(o)}
                              >
                                {o.dms_status === 'done' ? 'Re-download' : 'Download'}
                              </Button>
                            ) : (
                              <Typography variant="body2" color="textSecondary" sx={{ fontStyle: 'italic' }}>
                                Coming soon
                              </Typography>
                            )}
                            <Button
                              size="small"
                              variant="outlined"
                              color="error"
                              disabled={busyId === o.order_id}
                              startIcon={<IconBan size={16} />}
                              onClick={() => {
                                setRejectOrder(o);
                                setRejectNote('');
                              }}
                            >
                              Reject
                            </Button>
                            {busyId === o.order_id && <CircularProgress size={18} />}
                          </Stack>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
              <TablePagination
                component="div"
                count={filteredOrders.length}
                page={page}
                onPageChange={(e, newPage) => setPage(newPage)}
                rowsPerPage={rowsPerPage}
                onRowsPerPageChange={(e) => {
                  setRowsPerPage(parseInt(e.target.value, 10));
                  setPage(0);
                }}
                rowsPerPageOptions={[10, 25, 50, 100]}
              />
            </>
          )}
        </MainCard>
      </Grid>

      {/* Reject dialog — a note is required; rejecting clears the parts and sends the
          order back to Submitted Orders as Re-Submitted. */}
      <Dialog open={!!rejectOrder} onClose={() => !rejecting && setRejectOrder(null)} maxWidth="sm" fullWidth>
        <DialogTitle>
          Reject {rejectOrder?.order_number || (rejectOrder && `#${rejectOrder.order_id}`)}
        </DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
            The order returns to Submitted Orders, its parts are cleared, and this note is shown to the
            person who re-uploads the part convertor.
          </Typography>
          <TextField
            autoFocus
            fullWidth
            multiline
            minRows={3}
            label="Reason for rejection"
            value={rejectNote}
            onChange={(e) => setRejectNote(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRejectOrder(null)} disabled={rejecting}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color="error"
            onClick={submitReject}
            disabled={rejecting || !rejectNote.trim()}
            startIcon={rejecting ? <CircularProgress size={16} color="inherit" /> : <IconBan size={16} />}
          >
            Reject
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={photoOpen} onClose={closePhoto} maxWidth="md" fullWidth>
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', pr: 1 }}>
          <span>
            Order Photo
            {photo?.order ? ` — ${photo.order.order_number || `#${photo.order.order_id}`}` : ''}
          </span>
          <IconButton onClick={closePhoto} size="small" aria-label="close">
            <IconX size={18} />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers>
          {photoLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', p: 5 }}>
              <CircularProgress />
            </Box>
          ) : photoError ? (
            <Box sx={{ p: 3 }}>
              <Typography color="error">{photoError}</Typography>
            </Box>
          ) : photo?.url ? (
            <Box sx={{ display: 'flex', justifyContent: 'center' }}>
              <img
                src={photo.url}
                alt="Submitted order"
                style={{ maxWidth: '100%', maxHeight: '70vh', objectFit: 'contain' }}
              />
            </Box>
          ) : null}
        </DialogContent>
      </Dialog>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={5000}
        onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          severity={snackbar.severity}
          variant="filled"
          onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Grid>
  );
};

export default DownloadDmsInput;
