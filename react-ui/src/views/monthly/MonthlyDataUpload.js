import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Box,
  Button,
  Typography,
  CircularProgress,
  Paper,
  Chip,
  Alert,
  Tabs,
  Tab,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Snackbar,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import {
  IconUpload,
  IconFileSpreadsheet,
  IconCheck,
  IconInfoCircle,
  IconDownload,
  IconCalendar,
} from '@tabler/icons';
import api from '../../services/api';

// ---------------------------------------------------------------------------
// Feed catalogue — the four monthly manual uploads. `columns` drives both the
// "required format" dialog and the downloadable template.
// ---------------------------------------------------------------------------
const FEEDS = [
  {
    id: 'sales',
    label: 'Busy Sales Upload',
    table: 'busy_sales_data',
    color: '#1565c0',
    byDateRange: true,
    blurb: 'Hero sales exported from Busy — any date range. Dates in the file replace existing rows on those same dates; other dates are left untouched. Not tied to the month selector.',
    columns: [
      { name: 'Date', required: true, note: 'YYYY-MM-DD — any dates; existing rows on these dates get replaced' },
      { name: 'Vch/Bill No', required: false, note: 'Voucher / bill number' },
      { name: 'Particulars', required: true, note: 'Dealer name (attributed by exact match)' },
      { name: 'Item Details', required: true, note: 'Part number' },
      { name: 'Qty.', required: true, note: 'Quantity sold' },
      { name: 'Unit', required: false, note: 'e.g. Pcs.' },
      { name: 'Price', required: false, note: 'Unit price' },
      { name: 'Amount', required: true, note: 'Line amount (₹)' },
    ],
    sample: [
      ['2026-07-01', '26-27/01429/Hero', 'Janta Auto Parts | AFM | Meerganj', '14100KCC910S', '1', 'Pcs.', '802.9', '802.9'],
      ['2026-07-01', '26-27/01429/Hero', 'Janta Auto Parts | AFM | Meerganj', '14311035000S', '5', 'Pcs.', '39.82', '199.1'],
    ],
  },
  {
    id: 'part-groups',
    label: 'Part Group Mapping',
    table: 'part_groups',
    color: '#2e7d32',
    blurb: 'Part → part-group → scheme mapping for the month. Replaces the whole mapping for the selected period.',
    columns: [
      { name: 'Sr. No.', required: false, note: 'Ignored' },
      { name: 'Part number', required: true, note: 'Matches the part number in sales data' },
      { name: 'Description', required: false, note: 'Part description' },
      { name: 'Part Group', required: true, note: 'Group this part rolls up to' },
      { name: 'Scheme', required: false, note: 'PG / Basket 1 / Basket 2 / Ancillary / Chainsets' },
    ],
    sample: [
      ['1', '20K1010S', 'CHAIN SPROCKET KIT( XTREME/HUNK)', 'Chain Sprocket Kit', 'PG'],
      ['37', '43120365H70S', 'SHOE COMP.BRAKE', 'Brake Shoe', 'PG'],
    ],
  },
  {
    id: 'qty-targets',
    label: 'Quantity Targets',
    table: 'dealer_part_group_target',
    color: '#e65100',
    blurb:
      'One row per category × part-group × dealer. Scheme is auto-filled from that month\'s ' +
      'mapping. Only the categories present in the file are replaced — other categories\' ' +
      'targets for the month are left untouched.',
    columns: [
      { name: 'Dealer', required: true, note: 'Dealer name (must exist)' },
      { name: 'Category', required: true, note: 'Must match a category name (Parts, Oil, Tyre, …)' },
      { name: 'Part Group', required: true, note: 'Must exist in this month\'s mapping' },
      { name: 'Target Qty', required: true, note: 'Target quantity for the month' },
    ],
    sample: [
      ['Janta Auto Parts | AFM | Meerganj', 'Parts', 'Clutch', '55'],
      ['Janta Auto Parts | AFM | Meerganj', 'Parts', 'Cam Chain', '3'],
    ],
  },
  {
    id: 'money-targets',
    label: 'Rupee Targets',
    table: 'dealer_money_target',
    color: '#6a1b9a',
    blurb:
      'One row per category × dealer — the ₹ sales target for the month. Only the categories ' +
      'present in the file are replaced — other categories\' targets for the month are left ' +
      'untouched.',
    columns: [
      { name: 'Dealer', required: true, note: 'Dealer name (must exist)' },
      { name: 'Category', required: true, note: 'Must match a category name (Parts, Oil, Tyre, …)' },
      { name: 'Money Target', required: true, note: 'Rupee sales target for the month' },
    ],
    sample: [
      ['Janta Auto Parts | AFM | Meerganj', 'Parts', '200000'],
      ['Khandelwal Auto Parts', 'Oil', '150000'],
    ],
  },
  {
    id: 'product-categories',
    label: 'Product Categories',
    table: 'product.category_id',
    color: '#00838f',
    noPeriod: true,
    blurb:
      'Assign products to a category. Updates the product master in place — not tied to a month. ' +
      'Products are never created: an unknown Product String is reported as a row error.',
    columns: [
      { name: 'Product String', required: true, note: 'Must match an existing product string' },
      { name: 'Category', required: true, note: 'Oil / Battery / Tyre / Accessories / Pro Parts — blank clears it' },
    ],
    sample: [
      ['14100KCC910S', 'Pro Parts'],
      ['43120365H70S', 'Accessories'],
    ],
  },
];

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];
const NOW_YEAR = 2026;
const YEARS = [NOW_YEAR - 2, NOW_YEAR - 1, NOW_YEAR, NOW_YEAR + 1];

const csvEscape = (v) => (/[",\n]/.test(v) ? `"${String(v).replace(/"/g, '""')}"` : v);
const toCsv = (feed) =>
  [feed.columns.map((c) => c.name), ...feed.sample]
    .map((r) => r.map(csvEscape).join(','))
    .join('\n');

const useStyles = makeStyles((theme) => ({
  periodBar: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(2),
    padding: theme.spacing(2),
    marginBottom: theme.spacing(3),
    borderRadius: theme.shape.borderRadius,
    backgroundColor: theme.palette.grey[50],
    border: `1px solid ${theme.palette.divider}`,
    flexWrap: 'wrap',
  },
  card: {
    padding: theme.spacing(2.5),
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    borderTop: '4px solid',
  },
  dropZone: {
    border: `2px dashed ${theme.palette.divider}`,
    borderRadius: theme.shape.borderRadius,
    padding: theme.spacing(2.5),
    textAlign: 'center',
    cursor: 'pointer',
    marginTop: theme.spacing(1.5),
    transition: 'background 0.2s, border-color 0.2s',
    '&:hover': { backgroundColor: theme.palette.action.hover },
  },
  dropZoneDisabled: {
    opacity: 0.5,
    pointerEvents: 'none',
  },
  codeCell: { fontFamily: 'monospace', fontSize: '0.8rem' },
}));

// ---------------------------------------------------------------------------
// Single feed upload card
// ---------------------------------------------------------------------------
function FeedCard({ feed, year, month, disabled, loadedRows, statusLoading, statusError, onUploaded, onSnack }) {
  const classes = useStyles();
  const inputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [showFormat, setShowFormat] = useState(false);

  // Feeds that ignore the Year / Month selector: sales (dated rows drive it) and
  // product categories (a standing product attribute, not a monthly fact).
  const periodless = feed.byDateRange || feed.noPeriod;

  // Reset transient state when the period changes.
  useEffect(() => { setFile(null); setResult(null); setError(null); }, [year, month]);

  const pick = (f) => {
    if (!f) return;
    const ext = f.name.split('.').pop().toLowerCase();
    if (!['csv', 'xls', 'xlsx'].includes(ext)) {
      setError('Only CSV, XLS, and XLSX files are accepted.');
      return;
    }
    setFile(f); setResult(null); setError(null);
  };

  const upload = async () => {
    if (!file) return;
    setUploading(true); setResult(null); setError(null);
    const fd = new FormData();
    fd.append('file', file);
    // Sales loads by the dates in the file; product categories are periodless.
    if (!periodless) {
      fd.append('year', year);
      fd.append('month', month);
    }
    try {
      const res = await api.post(`admin/monthly/${feed.id}`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      if (res.data.success) {
        setResult(res.data);
        onSnack(
          `${feed.label}: ${res.data.inserted} loaded, ${res.data.replaced} replaced`,
          'success',
        );
        setFile(null);
        onUploaded();
      } else {
        setError(res.data.msg || 'Upload failed');
      }
    } catch (err) {
      setError(err.response?.data?.msg || 'Upload failed — check the file format and try again.');
    } finally {
      setUploading(false);
    }
  };

  const downloadTemplate = () => {
    const blob = new Blob([toCsv(feed)], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${feed.id}_template.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Paper variant="outlined" className={classes.card} style={{ borderTopColor: feed.color }}>
      <Box display="flex" alignItems="flex-start" justifyContent="space-between" style={{ gap: 8 }}>
        <Box>
          <Typography variant="h5" style={{ fontWeight: 600 }}>{feed.label}</Typography>
          <Typography variant="caption" color="textSecondary" className={classes.codeCell}>
            {feed.table}
          </Typography>
        </Box>
        <Button
          size="small"
          startIcon={<IconInfoCircle size={15} />}
          onClick={() => setShowFormat(true)}
          style={{ textTransform: 'none', flexShrink: 0 }}
        >
          Format
        </Button>
      </Box>

      <Typography variant="body2" color="textSecondary" style={{ marginTop: 8, minHeight: 40 }}>
        {feed.blurb}
      </Typography>

      {/* Periodless feeds have no per-period row count, so no "loaded" chip. */}
      {!periodless && (
        <Box mt={1}>
          {statusLoading ? (
            <Chip size="small" variant="outlined" icon={<CircularProgress size={12} />} label="Checking…" />
          ) : statusError ? (
            <Chip size="small" variant="outlined" label="Status unavailable"
              style={{ color: '#c62828', borderColor: '#ef9a9a' }} />
          ) : loadedRows > 0 ? (
            <Chip
              size="small"
              icon={<IconCheck size={14} />}
              label={`${loadedRows} rows loaded for this period`}
              style={{ backgroundColor: '#e8f5e9', color: '#2e7d32' }}
            />
          ) : (
            <Chip size="small" variant="outlined" label="Nothing loaded for this period" />
          )}
        </Box>
      )}

      {/* Drop zone */}
      <Box
        className={`${classes.dropZone} ${disabled ? classes.dropZoneDisabled : ''}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); pick(e.dataTransfer.files[0]); }}
      >
        <IconFileSpreadsheet size={28} color={feed.color} />
        <Typography variant="body2" style={{ marginTop: 4 }}>
          {file ? file.name : 'Drop file or click to browse'}
        </Typography>
        <Typography variant="caption" color="textSecondary">CSV · XLS · XLSX</Typography>
      </Box>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,.xls,.xlsx"
        style={{ display: 'none' }}
        onChange={(e) => pick(e.target.files[0])}
      />

      <Box mt={1.5}>
        <Button
          fullWidth
          variant="contained"
          disabled={disabled || !file || uploading}
          onClick={upload}
          startIcon={uploading ? <CircularProgress size={15} color="inherit" /> : <IconUpload size={16} />}
          style={{ backgroundColor: disabled || !file ? undefined : feed.color, color: disabled || !file ? undefined : '#fff' }}
        >
          {uploading
            ? 'Uploading…'
            : feed.byDateRange
              ? 'Upload sales data'
              : feed.noPeriod
                ? 'Update product categories'
                : `Replace ${MONTHS[month - 1]} ${year}`}
        </Button>
      </Box>

      {error && <Box mt={1.5}><Alert severity="error">{error}</Alert></Box>}

      {result && (
        <Box mt={1.5}>
          <Alert severity={result.error_count > 0 ? 'warning' : 'success'}>
            Loaded <strong>{result.inserted}</strong> · replaced {result.replaced} · skipped {result.skipped}
            {result.error_count > 0 && <> · <strong>{result.error_count} errors</strong></>}
          </Alert>
          {result.warnings?.map((w, i) => (
            <Typography key={i} variant="caption" color="textSecondary" display="block" style={{ marginTop: 4 }}>
              ⚠ {w}
            </Typography>
          ))}
          {result.errors?.length > 0 && (
            <TableContainer component={Paper} variant="outlined" style={{ maxHeight: 180, marginTop: 8 }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell>Row</TableCell>
                    <TableCell>Value</TableCell>
                    <TableCell>Reason</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {result.errors.map((e, i) => (
                    <TableRow key={i}>
                      <TableCell>{e.row}</TableCell>
                      <TableCell className={classes.codeCell}>{e.key || '—'}</TableCell>
                      <TableCell>{e.reason}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Box>
      )}

      {/* Format dialog */}
      <Dialog open={showFormat} onClose={() => setShowFormat(false)} maxWidth="md" fullWidth>
        <DialogTitle>
          {feed.label} — required file format
          <Typography variant="body2" color="textSecondary">
            Loads into <code>{feed.table}</code>. Column names are matched case-insensitively.
          </Typography>
        </DialogTitle>
        <DialogContent dividers>
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell><strong>Column</strong></TableCell>
                  <TableCell><strong>Required</strong></TableCell>
                  <TableCell><strong>Notes</strong></TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {feed.columns.map((c) => (
                  <TableRow key={c.name}>
                    <TableCell className={classes.codeCell}>{c.name}</TableCell>
                    <TableCell>
                      {c.required
                        ? <Chip size="small" label="required" style={{ backgroundColor: '#ffebee', color: '#c62828' }} />
                        : <Chip size="small" variant="outlined" label="optional" />}
                    </TableCell>
                    <TableCell><Typography variant="body2" color="textSecondary">{c.note}</Typography></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          <Typography variant="subtitle2" style={{ marginTop: 16, marginBottom: 4 }}>Example</Typography>
          <TableContainer component={Paper} variant="outlined" style={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  {feed.columns.map((c) => (
                    <TableCell key={c.name} className={classes.codeCell}><strong>{c.name}</strong></TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {feed.sample.map((row, i) => (
                  <TableRow key={i}>
                    {row.map((v, j) => <TableCell key={j} className={classes.codeCell}>{v}</TableCell>)}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          <Alert severity="info" style={{ marginTop: 16 }}>
            {feed.byDateRange ? (
              <>Sales loads by the <strong>dates inside the file</strong> — the Year / Month selector doesn't apply.
                Rows on a given date <strong>replace</strong> existing rows for that same date; dates not in the
                file are left untouched. (e.g. having Jul 1–10 and uploading Jul 8–13 keeps 1–7, replaces 8–10,
                adds 11–13.)</>
            ) : feed.noPeriod ? (
              <>A product's category is a <strong>standing attribute</strong>, so the Year / Month selector
                doesn't apply. Each row <strong>updates the product in place</strong>; products not listed in
                the file keep whatever category they already had. Nothing is ever deleted, and a product is
                <strong> never created</strong> — an unknown Product String is reported as a row error.
                Leave <strong>Category</strong> blank to clear a product's category.</>
            ) : (
              <>The period is taken from the <strong>Year / Month</strong> selector above — you don't put it in the file.
                Uploading <strong>replaces</strong> everything already loaded for that period.</>
            )}
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button startIcon={<IconDownload size={16} />} onClick={downloadTemplate}>
            Download template CSV
          </Button>
          <Button onClick={() => setShowFormat(false)} variant="contained">Close</Button>
        </DialogActions>
      </Dialog>
    </Paper>
  );
}

// ---------------------------------------------------------------------------
// MonthlyDataUpload tab
// ---------------------------------------------------------------------------
const MonthlyDataUpload = () => {
  const classes = useStyles();
  const [tab, setTab] = useState(0);
  const [year, setYear] = useState(NOW_YEAR);
  const [month, setMonth] = useState(7); // July
  const [status, setStatus] = useState({});
  const [statusLoading, setStatusLoading] = useState(true);
  const [statusError, setStatusError] = useState(null);
  const [snack, setSnack] = useState({ open: false, msg: '', severity: 'success' });

  const showSnack = (msg, severity = 'success') => setSnack({ open: true, msg, severity });

  const fetchStatus = useCallback(async () => {
    setStatusLoading(true);
    try {
      const res = await api.get('admin/monthly/status');
      if (res.data.success) {
        setStatus(res.data.status || {});
        setStatusError(null);
      } else {
        setStatusError(res.data.msg || 'Could not load what is already uploaded.');
      }
    } catch (err) {
      // Don't swallow — a silent failure here would look identical to "nothing loaded".
      setStatusError(
        err.response?.status === 401
          ? 'Your session has expired — please log out and back in.'
          : (err.response?.data?.msg || 'Could not reach the server to check loaded data.'),
      );
    } finally {
      setStatusLoading(false);
    }
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  const periodKey = `${year}-${String(month).padStart(2, '0')}-01`;
  const ready = Boolean(year && month);
  const activeFeed = FEEDS[tab];

  return (
    <Box p={3}>
      <Typography variant="h4" style={{ fontWeight: 600 }}>Order Uploads</Typography>
      <Typography variant="body2" color="textSecondary" style={{ marginTop: 4, marginBottom: 16 }}>
        Pick a feed, set the period, then upload. Every upload replaces that period's data — it never duplicates.
      </Typography>

      {statusError && (
        <Box mb={2}>
          <Alert severity="error">
            Couldn't check what's already loaded: {statusError}
          </Alert>
        </Box>
      )}

      {/* Feed tabs */}
      <Paper elevation={0} variant="outlined" style={{ marginBottom: 16 }}>
        <Tabs
          value={tab}
          onChange={(_, v) => setTab(v)}
          variant="scrollable"
          scrollButtons="auto"
          indicatorColor="primary"
          textColor="primary"
          style={{ borderBottom: '1px solid #e0e0e0' }}
        >
          {FEEDS.map((f) => (
            <Tab
              key={f.id}
              label={f.label}
              style={{ textTransform: 'none', minHeight: 52, fontWeight: 500 }}
            />
          ))}
        </Tabs>
      </Paper>

      {/* Period selector — only for the month-scoped feeds */}
      {!(activeFeed.byDateRange || activeFeed.noPeriod) && (
        <Box className={classes.periodBar}>
          <IconCalendar size={22} />
          <Box>
            <Typography variant="subtitle1" style={{ fontWeight: 600, lineHeight: 1.2 }}>Period</Typography>
            <Typography variant="caption" color="textSecondary">
              Applies to the mapping &amp; target feeds. Busy Sales loads by the dates in its own file.
            </Typography>
          </Box>
          <FormControl size="small" variant="outlined" style={{ minWidth: 130 }}>
            <InputLabel>Month</InputLabel>
            <Select value={month} label="Month" onChange={(e) => setMonth(e.target.value)}>
              {MONTHS.map((m, i) => <MenuItem key={m} value={i + 1}>{m}</MenuItem>)}
            </Select>
          </FormControl>
          <FormControl size="small" variant="outlined" style={{ minWidth: 110 }}>
            <InputLabel>Year</InputLabel>
            <Select value={year} label="Year" onChange={(e) => setYear(e.target.value)}>
              {YEARS.map((y) => <MenuItem key={y} value={y}>{y}</MenuItem>)}
            </Select>
          </FormControl>
          <Box flexGrow={1} />
          <Chip
            color="primary"
            variant="outlined"
            icon={<IconCalendar size={15} />}
            label={`Uploading for ${MONTHS[month - 1]} ${year}`}
          />
        </Box>
      )}

      {/* Active feed */}
      <FeedCard
        key={activeFeed.id}
        feed={activeFeed}
        year={year}
        month={month}
        disabled={(activeFeed.byDateRange || activeFeed.noPeriod) ? false : !ready}
        loadedRows={status[activeFeed.id]?.[periodKey] || 0}
        statusLoading={statusLoading}
        statusError={statusError}
        onUploaded={fetchStatus}
        onSnack={showSnack}
      />

      <Snackbar
        open={snack.open}
        autoHideDuration={4000}
        onClose={() => setSnack((s) => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert
          onClose={() => setSnack((s) => ({ ...s, open: false }))}
          severity={snack.severity}
          variant="filled"
        >
          {snack.msg}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default MonthlyDataUpload;
