import React, { useCallback, useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import {
  Autocomplete,
  Box,
  Button,
  Typography,
  CircularProgress,
  Grid,
  TextField,
  Paper,
  Alert,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconSearch } from '@tabler/icons';
import { lookupSku, suggestSkus, getFeedStatus } from '../../services/tatCheckService';
import { FEEDS, UploadRow } from '../dms-uploads/DmsFeedUpload';

// TAT Check — paste a SKU and see how much is in stock, in transit (dispatched by the
// supplier, GRN not yet approved) and on PO (not yet dispatched), and the TAT that
// follows. Built from three uploads (views/dms-uploads/DmsFeedUpload.js), which admins make
// on this page, and the SKU master from Admin.


const STATUS_COLOR = {
  'In stock': 'success',
  'In PO': 'warning',
  'Not available': 'default',
};

const useStyles = makeStyles((theme) => ({
  section: { marginBottom: theme.spacing(3) },
  muted: { color: '#7a869a' },
  mono: { fontFamily: 'monospace', fontSize: '0.85rem' },
  num: { whiteSpace: 'nowrap' },
  bucketValue: { fontWeight: 600, lineHeight: 1.2 },
  bucketEmpty: { opacity: 0.45 },
}));

const nf = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 });
const fmtDate = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
};
const fmtDateTime = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
};
const errMsg = (e, fallback) => e?.response?.data?.msg || fallback;
// Module-level on purpose: this MUI version resets an Autocomplete's typed text whenever
// its getOptionLabel changes identity, i.e. on every render if defined inline.
const optionLabel = (o) => (typeof o === 'string' ? o : o.sku_code);

// In transit is shown as its expected date of arrival (dispatch date + 5 days, worked out
// by the server). A date already passed is flagged: the goods are late, or arrived and the
// GRN is not yet approved in the DMS.
const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};
const isOverdue = (iso) => Boolean(iso) && iso < todayIso();
const etaText = (eta, etaLast) => {
  if (!eta) return 'Arrival date unknown';
  const range = etaLast && etaLast !== eta ? `${fmtDate(eta)} – ${fmtDate(etaLast)}` : fmtDate(eta);
  return isOverdue(etaLast || eta) ? `Overdue · was expected ${range}` : `Expected ${range}`;
};

const statusChip = (r) => {
  const transit = r.status === 'In transit';
  return (
    <Chip
      label={transit ? etaText(r.eta) : r.status}
      color={transit ? (isOverdue(r.eta) ? 'error' : 'info') : STATUS_COLOR[r.status] || 'default'}
      size="small"
      style={{ fontWeight: 600 }}
    />
  );
};

// ── one SKU ──────────────────────────────────────────────────────────────────

const SkuResult = ({ r }) => {
  const classes = useStyles();
  return (
    <Paper variant="outlined" className={classes.section} style={{ padding: 16 }}>
      <Box display="flex" alignItems="flex-start" justifyContent="space-between" flexWrap="wrap" gap={1}>
        <Box>
          <Typography variant="h5" className={classes.mono} style={{ fontWeight: 600 }}>
            {r.sku_code}
          </Typography>
          <Typography variant="body2" className={classes.muted}>
            {r.sku_name || '—'}
          </Typography>
        </Box>
        {statusChip(r)}
      </Box>

      <Grid container spacing={1.5} style={{ marginTop: 8 }}>
        {r.buckets.map((b) => (
          <Grid item xs={4} key={b.key}>
            <Paper
              variant="outlined"
              style={{ padding: 10, height: '100%' }}
              className={b.qty > 0 ? undefined : classes.bucketEmpty}
            >
              <Typography variant="caption" className={classes.muted}>
                {b.label}
              </Typography>
              <Typography variant="h4" className={classes.bucketValue}>
                {nf.format(b.qty)}
              </Typography>
              <Typography variant="caption" component="div" style={{ fontWeight: 600 }}>
                {b.key === 'transit' && b.qty > 0 ? etaText(b.eta, b.eta_last) : b.status}
              </Typography>
            </Paper>
          </Grid>
        ))}
      </Grid>

      {!r.in_inventory_file && (
        <Typography variant="caption" className={classes.muted} component="div" style={{ marginTop: 8 }}>
          This SKU is not in the latest inventory file.
        </Typography>
      )}

      {r.transit_lines.length > 0 && (
        <Box mt={2}>
          <Typography variant="subtitle2" gutterBottom>
            In transit — dispatched, GRN not approved yet
          </Typography>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Invoice</TableCell>
                  <TableCell>Dispatched</TableCell>
                  <TableCell>Expected arrival</TableCell>
                  <TableCell>Plant</TableCell>
                  <TableCell align="right">Qty</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {r.transit_lines.map((t) => (
                  <TableRow key={`${t.billing_doc}-${t.plant}`}>
                    <TableCell className={classes.mono}>{t.billing_doc}</TableCell>
                    <TableCell className={classes.num}>{fmtDate(t.billing_date)}</TableCell>
                    <TableCell className={classes.num} style={isOverdue(t.eta) ? { color: '#b91c1c', fontWeight: 600 } : undefined}>
                      {isOverdue(t.eta) ? `Overdue · was expected ${fmtDate(t.eta)}` : fmtDate(t.eta)}
                    </TableCell>
                    <TableCell>{t.plant}</TableCell>
                    <TableCell align="right">{nf.format(t.qty)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Box>
      )}

      {r.po_lines.length > 0 && (
        <Box mt={2}>
          <Typography variant="subtitle2" gutterBottom>
            In PO — not dispatched yet
          </Typography>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>PO</TableCell>
                  <TableCell>Ordered</TableCell>
                  <TableCell align="right">Order qty</TableCell>
                  <TableCell align="right">Delivered</TableCell>
                  <TableCell align="right">Open</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {r.po_lines.map((p, i) => (
                  // eslint-disable-next-line react/no-array-index-key
                  <TableRow key={`${p.po_number}-${i}`}>
                    <TableCell>{p.po_number || '—'}</TableCell>
                    <TableCell className={classes.num}>{fmtDate(p.order_date)}</TableCell>
                    <TableCell align="right">{nf.format(p.order_qty)}</TableCell>
                    <TableCell align="right">{nf.format(p.delivered_qty)}</TableCell>
                    <TableCell align="right" style={{ fontWeight: 600 }}>
                      {nf.format(p.open_qty)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Box>
      )}
    </Paper>
  );
};

// ── when each file was last uploaded ─────────────────────────────────────────

// Labels as on the upload rows; the SKU master is the one file not in FEEDS.
const SOURCE_LABEL = { sku_master: 'SKU Master', ...Object.fromEntries(FEEDS.map((f) => [f.feed, f.label])) };

const ageText = (iso) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  if (days <= 0) return 'today';
  return days === 1 ? 'yesterday' : `${days} days ago`;
};

const DataSources = ({ sources }) => {
  const classes = useStyles();
  const missing = sources.filter((s) => !s.last_upload);
  return (
    <Paper variant="outlined" className={classes.section} style={{ padding: 16 }}>
      <Typography variant="subtitle2" gutterBottom>
        Last uploaded
      </Typography>
      {sources.map((s, i) => {
        const last = s.last_upload;
        return (
          <Box
            key={s.key}
            display="flex"
            alignItems="baseline"
            flexWrap="wrap"
            style={{ gap: 8, padding: '6px 0', borderTop: i ? '1px solid #eef0f3' : 'none' }}
          >
            <Typography variant="body2" style={{ minWidth: 170, fontWeight: 600 }}>
              {SOURCE_LABEL[s.key] || s.label}
            </Typography>
            {last ? (
              <Typography variant="body2" style={{ color: '#b91c1c', fontWeight: 600 }}>
                {fmtDateTime(last.uploaded_on)} · {ageText(last.uploaded_on)}
                {last.uploaded_by ? ` · ${last.uploaded_by}` : ''}
              </Typography>
            ) : (
              <Typography variant="body2" style={{ fontWeight: 600, color: '#b91c1c' }}>
                Not uploaded yet
              </Typography>
            )}
          </Box>
        );
      })}
      {missing.length > 0 && (
        <Typography variant="caption" style={{ color: '#b91c1c', marginTop: 8 }} component="div">
          Results are incomplete until {missing.length === 1 ? 'it is' : 'they are'} uploaded by an admin.
        </Typography>
      )}
    </Paper>
  );
};

// Admins see the files with their upload controls instead of the read-only list. The SKU
// master is only shown: it is uploaded from Admin, as PO Builder uses it too.
const FilesPanel = ({ sources, feeds, onUploaded }) => {
  const classes = useStyles();
  const master = sources.find((s) => s.key === 'sku_master')?.last_upload;
  return (
    <Paper variant="outlined" className={classes.section} style={{ padding: 16 }}>
      <Typography variant="subtitle2">Files</Typography>
      <Box py={1.5} style={{ borderBottom: '1px solid #eef0f3' }}>
        <Typography variant="subtitle2">SKU Master</Typography>
        {master ? (
          <Typography variant="caption" component="div">
            <span style={{ color: '#b91c1c', fontWeight: 600 }}>
              Last: {fmtDateTime(master.uploaded_on)} · {ageText(master.uploaded_on)}
              {master.uploaded_by ? ` · ${master.uploaded_by}` : ''}
            </span>
            <span className={classes.muted}> · update from Admin → SKU Master Upload</span>
          </Typography>
        ) : (
          <Typography variant="caption" component="div" style={{ color: '#b91c1c' }}>
            Not uploaded yet — upload it from Admin → SKU Master Upload
          </Typography>
        )}
      </Box>
      {FEEDS.map((def) => (
        <UploadRow key={def.feed} def={def} statuses={feeds.filter((f) => f.feed === def.feed)} onUploaded={onUploaded} />
      ))}
    </Paper>
  );
};

// ── page ─────────────────────────────────────────────────────────────────────

const TatCheck = () => {
  const classes = useStyles();
  const { user } = useSelector((state) => state.account);
  const isAdmin = user?.role === 'admin';

  const [q, setQ] = useState('');
  const [options, setOptions] = useState([]);
  const [suggesting, setSuggesting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState(null);
  const [error, setError] = useState('');
  const [sources, setSources] = useState(null);
  const [feeds, setFeeds] = useState([]);

  const loadStatus = useCallback(() => {
    getFeedStatus()
      .then((res) => {
        setSources(res.sources || []);
        setFeeds(res.feeds || []);
      })
      .catch(() => setSources(null));
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  // Suggestions as you type, debounced so each keystroke does not fire a request.
  useEffect(() => {
    const term = q.trim();
    if (!term) {
      setOptions([]);
      return undefined;
    }
    setSuggesting(true);
    const timer = setTimeout(() => {
      suggestSkus(term)
        .then((res) => setOptions(res.results || []))
        .catch(() => setOptions([]))
        .finally(() => setSuggesting(false));
    }, 250);
    return () => clearTimeout(timer);
  }, [q]);

  const search = async (value) => {
    const term = (typeof value === 'string' ? value : q).trim();
    if (!term) return;
    setBusy(true);
    setError('');
    try {
      const res = await lookupSku(term);
      setResults(res.results || []);
    } catch (e) {
      setResults(null);
      setError(errMsg(e, 'Could not check this SKU.'));
    } finally {
      setBusy(false);
    }
  };


  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        TAT Check
      </Typography>
      <Typography variant="body2" className={classes.muted} style={{ marginBottom: 16 }}>
        Paste a SKU code to see how much is in stock, in transit and on PO. In stock ships now; in
        transit is dispatched by Ebco but not yet GRN-approved, expected 5 days after dispatch; in PO is
        ordered but not yet dispatched.
      </Typography>

      {sources &&
        (isAdmin ? (
          <FilesPanel
            sources={sources}
            feeds={feeds}
            onUploaded={() => {
              loadStatus();
              // Results on screen were worked out from the previous file.
              if (results) search(q);
            }}
          />
        ) : (
          <DataSources sources={sources} />
        ))}

      <Paper variant="outlined" className={classes.section} style={{ padding: 16 }}>
        <Box display="flex" gap={1}>
          <Autocomplete
            freeSolo
            fullWidth
            size="small"
            options={options}
            loading={suggesting}
            filterOptions={(x) => x}
            getOptionLabel={optionLabel}
            inputValue={q}
            onInputChange={(_, v) => setQ(v)}
            // Picking a suggestion, or pressing Enter on typed text, runs the check.
            onChange={(_, v) => {
              if (!v) return;
              const code = optionLabel(v);
              setQ(code);
              search(code);
            }}
            renderOption={(props, o) => (
              <li {...props} key={o.sku_code}>
                <Box>
                  <b className={classes.mono}>{o.sku_code}</b>
                  <Typography variant="caption" color="textSecondary" component="div">
                    {o.sku_name}
                  </Typography>
                </Box>
              </li>
            )}
            renderInput={(params) => (
              <TextField {...params} placeholder="SKU code or name, e.g. PS624-16" autoFocus />
            )}
          />
          <Button
            variant="contained"
            onClick={() => search()}
            disabled={busy || !q.trim()}
            startIcon={busy ? <CircularProgress size={16} /> : <IconSearch size={16} />}
          >
            Check
          </Button>
        </Box>
      </Paper>


      {error && (
        <Alert severity="error" className={classes.section}>
          {error}
        </Alert>
      )}

      {results && results.length === 0 && (
        <Alert severity="info" className={classes.section}>
          No SKU matching &ldquo;{q.trim()}&rdquo; in the SKU master.
        </Alert>
      )}
      {results && results.length > 1 && (
        <Typography variant="body2" className={classes.muted} style={{ marginBottom: 8 }}>
          {results.length} matching SKUs{results.length === 25 ? ' (first 25 — type more of the code to narrow)' : ''}
        </Typography>
      )}
      {results && results.map((r) => <SkuResult key={r.sku_code} r={r} />)}

    </Box>
  );
};

export default TatCheck;
