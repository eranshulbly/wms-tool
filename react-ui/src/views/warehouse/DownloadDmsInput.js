import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
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
import {
  IconPhoto, IconX, IconDownload, IconBan, IconPlus, IconUpload, IconBuildingWarehouse,
  IconChevronRight
} from '@tabler/icons';
import SubmittedOrderItems from './components/SubmittedOrderItems';

import MainCard from '../../ui-component/cards/MainCard';
import { gridSpacing } from '../../store/constant';
import { useWarehouse } from '../../context/WarehouseContext';
import {
  getSubmittedOrders,
  fetchSubmittedOrderPhoto,
  downloadDmsFile,
  rejectSubmittedOrder,
  createManualOrder,
  getOrderDealers,
  getDmsInventory,
  uploadDmsInventory,
  readBlobError
} from '../../services/orderService';

// Push a blob at the browser as a download. Shared by the per-order download and the
// direct converter so both behave identically (and both revoke the URL afterwards).
const saveBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
};

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
  // Clicking a row opens that order's line items in a modal (the order object, or
  // null when closed).
  const [detailOrder, setDetailOrder] = useState(null);
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

  // Inventory — stock the DMS files are allocated against. Refreshed after every upload
  // and after each download (a download consumes stock), so the banner stays truthful.
  const [inventory, setInventory] = useState(null);
  const [invOpen, setInvOpen] = useState(false);
  const [invFile, setInvFile] = useState(null);
  const [invUploading, setInvUploading] = useState(false);
  const invInputRef = useRef(null);

  const loadInventory = useCallback(async () => {
    try {
      const data = await getDmsInventory();
      if (data.success) setInventory(data.inventory);
    } catch (e) {
      setInventory(null);
    }
  }, []);

  useEffect(() => {
    loadInventory();
  }, [loadInventory]);

  const submitInventory = async () => {
    if (!invFile) return;
    setInvUploading(true);
    try {
      const data = await uploadDmsInventory(invFile);
      if (data.success) {
        setInventory(data.inventory);
        notify(
          `Inventory updated — ${data.parts_in_sheet} part${data.parts_in_sheet === 1 ? '' : 's'} in the sheet ` +
            `(${data.inserted} new, ${data.updated} updated` +
            (data.zeroed_not_in_sheet ? `, ${data.zeroed_not_in_sheet} set to 0 as they were not listed` : '') +
            ')'
        );
        setInvOpen(false);
        setInvFile(null);
        if (invInputRef.current) invInputRef.current.value = '';
      } else {
        notify(data.msg || 'Could not upload inventory.', 'error');
      }
    } catch (e) {
      notify(e?.response?.data?.msg || 'Could not upload inventory.', 'error');
    } finally {
      setInvUploading(false);
    }
  };

  // Add-order dialog — raise an order by hand from a parts sheet, for parts that came
  // in outside the app. It becomes an ordinary order in this same list.
  const BLANK_ORDER = { companyId: '', dealerId: '', warehouseId: '', notes: '', expectedDate: '' };
  const [addOpen, setAddOpen] = useState(false);
  const [newOrder, setNewOrder] = useState(BLANK_ORDER);
  const [newFile, setNewFile] = useState(null);
  const [creating, setCreating] = useState(false);
  const [dealers, setDealers] = useState([]);
  const [dealersLoading, setDealersLoading] = useState(false);
  const fileInputRef = useRef(null);

  const openAdd = () => {
    // Carry the filters in as defaults — the operator has usually already narrowed to
    // the company and warehouse they're working in.
    setNewOrder({
      ...BLANK_ORDER,
      companyId: companyFilter !== 'all' ? companyFilter : companies.length === 1 ? companies[0].id : '',
      warehouseId: warehouseFilter !== 'all' ? warehouseFilter : ''
    });
    setNewFile(null);
    setAddOpen(true);
  };

  // Dealers depend on the chosen company, so they're loaded per selection rather than
  // once — picking a different company must not leave the other company's dealers.
  useEffect(() => {
    if (!addOpen || !newOrder.companyId) {
      setDealers([]);
      return;
    }
    let cancelled = false;
    setDealersLoading(true);
    getOrderDealers(newOrder.companyId)
      .then((data) => {
        if (!cancelled) setDealers(data.success ? data.dealers || [] : []);
      })
      .catch(() => {
        if (!cancelled) setDealers([]);
      })
      .finally(() => {
        if (!cancelled) setDealersLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [addOpen, newOrder.companyId]);

  const canCreate = !!newFile && !!newOrder.companyId && !!newOrder.dealerId && !creating;

  const submitNewOrder = async () => {
    if (!canCreate) return;
    setCreating(true);
    try {
      const data = await createManualOrder({
        file: newFile,
        dealerId: newOrder.dealerId,
        companyId: newOrder.companyId,
        warehouseId: newOrder.warehouseId,
        notes: newOrder.notes,
        expectedDate: newOrder.expectedDate
      });
      if (data.success) {
        notify(
          `${data.order_number} created with ${data.item_count} part${data.item_count === 1 ? '' : 's'}` +
            (data.dms_available ? ' — ready to download' : ' — DMS layout for this company is not configured yet'),
          data.dms_available ? 'success' : 'warning'
        );
        setAddOpen(false);
        setNewFile(null);
        if (fileInputRef.current) fileInputRef.current.value = '';
        await fetchOrders();
      } else {
        notify(data.msg || 'Could not create the order.', 'error');
      }
    } catch (e) {
      notify(e?.response?.data?.msg || 'Could not create the order.', 'error');
    } finally {
      setCreating(false);
    }
  };

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
        const { blob, filename, shortfallCount, shortfallSummary } = await downloadDmsFile(order.order_id);
        saveBlob(blob, filename);
        if (shortfallCount > 0) {
          // Short supply is not an error, but it must not pass silently — the file asks
          // for less than the dealer ordered.
          notify(
            `Downloaded ${filename} — ${shortfallCount} part${shortfallCount === 1 ? '' : 's'} ` +
              `short-supplied from stock: ${shortfallSummary}`,
            'warning'
          );
        } else {
          notify(`Downloaded ${filename} — order marked Done`);
        }
        await Promise.all([fetchOrders(), loadInventory()]);
      } catch (e) {
        const msg = await readBlobError(e);
        notify(msg || 'Could not generate the DMS file.', 'error');
        // A refusal is usually stale stock; refresh so the banner explains why.
        await loadInventory();
      } finally {
        setBusyId(null);
      }
    },
    [fetchOrders, loadInventory]
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
          title={
            <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ width: '100%' }}>
              <span>{`Submitted Orders${filteredOrders.length ? ` (${filteredOrders.length})` : ''}`}</span>
              <Stack direction="row" spacing={1}>
                {/* Stock the DMS files are allocated against. Same operator as the
                    download, so it lives on the same screen. */}
                <Button
                  size="small"
                  variant="outlined"
                  startIcon={<IconBuildingWarehouse size={16} />}
                  onClick={() => {
                    setInvFile(null);
                    setInvOpen(true);
                  }}
                >
                  Upload Inventory
                </Button>
                {/* Parts that arrived outside the app (phone/WhatsApp) get an order raised
                    here, so they join this same list instead of needing a separate flow. */}
                <Button size="small" variant="contained" startIcon={<IconPlus size={16} />} onClick={openAdd}>
                  Add Order
                </Button>
              </Stack>
            </Stack>
          }
          content={false}
        >
          {/* Downloads are refused when stock is stale, so the state of it is shown here
              rather than discovered by clicking Download and getting an error. */}
          {inventory && (
            <Box sx={{ px: 2, pt: 2 }}>
              <Alert
                severity={inventory.fresh ? 'success' : 'warning'}
                action={
                  <Button
                    color="inherit"
                    size="small"
                    onClick={() => {
                      setInvFile(null);
                      setInvOpen(true);
                    }}
                  >
                    {inventory.last_uploaded_at ? 'Re-upload' : 'Upload'}
                  </Button>
                }
              >
                {inventory.last_uploaded_at
                  ? `Inventory: ${inventory.parts} parts, ${inventory.units} units — updated ${
                      inventory.age_minutes === 0 ? 'just now' : `${inventory.age_minutes} min ago`
                    }.${
                      inventory.fresh
                        ? ''
                        : ` Older than ${inventory.freshness_minutes} min, so DMS downloads are blocked until you re-upload.`
                    }`
                  : `No inventory uploaded yet — DMS downloads are blocked until stock is uploaded.`}
              </Alert>
            </Box>
          )}
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
                      <TableCell sx={{ width: 48 }} />
                      <TableCell>Order #</TableCell>
                      <TableCell>Dealer</TableCell>
                      <TableCell>Submitted by</TableCell>
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
                      <TableRow
                        key={o.order_id}
                        hover
                        sx={{ cursor: 'pointer' }}
                        onClick={() => setDetailOrder(o)}
                      >
                        <TableCell sx={{ width: 48 }}>
                          {/* Affordance only — the whole row opens the items modal. */}
                          <IconChevronRight size={18} style={{ color: '#9e9e9e' }} />
                        </TableCell>
                        <TableCell>{o.order_number || `#${o.order_id}`}</TableCell>
                        <TableCell>{o.dealer_name}</TableCell>
                        {/* Who raised it in the app. Not the dealer's assigned executive —
                            that can be a different person from whoever actually placed it. */}
                        <TableCell>{o.sales_executive_name || '—'}</TableCell>
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
                              onClick={(e) => { e.stopPropagation(); openPhoto(o); }}
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
                                onClick={(e) => { e.stopPropagation(); handleDownload(o); }}
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
                              onClick={(e) => {
                                e.stopPropagation();
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

      {/* Order line items — opened by clicking a row. Replaces the inline expander so
          several orders aren't unrolled into a wall of items at once. */}
      <Dialog
        open={Boolean(detailOrder)}
        onClose={() => setDetailOrder(null)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span>
            {detailOrder && (detailOrder.order_number || `#${detailOrder.order_id}`)}
            {detailOrder && detailOrder.dealer_name ? ` · ${detailOrder.dealer_name}` : ''}
          </span>
          <IconButton size="small" onClick={() => setDetailOrder(null)} aria-label="Close">
            <IconX size={18} />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers sx={{ p: 0 }}>
          {detailOrder && <SubmittedOrderItems orderId={detailOrder.order_id} />}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDetailOrder(null)}>Close</Button>
        </DialogActions>
      </Dialog>

      {/* Upload Inventory — a full stock snapshot (PART# | QTY). Deliberately spells out
          that omitted parts go to 0, because that is the surprising part of a snapshot. */}
      <Dialog open={invOpen} onClose={() => !invUploading && setInvOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Upload Inventory</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
            Upload the DMS stock export as-is (the <code>output - ….csv</code> file), or any sheet
            with the part number in the <strong>first column</strong> and a{' '}
            <strong>Stock on Hand</strong> quantity column. Excel and CSV both work.
          </Typography>
          <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
            This replaces the current stock figures — a part that is <strong>not</strong> listed in
            the file is set to 0, so upload your full stock each time, not just the changes.
          </Typography>
          <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
            DMS downloads allocate against these figures: if an order asks for more than is in
            stock, the file is generated for what is available. Downloads are blocked once the
            figures are more than {inventory?.freshness_minutes ?? 30} minutes old.
          </Typography>
          <Stack direction="row" spacing={2} alignItems="center">
            <Button variant="outlined" startIcon={<IconUpload size={16} />} onClick={() => invInputRef.current?.click()}>
              {invFile ? 'Change file' : 'Choose stock file'}
            </Button>
            <Typography variant="body2" color={invFile ? 'textPrimary' : 'textSecondary'} noWrap>
              {invFile ? invFile.name : 'No file chosen'}
            </Typography>
            <input
              ref={invInputRef}
              type="file"
              hidden
              // The DMS export is a .csv (tab-separated, UTF-16) — it was rejected by the
              // picker while this listed only the Excel extensions.
              accept=".csv,.txt,.tsv,.xlsx,.xlsm,.xls"
              onChange={(e) => setInvFile(e.target.files?.[0] || null)}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setInvOpen(false)} disabled={invUploading}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={submitInventory}
            disabled={!invFile || invUploading}
            startIcon={invUploading ? <CircularProgress size={16} color="inherit" /> : <IconUpload size={16} />}
          >
            Upload
          </Button>
        </DialogActions>
      </Dialog>

      {/* Add Order — order details plus the parts sheet. The sheet is the same layout the
          part convertor uses (PART# | QTY | DESC. | MRP), and the order is created ready
          for DMS download, so it appears in the list above straight away. */}
      <Dialog open={addOpen} onClose={() => !creating && setAddOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Add Order</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
            For parts that came in outside the app. Attach the parts sheet
            (PART# and QTY required; DESC. and MRP optional) — the order is created ready for
            DMS download and appears in the list above.
          </Typography>
          <Grid container spacing={2}>
            <Grid item xs={12} sm={6}>
              <FormControl fullWidth size="small" required>
                <InputLabel>Company</InputLabel>
                <Select
                  value={newOrder.companyId}
                  label="Company"
                  onChange={(e) =>
                    // Changing company invalidates the chosen dealer — it may not belong
                    // to the new one, and the backend would reject the pairing.
                    setNewOrder((o) => ({ ...o, companyId: e.target.value, dealerId: '' }))
                  }
                >
                  {companies.map((c) => (
                    <MenuItem key={c.id} value={c.id}>
                      {c.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} sm={6}>
              <FormControl fullWidth size="small" required disabled={!newOrder.companyId || dealersLoading}>
                <InputLabel>Dealer</InputLabel>
                <Select
                  value={newOrder.dealerId}
                  label="Dealer"
                  onChange={(e) => setNewOrder((o) => ({ ...o, dealerId: e.target.value }))}
                >
                  {dealers.map((d) => (
                    <MenuItem key={d.dealer_id} value={d.dealer_id}>
                      {d.name}
                      {d.dealer_code ? ` (${d.dealer_code})` : ''}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              {newOrder.companyId && !dealersLoading && dealers.length === 0 && (
                <Typography variant="caption" color="error">
                  No active dealers for this company.
                </Typography>
              )}
            </Grid>
            <Grid item xs={12} sm={6}>
              <FormControl fullWidth size="small">
                <InputLabel>Warehouse</InputLabel>
                <Select
                  value={newOrder.warehouseId}
                  label="Warehouse"
                  onChange={(e) => setNewOrder((o) => ({ ...o, warehouseId: e.target.value }))}
                >
                  <MenuItem value="">
                    <em>None</em>
                  </MenuItem>
                  {warehouses.map((w) => (
                    <MenuItem key={w.id} value={w.id}>
                      {w.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                size="small"
                type="date"
                label="Expected delivery"
                value={newOrder.expectedDate}
                onChange={(e) => setNewOrder((o) => ({ ...o, expectedDate: e.target.value }))}
                InputLabelProps={{ shrink: true }}
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                size="small"
                multiline
                minRows={2}
                label="Notes (optional)"
                value={newOrder.notes}
                onChange={(e) => setNewOrder((o) => ({ ...o, notes: e.target.value }))}
              />
            </Grid>
            <Grid item xs={12}>
              <Stack direction="row" spacing={2} alignItems="center">
                <Button variant="outlined" startIcon={<IconUpload size={16} />} onClick={() => fileInputRef.current?.click()}>
                  {newFile ? 'Change file' : 'Choose parts Excel'}
                </Button>
                <Typography variant="body2" color={newFile ? 'textPrimary' : 'textSecondary'} noWrap>
                  {newFile ? newFile.name : 'No file chosen'}
                </Typography>
                <input
                  ref={fileInputRef}
                  type="file"
                  hidden
                  accept=".xlsx,.xlsm,.xls"
                  onChange={(e) => setNewFile(e.target.files?.[0] || null)}
                />
              </Stack>
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddOpen(false)} disabled={creating}>
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={submitNewOrder}
            disabled={!canCreate}
            startIcon={creating ? <CircularProgress size={16} color="inherit" /> : <IconPlus size={16} />}
          >
            Create Order
          </Button>
        </DialogActions>
      </Dialog>

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
