import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Box,
  Button,
  IconButton,
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
  Tabs,
  Tab,
  Snackbar,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  Autocomplete,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconRefresh, IconDownload, IconX } from '@tabler/icons';
import api from '../../../services/api';
import { useWarehouse } from '../../../context/WarehouseContext';
import { useColumnSearch } from '../../../hooks/useColumnSearch';
import { dealerLabel } from '../../../utils/dealerLabel';

const BASE = 'admin/sales-report';

const PRODUCT_COLUMNS = [
  { key: 'product_name', label: 'Product', type: 'text' },
  { key: 'sku_code', label: 'SKU', type: 'text' },
  { key: 'category', label: 'Category', type: 'text' },
  { key: 'quantity', label: 'Qty', type: 'int' },
  { key: 'revenue', label: 'Revenue', type: 'money' },
  { key: 'max_rate', label: 'Max Rate', type: 'money' },
  { key: 'margin', label: 'Margin', type: 'money' },
  { key: 'margin_pct', label: 'Margin %', type: 'pct' },
  { key: 'dealers_reached', label: 'Dealers', type: 'int' },
  { key: 'orders', label: 'Invoiced Orders', type: 'int' },
  { key: 'last_sale', label: 'Last Invoice Date', type: 'date' },
];

const DEALER_COLUMNS = [
  { key: 'dealer_name', label: 'Dealer', type: 'text' },
  { key: 'executive_name', label: 'Executive', type: 'text' },
  { key: 'quantity', label: 'Qty', type: 'int' },
  { key: 'revenue', label: 'Revenue', type: 'money' },
  { key: 'margin', label: 'Margin', type: 'money' },
  { key: 'margin_pct', label: 'Margin %', type: 'pct' },
  { key: 'products_bought', label: 'Products', type: 'int' },
  { key: 'orders', label: 'Invoiced Orders', type: 'int' },
  { key: 'last_sale', label: 'Last Invoice Date', type: 'date' },
];

const BATCH_COLUMNS = [
  { key: 'batch_number', label: 'Batch #', type: 'text' },
  { key: 'product_name', label: 'Product', type: 'text' },
  { key: 'sku_code', label: 'SKU', type: 'text' },
  { key: 'expiry', label: 'Expiry', type: 'date' },
  { key: 'quantity', label: 'Qty', type: 'int' },
  { key: 'revenue', label: 'Revenue', type: 'money' },
  { key: 'max_rate', label: 'Max Rate', type: 'money' },
  { key: 'margin', label: 'Margin', type: 'money' },
  { key: 'margin_pct', label: 'Margin %', type: 'pct' },
  { key: 'dealers_reached', label: 'Dealers', type: 'int' },
  { key: 'orders', label: 'Invoiced Orders', type: 'int' },
  { key: 'last_sale', label: 'Last Invoice Date', type: 'date' },
];

// Grouped by (counterpart, rate) — one row per DISTINCT price actually charged, not one
// row per invoice (which would repeat the same rate every time it recurred) and not one
// row per dealer/product (which averages genuinely different rates together and hides
// them). Two invoices billed at the same rate collapse into one row; two different rates
// stay two separate rows, however many invoices each one covers.
const DRILL_PRODUCT_COLUMNS = [
  { key: 'dealer_name', label: 'Dealer', type: 'text' },
  { key: 'rate', label: 'Rate', type: 'money' },
  { key: 'quantity', label: 'Qty', type: 'int' },
  { key: 'revenue', label: 'Revenue', type: 'money' },
  { key: 'orders', label: 'Invoiced Orders', type: 'int' },
  { key: 'last_sale', label: 'Last Invoice Date', type: 'date' },
];

// Same shape as the product drill (a batch is just a product narrowed to one lot) —
// who bought this exact batch, and at what distinct rate(s) each time.
const DRILL_BATCH_COLUMNS = DRILL_PRODUCT_COLUMNS;

const DRILL_DEALER_COLUMNS = [
  { key: 'product_name', label: 'Product', type: 'text' },
  { key: 'sku_code', label: 'SKU', type: 'text' },
  { key: 'rate', label: 'Rate', type: 'money' },
  { key: 'quantity', label: 'Qty', type: 'int' },
  { key: 'revenue', label: 'Revenue', type: 'money' },
  { key: 'orders', label: 'Invoiced Orders', type: 'int' },
  { key: 'last_sale', label: 'Last Invoice Date', type: 'date' },
];

const useStyles = makeStyles((theme) => ({
  section: { marginBottom: theme.spacing(2) },
  muted: { color: '#7a869a' },
  num: { whiteSpace: 'nowrap' },
  head: {
    whiteSpace: 'nowrap',
    fontWeight: 600,
    position: 'sticky',
    top: 0,
    zIndex: 3,
    background: '#fff',
  },
  scroll: { maxHeight: '55vh' },
  filterCell: {
    position: 'sticky',
    top: 37,
    zIndex: 3,
    background: '#fff',
    paddingTop: 0,
    paddingBottom: 6,
  },
  statCard: { padding: 16, height: '100%' },
  statLabel: { color: '#7a869a', fontSize: 13 },
  statValue: { fontWeight: 600, marginTop: 4 },
  positive: { color: '#1b873f' },
  clickableRow: { cursor: 'pointer' },
}));

const nf2 = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const dt = (v) => {
  if (!v) return '—';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
};

const render = (type, v) => {
  if (v === null || v === undefined || v === '') return '—';
  if (type === 'money') return `₹ ${nf2.format(Number(v))}`;
  if (type === 'pct') return `${nf2.format(Number(v))}%`;
  if (type === 'int') return Number(v).toLocaleString('en-IN');
  if (type === 'date') return dt(v);
  return String(v);
};

const isNumeric = (t) => t === 'money' || t === 'pct' || t === 'int';

const drillColumns = (kind) => {
  if (kind === 'dealer') return DRILL_DEALER_COLUMNS;
  if (kind === 'batch') return DRILL_BATCH_COLUMNS;
  return DRILL_PRODUCT_COLUMNS;
};

const StatCard = ({ label, value, sub }) => {
  const classes = useStyles();
  return (
    <Paper variant="outlined" className={classes.statCard}>
      <Typography className={classes.statLabel}>{label}</Typography>
      <Typography variant="h5" className={classes.statValue}>
        {value}
      </Typography>
      {sub && (
        <Typography variant="caption" className={classes.muted}>
          {sub}
        </Typography>
      )}
    </Paper>
  );
};

const emptySummary = { order_total: null, landing_cost: null, margin: null, margin_pct: null };

// Groups `lines` by (groupKey, net_rate) — see DRILL_PRODUCT_COLUMNS' own note on why
// rate joins the group key instead of being averaged away or left to repeat one row per
// invoice. `null`/`undefined` rates (no price on file for that line) group together too,
// rather than being dropped or merged into a real rate's total.
const rateGroups = (lines, groupKey, labelFields) => {
  const groups = new Map();
  lines.forEach((l) => {
    const gid = l[groupKey];
    if (gid === null || gid === undefined) return;
    const rate = l.net_rate ?? null;
    const compositeKey = `${gid}|${rate}`;
    if (!groups.has(compositeKey)) {
      const row = { id: compositeKey, rate };
      labelFields.forEach((f) => {
        row[f] = l[f];
      });
      row.quantity = 0;
      row.revenue = 0;
      row._orderIds = new Set();
      row._lastSale = null;
      groups.set(compositeKey, row);
    }
    const row = groups.get(compositeKey);
    row.quantity += l.quantity || 0;
    if (rate !== null) {
      row.revenue += rate * (l.quantity || 0);
    }
    if (l.potential_order_id) row._orderIds.add(l.potential_order_id);
    if (l.invoice_date && (!row._lastSale || l.invoice_date > row._lastSale)) {
      row._lastSale = l.invoice_date;
    }
  });
  return Array.from(groups.values())
    .map((row) => ({
      ...row,
      revenue: Math.round(row.revenue * 100) / 100,
      orders: row._orderIds.size,
      last_sale: row._lastSale,
    }))
    // By the group's own label first (dealer or product, whichever labelFields led with),
    // then highest rate first, so a dealer's/product's several rates read newest-ish-first
    // rather than shuffled.
    .sort((a, b) => {
      const labelKey = labelFields[0];
      return String(a[labelKey] || '').localeCompare(String(b[labelKey] || ''))
        || (b.rate || 0) - (a.rate || 0);
    });
};

const SalesReport = () => {
  const classes = useStyles();
  const { companies, selectedCompany, setSelectedCompany } = useWarehouse();

  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [productFilter, setProductFilter] = useState([]); // selected product_options
  const [dealerFilter, setDealerFilter] = useState([]); // selected dealer_options
  const [tab, setTab] = useState('products');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState(null);
  const [drill, setDrill] = useState(null); // { kind: 'product'|'dealer'|'batch', id, label }

  const load = useCallback(async () => {
    if (!selectedCompany) {
      setData(null);
      return;
    }
    setLoading(true);
    try {
      const params = { company_id: selectedCompany };
      if (from) params.from = from;
      if (to) params.to = to;
      if (productFilter.length) params.product_ids = productFilter.map((p) => p.id).join(',');
      if (dealerFilter.length) params.dealer_ids = dealerFilter.map((d) => d.id).join(',');
      const res = await api.get(BASE, { params });
      setData(res.data);
    } catch (e) {
      setToast({
        severity: 'error',
        msg: e?.response?.data?.msg || 'Could not load the sales report',
      });
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [selectedCompany, from, to, productFilter, dealerFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const summary = data?.summary || emptySummary;
  const products = data?.products || [];
  // Dealer name folds in the town right here ("M.S DISTRIBUTORS - Rajkot") — the one
  // place every dealer-name display in this screen (the table, the drill titles, the
  // filter) draws from, so the town can't show up in one and not another.
  const dealers = useMemo(
    () => (data?.dealers || []).map((d) => ({ ...d, dealer_name: dealerLabel(d.dealer_name, d.town) })),
    [data]
  );
  const trend = data?.trend || [];
  const lines = useMemo(() => data?.lines || [], [data]);
  const batches = data?.batches || [];

  const columns = tab === 'products' ? PRODUCT_COLUMNS : tab === 'dealers' ? DEALER_COLUMNS : BATCH_COLUMNS;
  const rows = tab === 'products' ? products : tab === 'dealers' ? dealers : batches;

  // Separate search state per tab (not one shared instance) — Products, Dealers and
  // Batches share some column keys (revenue, margin, orders...), and reusing one filter
  // set across the switch would silently carry a "Revenue > 50000" search from one
  // table into the other instead of starting the new tab clean.
  const productSearch = useColumnSearch(products, PRODUCT_COLUMNS, render);
  const dealerSearch = useColumnSearch(dealers, DEALER_COLUMNS, render);
  const batchSearch = useColumnSearch(batches, BATCH_COLUMNS, render);
  const activeSearch = tab === 'products' ? productSearch : tab === 'dealers' ? dealerSearch : batchSearch;

  const openDrill = (kind, row) => {
    if (kind === 'product' || kind === 'batch') {
      // Batch rows narrow the same product/dealer line filter down to one batch_id —
      // both drills land on "who bought this and at what distinct rate(s)", just at a
      // different grain.
      const filterKey = kind === 'batch' ? 'batch_id' : 'product_id';
      const rows2 = rateGroups(
        lines.filter((l) => l[filterKey] === row.id),
        'dealer_id',
        ['dealer_name', 'town']
      ).map((r) => ({ ...r, dealer_name: dealerLabel(r.dealer_name, r.town) }));
      const label = kind === 'batch' ? `${row.product_name} — Batch ${row.batch_number || row.id}` : row.product_name;
      setDrill({ kind, label, sub: row.sku_code, rows: rows2 });
    } else {
      const rows2 = rateGroups(
        lines.filter((l) => l.dealer_id === row.id),
        'product_id',
        ['product_name', 'sku_code']
      );
      setDrill({ kind, label: row.dealer_name, rows: rows2 });
    }
  };

  const exportCsv = () => {
    const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const csv = [
      columns.map((c) => esc(c.label)).join(','),
      ...activeSearch.visible.map((r) => columns.map((c) => esc(r[c.key])).join(',')),
    ].join('\n');
    const company = companies.find((c) => c.id === selectedCompany);
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(company?.name || 'sales').replace(/\s+/g, '_')}_${tab}_${from || 'all'}_to_${to || 'date'}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Sales Report
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
          <Grid item xs={6} sm={2}>
            <TextField
              fullWidth
              size="small"
              type="date"
              label="From"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              InputLabelProps={{ shrink: true }}
            />
          </Grid>
          <Grid item xs={6} sm={2}>
            <TextField
              fullWidth
              size="small"
              type="date"
              label="To"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              InputLabelProps={{ shrink: true }}
            />
          </Grid>
          <Grid item xs={12} sm={5}>
            <Box display="flex" alignItems="center">
              <Typography variant="body2" className={classes.muted}>
                {loading
                  ? 'Loading…'
                  : data
                  ? `${data.order_count} order${data.order_count === 1 ? '' : 's'} · ${data.dealer_count} dealer${data.dealer_count === 1 ? '' : 's'} · ${data.product_count} product${data.product_count === 1 ? '' : 's'}`
                  : 'Select a company'}
              </Typography>
              <Box flexGrow={1} />
              <Button size="small" startIcon={<IconRefresh size={16} />} onClick={load} disabled={loading}>
                Refresh
              </Button>
              <Button
                size="small"
                startIcon={<IconDownload size={16} />}
                onClick={exportCsv}
                disabled={!activeSearch.visible.length}
              >
                Export
              </Button>
            </Box>
          </Grid>
        </Grid>

        <Grid container spacing={2} style={{ marginTop: 4 }}>
          <Grid item xs={12} sm={6}>
            <Autocomplete
              multiple
              size="small"
              options={data?.product_options || []}
              value={productFilter}
              onChange={(e, v) => setProductFilter(v)}
              filterSelectedOptions
              getOptionLabel={(o) => o.name || ''}
              isOptionEqualToValue={(o, v) => o.id === v.id}
              renderInput={(params) => (
                <TextField {...params} label="Filter by product" placeholder={productFilter.length ? '' : 'All products'} />
              )}
            />
          </Grid>
          <Grid item xs={12} sm={6}>
            <Autocomplete
              multiple
              size="small"
              options={data?.dealer_options || []}
              value={dealerFilter}
              onChange={(e, v) => setDealerFilter(v)}
              filterSelectedOptions
              getOptionLabel={(o) => dealerLabel(o.name, o.town)}
              isOptionEqualToValue={(o, v) => o.id === v.id}
              renderInput={(params) => (
                <TextField {...params} label="Filter by dealer" placeholder={dealerFilter.length ? '' : 'All dealers'} />
              )}
            />
          </Grid>
        </Grid>
      </Paper>

      <Grid container spacing={2} className={classes.section}>
        <Grid item xs={6} sm={3}>
          <StatCard
            label="Revenue"
            value={summary.order_total !== null ? `₹ ${nf2.format(summary.order_total)}` : '—'}
          />
        </Grid>
        <Grid item xs={6} sm={3}>
          <StatCard
            label="Margin"
            value={summary.margin !== null ? `₹ ${nf2.format(summary.margin)}` : '—'}
            sub={summary.margin_pct !== null ? `${nf2.format(summary.margin_pct)}%` : undefined}
          />
        </Grid>
        <Grid item xs={6} sm={3}>
          <StatCard label="Orders" value={data ? String(data.order_count) : '—'} />
        </Grid>
        <Grid item xs={6} sm={3}>
          <StatCard
            label="Dealers / Products"
            value={data ? `${data.dealer_count} / ${data.product_count}` : '—'}
          />
        </Grid>
      </Grid>

      {trend.length > 0 && (
        <TableContainer component={Paper} variant="outlined" className={classes.section}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell className={classes.head}>Invoice Month</TableCell>
                <TableCell className={classes.head} align="right">
                  Revenue
                </TableCell>
                <TableCell className={classes.head} align="right">
                  Margin
                </TableCell>
                <TableCell className={classes.head} align="right">
                  Qty
                </TableCell>
                <TableCell className={classes.head} align="right">
                  Orders
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {trend.map((m) => (
                <TableRow key={m.month}>
                  <TableCell>{m.month}</TableCell>
                  <TableCell align="right" className={classes.num}>
                    {render('money', m.revenue)}
                  </TableCell>
                  <TableCell align="right" className={classes.num}>
                    {render('money', m.margin)}
                  </TableCell>
                  <TableCell align="right" className={classes.num}>
                    {render('int', m.quantity)}
                  </TableCell>
                  <TableCell align="right" className={classes.num}>
                    {render('int', m.orders)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Tabs value={tab} onChange={(e, v) => setTab(v)} className={classes.section}>
        <Tab label="By Product" value="products" />
        <Tab label="By Dealer" value="dealers" />
        <Tab label="By Batch" value="batches" />
      </Tabs>

      {loading && !rows.length ? (
        <Box display="flex" justifyContent="center" p={4}>
          <CircularProgress />
        </Box>
      ) : (
        <TableContainer component={Paper} variant="outlined" className={classes.scroll}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                {columns.map((c) => (
                  <TableCell
                    key={c.key}
                    className={classes.head}
                    align={isNumeric(c.type) ? 'right' : 'left'}
                    sortDirection={activeSearch.sort?.key === c.key ? activeSearch.sort.dir : false}
                  >
                    <TableSortLabel
                      active={activeSearch.sort?.key === c.key}
                      direction={activeSearch.sort?.key === c.key ? activeSearch.sort.dir : 'desc'}
                      onClick={() => activeSearch.toggleSort(c.key)}
                    >
                      {c.label}
                    </TableSortLabel>
                  </TableCell>
                ))}
              </TableRow>
              <TableRow>
                {columns.map((c) => (
                  <TableCell key={c.key} className={classes.filterCell}>
                    <TextField
                      variant="standard"
                      placeholder="Search"
                      value={activeSearch.filters[c.key] || ''}
                      onChange={(e) => activeSearch.setFilter(c.key, e.target.value)}
                      InputProps={{ style: { fontSize: '0.75rem' } }}
                      fullWidth
                    />
                  </TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {!activeSearch.visible.length && (
                <TableRow>
                  <TableCell colSpan={columns.length} align="center">
                    <Typography variant="body2" className={classes.muted}>
                      {!selectedCompany
                        ? 'Select a company.'
                        : !rows.length
                        ? 'No sales in this window.'
                        : 'No rows match the current search.'}
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
              {activeSearch.visible.map((r) => (
                <TableRow
                  key={r.id}
                  hover
                  className={classes.clickableRow}
                  onClick={() => openDrill(tab === 'products' ? 'product' : tab === 'dealers' ? 'dealer' : 'batch', r)}
                >
                  {columns.map((c) => (
                    <TableCell
                      key={c.key}
                      align={isNumeric(c.type) ? 'right' : 'left'}
                      className={isNumeric(c.type) ? classes.num : undefined}
                    >
                      {render(c.type, r[c.key])}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Dialog open={!!drill} onClose={() => setDrill(null)} maxWidth="md" fullWidth>
        <DialogTitle disableTypography>
          <Box display="flex" alignItems="center">
            <Box>
              <Typography variant="h6">{drill?.label}</Typography>
              {drill?.sub && (
                <Typography variant="body2" className={classes.muted}>
                  {drill.sub}
                </Typography>
              )}
            </Box>
            <Box flexGrow={1} />
            <IconButton size="small" onClick={() => setDrill(null)}>
              <IconX size={18} />
            </IconButton>
          </Box>
        </DialogTitle>
        <DialogContent dividers>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  {drillColumns(drill?.kind).map((c) => (
                    <TableCell key={c.key} className={classes.head} align={isNumeric(c.type) ? 'right' : 'left'}>
                      {c.label}
                    </TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {(drill?.rows || []).map((r) => (
                  <TableRow key={r.id}>
                    {drillColumns(drill?.kind).map((c) => (
                      <TableCell key={c.key} align={isNumeric(c.type) ? 'right' : 'left'}>
                        {render(c.type, r[c.key])}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </DialogContent>
      </Dialog>

      <Snackbar
        open={!!toast}
        autoHideDuration={5000}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity={toast?.severity || 'info'} onClose={() => setToast(null)}>
          {toast?.msg}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default SalesReport;
