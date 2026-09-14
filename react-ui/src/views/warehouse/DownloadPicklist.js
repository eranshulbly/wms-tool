// Download Picklist — pick lists for orders that are open and ready to be picked.
//
// The list shows only Open orders, because that is the only status a picklist means
// anything in: an order before it has not been accepted, and one after it has already
// been picked. Selecting several downloads a zip of one PDF per order, so a sheet can be
// handed to a picker or filed on its own.

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  CircularProgress,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Snackbar,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography
} from '@material-ui/core';
import { IconFileDownload, IconRefresh } from '@tabler/icons';

import MainCard from '../../ui-component/cards/MainCard';
import { useWarehouse } from '../../context/WarehouseContext';
import { getPicklistOptions, downloadPicklists, readBlobError } from '../../services/orderService';

const formatDate = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('en-IN', { dateStyle: 'medium' });
};

const DownloadPicklist = () => {
  const { warehouses, companies } = useWarehouse();

  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState([]);
  const [downloading, setDownloading] = useState(false);
  const [warehouseFilter, setWarehouseFilter] = useState('all');
  const [companyFilter, setCompanyFilter] = useState('all');
  const [snackbar, setSnackbar] = useState({ open: false, message: '', severity: 'success' });

  const notify = (message, severity = 'success') => setSnackbar({ open: true, message, severity });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getPicklistOptions(warehouseFilter, companyFilter);
      if (data.success) {
        setOrders(data.orders || []);
        // Anything no longer open must drop out of the selection, or the download would
        // ask for orders the server will refuse and the count shown would be a lie.
        const live = new Set((data.orders || []).map((o) => o.potential_order_id));
        setSelected((prev) => prev.filter((id) => live.has(id)));
      } else {
        setError(data.msg || 'Could not load orders.');
      }
    } catch (e) {
      setError(e?.response?.data?.msg || 'Could not load orders.');
    } finally {
      setLoading(false);
    }
  }, [warehouseFilter, companyFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const allSelected = orders.length > 0 && selected.length === orders.length;
  const someSelected = selected.length > 0 && !allSelected;

  const toggleAll = () => setSelected(allSelected ? [] : orders.map((o) => o.potential_order_id));

  const toggleOne = (id) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const totalLines = useMemo(
    () =>
      orders
        .filter((o) => selected.includes(o.potential_order_id))
        .reduce((sum, o) => sum + (o.line_count || 0), 0),
    [orders, selected]
  );

  const download = async () => {
    if (!selected.length) return;
    setDownloading(true);
    try {
      const { blob, filename } = await downloadPicklists(selected, companyFilter);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      notify(
        `Downloaded ${selected.length} picklist${selected.length === 1 ? '' : 's'} (${filename})`
      );
    } catch (e) {
      // The error body is a Blob here, because the request asked for one.
      const msg = await readBlobError(e);
      notify(msg || 'Could not generate the picklist.', 'error');
    } finally {
      setDownloading(false);
    }
  };

  return (
    <MainCard title="Download Picklist">
      <Grid container spacing={2}>
        <Grid item xs={12}>
          <Typography variant="body2" color="textSecondary">
            Pick lists for orders that are open and ready to pick. Quantities print in the unit the
            order was placed in, with the number of full cases beside them. Select several orders to
            download a zip containing one PDF each.
          </Typography>
        </Grid>

        <Grid item xs={12}>
          <Card variant="outlined">
            <CardContent>
              <Grid container spacing={2} alignItems="center">
                {companies?.length > 1 && (
                  <Grid item xs={12} sm={3}>
                    <FormControl fullWidth size="small">
                      <InputLabel>Company</InputLabel>
                      <Select
                        value={companyFilter}
                        label="Company"
                        onChange={(e) => setCompanyFilter(e.target.value)}
                      >
                        <MenuItem value="all">All companies</MenuItem>
                        {companies.map((c) => (
                          <MenuItem key={c.id} value={c.id}>
                            {c.name}
                          </MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </Grid>
                )}
                {warehouses?.length > 1 && (
                  <Grid item xs={12} sm={3}>
                    <FormControl fullWidth size="small">
                      <InputLabel>Warehouse</InputLabel>
                      <Select
                        value={warehouseFilter}
                        label="Warehouse"
                        onChange={(e) => setWarehouseFilter(e.target.value)}
                      >
                        <MenuItem value="all">All warehouses</MenuItem>
                        {warehouses.map((w) => (
                          <MenuItem key={w.id} value={w.id}>
                            {w.name}
                          </MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </Grid>
                )}
                <Grid item xs>
                  <Box display="flex" gap={1} justifyContent="flex-end">
                    <Button
                      variant="outlined"
                      startIcon={<IconRefresh size={18} />}
                      onClick={load}
                      disabled={loading}
                    >
                      Refresh
                    </Button>
                    <Button
                      variant="contained"
                      color="primary"
                      startIcon={
                        downloading ? <CircularProgress size={16} color="inherit" /> : <IconFileDownload size={18} />
                      }
                      onClick={download}
                      disabled={!selected.length || downloading}
                    >
                      {downloading
                        ? 'Preparing…'
                        : selected.length
                        ? `Download ${selected.length} picklist${selected.length === 1 ? '' : 's'}`
                        : 'Download picklist'}
                    </Button>
                  </Box>
                </Grid>
              </Grid>
            </CardContent>
          </Card>
        </Grid>

        {selected.length > 0 && (
          <Grid item xs={12}>
            <Alert severity="info">
              {selected.length} order{selected.length === 1 ? '' : 's'} selected — {totalLines} line
              {totalLines === 1 ? '' : 's'} to pick.
            </Alert>
          </Grid>
        )}

        {error && (
          <Grid item xs={12}>
            <Alert severity="error">{error}</Alert>
          </Grid>
        )}

        <Grid item xs={12}>
          {loading ? (
            <Box display="flex" justifyContent="center" py={5}>
              <CircularProgress />
            </Box>
          ) : orders.length === 0 ? (
            <Alert severity="info">
              No orders are open for picking. An order becomes available here once it has been
              uploaded and is in Open status.
            </Alert>
          ) : (
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell padding="checkbox">
                      <Checkbox
                        checked={allSelected}
                        indeterminate={someSelected}
                        onChange={toggleAll}
                      />
                    </TableCell>
                    <TableCell>Order No</TableCell>
                    <TableCell>Dealer</TableCell>
                    <TableCell>City</TableCell>
                    <TableCell>Order Date</TableCell>
                    <TableCell align="right">Lines</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {orders.map((o) => (
                    <TableRow
                      key={o.potential_order_id}
                      hover
                      selected={selected.includes(o.potential_order_id)}
                      onClick={() => toggleOne(o.potential_order_id)}
                      style={{ cursor: 'pointer' }}
                    >
                      <TableCell padding="checkbox">
                        <Checkbox checked={selected.includes(o.potential_order_id)} />
                      </TableCell>
                      <TableCell>{o.order_number}</TableCell>
                      <TableCell>{o.dealer_name || '—'}</TableCell>
                      <TableCell>{o.town || '—'}</TableCell>
                      <TableCell>{formatDate(o.order_date)}</TableCell>
                      <TableCell align="right">{o.line_count}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Grid>
      </Grid>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
          severity={snackbar.severity}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>
    </MainCard>
  );
};

export default DownloadPicklist;
