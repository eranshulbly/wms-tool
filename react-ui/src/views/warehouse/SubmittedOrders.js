import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
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
  IconButton,
  Snackbar,
  Alert
} from '@material-ui/core';
import { IconPhoto, IconX, IconFileUpload } from '@tabler/icons';

import MainCard from '../../ui-component/cards/MainCard';
import { gridSpacing } from '../../store/constant';
import { useWarehouse } from '../../context/WarehouseContext';
import {
  getSubmittedOrders,
  fetchSubmittedOrderPhoto,
  uploadPartConvertor
} from '../../services/orderService';

// Submitted Orders — stage 1 of the DMS pipeline. App orders awaiting a part-convertor
// upload: fresh photo orders (dms_status 'submitted') and orders bounced back from the
// Download DMS tab (dms_status 're_submitted', with a reject note). Uploading the part
// convertor moves the order forward to the Download DMS input file tab.

const STATUS_LABELS = { submitted: 'Submitted', re_submitted: 'Re-Submitted' };

const formatDateTime = (v) => {
  if (!v) return '—';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
};

const SubmittedOrders = () => {
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

  // Photo viewer: the object URL of the currently-open image, plus loading/error.
  const [photo, setPhoto] = useState(null); // { url, order } once loaded
  const [photoLoading, setPhotoLoading] = useState(false);
  const [photoError, setPhotoError] = useState(null);
  const [photoOpen, setPhotoOpen] = useState(false);

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
    // Release the blob URL so it isn't leaked; do it after the dialog closes.
    setPhoto((p) => {
      if (p?.url) URL.revokeObjectURL(p.url);
      return null;
    });
    setPhotoError(null);
  }, []);

  // DMS file + part-convertor upload.
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' });
  const [busyId, setBusyId] = useState(null); // order currently downloading/uploading
  const fileInputRef = useRef(null);
  const pendingUploadOrder = useRef(null);

  const notify = (message, severity = 'success') => setSnackbar({ open: true, message, severity });

  const fetchOrders = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const wh = warehouseFilter !== 'all' ? warehouseFilter : null;
      const co = companyFilter !== 'all' ? companyFilter : null;
      const data = await getSubmittedOrders(wh, co);
      if (data.success) {
        setOrders(data.orders || []);
      } else {
        setError(data.msg || 'Failed to load submitted orders');
      }
    } catch (e) {
      setError(e?.response?.data?.msg || 'Failed to load submitted orders');
    } finally {
      setLoading(false);
    }
  }, [warehouseFilter, companyFilter]);

  useEffect(() => {
    fetchOrders();
  }, [fetchOrders]);

  // A changed filter narrows the result set, so start back on the first page.
  useEffect(() => {
    setPage(0);
  }, [warehouseFilter, companyFilter, statusFilter, dealerFilter]);

  // Dealer dropdown options are derived from the loaded orders (company/warehouse
  // scope), so you can only filter by dealers that actually have orders here.
  const dealerOptions = useMemo(() => {
    const seen = new Map();
    orders.forEach((o) => {
      if (o.dealer_id != null && !seen.has(o.dealer_id)) {
        seen.set(o.dealer_id, o.dealer_name || `Dealer ${o.dealer_id}`);
      }
    });
    return Array.from(seen, ([id, name]) => ({ id, name })).sort((a, b) =>
      a.name.localeCompare(b.name)
    );
  }, [orders]);

  // Status (dms_status) + dealer are filtered client-side over the fetched set.
  const filteredOrders = useMemo(
    () =>
      orders.filter(
        (o) =>
          (statusFilter === 'all' || o.dms_status === statusFilter) &&
          (dealerFilter === 'all' || o.dealer_id === dealerFilter)
      ),
    [orders, statusFilter, dealerFilter]
  );

  const handleUploadClick = (order) => {
    pendingUploadOrder.current = order;
    if (fileInputRef.current) {
      fileInputRef.current.value = ''; // let the user re-pick the same file
      fileInputRef.current.click();
    }
  };

  const handleFileSelected = async (e) => {
    const file = e.target.files && e.target.files[0];
    const order = pendingUploadOrder.current;
    pendingUploadOrder.current = null;
    if (!file || !order) return;
    setBusyId(order.order_id);
    try {
      const data = await uploadPartConvertor(order.order_id, file);
      if (data.success) {
        notify(`Imported ${data.item_count} part(s) for ${order.order_number || `#${order.order_id}`}`);
        await fetchOrders();
      } else {
        notify(data.msg || 'Could not import the sheet.', 'error');
      }
    } catch (err) {
      notify(err?.response?.data?.msg || 'Could not import the sheet.', 'error');
    } finally {
      setBusyId(null);
    }
  };

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
                  <Select
                    value={companyFilter}
                    label="Company"
                    onChange={(e) => setCompanyFilter(e.target.value)}
                  >
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
                  <Select
                    value={warehouseFilter}
                    label="Warehouse"
                    onChange={(e) => setWarehouseFilter(e.target.value)}
                  >
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
                  <Select
                    value={statusFilter}
                    label="Status"
                    onChange={(e) => setStatusFilter(e.target.value)}
                  >
                    <MenuItem value="all">All Statuses</MenuItem>
                    <MenuItem value="submitted">Submitted</MenuItem>
                    <MenuItem value="re_submitted">Re-Submitted</MenuItem>
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <FormControl fullWidth size="small">
                  <InputLabel>Dealer</InputLabel>
                  <Select
                    value={dealerFilter}
                    label="Dealer"
                    onChange={(e) => setDealerFilter(e.target.value)}
                  >
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
          title={`Submitted Orders${filteredOrders.length ? ` (${filteredOrders.length})` : ''}`}
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
                {orders.length === 0 ? 'No submitted orders found.' : 'No orders match the filters.'}
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
                      <TableCell>Sales Executive</TableCell>
                      <TableCell>Company</TableCell>
                      <TableCell>Warehouse</TableCell>
                      <TableCell>Submitted</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell>Reject Note</TableCell>
                      <TableCell>Photo</TableCell>
                      <TableCell>Part Convertor</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {pagedOrders.map((o) => (
                      <TableRow key={o.order_id} hover>
                        <TableCell>{o.order_number || `#${o.order_id}`}</TableCell>
                        <TableCell>{o.dealer_name}</TableCell>
                        {/* Who raised the order in the app — blank for any order that
                            predates the field rather than guessing at one. */}
                        <TableCell>{o.sales_executive_name || '—'}</TableCell>
                        <TableCell>{o.company_name || '—'}</TableCell>
                        <TableCell>{o.warehouse_name || '—'}</TableCell>
                        <TableCell>{formatDateTime(o.submitted_at || o.created_at)}</TableCell>
                        <TableCell>
                          <Chip
                            size="small"
                            color={o.dms_status === 're_submitted' ? 'warning' : 'primary'}
                            label={STATUS_LABELS[o.dms_status] || o.dms_status}
                          />
                        </TableCell>
                        <TableCell sx={{ maxWidth: 240 }}>
                          {o.reject_note ? (
                            <Typography variant="body2" color="error">
                              {o.reject_note}
                            </Typography>
                          ) : (
                            <Typography variant="body2" color="textSecondary">
                              —
                            </Typography>
                          )}
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
                            <Button
                              size="small"
                              variant="contained"
                              disabled={busyId === o.order_id}
                              startIcon={<IconFileUpload size={16} />}
                              onClick={() => handleUploadClick(o)}
                            >
                              Upload Part Convertor
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

      {/* Hidden picker shared by every row's Upload/Replace Sheet action. */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".xlsx,.xls"
        style={{ display: 'none' }}
        onChange={handleFileSelected}
      />

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

export default SubmittedOrders;
