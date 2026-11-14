import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Box,
  Button,
  Chip,
  Grid,
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
  TextField,
  MenuItem,
  Alert,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { useSelector } from 'react-redux';
import { IconRefresh, IconFilterOff, IconFileSpreadsheet } from '@tabler/icons';
import api from '../../../services/api';
import { getFeedStatus, exportInventoryByCategory } from '../../../services/tatCheckService';
import { FEEDS, UploadRow } from '../../dms-uploads/DmsFeedUpload';

// In-stock SKUs by category: the latest DMS Inventory Report (TAT Check upload), each
// code with stock under its category from the SKU master in force (PO Builder upload).
const URL_BY_CATEGORY = 'tat-check/inventory-by-category';

// The inventory upload is TAT Check's own row — same component, same API
// (tat-check/upload, tat-check/status) — so a file uploaded here or on TAT Check is the
// one file both pages read, and both show the same Last Updated.
const INVENTORY_FEED = FEEDS.find((f) => f.feed === 'inventory');

const ALL = '';

const COLUMNS = [
  { key: 'category', label: 'Category', filter: 'select', width: '22%' },
  { key: 'sku_code', label: 'SKU Code', filter: 'text', width: '20%' },
  { key: 'description', label: 'SKU Description', filter: 'text' },
  { key: 'qty', label: 'Qty', filter: 'number', numeric: true, width: '12%' },
];

const useStyles = makeStyles((theme) => ({
  section: { marginBottom: theme.spacing(2), padding: 16, borderRadius: 10 },
  muted: { color: '#7a869a' },
  tile: { padding: '12px 16px', borderRadius: 10, height: '100%' },
  tileLabel: { color: '#7a869a', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: 0.4 },
  tileValue: { fontSize: '1.5rem', fontWeight: 700, lineHeight: 1.3 },
  // Two header rows both stick: labels at top 0, filters just below them.
  head: {
    whiteSpace: 'nowrap',
    fontWeight: 600,
    position: 'sticky',
    top: 0,
    zIndex: 3,
    background: '#f7f9fc',
    borderBottom: 'none',
  },
  filterCell: {
    position: 'sticky',
    top: 41,
    zIndex: 3,
    background: '#f7f9fc',
    paddingTop: 0,
    paddingBottom: 8,
  },
  row: {
    '&:nth-of-type(even)': { background: '#fbfcfe' },
  },
  mono: { fontFamily: 'monospace', fontSize: '0.82rem', whiteSpace: 'nowrap' },
  qty: { fontWeight: 600, whiteSpace: 'nowrap' },
  chip: { fontSize: '0.72rem', height: 22, maxWidth: '100%' },
  total: { background: '#f7f9fc', fontWeight: 700, position: 'sticky', bottom: 0 },
  scroll: { maxHeight: '64vh', borderRadius: 10 },
}));

const fmt = (v) => Number(v || 0).toLocaleString('en-IN');

// The Excel file is named for the inventory upload's date, in IST, as the server names it:
// In_Stock_SKUs_by_Category_14-Nov-2026.xlsx
const excelName = (uploadedIso) => {
  const d = uploadedIso ? new Date(uploadedIso) : new Date();
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric' })
      .formatToParts(d)
      .map((p) => [p.type, p.value])
  );
  return `In_Stock_SKUs_by_Category_${parts.day}-${parts.month}-${parts.year}.xlsx`;
};

const when = (iso) =>
  iso
    ? new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
    : '';

// One soft colour per category, the same every time, so a category reads at a glance.
const PALETTE = ['#e3f2fd', '#e8f5e9', '#fff3e0', '#f3e5f5', '#e0f7fa', '#fce4ec', '#f1f8e9', '#ede7f6', '#fffde7', '#efebe9'];
const tint = (name) => {
  let h = 0;
  for (let i = 0; i < name.length; i += 1) h = (h * 31 + name.charCodeAt(i)) % 9973;
  return PALETTE[h % PALETTE.length];
};

// Qty filter: "100" exact, ">100", ">=100", "<50", "<=50", or a range "10-100".
const qtyMatch = (term, qty) => {
  const t = term.replace(/[\s,]/g, '');
  if (!t) return true;
  const range = t.match(/^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)$/);
  if (range) return qty >= Number(range[1]) && qty <= Number(range[2]);
  const cmp = t.match(/^(>=|<=|>|<|=)?(\d+(?:\.\d+)?)$/);
  if (!cmp) return String(qty).includes(t);
  const n = Number(cmp[2]);
  switch (cmp[1]) {
    case '>':
      return qty > n;
    case '>=':
      return qty >= n;
    case '<':
      return qty < n;
    case '<=':
      return qty <= n;
    default:
      return qty === n;
  }
};

const Tile = ({ label, value, classes }) => (
  <Paper variant="outlined" className={classes.tile}>
    <Typography className={classes.tileLabel}>{label}</Typography>
    <Typography className={classes.tileValue}>{value}</Typography>
  </Paper>
);

const CategoryStock = () => {
  const classes = useStyles();
  const { user } = useSelector((state) => state.account);
  const isAdmin = user?.role === 'admin';
  const [categories, setCategories] = useState([]);
  const [sources, setSources] = useState([]);
  const [feeds, setFeeds] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [filters, setFilters] = useState({});
  const [sort, setSort] = useState({ key: 'category', dir: 'asc' });
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [{ data }, status] = await Promise.all([api.get(URL_BY_CATEGORY), getFeedStatus()]);
      setCategories(data.categories || []);
      setSources(status.sources || []);
      setFeeds(status.feeds || []);
    } catch (e) {
      setCategories([]);
      setError(e?.response?.data?.msg || 'Could not load stock by category');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // One flat row per in-stock SKU. The server orders categories by stock; that order is
  // kept as the default "category" sort so the biggest categories come first.
  const allRows = useMemo(
    () =>
      categories.flatMap((c, rank) =>
        c.items.map((i) => ({ category: c.category, rank, sku_code: i.sku_code, description: i.description, qty: Number(i.qty || 0) }))
      ),
    [categories]
  );

  const categoryOptions = useMemo(() => categories.filter((c) => c.items.length).map((c) => c.category), [categories]);

  const visible = useMemo(() => {
    const rows = allRows.filter((r) =>
      COLUMNS.every((c) => {
        const term = (filters[c.key] || '').trim();
        if (!term) return true;
        if (c.filter === 'select') return r.category === term;
        if (c.filter === 'number') return qtyMatch(term, r.qty);
        return String(r[c.key] || '').toLowerCase().includes(term.toLowerCase());
      })
    );
    const dir = sort.dir === 'asc' ? 1 : -1;
    const by = {
      category: (a, b) => a.rank - b.rank || a.sku_code.localeCompare(b.sku_code),
      sku_code: (a, b) => a.sku_code.localeCompare(b.sku_code),
      description: (a, b) => a.description.localeCompare(b.description),
      qty: (a, b) => a.qty - b.qty,
    }[sort.key];
    return [...rows].sort((a, b) => dir * by(a, b));
  }, [allRows, filters, sort]);

  const totals = useMemo(
    () => ({
      skus: visible.length,
      qty: visible.reduce((a, r) => a + r.qty, 0),
      categories: new Set(visible.map((r) => r.category)).size,
    }),
    [visible]
  );

  const activeFilters = Object.values(filters).some((v) => (v || '').trim());

  const toggleSort = (key) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'qty' ? 'desc' : 'asc' }));

  const exportExcel = async () => {
    setExporting(true);
    setExportError('');
    try {
      await exportInventoryByCategory(
        visible.map(({ category, sku_code, description, qty }) => ({ category, sku_code, description, qty })),
        excelName(inventorySource?.last_upload?.uploaded_on)
      );
    } catch (e) {
      let msg = 'Could not build the Excel file.';
      try {
        msg = JSON.parse(await e?.response?.data?.text?.()).msg || msg;
      } catch (_) {
        /* keep the generic message */
      }
      setExportError(msg);
    } finally {
      setExporting(false);
    }
  };

  const inventorySource = sources.find((s) => s.key === 'inventory');
  const masterSource = sources.find((s) => s.key === 'sku_master');

  return (
    <Box>
      <Grid container spacing={2} style={{ marginBottom: 8 }}>
        <Grid item xs={12} sm={4}>
          <Tile classes={classes} label={activeFilters ? 'In-stock SKUs (filtered)' : 'In-stock SKUs'} value={loading ? '—' : fmt(totals.skus)} />
        </Grid>
        <Grid item xs={12} sm={4}>
          <Tile classes={classes} label="Units in stock" value={loading ? '—' : fmt(totals.qty)} />
        </Grid>
        <Grid item xs={12} sm={4}>
          <Tile classes={classes} label="Categories" value={loading ? '—' : fmt(totals.categories)} />
        </Grid>
      </Grid>

      <Paper variant="outlined" className={classes.section}>
        <Box display="flex" alignItems="center" flexWrap="wrap" style={{ gap: 8 }}>
          <Box>
            <Typography variant="body2" className={classes.muted}>
              SKU Master: {masterSource?.last_upload ? when(masterSource.last_upload.uploaded_on) : 'not uploaded yet'}
            </Typography>
            {!isAdmin && (
              <Typography variant="body2" style={{ color: '#b91c1c', fontWeight: 600 }}>
                Inventory Last Updated: {inventorySource?.last_upload ? when(inventorySource.last_upload.uploaded_on) : 'not uploaded yet'}
              </Typography>
            )}
          </Box>
          <Box flexGrow={1} />
          <Button size="small" variant="outlined" startIcon={<IconRefresh size={16} />} onClick={load} disabled={loading}>
            Refresh
          </Button>
        </Box>
        {isAdmin && INVENTORY_FEED && (
          <UploadRow def={INVENTORY_FEED} statuses={feeds.filter((f) => f.feed === 'inventory')} onUploaded={load} />
        )}
      </Paper>

      {/* The report's own bar: what the table shows, and its downloads. */}
      <Box display="flex" alignItems="center" flexWrap="wrap" style={{ gap: 8, marginBottom: 8 }}>
        <Typography variant="subtitle1" style={{ fontWeight: 600 }}>
          In-stock SKUs by Category
        </Typography>
        <Typography variant="body2" className={classes.muted}>
          {loading ? 'Loading…' : `${fmt(totals.skus)} SKU${totals.skus === 1 ? '' : 's'} · ${fmt(totals.qty)} units${activeFilters ? ' (filtered)' : ''}`}
        </Typography>
        <Box flexGrow={1} />
        {activeFilters && (
          <Button size="small" startIcon={<IconFilterOff size={16} />} onClick={() => setFilters({})}>
            Clear filters
          </Button>
        )}
        <Button
          size="small"
          variant="contained"
          color="primary"
          disableElevation
          startIcon={exporting ? <CircularProgress size={14} color="inherit" /> : <IconFileSpreadsheet size={16} />}
          onClick={exportExcel}
          disabled={!visible.length || exporting}
        >
          {exporting ? 'Preparing…' : 'Download Report Excel'}
        </Button>
      </Box>
      {exportError && (
        <Alert severity="error" onClose={() => setExportError('')} style={{ marginBottom: 8 }}>
          {exportError}
        </Alert>
      )}

      <TableContainer component={Paper} variant="outlined" className={classes.scroll}>
        <Table size="small" style={{ tableLayout: 'fixed' }}>
          <TableHead>
            <TableRow>
              {COLUMNS.map((c) => (
                <TableCell key={c.key} align={c.numeric ? 'right' : 'left'} className={classes.head} style={{ width: c.width }}>
                  <TableSortLabel
                    active={sort.key === c.key}
                    direction={sort.key === c.key ? sort.dir : 'asc'}
                    onClick={() => toggleSort(c.key)}
                  >
                    {c.label}
                  </TableSortLabel>
                </TableCell>
              ))}
            </TableRow>
            <TableRow>
              {COLUMNS.map((c) => (
                <TableCell key={c.key} className={classes.filterCell}>
                  {c.filter === 'select' ? (
                    <TextField
                      select
                      variant="standard"
                      fullWidth
                      value={filters[c.key] || ALL}
                      onChange={(e) => setFilters((f) => ({ ...f, [c.key]: e.target.value }))}
                      SelectProps={{ displayEmpty: true }}
                      InputProps={{ style: { fontSize: '0.78rem' } }}
                    >
                      <MenuItem value={ALL}>All categories</MenuItem>
                      {categoryOptions.map((name) => (
                        <MenuItem key={name} value={name}>
                          {name}
                        </MenuItem>
                      ))}
                    </TextField>
                  ) : (
                    <TextField
                      variant="standard"
                      fullWidth
                      placeholder={c.filter === 'number' ? 'e.g. >100, 10-50' : 'Search'}
                      value={filters[c.key] || ''}
                      onChange={(e) => setFilters((f) => ({ ...f, [c.key]: e.target.value }))}
                      inputProps={{ style: { fontSize: '0.78rem', textAlign: c.numeric ? 'right' : 'left' } }}
                    />
                  )}
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {loading && (
              <TableRow>
                <TableCell colSpan={COLUMNS.length} align="center" style={{ padding: 32 }}>
                  <CircularProgress size={24} />
                </TableCell>
              </TableRow>
            )}
            {!loading && !visible.length && (
              <TableRow>
                <TableCell colSpan={COLUMNS.length} align="center" className={classes.muted} style={{ padding: 32 }}>
                  {error ||
                    (allRows.length
                      ? 'No in-stock SKUs match these filters.'
                      : 'No Inventory Report uploaded yet — upload it above or under TAT Check.')}
                </TableCell>
              </TableRow>
            )}
            {!loading &&
              visible.map((r) => (
                <TableRow key={`${r.category}-${r.sku_code}`} hover className={classes.row}>
                  <TableCell>
                    <Chip
                      size="small"
                      label={r.category}
                      className={classes.chip}
                      style={{ background: tint(r.category) }}
                      onClick={() => setFilters((f) => ({ ...f, category: r.category }))}
                      title="Show only this category"
                    />
                  </TableCell>
                  <TableCell className={classes.mono}>{r.sku_code}</TableCell>
                  <TableCell>{r.description}</TableCell>
                  <TableCell align="right" className={classes.qty}>
                    {fmt(r.qty)}
                  </TableCell>
                </TableRow>
              ))}
            {!loading && visible.length > 0 && (
              <TableRow>
                <TableCell colSpan={3} className={classes.total}>
                  Total · {fmt(totals.skus)} SKU{totals.skus === 1 ? '' : 's'}
                </TableCell>
                <TableCell align="right" className={classes.total}>
                  {fmt(totals.qty)}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
};

export default CategoryStock;
