import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
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
import {
  IconUpload,
  IconRefresh,
} from '@tabler/icons';
import api from '../../services/api';
import { useWarehouse } from '../../context/WarehouseContext';

// Relative to the axios baseURL ('/api/'), so NO leading slash and no '/api' prefix —
// otherwise every request goes to '/api/api/...' and 404s.
const BASE = 'admin/inventory/ingestion';

const useStyles = makeStyles((theme) => ({
  section: { marginBottom: theme.spacing(3) },
  dropzone: {
    border: '2px dashed #c3c9d5',
    borderRadius: 8,
    padding: theme.spacing(4),
    textAlign: 'center',
    cursor: 'pointer',
    transition: 'border-color .2s, background .2s',
    '&:hover': { borderColor: theme.palette.primary.main, background: '#fafbfc' },
  },
  hidden: { display: 'none' },
  mono: { fontFamily: 'monospace', fontSize: '0.82rem' },
  variance: { color: '#c62828', fontWeight: 600 },
  muted: { color: '#7a869a' },
}));

// meta_info and batch_params are JSON columns; tolerate anything unparseable.
const parseMeta = (v) => {
  if (!v) return {};
  if (typeof v === 'object') return v;
  try { return JSON.parse(v); } catch (e) { return {}; }
};

const rate4 = (v) =>
  v === null || v === undefined || v === '' ? '—' : Number(v).toFixed(4);

// One definition per column: its heading, alignment, and the text a search matches
// against. Deriving all three from one place means a column cannot end up searchable on
// a different value from the one it displays.
const COLUMNS = [
  { key: 'invoice', label: 'Invoice',       align: 'left'  },
  { key: 'product', label: 'Product',       align: 'left'  },
  { key: 'batch',   label: 'Batch',         align: 'left'  },
  { key: 'expiry',  label: 'Expiry',        align: 'left'  },
  { key: 'qty',     label: 'Qty',           align: 'right' },
  { key: 'mrp',     label: 'MRP',           align: 'right' },
  { key: 'landing', label: 'Landing price', align: 'right' },
  { key: 'cn',      label: 'CN',            align: 'right' },
  { key: 'final',   label: 'Final landing', align: 'right' },
  { key: 'finalgst', label: 'Final landing (inc-GST)', align: 'right' },
];

// Both the stored value and the on-screen rendering, so either matches a search.
const num = (raw, shown) => `${raw ?? ''} ${shown ?? ''}`;

const money = (v) =>
  v === null || v === undefined || v === '' ? '—' : Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const InventoryIngestion = () => {
  const classes = useStyles();
  const fileRef = useRef(null);

  // Warehouses and companies come from the shared context rather than a private fetch,
  // so this tab agrees with every other screen about what the operator has selected.
  const { warehouses, companies, selectedCompany, setSelectedCompany } = useWarehouse();
  const [warehouseId, setWarehouseId] = useState('');
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);
  const [received, setReceived] = useState([]);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState(null);
  const [filters, setFilters] = useState({});

  useEffect(() => {
    if (!warehouseId && warehouses.length) {
      const first = warehouses[0];
      setWarehouseId(first.warehouse_id ?? first.id);
    }
  }, [warehouses, warehouseId]);

  // Scoped to the selected company. An unrestricted admin has no implicit company, so
  // without this the list comes back holding every tenant's stock at once.
  const loadReceived = useCallback(async () => {
    if (!selectedCompany) {
      setReceived([]);
      return;
    }
    setLoading(true);
    try {
      const { data } = await api.get(`${BASE}/received`, {
        params: { limit: 200, company_id: selectedCompany, warehouse_id: warehouseId || undefined },
      });
      setReceived(data.received || []);
    } catch (e) {
      setToast({ severity: 'error', msg: 'Could not load received stock' });
    } finally {
      setLoading(false);
    }
  }, [selectedCompany, warehouseId]);

  // Reloads whenever the company or warehouse changes, so the table always shows the
  // selection rather than whatever was loaded first.
  useEffect(() => {
    loadReceived();
  }, [loadReceived]);

  // Flatten each row once into the exact strings the table shows, so a search matches
  // what the user can actually see — including the formatted numbers and the values that
  // live inside the meta_info / batch_params JSON columns.
  const rows = useMemo(
    () =>
      received.map((r) => {
        const meta = parseMeta(r.meta_info);
        const batch = parseMeta(r.batch_params);
        return {
          ...r,
          invoice: meta.invoice || String(r.transferin_id ?? ''),
          batch: batch.batch_number || '',
          expiry: batch.expiry || '',
          _search: {
            invoice: meta.invoice || String(r.transferin_id ?? ''),
            product: `${r.product_name || ''} ${r.sku_code || ''}`,
            batch: batch.batch_number || '',
            expiry: batch.expiry || '',
            // Numbers are searchable both as stored and as displayed, so typing what is
            // on screen ("1,26,720") matches as readily as the raw value ("126720").
            qty: num(r.quantity, Number(r.quantity || 0).toLocaleString('en-IN')),
            mrp: num(r.mrp, money(r.mrp)),
            landing: num(r.landing_price, rate4(r.landing_price)),
            cn: num(r.cn_rate, rate4(r.cn_rate)),
            final: num(r.final_landing_price, rate4(r.final_landing_price)),
            finalgst: num(r.final_landing_inc_gst, rate4(r.final_landing_inc_gst)),
          },
        };
      }),
    [received]
  );

  // Every non-empty box must match — the filters narrow together rather than compete.
  const visible = useMemo(() => {
    const active = Object.entries(filters).filter(([, v]) => (v || '').trim());
    if (!active.length) return rows;
    return rows.filter((r) =>
      active.every(([key, term]) =>
        (r._search[key] || '').toLowerCase().includes(term.trim().toLowerCase())
      )
    );
  }, [rows, filters]);

  const handleFiles = async (files) => {
    if (!files || !files.length) return;
    if (!warehouseId) {
      setToast({ severity: 'warning', msg: 'Select a warehouse first' });
      return;
    }
    // An admin with access to every company has no implicit "own" company, so the
    // backend refuses an upload that does not name one. Sending it explicitly is what
    // keeps these documents off another tenant's books.
    if (!selectedCompany) {
      setToast({ severity: 'warning', msg: 'Select a company first' });
      return;
    }
    const form = new FormData();
    Array.from(files).forEach((f) => form.append('files', f));
    form.append('warehouse_id', warehouseId);
    form.append('company_id', selectedCompany);

    setUploading(true);
    setResult(null);
    try {
      const { data } = await api.post(`${BASE}/upload`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setResult(data);
      loadReceived();
    } catch (e) {
      setToast({ severity: 'error', msg: e?.response?.data?.msg || 'Upload failed' });
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Inventory Ingestion
      </Typography>

      {/* ── Upload ─────────────────────────────────────────────────────── */}
      <Paper variant="outlined" className={classes.section} style={{ padding: 16 }}>
        <Typography variant="subtitle2" style={{ fontWeight: 600 }}>
          Company &amp; warehouse
        </Typography>

        {/* alignItems flex-start, and both fields carry helper text, so they line up on
            the same baseline instead of stepping. */}
        <Grid container spacing={2} alignItems="flex-start" style={{ marginTop: 8 }}>
          <Grid item xs={12} sm={6}>
            <TextField
              select
              fullWidth
              size="small"
              label="Company"
              value={selectedCompany || ''}
              onChange={(e) => setSelectedCompany(e.target.value)}
              helperText="Applies to uploads and the table below"
            >
              {companies.map((c) => (
                <MenuItem key={c.id} value={c.id}>
                  {c.name}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid item xs={12} sm={6}>
            <TextField
              select
              fullWidth
              size="small"
              label="Warehouse"
              value={warehouseId}
              onChange={(e) => setWarehouseId(e.target.value)}
              helperText="Applies to uploads and the table below"
            >
              {warehouses.map((w) => (
                <MenuItem key={w.warehouse_id ?? w.id} value={w.warehouse_id ?? w.id}>
                  {w.name} ({w.code})
                </MenuItem>
              ))}
            </TextField>
          </Grid>
        </Grid>

        <Box
          mt={2}
          className={classes.dropzone}
          onClick={() => fileRef.current && fileRef.current.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            handleFiles(e.dataTransfer.files);
          }}
        >
          {uploading ? (
            <CircularProgress size={28} />
          ) : (
            <>
              <IconUpload size={28} />
              <Typography variant="subtitle1">Drop PDFs here, or click to choose</Typography>
              <Typography variant="caption" className={classes.muted}>
                Multiple files supported. Re-uploading a document already on file is
                ignored rather than duplicated.
              </Typography>
            </>
          )}
        </Box>
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf"
          multiple
          className={classes.hidden}
          onChange={(e) => handleFiles(e.target.files)}
        />
      </Paper>

      {/* ── Upload result ──────────────────────────────────────────────── */}
      {result && (
        <Box className={classes.section}>
          {result.ingested?.map((r) => (
            <Alert
              key={r.filename}
              severity={r.duplicate ? 'info' : r.warnings?.length ? 'warning' : 'success'}
              style={{ marginBottom: 6 }}
            >
              <strong>{r.filename}</strong> — {r.doc_type} {r.doc_number}, {r.lines} line(s)
              {r.duplicate
                ? ' — already received, nothing changed'
                : r.moved_stock
                ? ` — ${r.received} line(s) received into stock`
                : ` — ${r.adjusted} price adjustment(s), no stock moved`}
              {!r.duplicate && r.created_products?.length > 0 && (
                <div>
                  New products created: <strong>{r.created_products.join(', ')}</strong>
                </div>
              )}
              {Math.abs(Number(r.total_variance)) >= 1 && (
                <>
                  {' '}
                  · <span className={classes.variance}>totals differ by {money(r.total_variance)}</span>
                </>
              )}
              {r.warnings?.map((w, i) => (
                <div key={i} className={classes.mono}>
                  {w}
                </div>
              ))}
            </Alert>
          ))}
          {result.failed?.map((r) => (
            <Alert key={r.filename} severity="error" style={{ marginBottom: 6 }}>
              <strong>{r.filename}</strong> — {r.error}
            </Alert>
          ))}
        </Box>
      )}

      {/* ── Received stock ─────────────────────────────────────────────── */}
      <Box display="flex" alignItems="center" mb={1}>
        <Typography variant="subtitle2" style={{ fontWeight: 600 }}>
          Received stock
        </Typography>
        <Box flexGrow={1} />
        {Object.values(filters).some((v) => (v || '').trim()) && (
          <Typography variant="caption" className={classes.muted} style={{ marginRight: 12 }}>
            {visible.length} of {rows.length}
          </Typography>
        )}
        {Object.values(filters).some((v) => (v || '').trim()) && (
          <Button size="small" onClick={() => setFilters({})} style={{ marginRight: 8 }}>
            Clear search
          </Button>
        )}
        <Button
          size="small"
          variant="outlined"
          startIcon={<IconRefresh size={16} />}
          onClick={loadReceived}
          disabled={loading}
        >
          Refresh
        </Button>
      </Box>
      <TableContainer component={Paper} variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              {COLUMNS.map((c) => (
                <TableCell key={c.key} align={c.align}>
                  {c.label}
                </TableCell>
              ))}
            </TableRow>
            <TableRow>
              {COLUMNS.map((c) => (
                <TableCell key={c.key} style={{ paddingTop: 0, paddingBottom: 6 }}>
                  <TextField
                    variant="standard"
                    placeholder="Search"
                    value={filters[c.key] || ''}
                    onChange={(e) =>
                      setFilters((f) => ({ ...f, [c.key]: e.target.value }))
                    }
                    InputProps={{ style: { fontSize: '0.78rem' } }}
                    fullWidth
                  />
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {visible.length === 0 && !loading && (
              <TableRow>
                <TableCell colSpan={10} align="center" className={classes.muted}>
                  {!selectedCompany
                    ? 'Select a company to see its received stock.'
                    : received.length === 0
                    ? 'Nothing received yet.'
                    : 'No rows match the current search.'}
                </TableCell>
              </TableRow>
            )}
            {visible.map((r) => (
              <TableRow key={r.id} hover>
                <TableCell className={classes.mono}>{r.invoice}</TableCell>
                <TableCell>
                  {r.product_name}
                  <div className={classes.mono} style={{ color: '#7a869a' }}>
                    {r.sku_code}
                  </div>
                </TableCell>
                <TableCell className={classes.mono}>{r.batch || '—'}</TableCell>
                <TableCell>{r.expiry || '—'}</TableCell>
                <TableCell align="right">{Number(r.quantity).toLocaleString('en-IN')}</TableCell>
                <TableCell align="right">{money(r.mrp)}</TableCell>
                <TableCell align="right">{rate4(r.landing_price)}</TableCell>
                <TableCell align="right">
                  {Number(r.cn_rate || 0)
                    ? <span className={classes.variance}>-{rate4(r.cn_rate)}</span>
                    : '—'}
                </TableCell>
                <TableCell align="right">{rate4(r.final_landing_price)}</TableCell>
                <TableCell align="right">
                  <strong>{rate4(r.final_landing_inc_gst)}</strong>
                  {Number(r.gst_rate || 0) > 0 && (
                    <div className={classes.muted} style={{ fontSize: '0.7rem' }}>
                      GST {Number(r.gst_rate)}%
                    </div>
                  )}
                </TableCell>
              </TableRow>
            ))}
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

export default InventoryIngestion;
