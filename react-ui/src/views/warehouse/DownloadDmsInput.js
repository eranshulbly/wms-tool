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
  CircularProgress,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  IconButton,
  Snackbar,
  Alert,
  Tabs,
  Tab,
  Autocomplete
} from '@material-ui/core';
import {
  IconPhoto, IconX, IconPlus, IconUpload, IconChevronRight, IconDownload, IconBan
} from '@tabler/icons';
import SubmittedOrderItems from './components/SubmittedOrderItems';

import MainCard from '../../ui-component/cards/MainCard';
import { gridSpacing } from '../../store/constant';
import { useWarehouse } from '../../context/WarehouseContext';
import {
  getSubmittedOrders,
  fetchSubmittedOrderPhoto,
  getSubmittedOrderItems,
  rejectSubmittedOrder,
  createManualOrder,
  createCartOrder,
  getOrderDealers,
  getOrderProducts
} from '../../services/orderService';
import { dealerLabel } from '../../utils/dealerLabel';

// Push a blob at the browser as a download, then release the object URL.
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

// A CSV cell, quoted only when it needs to be — a comma, quote or newline in the value.
const csvCell = (v) => {
  const s = String(v ?? '');
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

// Submitted Orders — orders raised by hand here (Add Order, file or cart) or brought in
// from the app. Viewing, creating, downloading a plain product/quantity list, and
// rejecting; no DMS file generation or stock-upload step lives on this screen.

// The grid's column headers show the plain word a rep actually says ("Box", "Case")
// rather than the pack-specific code the catalogue stores ("30X10T").
const GENERIC_UOM_WORD = { STRIP: 'Strip', BOX: 'Box', CASE: 'Case', TAB: 'Tablet', UNIT: 'Unit' };
const uomWord = (code) => GENERIC_UOM_WORD[code] || (code ? code.charAt(0) + code.slice(1).toLowerCase() : '');

const DownloadDmsInput = () => {
  const { warehouses, companies } = useWarehouse();

  const [companyFilter, setCompanyFilter] = useState('all');
  const [warehouseFilter, setWarehouseFilter] = useState('all');
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

  // 'file' — the original parts-sheet upload. 'cart' — a grid: one row per product,
  // one column per unit (Strip/Box/Case) it can be ordered in, filled in directly.
  const [orderMode, setOrderMode] = useState('file');
  // [{ key, product, qtyByUom: { STRIP: '2', BOX: '', CASE: '1' } }] — a row per
  // product, however many of its units the operator actually filled in.
  const [cartRows, setCartRows] = useState([]);
  const [productOptions, setProductOptions] = useState([]);
  const [productSearch, setProductSearch] = useState('');
  const [productsLoading, setProductsLoading] = useState(false);

  const openAdd = () => {
    // Carry the filters in as defaults — the operator has usually already narrowed to
    // the company and warehouse they're working in.
    setNewOrder({
      ...BLANK_ORDER,
      companyId: companyFilter !== 'all' ? companyFilter : companies.length === 1 ? companies[0].id : '',
      warehouseId: warehouseFilter !== 'all' ? warehouseFilter : ''
    });
    setNewFile(null);
    setOrderMode('file');
    setCartRows([]);
    setProductSearch('');
    setAddOpen(true);
  };

  // Product options for the cart picker, reloaded as the operator types. Narrowed to
  // the chosen company — a product must be orderable against the company the order is
  // raised for, same as the dealer picker just above.
  useEffect(() => {
    if (!addOpen || orderMode !== 'cart' || !newOrder.companyId) {
      setProductOptions([]);
      return;
    }
    let cancelled = false;
    setProductsLoading(true);
    const t = setTimeout(() => {
      getOrderProducts(newOrder.companyId, productSearch)
        .then((data) => {
          if (!cancelled) setProductOptions(data.success ? data.products || [] : []);
        })
        .catch(() => {
          if (!cancelled) setProductOptions([]);
        })
        .finally(() => {
          if (!cancelled) setProductsLoading(false);
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [addOpen, orderMode, newOrder.companyId, productSearch]);

  // Picking a product adds its row to the grid straight away — there's nothing to
  // configure first, since every unit it has gets its own cell right there. Picking
  // one already in the cart is a no-op rather than a second row for the same product.
  const addProductRow = (product) => {
    if (!product) return;
    setCartRows((rows) =>
      rows.some((r) => r.product.product_id === product.product_id)
        ? rows
        : [...rows, { key: `${product.product_id}-${Date.now()}`, product, qtyByUom: {} }]
    );
    setProductSearch('');
  };

  const setRowQty = (key, uomCode, value) =>
    setCartRows((rows) => rows.map((r) => (r.key === key ? { ...r, qtyByUom: { ...r.qtyByUom, [uomCode]: value } } : r)));

  const removeCartRow = (key) => setCartRows((rows) => rows.filter((r) => r.key !== key));

  // Three fixed columns, not one per unit name. A product's own priced/stocked unit
  // varies (Strip for a tablet, Bottle for a syrup, Vial for an injectable) — showing
  // each as its own column meant a cart mixing product types grew a column per name.
  // "Qty" always means that row's own base unit, whatever it's actually called; Box
  // and Case are genuinely shared across the catalog, so they stay as themselves.
  const CART_SLOTS = [
    { header: 'Qty', match: (u) => u.is_stock_unit },
    { header: 'Box', match: (u) => u.uom_code === 'BOX' },
    { header: 'Case', match: (u) => u.uom_code === 'CASE' }
  ];

  // How many stock units (strips, usually) a row's filled-in cells come to — shown per
  // row so "2 Case + 6 Box" reads as a total before the order is even submitted.
  const rowPreview = (row) => {
    const stock = row.product.uoms.find((u) => u.is_stock_unit) || row.product.uoms[0];
    if (!stock || !stock.factor_to_base) return null;
    let total = 0;
    let any = false;
    row.product.uoms.forEach((u) => {
      const raw = row.qtyByUom[u.uom_code];
      if (raw && Number(raw) > 0) {
        any = true;
        total += (Number(raw) * u.factor_to_base) / stock.factor_to_base;
      }
    });
    if (!any) return null;
    const whole = Math.round(total);
    return { whole, exact: Math.abs(total - whole) < 0.001, word: uomWord(stock.uom_code) };
  };

  // Flattened to the same {productId, uom, quantity} shape the cart endpoint already
  // takes — it merges same-product entries itself, so a row with several filled-in
  // units becomes several array entries for one product, same as adding them one at a
  // time used to.
  const cartPayloadItems = useMemo(
    () =>
      cartRows.flatMap((row) =>
        Object.entries(row.qtyByUom)
          .filter(([, v]) => v && Number(v) > 0)
          .map(([uom, v]) => ({ productId: row.product.product_id, uom, quantity: Number(v) }))
      ),
    [cartRows]
  );

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

  const canCreate =
    !!newOrder.companyId &&
    !!newOrder.dealerId &&
    !creating &&
    (orderMode === 'file' ? !!newFile : cartPayloadItems.length > 0);

  const submitNewOrder = async () => {
    if (!canCreate) return;
    setCreating(true);
    try {
      const data =
        orderMode === 'file'
          ? await createManualOrder({
              file: newFile,
              dealerId: newOrder.dealerId,
              companyId: newOrder.companyId,
              warehouseId: newOrder.warehouseId,
              notes: newOrder.notes,
              expectedDate: newOrder.expectedDate
            })
          : await createCartOrder({
              items: cartPayloadItems,
              dealerId: newOrder.dealerId,
              companyId: newOrder.companyId,
              warehouseId: newOrder.warehouseId,
              notes: newOrder.notes,
              expectedDate: newOrder.expectedDate
            });
      if (data.success) {
        notify(`${data.order_number} created with ${data.item_count} part${data.item_count === 1 ? '' : 's'}`);
        setAddOpen(false);
        setNewFile(null);
        setCartRows([]);
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
  }, [warehouseFilter, companyFilter, dealerFilter]);

  const dealerOptions = useMemo(() => {
    const seen = new Map();
    orders.forEach((o) => {
      if (o.dealer_id != null && !seen.has(o.dealer_id)) {
        seen.set(o.dealer_id, dealerLabel(o.dealer_name, o.dealer_town) || `Dealer ${o.dealer_id}`);
      }
    });
    return Array.from(seen, ([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name));
  }, [orders]);

  const filteredOrders = useMemo(
    () => orders.filter((o) => dealerFilter === 'all' || o.dealer_id === dealerFilter),
    [orders, dealerFilter]
  );

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

  // A plain product/quantity list — Product, SKU, Quantity, Unit — not the company's
  // DMS layout, no stock allocation, nothing marked Done. Quantity/Unit is the same
  // pair the order-detail dialog shows: the true count in the product's own stock unit
  // (strips, bottles, vials…), not whatever pack it was ordered in.
  const handleDownload = useCallback(async (order) => {
    setBusyId(order.order_id);
    try {
      const data = await getSubmittedOrderItems(order.order_id);
      if (!data.success) {
        notify(data.msg || 'Could not load this order.', 'error');
        return;
      }
      const rows = [
        ['Product', 'SKU', 'Quantity', 'Unit'],
        ...(data.items || []).map((it) => [it.product_name, it.sku_code, it.quantity, it.uom || ''])
      ];
      const csv = rows.map((r) => r.map(csvCell).join(',')).join('\n');
      saveBlob(
        new Blob([csv], { type: 'text/csv;charset=utf-8;' }),
        `${(order.order_number || `order_${order.order_id}`)}_products.csv`
      );
    } catch (e) {
      notify(e?.response?.data?.msg || 'Could not download this order.', 'error');
    } finally {
      setBusyId(null);
    }
  }, []);

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
              {/* Parts that arrived outside the app (phone/WhatsApp) get an order raised
                  here, so they join this same list instead of needing a separate flow. */}
              <Button size="small" variant="contained" startIcon={<IconPlus size={16} />} onClick={openAdd}>
                Add Order
              </Button>
            </Stack>
          }
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
                {orders.length === 0 ? 'No orders yet.' : 'No orders match the filters.'}
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
                        <TableCell>{dealerLabel(o.dealer_name, o.dealer_town)}</TableCell>
                        {/* Who raised it in the app. Not the dealer's assigned executive —
                            that can be a different person from whoever actually placed it. */}
                        <TableCell>{o.sales_executive_name || '—'}</TableCell>
                        <TableCell>{o.company_name || '—'}</TableCell>
                        <TableCell>{o.warehouse_name || '—'}</TableCell>
                        <TableCell align="right">{o.item_count}</TableCell>
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
                            <Button
                              size="small"
                              variant="contained"
                              disabled={busyId === o.order_id}
                              startIcon={<IconDownload size={16} />}
                              onClick={(e) => { e.stopPropagation(); handleDownload(o); }}
                            >
                              Download
                            </Button>
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
            {detailOrder && detailOrder.dealer_name
              ? ` · ${dealerLabel(detailOrder.dealer_name, detailOrder.dealer_town)}`
              : ''}
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

      {/* Add Order — order details plus either a parts sheet or a hand-built cart. Either
          way the order is created and appears in the list above. */}
      <Dialog open={addOpen} onClose={() => !creating && setAddOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Add Order</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
            For orders that came in outside the app — a phone or WhatsApp order the rep never
            entered. Either attach the parts sheet it arrived as, or build it line by line from
            the catalogue below.
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
              <Autocomplete
                fullWidth
                size="small"
                options={dealers}
                value={dealers.find((d) => d.dealer_id === newOrder.dealerId) || null}
                onChange={(e, v) => setNewOrder((o) => ({ ...o, dealerId: v ? v.dealer_id : '' }))}
                getOptionLabel={(d) => dealerLabel(`${d.name}${d.dealer_code ? ` (${d.dealer_code})` : ''}`, d.town)}
                isOptionEqualToValue={(o, v) => o.dealer_id === v.dealer_id}
                // Matches name, code and town, so typing a town narrows a long dealer list
                // just as well as typing the name does.
                filterOptions={(opts, { inputValue }) => {
                  const t = inputValue.trim().toLowerCase();
                  if (!t) return opts;
                  return opts.filter((d) =>
                    `${d.name} ${d.dealer_code || ''} ${d.town || ''}`.toLowerCase().includes(t)
                  );
                }}
                renderOption={(props, d) => (
                  <li {...props} key={d.dealer_id}>
                    <Box>
                      <Typography variant="body2">
                        {d.name}
                        {d.dealer_code ? ` (${d.dealer_code})` : ''}
                      </Typography>
                      {d.town && (
                        <Typography variant="caption" color="textSecondary">
                          {d.town}
                        </Typography>
                      )}
                    </Box>
                  </li>
                )}
                loading={dealersLoading}
                disabled={!newOrder.companyId || dealersLoading}
                noOptionsText={newOrder.companyId ? 'No active dealers for this company' : 'Choose a company first'}
                renderInput={(params) => (
                  <TextField
                    {...params}
                    required
                    label="Dealer"
                    placeholder={newOrder.companyId ? 'Search by name or town' : ''}
                    InputProps={{
                      ...params.InputProps,
                      endAdornment: (
                        <>
                          {dealersLoading ? <CircularProgress size={16} /> : null}
                          {params.InputProps.endAdornment}
                        </>
                      )
                    }}
                  />
                )}
              />
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
              <Tabs
                value={orderMode}
                onChange={(e, v) => setOrderMode(v)}
                variant="fullWidth"
                sx={{ minHeight: 36, mb: 1, borderBottom: 1, borderColor: 'divider' }}
              >
                <Tab value="file" label="Upload Parts Excel" sx={{ minHeight: 36 }} />
                <Tab value="cart" label="Build From Catalogue" sx={{ minHeight: 36 }} />
              </Tabs>
            </Grid>

            {orderMode === 'file' ? (
              <Grid item xs={12}>
                <Typography variant="body2" color="textSecondary" sx={{ mb: 1 }}>
                  PART# and QTY required; DESC. and MRP optional.
                </Typography>
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
            ) : (
              <Grid item xs={12}>
                <Stack spacing={1.5}>
                  <Autocomplete
                    size="small"
                    options={productOptions.filter(
                      (p) => !cartRows.some((r) => r.product.product_id === p.product_id)
                    )}
                    // Selecting a product adds its row immediately — nothing else to
                    // configure first, so there's no value to hold onto afterwards.
                    value={null}
                    onChange={(e, v) => addProductRow(v)}
                    // inputValue is fully controlled (rather than left to MUI) so a
                    // selection reliably clears the box: addProductRow already sets
                    // productSearch back to '', and since the box shows exactly that
                    // value, it goes blank instead of settling on the picked label.
                    inputValue={productSearch}
                    onInputChange={(e, v, reason) => {
                      if (reason === 'input') setProductSearch(v);
                    }}
                    getOptionLabel={(o) => (o ? `${o.name}${o.sku_code ? ` (${o.sku_code})` : ''}` : '')}
                    isOptionEqualToValue={(o, v) => o.product_id === v.product_id}
                    loading={productsLoading}
                    disabled={!newOrder.companyId}
                    noOptionsText={newOrder.companyId ? 'No matching products' : 'Choose a company first'}
                    renderInput={(params) => (
                      <TextField
                        {...params}
                        label="Add a product"
                        placeholder={newOrder.companyId ? 'Search by name or SKU' : ''}
                        InputProps={{
                          ...params.InputProps,
                          endAdornment: (
                            <>
                              {productsLoading ? <CircularProgress size={16} /> : null}
                              {params.InputProps.endAdornment}
                            </>
                          )
                        }}
                      />
                    )}
                  />

                  {cartRows.length > 0 ? (
                    <TableContainer component={Paper} variant="outlined">
                      <Table size="small">
                        <TableHead>
                          <TableRow>
                            <TableCell>Product</TableCell>
                            {CART_SLOTS.map((slot) => (
                              <TableCell key={slot.header} align="center">
                                {slot.header}
                              </TableCell>
                            ))}
                            <TableCell align="right">Total</TableCell>
                            <TableCell sx={{ width: 40 }} />
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {cartRows.map((row) => {
                            const preview = rowPreview(row);
                            return (
                              <TableRow key={row.key}>
                                <TableCell>
                                  {row.product.name}
                                  {row.product.sku_code ? (
                                    <Typography variant="caption" color="textSecondary" display="block">
                                      {row.product.sku_code}
                                    </Typography>
                                  ) : null}
                                </TableCell>
                                {CART_SLOTS.map((slot) => {
                                  const uomEntry = row.product.uoms.find(slot.match);
                                  return (
                                    <TableCell key={slot.header} align="center">
                                      {uomEntry ? (
                                        <Box>
                                          <TextField
                                            variant="standard"
                                            type="number"
                                            value={row.qtyByUom[uomEntry.uom_code] || ''}
                                            onChange={(e) => setRowQty(row.key, uomEntry.uom_code, e.target.value)}
                                            inputProps={{ min: 0, step: 1, style: { textAlign: 'center', width: 48 } }}
                                          />
                                          {/* Qty's real unit varies by product (Strip, Bottle,
                                              Vial…) — named small here since the header can't
                                              say it for every row at once. */}
                                          {slot.header === 'Qty' && (
                                            <Typography variant="caption" color="textSecondary" display="block">
                                              {uomWord(uomEntry.uom_code)}
                                            </Typography>
                                          )}
                                        </Box>
                                      ) : (
                                        <Typography variant="body2" color="textSecondary">
                                          —
                                        </Typography>
                                      )}
                                    </TableCell>
                                  );
                                })}
                                <TableCell align="right">
                                  {preview ? (
                                    <Typography
                                      variant="body2"
                                      color={preview.exact ? 'textPrimary' : 'error'}
                                      noWrap
                                    >
                                      {preview.exact
                                        ? `${preview.whole} ${preview.word}${preview.whole === 1 ? '' : 's'}`
                                        : 'uneven qty'}
                                    </Typography>
                                  ) : (
                                    <Typography variant="body2" color="textSecondary">
                                      —
                                    </Typography>
                                  )}
                                </TableCell>
                                <TableCell>
                                  <IconButton size="small" onClick={() => removeCartRow(row.key)} aria-label="Remove">
                                    <IconX size={16} />
                                  </IconButton>
                                </TableCell>
                              </TableRow>
                            );
                          })}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  ) : (
                    <Typography variant="body2" color="textSecondary">
                      No products added yet — search above to add a row, then fill in whichever
                      units it's being ordered in (Case and Box, plus whatever that product is
                      priced in — Strip, Bottle, Vial, Tube… — any or all of them).
                    </Typography>
                  )}
                </Stack>
              </Grid>
            )}
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
            The order returns to Submitted Orders and its parts are cleared. This note is shown
            to whoever re-submits it.
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
