import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Autocomplete,
  Box,
  Button,
  Chip,
  Typography,
  CircularProgress,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TableSortLabel,
  Paper,
  Grid,
  MenuItem,
  TextField,
  Tooltip,
  Snackbar,
  Alert,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconRefresh, IconDownload } from '@tabler/icons';
import api from '../../../services/api';
import { useWarehouse } from '../../../context/WarehouseContext';

const BASE = 'admin/inventory/analytics/movement';

const WINDOWS = [
  { value: 30, label: 'Last 30 days' },
  { value: 60, label: 'Last 60 days' },
  { value: 90, label: 'Last 90 days' },
  { value: 180, label: 'Last 6 months' },
  { value: 365, label: 'Last 12 months' },
];

// The bands, worst first. Colour carries the same ordering as the list, so the table
// reads as a heat map without anyone having to consult the legend.
const BAND_STYLE = {
  Expired: { bg: '#7f1d1d', fg: '#fff' },
  'Will expire unsold': { bg: '#fecaca', fg: '#7f1d1d' },
  'Over 12 months cover': { bg: '#fed7aa', fg: '#7c2d12' },
  '4-12 months cover': { bg: '#fef3c7', fg: '#78350f' },
  '2-4 months cover': { bg: '#ecfccb', fg: '#3f6212' },
  '1-2 months cover': { bg: '#d1fae5', fg: '#065f46' },
  'Under 30 days cover': { bg: '#dbeafe', fg: '#1e3a8a' },
  'Nil stock': { bg: '#e5e7eb', fg: '#374151' },
  'No sale data': { bg: '#f3f4f6', fg: '#6b7280' },
};

// One definition per column drives the header, the sort, the cell and the CSV export, so
// a column cannot be exported on a different value from the one it displays.
const COLUMNS = [
  { key: 'product_name', label: 'Product', type: 'text' },
  { key: 'pack', label: 'Pack', type: 'text' },
  { key: 'stock_units', label: 'Stock (units)', type: 'qty' },
  { key: 'sale_rate_month', label: 'Sale rate (units/month)', type: 'qty1' },
  { key: 'months_cover', label: 'Months of cover', type: 'num2' },
  { key: 'first_expiry', label: 'Batch expiry', type: 'monthyear' },
  { key: 'months_to_expiry', label: 'Months to expiry', type: 'num2' },
  { key: 'rate_to_clear', label: 'Rate needed to clear', type: 'qty' },
  { key: 'stock_value', label: 'Stock value', type: 'money' },
  { key: 'units_at_risk', label: 'Units at risk', type: 'qty' },
  { key: 'value_at_risk', label: 'Value at risk', type: 'money' },
  { key: 'band', label: 'Push band', type: 'band' },
];

const useStyles = makeStyles((theme) => ({
  section: { marginBottom: theme.spacing(2) },
  num: { whiteSpace: 'nowrap' },
  muted: { color: '#7a869a' },
  head: {
    whiteSpace: 'normal',
    fontWeight: 600,
    verticalAlign: 'bottom',
    position: 'sticky',
    top: 0,
    zIndex: 3,
    background: '#fff',
    minWidth: 78,
  },
  scroll: { maxHeight: '62vh' },
  tile: { padding: 12, height: '100%' },
  tileValue: { fontWeight: 600, lineHeight: 1.2 },
}));

const nf0 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const MONTH_YEAR = (iso) => {
  if (!iso) return '—';
  const [y, m] = String(iso).split('-');
  return `${Number(m)}/${String(y).slice(2)}`;
};

const render = (type, v) => {
  if (v === null || v === undefined || v === '') return '—';
  if (type === 'qty') return nf0.format(Number(v));
  if (type === 'qty1') return nf1.format(Number(v));
  if (type === 'num2') return nf2.format(Number(v));
  if (type === 'money') return `₹${nf0.format(Number(v))}`;
  if (type === 'monthyear') return MONTH_YEAR(v);
  return String(v);
};

const isNumeric = (t) => t === 'qty' || t === 'qty1' || t === 'num2' || t === 'money';

const money = (v) => `₹${nf0.format(Number(v || 0))}`;

const StockMovement = () => {
  const classes = useStyles();
  const { companies, selectedCompany, setSelectedCompany } = useWarehouse();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [windowDays, setWindowDays] = useState(90);
  const [picked, setPicked] = useState([]);
  const [band, setBand] = useState('');
  const [sort, setSort] = useState({ key: 'value_at_risk', dir: 'desc' });
  const [toast, setToast] = useState(null);

  const load = useCallback(async () => {
    if (!selectedCompany) {
      setData(null);
      return;
    }
    setLoading(true);
    try {
      const { data: d } = await api.get(BASE, {
        params: { company_id: selectedCompany, window_days: windowDays },
      });
      setData(d);
    } catch (e) {
      setToast({ severity: 'error', msg: 'Could not load the stock movement report' });
    } finally {
      setLoading(false);
    }
  }, [selectedCompany, windowDays]);

  useEffect(() => {
    load();
  }, [load]);

  const rows = useMemo(() => data?.rows || [], [data]);

  // The dropdown's options are the products in the report, not the whole catalogue —
  // picking something the report has no row for would only ever empty the table.
  const options = useMemo(
    () =>
      rows
        .map((r) => ({
          label: r.product_name,
          sku: r.sku_code || '',
          pack: r.pack || '',
          category: r.category || '',
        }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [rows]
  );

  const visible = useMemo(() => {
    // A picked option carries its exact name; a typed term stays a plain string. Both
    // are matched the same way, so typing "ROSUBEST" still pulls every variant while
    // choosing one from the list narrows to it.
    const terms = picked
      .map((p) => (typeof p === 'string' ? p : p.label))
      .map((t) => t.trim().toLowerCase())
      .filter(Boolean);
    let out = rows;
    if (band) out = out.filter((r) => r.band === band);
    if (terms.length) {
      out = out.filter((r) => {
        const hay = [r.product_name, r.sku_code, r.pack, r.category]
          .filter(Boolean)
          .join(' ')
          .toLowerCase();
        return terms.some((t) => hay.includes(t));
      });
    }
    // Nulls always sort last, in either direction: a missing figure is not a small one,
    // and letting it float to the top would bury the rows the sort was asked for.
    const { key, dir } = sort;
    const sign = dir === 'asc' ? 1 : -1;
    return [...out].sort((a, b) => {
      const x = a[key];
      const y = b[key];
      if (x === null || x === undefined) return y === null || y === undefined ? 0 : 1;
      if (y === null || y === undefined) return -1;
      if (typeof x === 'number' && typeof y === 'number') return (x - y) * sign;
      return String(x).localeCompare(String(y)) * sign;
    });
  }, [rows, picked, band, sort]);

  const toggleSort = (key) =>
    setSort((s) => ({ key, dir: s.key === key && s.dir === 'desc' ? 'asc' : 'desc' }));

  const exportCsv = () => {
    const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const csv = [
      ['SKU code', ...COLUMNS.map((c) => c.label)].map(esc).join(','),
      ...visible.map((r) => [r.sku_code, ...COLUMNS.map((c) => r[c.key])].map(esc).join(',')),
    ].join('\n');
    const company = companies.find((c) => c.id === selectedCompany);
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(company?.name || 'stock').replace(/\s+/g, '_')}_Stock_Movement.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const s = data?.summary;
  const tiles = s
    ? [
        { label: 'Products', value: nf0.format(s.products), hint: 'Holding stock, or moved in the period.' },
        { label: 'Stock value', value: money(s.stock_value), hint: 'On hand, at landed cost.' },
        {
          label: 'Value at risk',
          value: money(s.value_at_risk),
          hint: 'Stock that will not clear before its earliest batch expires, at the current rate.',
          color: s.value_at_risk > 0 ? '#b91c1c' : undefined,
        },
        {
          label: 'Expiring unsold',
          value: nf0.format(s.at_risk_products),
          hint: 'Products whose cover runs past their expiry.',
          color: s.at_risk_products > 0 ? '#b91c1c' : undefined,
        },
        {
          label: 'Under 30 days cover',
          value: nf0.format(s.stockout_products),
          hint: 'Products that will run out within the month at the current rate.',
        },
        {
          label: 'No sale history',
          value: money(s.unmeasured_value),
          hint: `${s.no_sale_products} product(s) have never shipped, so no rate can be measured. Not counted in value at risk.`,
        },
      ]
    : [];

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Stock Movement
      </Typography>
      <Typography variant="body2" className={classes.muted} sx={{ mb: 2 }}>
        What is selling, how long the stock on hand will last, and what will expire before it
        clears. Sales are counted from stock actually dispatched, not from orders raised.
      </Typography>

      <Paper variant="outlined" className={classes.section} style={{ padding: 12 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} sm={3}>
            <TextField
              select
              fullWidth
              size="small"
              label="Company"
              value={selectedCompany || ''}
              onChange={(e) => setSelectedCompany(e.target.value)}
            >
              {companies.map((c) => (
                <MenuItem key={c.id} value={c.id}>
                  {c.name}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid item xs={12} sm={3}>
            <TextField
              select
              fullWidth
              size="small"
              label="Sale rate measured over"
              value={windowDays}
              onChange={(e) => setWindowDays(Number(e.target.value))}
            >
              {WINDOWS.map((w) => (
                <MenuItem key={w.value} value={w.value}>
                  {w.label}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid item xs={12} sm={3}>
            {/* freeSolo on purpose: picking products off the list is the common case, but
                a typed term still works as a search, so "ROSUBEST" can pull every variant
                without hunting each one down in the dropdown. */}
            <Autocomplete
              multiple
              freeSolo
              size="small"
              options={options}
              value={picked}
              onChange={(e, v) => setPicked(v)}
              filterSelectedOptions
              getOptionLabel={(o) => (typeof o === 'string' ? o : o.label)}
              isOptionEqualToValue={(o, v) =>
                (typeof o === 'string' ? o : o.label) === (typeof v === 'string' ? v : v.label)
              }
              // Match the code and category too, so a part number finds its product.
              filterOptions={(opts, { inputValue }) => {
                const t = inputValue.trim().toLowerCase();
                if (!t) return opts.slice(0, 100);
                return opts
                  .filter((o) =>
                    `${o.label} ${o.sku} ${o.pack} ${o.category}`.toLowerCase().includes(t)
                  )
                  .slice(0, 100);
              }}
              renderOption={(props, o) => (
                <li {...props} key={o.label}>
                  <Box>
                    <Typography variant="body2">{o.label}</Typography>
                    <Typography variant="caption" className={classes.muted}>
                      {[o.sku, o.pack, o.category].filter(Boolean).join(' · ')}
                    </Typography>
                  </Box>
                </li>
              )}
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Search product"
                  placeholder={picked.length ? '' : 'Type or pick'}
                />
              )}
            />
          </Grid>
          <Grid item xs={12} sm={3}>
            <Box display="flex" alignItems="center" justifyContent="flex-end">
              <Button
                size="small"
                variant="outlined"
                startIcon={<IconDownload size={16} />}
                onClick={exportCsv}
                disabled={!visible.length}
                style={{ marginRight: 8 }}
              >
                Export CSV
              </Button>
              <Button
                size="small"
                variant="outlined"
                startIcon={<IconRefresh size={16} />}
                onClick={load}
                disabled={loading}
              >
                Refresh
              </Button>
            </Box>
          </Grid>
        </Grid>
      </Paper>

      {s && (
        <Grid container spacing={2} className={classes.section}>
          {tiles.map((t) => (
            <Grid item xs={6} sm={4} md={2} key={t.label}>
              <Tooltip title={t.hint}>
                <Paper variant="outlined" className={classes.tile}>
                  <Typography variant="body2" className={classes.muted}>
                    {t.label}
                  </Typography>
                  <Typography variant="h4" className={classes.tileValue} style={{ color: t.color }}>
                    {t.value}
                  </Typography>
                </Paper>
              </Tooltip>
            </Grid>
          ))}
        </Grid>
      )}

      {/* The legend doubles as the filter — the bands are the report's main way of
          slicing the list, so clicking one is more direct than a dropdown. */}
      {s && (
        <Box className={classes.section} display="flex" flexWrap="wrap" gap={1}>
          <Chip
            size="small"
            label={`All (${rows.length})`}
            onClick={() => setBand('')}
            variant={band === '' ? 'filled' : 'outlined'}
          />
          {s.bands
            .filter((b) => b.products > 0)
            .map((b) => (
              <Chip
                key={b.band}
                size="small"
                label={`${b.band} (${b.products})`}
                onClick={() => setBand(band === b.band ? '' : b.band)}
                variant={band === b.band ? 'filled' : 'outlined'}
                style={
                  band === b.band
                    ? { background: BAND_STYLE[b.band]?.bg, color: BAND_STYLE[b.band]?.fg }
                    : { borderColor: BAND_STYLE[b.band]?.bg }
                }
              />
            ))}
        </Box>
      )}

      <TableContainer component={Paper} variant="outlined" className={classes.scroll}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              {COLUMNS.map((c) => (
                <TableCell
                  key={c.key}
                  align={isNumeric(c.type) ? 'right' : 'left'}
                  className={classes.head}
                  sortDirection={sort.key === c.key ? sort.dir : false}
                >
                  <TableSortLabel
                    active={sort.key === c.key}
                    direction={sort.key === c.key ? sort.dir : 'desc'}
                    onClick={() => toggleSort(c.key)}
                  >
                    {c.label}
                  </TableSortLabel>
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {loading && (
              <TableRow>
                <TableCell colSpan={COLUMNS.length} align="center">
                  <CircularProgress size={22} />
                </TableCell>
              </TableRow>
            )}
            {!loading && visible.length === 0 && (
              <TableRow>
                <TableCell colSpan={COLUMNS.length} align="center" className={classes.muted}>
                  {!selectedCompany
                    ? 'Select a company to see its stock movement.'
                    : rows.length === 0
                    ? 'No stock and no movement yet — receive stock under Inventory Ingestion first.'
                    : 'No products match the current filter.'}
                </TableCell>
              </TableRow>
            )}
            {!loading &&
              visible.map((r) => (
                <TableRow key={r.product_id} hover>
                  {COLUMNS.map((c) => {
                    if (c.type === 'band') {
                      const st = BAND_STYLE[r.band] || {};
                      return (
                        <TableCell key={c.key}>
                          <Chip
                            size="small"
                            label={r.band}
                            style={{ background: st.bg, color: st.fg, fontWeight: 600 }}
                          />
                        </TableCell>
                      );
                    }
                    if (c.key === 'product_name') {
                      return (
                        <TableCell key={c.key}>
                          <Typography variant="body2" sx={{ fontWeight: 600 }}>
                            {r.product_name}
                          </Typography>
                          <Typography variant="caption" className={classes.muted}>
                            {r.sku_code}
                            {r.category ? ` · ${r.category}` : ''}
                          </Typography>
                        </TableCell>
                      );
                    }
                    if (c.key === 'sale_rate_month') {
                      return (
                        <TableCell key={c.key} align="right" className={classes.num}>
                          {render(c.type, r.sale_rate_month)}
                          {/* How much history the rate is actually based on. Stock received
                              last week is measured over last week, not over the whole
                              window, and saying so stops the figure being over-read. */}
                          {r.sale_rate_month !== null && r.observed_days < windowDays && (
                            <Typography variant="caption" className={classes.muted} display="block">
                              over {r.observed_days}d
                            </Typography>
                          )}
                        </TableCell>
                      );
                    }
                    const v = r[c.key];
                    return (
                      <TableCell
                        key={c.key}
                        align={isNumeric(c.type) ? 'right' : 'left'}
                        className={isNumeric(c.type) ? classes.num : ''}
                        style={
                          c.key === 'value_at_risk' && v > 0 ? { color: '#b91c1c', fontWeight: 600 } : undefined
                        }
                      >
                        {render(c.type, v)}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
          </TableBody>
        </Table>
      </TableContainer>

      {data && (
        <Typography variant="caption" className={classes.muted} display="block" sx={{ mt: 1 }}>
          Showing {visible.length} of {rows.length} products · sale rate measured over the last{' '}
          {data.window_days} days · as of {data.as_of}. Cover is stock ÷ sale rate. Value at risk is
          the stock that will still be on hand when the earliest batch in stock expires, at landed
          cost — blank where there is no sale history to project from.
        </Typography>
      )}

      <Snackbar
        open={!!toast}
        autoHideDuration={5000}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        {toast && <Alert severity={toast.severity}>{toast.msg}</Alert>}
      </Snackbar>
    </Box>
  );
};

export default StockMovement;
