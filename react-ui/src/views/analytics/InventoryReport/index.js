import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Box,
  Button,
  Typography,
  CircularProgress,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Grid,
  MenuItem,
  TextField,
  Snackbar,
  Alert,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconRefresh, IconDownload } from '@tabler/icons';
import api from '../../../services/api';
import { useWarehouse } from '../../../context/WarehouseContext';

const BASE = 'admin/inventory/ingestion';

// One definition per column drives the header, the search row, the cell rendering and the
// CSV export — so a column cannot end up searchable or exported on a different value from
// the one it displays.
//   money : 2dp, thousands separated       rate : 4dp, the precision costs are held at
const COLUMNS = [
  { key: 'product_name', label: 'Product', type: 'text' },
  { key: 'batch_number', label: 'Batch', type: 'mono' },
  { key: 'qty', label: 'Qty', type: 'qty' },
  { key: 'rate_invoice', label: 'Rate / Unit (Invoice)', type: 'rate' },
  { key: 'rate_cn', label: 'Rate / Unit (CN/DN)', type: 'rate' },
  { key: 'landed_ex_gst', label: 'Landed Cost / Unit (ex-GST)', type: 'rate' },
  { key: 'landed_inc_gst', label: 'Landed Cost / Unit (inc-GST)', type: 'rate' },
  { key: 'mrp', label: 'MRP / Unit', type: 'money' },
  { key: 'margin_5', label: 'Margin @+5%', type: 'rate' },
  { key: 'margin_10', label: 'Margin @+10%', type: 'rate' },
  { key: 'margin_15', label: 'Margin @+15%', type: 'rate' },
];

const useStyles = makeStyles((theme) => ({
  section: { marginBottom: theme.spacing(2) },
  mono: { fontFamily: 'monospace', fontSize: '0.8rem', whiteSpace: 'nowrap' },
  num: { whiteSpace: 'nowrap' },
  negative: { color: '#c62828' },
  muted: { color: '#7a869a' },
  // Two header rows both stick. MUI's stickyHeader pins every header cell to top:0, so
  // without an explicit offset the search row would sit on top of the labels. The
  // background is required too — a sticky cell is transparent by default and the rows
  // scrolling underneath would show through it.
  head: {
    whiteSpace: 'nowrap',
    fontWeight: 600,
    verticalAlign: 'bottom',
    position: 'sticky',
    top: 0,
    zIndex: 3,
    background: '#fff',
    borderBottom: 'none',
  },
  filterCell: {
    position: 'sticky',
    top: 37,                 // clears the label row above it
    zIndex: 3,
    background: '#fff',
    paddingTop: 0,
    paddingBottom: 6,
  },
  scroll: { maxHeight: '68vh' },
}));

const nf2 = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const nf4 = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 4, maximumFractionDigits: 4 });

const render = (type, v) => {
  if (v === null || v === undefined || v === '') return '—';
  if (type === 'money') return nf2.format(Number(v));
  if (type === 'rate') return nf4.format(Number(v));
  if (type === 'qty') return Number(v).toLocaleString('en-IN');
  return String(v);
};

const isNumeric = (t) => t === 'money' || t === 'rate' || t === 'qty';

const InventoryReport = () => {
  const classes = useStyles();
  const { companies, selectedCompany, setSelectedCompany } = useWarehouse();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState({});
  const [toast, setToast] = useState(null);

  const load = useCallback(async () => {
    if (!selectedCompany) {
      setRows([]);
      return;
    }
    setLoading(true);
    try {
      const { data } = await api.get(`${BASE}/report`, {
        params: { company_id: selectedCompany, limit: 5000 },
      });
      setRows(data.rows || []);
    } catch (e) {
      setToast({ severity: 'error', msg: 'Could not load the inventory report' });
    } finally {
      setLoading(false);
    }
  }, [selectedCompany]);

  useEffect(() => {
    load();
  }, [load]);

  // Numbers are matched both as stored and as displayed, so typing what is on screen
  // ("1,26,720") works as readily as the raw value.
  const searchable = useMemo(
    () =>
      rows.map((r) => ({
        row: r,
        text: COLUMNS.reduce((acc, c) => {
          acc[c.key] = `${r[c.key] ?? ''} ${render(c.type, r[c.key])}`.toLowerCase();
          return acc;
        }, {}),
      })),
    [rows]
  );

  const visible = useMemo(() => {
    const active = Object.entries(filters).filter(([, v]) => (v || '').trim());
    if (!active.length) return searchable.map((s) => s.row);
    return searchable
      .filter((s) => active.every(([k, term]) => (s.text[k] || '').includes(term.trim().toLowerCase())))
      .map((s) => s.row);
  }, [searchable, filters]);

  // Totals follow the filter, so a narrowed view reports on what it shows.
  const totals = useMemo(() => {
    // Only quantity is meaningfully additive here — summing per-unit rates or margins
    // across different products would produce a number that means nothing.
    return { qty: visible.reduce((a, r) => a + Number(r.qty || 0), 0) };
  }, [visible]);

  const exportCsv = () => {
    const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const csv = [
      COLUMNS.map((c) => esc(c.label)).join(','),
      ...visible.map((r) => COLUMNS.map((c) => esc(r[c.key])).join(',')),
    ].join('\n');
    const company = companies.find((c) => c.id === selectedCompany);
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(company?.name || 'inventory').replace(/\s+/g, '_')}_Batch_Costing.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const activeFilters = Object.values(filters).some((v) => (v || '').trim());

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Batch Costing
      </Typography>

      <Paper variant="outlined" className={classes.section} style={{ padding: 12 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} sm={4}>
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
          <Grid item xs={12} sm={8}>
            <Box display="flex" alignItems="center">
              <Typography variant="body2" className={classes.muted}>
                {loading
                  ? 'Loading…'
                  : `${visible.length}${activeFilters ? ` of ${rows.length}` : ''} batch${
                      visible.length === 1 ? '' : 'es'
                    }`}
              </Typography>
              <Box flexGrow={1} />
              {activeFilters && (
                <Button size="small" onClick={() => setFilters({})} style={{ marginRight: 8 }}>
                  Clear search
                </Button>
              )}
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

      <TableContainer component={Paper} variant="outlined" className={classes.scroll}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              {COLUMNS.map((c) => (
                <TableCell
                  key={c.key}
                  align={isNumeric(c.type) ? 'right' : 'left'}
                  className={classes.head}
                >
                  {c.label}
                </TableCell>
              ))}
            </TableRow>
            <TableRow>
              {COLUMNS.map((c) => (
                <TableCell key={c.key} className={classes.filterCell}>
                  <TextField
                    variant="standard"
                    placeholder="Search"
                    value={filters[c.key] || ''}
                    onChange={(e) => setFilters((f) => ({ ...f, [c.key]: e.target.value }))}
                    InputProps={{ style: { fontSize: '0.75rem' } }}
                    fullWidth
                  />
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
                    ? 'Select a company to see its inventory.'
                    : rows.length === 0
                    ? 'No inventory yet — upload supplier invoices under Inventory Ingestion.'
                    : 'No rows match the current search.'}
                </TableCell>
              </TableRow>
            )}
            {!loading &&
              visible.map((r) => (
                <TableRow key={`${r.sku_id}-${r.batch_id}`} hover>
                  {COLUMNS.map((c) => {
                    const v = r[c.key];
                    const neg = isNumeric(c.type) && Number(v) < 0;
                    return (
                      <TableCell
                        key={c.key}
                        align={isNumeric(c.type) ? 'right' : 'left'}
                        className={[
                          c.type === 'mono' ? classes.mono : '',
                          isNumeric(c.type) ? classes.num : '',
                          neg ? classes.negative : '',
                        ].join(' ')}
                      >
                        {render(c.type, v)}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
            {!loading && visible.length > 0 && (
              <TableRow>
                {COLUMNS.map((c, i) => (
                  <TableCell key={c.key} align={isNumeric(c.type) ? 'right' : 'left'}>
                    {i === 0 ? (
                      <strong>Total ({visible.length})</strong>
                    ) : totals[c.key] !== undefined ? (
                      <strong>{render(c.type, totals[c.key])}</strong>
                    ) : (
                      ''
                    )}
                  </TableCell>
                ))}
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

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

export default InventoryReport;
