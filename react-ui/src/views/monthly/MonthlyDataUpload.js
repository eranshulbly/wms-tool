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
  FormControlLabel,
  Checkbox,
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
  TextField,
  Link as MuiLink,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import {
  IconUpload,
  IconFileSpreadsheet,
  IconCheck,
  IconInfoCircle,
  IconDownload,
  IconCalendar,
  IconBuildingStore,
} from '@tabler/icons';
import api from '../../services/api';
import { useWarehouse } from '../../context/WarehouseContext';

// ---------------------------------------------------------------------------
// Feed catalogue — the manual admin uploads. `columns` drives both the
// "required format" dialog and the downloadable template.
// ---------------------------------------------------------------------------
const FEEDS = [
  {
    id: 'sales',
    label: 'Busy Sales Upload',
    table: 'busy_sales_data',
    color: '#1565c0',
    byDateRange: true,
    canCreateDealers: true,
    blurb: 'Hero sales exported from Busy — any date range. Dates in the file replace existing rows on those same dates; other dates are left untouched. Not tied to the month selector.',
    columns: [
      { name: 'Date', required: true, note: 'DD-MM-YYYY — blank on a voucher\'s follow-on lines; existing rows on these dates get replaced' },
      { name: 'Vch/Bill No', required: false, note: 'Voucher / bill number (first line of the voucher only)' },
      { name: 'Particulars', required: true, note: 'Dealer name, attributed by exact match (first line of the voucher only)' },
      { name: 'Item Details', required: true, note: 'Part number' },
      { name: 'Qty', required: true, note: 'Quantity sold ("Qty." also accepted)' },
      { name: 'Unit', required: false, note: 'e.g. Pcs.' },
      { name: 'Price', required: false, note: 'Unit price' },
      { name: 'Amount', required: true, note: 'Line amount (₹)' },
    ],
    sample: [
      ['01-07-2026', '26-27/01429/Hero', 'Janta Auto Parts | AFM | Meerganj', '14100KCC910S', '1', 'Pcs.', '802.9', '802.9'],
      ['', '', '', '14311035000S', '5', 'Pcs.', '39.82', '199.1'],
    ],
  },
  {
    id: 'part-groups',
    label: 'Part Group Mapping',
    table: 'part_groups',
    color: '#2e7d32',
    needsScheme: true,
    blurb:
      'One scheme at a time. Pick the scheme and month first — the scheme is not read from '
      + 'the file — then upload the parts that belong to it. Uploading replaces that scheme for '
      + 'the selected month only; the other schemes in that month are left alone.',
    columns: [
      { name: 'Part number', required: true, note: 'Matches the part number in sales data' },
      { name: 'Part Group', required: false, note: 'Group this part rolls up to. Leave blank and the scheme name is used.' },
    ],
    sample: [
      ['20K1010S', 'Chain Sprocket Kit'],
      ['43120365H70S', 'Brake Shoe'],
      ['14100KCC910S', ''],
    ],
  },
  {
    id: 'targets',
    label: 'Dealer Targets',
    table: 'dealer_target',
    color: '#ad1457',
    twoRowHeader: true,
    blurb:
      'Every target for the month in one wide sheet — one row per dealer, one column per '
      + 'target. Row 1 says what level each column is set at, row 2 names it and gives the '
      + 'unit. Only the columns the file carries are replaced; anything it does not name is '
      + 'left untouched.',
    columns: [
      { name: 'Row 1 — level band', required: true, note: 'Above each target column: Category, Scheme, or "Part Group : <scheme>". This is what tells the loader whether "Basket 2" means the scheme or the part group of the same name.' },
      { name: 'Row 2 — name (unit)', required: true, note: 'The name exactly as it appears in the categories master or this month\'s part-group mapping, then the unit in brackets: (Rs), (Qty) or (Litres).' },
      { name: 'Dealer Name', required: true, note: 'First column. Dealer must already exist.' },
      { name: 'Each target cell', required: false, note: 'A number, or blank for "no target here". Blank is not zero — a stored 0 would show the dealer failing a target nobody set.' },
    ],
    // Two header rows, so this feed supplies its template verbatim rather than building
    // one from `columns`.
    templateRows: [
      ['', 'Category', 'Scheme', 'Scheme', 'Part Group : PG', 'Part Group : PG', 'Category', 'Category'],
      ['Dealer Name', 'Parts (Rs)', 'Basket 1 (Rs)', 'Basket 2 (Rs)', 'Brake Shoe (Qty)', 'Spark Plug (Qty)', 'Pro Parts (Rs)', 'Oil (Litres)'],
      ['Janta Auto Parts | AFM | Meerganj', '200000', '30000', '30000', '140', '200', '5000', '800'],
      ['Khandelwal Auto Parts', '25000', '3750', '3750', '20', '25', '625', '100'],
    ],
    sample: [],
  },
  {
    id: 'products',
    label: 'Products',
    table: 'product',
    color: '#00838f',
    noPeriod: true,
    blurb:
      'The product master itself — not tied to a month. Matched on Part Number: existing ' +
      'products are updated, new ones are created, nothing is ever deleted. Every column is ' +
      'optional, so a file covering just a few of them updates only those.',
    columns: [
      { name: 'Part Number', required: true, note: 'The key rows are matched on. Also accepted: Part No, Product String' },
      { name: 'Name', required: false, note: 'Product name; on a new product defaults to the description' },
      { name: 'Description', required: false, note: 'Longer description. Also accepted: Part Description' },
      { name: 'Product Category', required: false, note: 'Sub-category, e.g. HHML Parts / HDX Parts / VIDA Parts' },
      { name: 'Category', required: false, note: 'Parts / Oil / Battery / Tyre / Accessories / Publications / Pro Parts' },
      { name: 'Nickname', required: false, note: 'Short display name (max 200 chars)' },
      { name: 'UOM', required: false, note: 'Selling unit, e.g. Pcs. (max 20 chars)' },
      { name: 'Size', required: false, note: 'Packed size, e.g. 390 x 240 x 330 MM (max 100 chars)' },
      { name: 'Weight', required: false, note: 'Number, stored as-is with no unit conversion. Also accepted: Net Weight' },
      { name: 'Price', required: false, note: 'Number, up to 2 decimal places' },
      { name: 'Barcode', required: false, note: 'Must be unique across products (max 100 chars)' },
      { name: 'HSN Code', required: false, note: 'Max 20 chars. Also accepted: HSN' },
      { name: 'is_active', required: false, note: 'Y or N — defaults to active on a new product' },
    ],
    sample: [
      ['HDH96600060220FS', 'SOCKET BOLT 6X22', 'SOCKET BOLT 6X22', 'HDX Parts', 'Parts', '', 'Pcs.', '90 x 40 x 40 MM', '12', '', '', '', 'Y'],
      ['22121198900S', 'CENTER CLUTCH', 'CENTER CLUTCH', 'HHML Parts', 'Parts', '', 'Pcs.', '390 x 240 x 330 MM', '223', '', '', '', 'Y'],
    ],
  },
];

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];
// Sentinel for the "add a new scheme" row. Not a valid scheme name, so it can never
// collide with a real one.
const NEW_SCHEME = '__new__';

const NOW_YEAR = 2026;
const YEARS = [NOW_YEAR - 2, NOW_YEAR - 1, NOW_YEAR, NOW_YEAR + 1];

const csvEscape = (v) => (/[",\n]/.test(v) ? `"${String(v).replace(/"/g, '""')}"` : v);
// `templateRows` is the escape hatch for a feed whose header is not one row of column
// names — the target sheet's is two, and the level band above the names is the part an
// operator most needs an example of.
const toCsv = (feed) =>
  (feed.templateRows || [feed.columns.map((c) => c.name), ...feed.sample])
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
  // The scheme sits in its own tinted band so it reads as part of the period context
  // above it, not as one more field inside the upload form.
  schemeBar: {
    padding: theme.spacing(1.5),
    borderRadius: theme.shape.borderRadius,
    backgroundColor: theme.palette.grey[50],
    border: `1px solid ${theme.palette.divider}`,
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
function FeedCard({ feed, year, month, companyId, schemes, disabled, loadedRows, statusLoading, statusError, onUploaded, onSnack }) {
  const [scheme, setScheme] = useState('');
  const [addingScheme, setAddingScheme] = useState(false);
  const classes = useStyles();
  const inputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [showFormat, setShowFormat] = useState(false);
  // Opt-in per upload, never remembered — creating dealers should be a deliberate act
  // each time, not a setting someone turned on months ago and forgot.
  const [createDealers, setCreateDealers] = useState(false);

  // Feeds that ignore the Year / Month selector: sales (dated rows drive it) and
  // the product master (standing reference data, not a monthly fact).
  const periodless = feed.byDateRange || feed.noPeriod;

  // Reset transient state when the period or company changes — a result for one
  // company must not stay on screen while another is selected.
  useEffect(() => {
    setFile(null); setResult(null); setError(null); setCreateDealers(false);
  }, [year, month, companyId]);

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
    // Which company's rows this file becomes. Sent alongside the file for every feed —
    // the sheet itself never carries a company column.
    fd.append('company_id', companyId);
    if (feed.canCreateDealers && createDealers) fd.append('create_missing_dealers', 'true');
    // Sales loads by the dates in the file; the product master is periodless.
    if (!periodless) {
      fd.append('year', year);
      fd.append('month', month);
    }
    // The scheme is an operator choice, not a column — one upload is one basket.
    if (feed.needsScheme) fd.append('scheme', scheme);
    try {
      const res = await api.post(`admin/monthly/${feed.id}`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      if (res.data.success) {
        setResult(res.data);
        onSnack(
          feed.noPeriod
            ? `${feed.label}: ${res.data.inserted} created, ${res.data.updated ?? res.data.replaced} updated`
            : `${feed.label}: ${res.data.inserted} loaded, ${res.data.replaced} replaced`,
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

      {/* One upload is one scheme, and the scheme decides what the upload REPLACES — so
          it is answered before the file is chosen, not after. A closed list, so a typo
          can't silently create a stray basket that nothing rolls up to. There is no
          scheme master table, though, so "add a new scheme" has to stay reachable —
          it is an explicit choice in the list rather than free typing. */}
      {feed.needsScheme && (
        <Box className={classes.schemeBar} mt={1.5}>
          {addingScheme ? (
            <TextField
              fullWidth
              size="small"
              autoFocus
              label="New scheme name"
              value={scheme}
              onChange={(e) => setScheme(e.target.value)}
              helperText={
                <>
                  Creates the scheme on upload.{' '}
                  <MuiLink component="button" type="button" onClick={() => { setAddingScheme(false); setScheme(''); }}>
                    Pick an existing one instead
                  </MuiLink>
                </>
              }
            />
          ) : (
            <TextField
              select
              fullWidth
              size="small"
              required
              label="Scheme"
              value={scheme}
              onChange={(e) => {
                if (e.target.value === NEW_SCHEME) {
                  setAddingScheme(true);
                  setScheme('');
                } else {
                  setScheme(e.target.value);
                }
              }}
              helperText={
                // The period comes from the selector above, so name it here — this pair
                // is the whole scope of what the upload is about to overwrite.
                scheme
                  ? `Replaces "${scheme}" for ${MONTHS[month - 1]} ${year} only`
                  : 'Pick the scheme this file belongs to'
              }
            >
              {schemes.map((x) => (
                <MenuItem key={x.name} value={x.name}>{x.name}</MenuItem>
              ))}
              {schemes.length === 0 && (
                <MenuItem disabled value="">No schemes loaded yet</MenuItem>
              )}
              <MenuItem value={NEW_SCHEME}>＋ Add a new scheme…</MenuItem>
            </TextField>
          )}
        </Box>
      )}

      {/* Drop zone — after the scheme, because the file is meaningless without it. */}
      <Box
        className={`${classes.dropZone} ${disabled ? classes.dropZoneDisabled : ''} ${
          feed.needsScheme && !scheme.trim() ? classes.dropZoneDisabled : ''
        }`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); pick(e.dataTransfer.files[0]); }}
      >
        <IconFileSpreadsheet size={28} color={feed.color} />
        <Typography variant="body2" style={{ marginTop: 4 }}>
          {file ? file.name : 'Drop file or click to browse'}
        </Typography>
        <Typography variant="caption" color="textSecondary">
          {feed.needsScheme && !scheme.trim() ? 'Pick a scheme first' : 'CSV · XLS · XLSX'}
        </Typography>
      </Box>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,.xls,.xlsx"
        style={{ display: 'none' }}
        onChange={(e) => pick(e.target.files[0])}
      />

      {feed.canCreateDealers && (
        <Box mt={1.5}>
          <FormControlLabel
            control={
              <Checkbox
                size="small"
                checked={createDealers}
                disabled={disabled || uploading}
                onChange={(e) => setCreateDealers(e.target.checked)}
              />
            }
            label={
              <Typography variant="caption" color="textSecondary">
                Create dealers for names not yet in the system
              </Typography>
            }
          />
          <Typography variant="caption" color="textSecondary" display="block" style={{ marginLeft: 30, marginTop: -4 }}>
            Off by default — &quot;Particulars&quot; also carries ledger lines like Cash or GST.
            New dealers are created with no sales executive, so assign one before their
            sales will be attributed.
          </Typography>
        </Box>
      )}

      <Box mt={1.5}>
        <Button
          fullWidth
          variant="contained"
          disabled={disabled || !file || uploading || (feed.needsScheme && !scheme.trim())}
          onClick={upload}
          startIcon={uploading ? <CircularProgress size={15} color="inherit" /> : <IconUpload size={16} />}
          style={{ backgroundColor: disabled || !file ? undefined : feed.color, color: disabled || !file ? undefined : '#fff' }}
        >
          {uploading
            ? 'Uploading…'
            : feed.byDateRange
              ? 'Upload sales data'
              : feed.noPeriod
                ? 'Merge into product master'
                : `Replace ${MONTHS[month - 1]} ${year}`}
        </Button>
      </Box>

      {error && <Box mt={1.5}><Alert severity="error">{error}</Alert></Box>}

      {result && (
        <Box mt={1.5}>
          <Alert severity={result.error_count > 0 ? 'warning' : 'success'}>
            {feed.noPeriod ? (
              <>Created <strong>{result.inserted}</strong> · updated {result.updated ?? result.replaced} · skipped {result.skipped}</>
            ) : (
              <>Loaded <strong>{result.inserted}</strong> · replaced {result.replaced} · skipped {result.skipped}</>
            )}
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
            {/* A two-row-header feed can't be shown as one header row over a body — the
                level band IS the thing worth showing, so the sheet is rendered verbatim
                with both header rows emphasised. */}
            <Table size="small">
              {feed.templateRows ? (
                <TableBody>
                  {feed.templateRows.map((row, i) => (
                    <TableRow key={i} style={i < 2 ? { backgroundColor: '#fafafa' } : undefined}>
                      {row.map((v, j) => (
                        <TableCell key={j} className={classes.codeCell}>
                          {i < 2 ? <strong>{v}</strong> : v}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              ) : (
                <>
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
                </>
              )}
            </Table>
          </TableContainer>

          <Alert severity="info" style={{ marginTop: 16 }}>
            {feed.byDateRange ? (
              <>Sales loads by the <strong>dates inside the file</strong> — the Year / Month selector doesn't apply.
                Rows on a given date <strong>replace</strong> existing rows for that same date; dates not in the
                file are left untouched. (e.g. having Jul 1–10 and uploading Jul 8–13 keeps 1–7, replaces 8–10,
                adds 11–13.)</>
            ) : feed.noPeriod ? (
              <>The product master is <strong>standing reference data</strong>, so the Year / Month selector
                doesn't apply. Rows are <strong>merged on Part Number</strong>: a part already in the master
                is updated, a new one is created, and nothing is ever deleted — so re-uploading a corrected
                or extended file is always safe. Only the <strong>columns present in the file</strong> are
                written, and a <strong>blank cell means "no value supplied"</strong> rather than "clear this
                field" — a file carrying just Part Number and Category updates categories and leaves names
                and descriptions intact.</>
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
  const { companies, selectedCompany, setSelectedCompany } = useWarehouse();
  // Scheme names already in use, for the Part Group Mapping dropdown.
  const [schemes, setSchemes] = useState([]);
  const [tab, setTab] = useState(0);
  const [year, setYear] = useState(NOW_YEAR);
  const [month, setMonth] = useState(7); // July
  const [status, setStatus] = useState({});
  const [statusLoading, setStatusLoading] = useState(true);
  const [statusError, setStatusError] = useState(null);
  const [snack, setSnack] = useState({ open: false, msg: '', severity: 'success' });

  const showSnack = (msg, severity = 'success') => setSnack({ open: true, msg, severity });

  const fetchStatus = useCallback(async () => {
    if (!selectedCompany) { setStatus({}); setStatusLoading(false); setSchemes([]); return; }
    api
      .get('admin/monthly/schemes', { params: { company_id: selectedCompany } })
      .then((r) => setSchemes(r.data.success ? r.data.schemes : []))
      .catch(() => setSchemes([]));
    setStatusLoading(true);
    try {
      // Scoped to the selected company so "already loaded" describes the rows this
      // upload would actually replace, not another tenant's.
      const res = await api.get('admin/monthly/status', {
        params: { company_id: selectedCompany },
      });
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
  }, [selectedCompany]);

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

      {/* Company — applies to every feed. Sent with the file; the sheet itself never
          carries a company column. */}
      <Box className={classes.periodBar} mb={2}>
        <IconBuildingStore size={22} />
        <Box>
          <Typography variant="subtitle1" style={{ fontWeight: 600, lineHeight: 1.2 }}>Company</Typography>
          <Typography variant="caption" color="textSecondary">
            Every feed loads into this company. Products the upload has to create are added under it too.
          </Typography>
        </Box>
        <FormControl size="small" variant="outlined" style={{ minWidth: 220 }}>
          <InputLabel>Company</InputLabel>
          <Select
            value={selectedCompany || ''}
            label="Company"
            onChange={(e) => setSelectedCompany(e.target.value)}
          >
            <MenuItem value=""><em>Select a company</em></MenuItem>
            {companies.map((c) => <MenuItem key={c.id} value={c.id}>{c.name}</MenuItem>)}
          </Select>
        </FormControl>
        <Box flexGrow={1} />
      </Box>

      {!selectedCompany && (
        <Box mb={2}>
          <Alert severity="info">
            Pick a company before uploading — it decides which company&apos;s data is replaced.
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
        key={`${activeFeed.id}-${selectedCompany}`}
        feed={activeFeed}
        year={year}
        month={month}
        companyId={selectedCompany}
        schemes={schemes}
        disabled={!selectedCompany || ((activeFeed.byDateRange || activeFeed.noPeriod) ? false : !ready)}
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
