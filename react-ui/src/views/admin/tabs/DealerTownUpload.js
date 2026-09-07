import React, { useState, useRef, useEffect, useCallback } from 'react';
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
  Chip,
  Alert,
  Divider,
  Grid,
  TextField,
  MenuItem,
  IconButton,
  Tooltip,
  InputAdornment,
  Snackbar,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import {
  IconUpload,
  IconFileSpreadsheet,
  IconCheck,
  IconAlertTriangle,
  IconPencil,
  IconDeviceFloppy,
  IconX,
  IconSearch,
  IconRefresh,
} from '@tabler/icons';
import api from '../../../services/api';
import UploadFormatHelp from '../UploadFormatHelp';

// ---------------------------------------------------------------------------
// File format spec — drives both the "required format" dialog and the
// downloadable sample template.
// ---------------------------------------------------------------------------
const FORMAT_SPEC = {
  id: 'dealer_town',
  label: 'Dealer Master',
  table: 'dealer',
  blurb:
    'Upload the dealer master for ONE company — pick the company first, since the file ' +
    'carries no company column. Existing dealers are matched and updated; anything new ' +
    'is created under that company.',
  // Mirrors DEALER_ALL_COLUMNS / DEALER_REQUIRED_COLUMNS on the server. If the two ever
  // disagree, this panel is the one that lies to the operator.
  columns: [
    { name: 'name', required: true, note: 'Dealer name — used to match when no dealer code is given' },
    { name: 'dealer_code', required: false, note: "Optional. When present it's the match key, within this company" },
    { name: 'town', required: true, note: 'Town the dealer belongs to' },
    { name: 'latitude', required: false, note: 'Optional. Decimal degrees, e.g. 28.3670' },
    { name: 'longitude', required: false, note: 'Optional. Decimal degrees, e.g. 79.4304' },
    { name: 'phone', required: true, note: 'Contact number' },
    { name: 'address', required: true, note: 'Full postal address' },
    { name: 'gstin', required: true, note: '15-character GSTIN' },
  ],
  // Shaped on real rows from the pharma dealer master. The second leaves dealer_code and
  // the coordinates blank, because those are optional and a template that fills every
  // column teaches the operator that all of them are required.
  sample: [
    ['CHIKITSA 24.', 'D-1042', 'Bareilly', '28.3670', '79.4304', '6398296265',
     'Basement H No-7/124 Nawada Jogiyan', '09GAXPD0902H1ZK'],
    ['ANAND MEDICAL AGENCY', '', 'Puranpur', '', '', '9759010188',
     'Near Charlie Tailors Mohall Chowk', '09AHUPG0097L1ZP'],
  ],
  info: (
    <>
      Headers are matched case-insensitively, and spaces are treated as underscores — so
      <strong> Dealer Code</strong> and <strong>dealer_code</strong> are both accepted.
      <br /><br />
      <strong>name</strong>, <strong>town</strong>, <strong>phone</strong>,{' '}
      <strong>address</strong> and <strong>gstin</strong> are mandatory;{' '}
      <strong>dealer_code</strong>, <strong>latitude</strong> and <strong>longitude</strong>{' '}
      are optional.
      <br /><br />
      The whole file is validated <strong>before anything is written</strong>. A missing
      mandatory column, a blank mandatory value on any row, an unreadable coordinate, or a
      dealer code already owned by another company rejects the <strong>entire</strong>{' '}
      upload and names the rows at fault — a half-imported dealer master is worse than none,
      because you cannot tell which rows landed.
      <br /><br />
      Rows are matched <strong>within the selected company only</strong>: by{' '}
      <strong>dealer_code</strong> where the file gives one, otherwise by{' '}
      <strong>name</strong>. A match is updated; anything else is created under that
      company. The same code under a different company is a different dealer and is left
      alone.
    </>
  ),
};

const useStyles = makeStyles((theme) => ({
  section: {
    marginBottom: theme.spacing(4),
  },
  sectionTitle: {
    fontWeight: 600,
    marginBottom: theme.spacing(2),
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(1),
  },
  dropZone: {
    border: `2px dashed ${theme.palette.primary.main}`,
    borderRadius: theme.shape.borderRadius,
    padding: theme.spacing(4),
    textAlign: 'center',
    cursor: 'pointer',
    transition: 'background 0.2s',
    '&:hover': { backgroundColor: theme.palette.action.hover },
  },
  dropZoneActive: {
    backgroundColor: theme.palette.action.selected,
  },
  uploadButton: {
    marginTop: theme.spacing(2),
    minWidth: 160,
  },
  statBox: {
    textAlign: 'center',
    padding: theme.spacing(2),
    borderRadius: theme.shape.borderRadius,
    border: `1px solid ${theme.palette.divider}`,
  },
  statValue: {
    fontSize: '1.8rem',
    fontWeight: 700,
    lineHeight: 1.2,
  },
  tableContainer: {
    maxHeight: 520,
  },
  editInput: {
    '& .MuiInputBase-input': {
      padding: '6px 10px',
      fontSize: '0.875rem',
    },
  },
  townCell: {
    color: theme.palette.text.secondary,
    fontStyle: (props) => (props ? 'normal' : 'italic'),
  },
  searchBar: {
    marginBottom: theme.spacing(2),
  },
  tableToolbar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: theme.spacing(2),
    flexWrap: 'wrap',
    gap: theme.spacing(1),
  },
}));

const ACCEPTED_TYPES = '.csv,.xls,.xlsx';

// ---------------------------------------------------------------------------
// Per-row failures, as a table. Shared by both outcomes: rows the server
// REJECTED before writing anything (400 — the whole file was refused), and rows
// that failed during a write that otherwise succeeded (200). Same shape either
// way, so the operator reads one thing and fixes the same spreadsheet cells.
//
// Name is shown alongside the code because most dealers have no code, and "row
// 34 failed" is not something you can find in a file of several hundred.
// ---------------------------------------------------------------------------
const RowErrorTable = ({ errors, title }) => (
  <Box mt={2}>
    <Box display="flex" alignItems="center" style={{ gap: 6, marginBottom: 8 }}>
      <IconAlertTriangle size={16} color="#c62828" />
      <Typography variant="body2" style={{ color: '#c62828', fontWeight: 600 }}>
        {title} ({errors.length})
      </Typography>
    </Box>
    <TableContainer component={Paper} variant="outlined" style={{ maxHeight: 320 }}>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            <TableCell><strong>Row</strong></TableCell>
            <TableCell><strong>Name</strong></TableCell>
            <TableCell><strong>Dealer Code</strong></TableCell>
            <TableCell><strong>Reason</strong></TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {errors.map((e, i) => (
            <TableRow key={i}>
              <TableCell>{e.row}</TableCell>
              <TableCell>{e.name || '—'}</TableCell>
              <TableCell>{e.dealer_code || '—'}</TableCell>
              <TableCell>{e.reason}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  </Box>
);

// ---------------------------------------------------------------------------
// DealerTownUpload
// ---------------------------------------------------------------------------
const DealerTownUpload = () => {
  const classes = useStyles();
  const fileInputRef = useRef(null);

  // ── Upload state ──────────────────────────────────────────────────────
  const [file, setFile]         = useState(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const [uploadError, setUploadError]   = useState(null);
  // Rows the server refused. Separate from uploadResult because on a rejection
  // there IS no result — the file was validated and thrown back whole.
  const [rejectedRows, setRejectedRows] = useState([]);

  // ── Company ───────────────────────────────────────────────────────────
  // One upload is one company: the file has no company column, and a dealer
  // created without a company can't be seen by any rep in the mobile app.
  const [companies, setCompanies] = useState([]);
  const [companyId, setCompanyId] = useState('');

  // ── Dealer table state ────────────────────────────────────────────────
  const [dealers, setDealers]       = useState([]);
  const [tableLoading, setTableLoading] = useState(false);
  const [search, setSearch]         = useState('');
  const [editingId, setEditingId]   = useState(null);   // dealer_id being edited
  const [editValue, setEditValue]   = useState('');     // draft town value
  const [savingId, setSavingId]     = useState(null);   // dealer_id being saved

  // ── Snackbar ──────────────────────────────────────────────────────────
  const [snack, setSnack] = useState({ open: false, msg: '', severity: 'success' });
  const showSnack = (msg, severity = 'success') =>
    setSnack({ open: true, msg, severity });

  // ── Fetch dealers ─────────────────────────────────────────────────────
  const fetchDealers = useCallback(async (q = '') => {
    setTableLoading(true);
    try {
      const params = q ? { search: q } : {};
      const res = await api.get('admin/dealers', { params });
      if (res.data.success) setDealers(res.data.dealers);
    } catch {
      showSnack('Failed to load dealers', 'error');
    } finally {
      setTableLoading(false);
    }
  }, []);

  useEffect(() => { fetchDealers(); }, [fetchDealers]);

  // ── Fetch companies ───────────────────────────────────────────────────
  useEffect(() => {
    let live = true;
    api.get('companies')
      .then((res) => {
        if (!live) return;
        const cos = res.data?.companies || [];
        setCompanies(cos);
        // Only pre-select when there is no choice to make — picking one of
        // several for the admin is how a file lands on the wrong company.
        if (cos.length === 1) setCompanyId(cos[0].id);
      })
      .catch(() => live && showSnack('Failed to load companies', 'error'));
    return () => { live = false; };
  }, []);

  // Debounced search
  useEffect(() => {
    const t = setTimeout(() => fetchDealers(search), 350);
    return () => clearTimeout(t);
  }, [search, fetchDealers]);

  // ── File handling ─────────────────────────────────────────────────────
  const handleFile = (f) => {
    if (!f) return;
    const ext = f.name.split('.').pop().toLowerCase();
    if (!['csv', 'xls', 'xlsx'].includes(ext)) {
      setUploadError('Only CSV, XLS, and XLSX files are accepted.');
      return;
    }
    setFile(f);
    setUploadResult(null);
    setUploadError(null);
    setRejectedRows([]);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    handleFile(e.dataTransfer.files[0]);
  };

  // ── Bulk upload ───────────────────────────────────────────────────────
  const handleUpload = async () => {
    if (!file || !companyId) return;
    setUploading(true);
    setUploadResult(null);
    setUploadError(null);
    setRejectedRows([]);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('company_id', companyId);

    try {
      const res = await api.post('admin/dealer-town', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setUploadResult(res.data);
      if (res.data.success) {
        showSnack(
          `Done — ${res.data.updated} updated, ${res.data.created} created`,
          'success'
        );
        fetchDealers(search); // refresh table
      } else {
        setUploadError(res.data.msg || 'Upload failed');
        setRejectedRows(res.data.errors || []);
      }
    } catch (err) {
      // A validation rejection is a 400, so it lands here rather than above. The
      // body carries the offending rows; keep them, they are the whole point.
      setUploadError(
        err.response?.data?.msg || 'Upload failed — check file format and try again.'
      );
      setRejectedRows(err.response?.data?.errors || []);
    } finally {
      setUploading(false);
    }
  };

  // ── Inline edit ───────────────────────────────────────────────────────
  const startEdit = (dealer) => {
    setEditingId(dealer.dealer_id);
    setEditValue(dealer.town || '');
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditValue('');
  };

  const saveEdit = async (dealerId) => {
    setSavingId(dealerId);
    try {
      const res = await api.patch(`admin/dealers/${dealerId}/town`, { town: editValue });
      if (res.data.success) {
        setDealers((prev) =>
          prev.map((d) =>
            d.dealer_id === dealerId ? { ...d, town: editValue } : d
          )
        );
        showSnack('Town updated', 'success');
        cancelEdit();
      } else {
        showSnack(res.data.msg || 'Save failed', 'error');
      }
    } catch (err) {
      showSnack(err.response?.data?.msg || 'Save failed', 'error');
    } finally {
      setSavingId(null);
    }
  };

  const handleEditKeyDown = (e, dealerId) => {
    if (e.key === 'Enter') saveEdit(dealerId);
    if (e.key === 'Escape') cancelEdit();
  };

  // ── Render ────────────────────────────────────────────────────────────
  return (
    <Box p={3}>

      {/* ── Section 1: Bulk Upload ──────────────────────────────────── */}
      <Box className={classes.section}>
        <Typography variant="h5" className={classes.sectionTitle}>
          <IconUpload size={18} />
          Bulk Upload (CSV / Excel)
        </Typography>

        <UploadFormatHelp spec={FORMAT_SPEC} />

        {/* Company — asked before the file, because it decides which dealers the
            rows match and which company any new dealer is created under. */}
        <Box mb={2} mt={2} style={{ maxWidth: 360 }}>
          <TextField
            select
            fullWidth
            required
            size="small"
            variant="outlined"
            label="Company"
            value={companyId}
            onChange={(e) => setCompanyId(e.target.value)}
            helperText="Every row in the file belongs to this company. Dealers that don't exist here are created under it."
          >
            {companies.map((c) => (
              <MenuItem key={c.id} value={c.id}>{c.name}</MenuItem>
            ))}
          </TextField>
        </Box>

        {/* Drop zone */}
        <Box
          className={`${classes.dropZone} ${dragging ? classes.dropZoneActive : ''}`}
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
        >
          <IconFileSpreadsheet size={36} color="#1976d2" />
          <Typography variant="h6" style={{ marginTop: 8 }}>
            {file ? file.name : 'Drop file here or click to browse'}
          </Typography>
          <Typography variant="caption" color="textSecondary">
            CSV · XLS · XLSX
          </Typography>
          {file && (
            <Box mt={1}>
              <Chip
                label={`${file.name}  (${(file.size / 1024).toFixed(1)} KB)`}
                color="primary"
                variant="outlined"
                size="small"
              />
            </Box>
          )}
        </Box>

        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_TYPES}
          style={{ display: 'none' }}
          onChange={(e) => handleFile(e.target.files[0])}
        />

        <Box display="flex" flexDirection="column" alignItems="center">
          <Button
            variant="contained"
            color="primary"
            className={classes.uploadButton}
            onClick={handleUpload}
            disabled={!file || !companyId || uploading}
            startIcon={
              uploading
                ? <CircularProgress size={16} color="inherit" />
                : <IconUpload size={16} />
            }
          >
            {uploading ? 'Uploading…' : 'Upload File'}
          </Button>
          {/* Says WHY the button is dead, rather than leaving it greyed out. */}
          {file && !companyId && (
            <Typography variant="caption" color="textSecondary" style={{ marginTop: 6 }}>
              Select a company to upload.
            </Typography>
          )}
        </Box>

        {uploadError && (
          <Box mt={2}><Alert severity="error">{uploadError}</Alert></Box>
        )}

        {/* Nothing was saved when these are present — the message above says so;
            this is the list of cells to go and fix. */}
        {rejectedRows.length > 0 && (
          <RowErrorTable errors={rejectedRows} title="Rows to fix — nothing was uploaded" />
        )}

        {/* Upload result summary */}
        {uploadResult?.success && (
          <Box mt={2} p={2} border={1} borderColor="divider" borderRadius={1}>
            <Box display="flex" alignItems="center" style={{ gap: 8, marginBottom: 12 }}>
              <IconCheck size={18} color="#2e7d32" />
              <Typography variant="subtitle1" style={{ fontWeight: 600, color: '#2e7d32' }}>
                Upload Complete
              </Typography>
            </Box>
            <Grid container spacing={2}>
              {[
                { label: 'Updated', value: uploadResult.updated, color: '#1565c0' },
                { label: 'Created', value: uploadResult.created, color: '#2e7d32' },
                { label: 'Skipped', value: uploadResult.skipped, color: '#e65100' },
                { label: 'Errors',  value: uploadResult.errors?.length || 0, color: '#c62828' },
              ].map(({ label, value, color }) => (
                <Grid item xs={6} sm={3} key={label}>
                  <Box className={classes.statBox}>
                    <Typography className={classes.statValue} style={{ color }}>
                      {value}
                    </Typography>
                    <Typography variant="caption" color="textSecondary">{label}</Typography>
                  </Box>
                </Grid>
              ))}
            </Grid>

            {uploadResult.errors?.length > 0 && (
              <RowErrorTable errors={uploadResult.errors} title="Row Errors" />
            )}
          </Box>
        )}
      </Box>

      <Divider />

      {/* ── Section 2: Dealer Table ─────────────────────────────────── */}
      <Box className={classes.section} mt={3}>
        <Box className={classes.tableToolbar}>
          <Typography variant="h5" className={classes.sectionTitle} style={{ marginBottom: 0 }}>
            All Dealers
            {!tableLoading && (
              <Typography
                component="span"
                variant="caption"
                color="textSecondary"
                style={{ marginLeft: 8, fontWeight: 400 }}
              >
                ({dealers.length} dealers)
              </Typography>
            )}
          </Typography>

          <Box display="flex" alignItems="center" style={{ gap: 8 }}>
            <TextField
              size="small"
              variant="outlined"
              placeholder="Search by name or code…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ width: 260 }}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <IconSearch size={16} />
                  </InputAdornment>
                ),
                endAdornment: search ? (
                  <InputAdornment position="end">
                    <IconButton size="small" onClick={() => setSearch('')}>
                      <IconX size={14} />
                    </IconButton>
                  </InputAdornment>
                ) : null,
              }}
            />
            <Tooltip title="Refresh">
              <IconButton size="small" onClick={() => fetchDealers(search)}>
                <IconRefresh size={18} />
              </IconButton>
            </Tooltip>
          </Box>
        </Box>

        <TableContainer component={Paper} variant="outlined" className={classes.tableContainer}>
          <Table stickyHeader size="small">
            <TableHead>
              <TableRow>
                <TableCell style={{ fontWeight: 600 }}>#</TableCell>
                <TableCell style={{ fontWeight: 600 }}>Dealer Name</TableCell>
                <TableCell style={{ fontWeight: 600 }}>Dealer Code</TableCell>
                <TableCell style={{ fontWeight: 600 }}>Company</TableCell>
                <TableCell style={{ fontWeight: 600 }}>Town</TableCell>
                <TableCell style={{ fontWeight: 600, width: 100 }}>Action</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {tableLoading ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <TableRow key={i}>
                    {[1, 2, 3, 4, 5, 6].map((c) => (
                      <TableCell key={c}>
                        <Box
                          style={{
                            height: 14,
                            background: '#e0e0e0',
                            borderRadius: 4,
                            width: c === 6 ? 60 : '80%',
                            animation: 'pulse 1.5s infinite',
                          }}
                        />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : dealers.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} align="center" style={{ padding: 32 }}>
                    <Typography variant="body2" color="textSecondary">
                      {search ? `No dealers matching "${search}"` : 'No dealers found'}
                    </Typography>
                  </TableCell>
                </TableRow>
              ) : (
                dealers.map((dealer, idx) => {
                  const isEditing = editingId === dealer.dealer_id;
                  const isSaving  = savingId  === dealer.dealer_id;

                  return (
                    <TableRow key={dealer.dealer_id} hover>
                      <TableCell style={{ color: '#9e9e9e', width: 40 }}>
                        {idx + 1}
                      </TableCell>
                      <TableCell>{dealer.name}</TableCell>
                      <TableCell>
                        {dealer.dealer_code
                          ? <code style={{ fontSize: '0.8rem' }}>{dealer.dealer_code}</code>
                          : <span style={{ color: '#bdbdbd' }}>—</span>}
                      </TableCell>

                      {/* Company — a blank one is a real problem, not a cosmetic
                          gap: the mobile app scopes every read by company, so an
                          unassigned dealer is invisible to every rep. Flagged
                          rather than dashed out like an ordinary missing value. */}
                      <TableCell>
                        {dealer.company_name ? (
                          <Typography variant="body2">{dealer.company_name}</Typography>
                        ) : (
                          <Tooltip title="No company — this dealer is hidden from the mobile app until one is assigned">
                            <Chip
                              size="small"
                              variant="outlined"
                              icon={<IconAlertTriangle size={13} />}
                              label="Unassigned"
                              style={{ color: '#ed6c02', borderColor: '#ed6c02' }}
                            />
                          </Tooltip>
                        )}
                      </TableCell>

                      {/* Town — view or edit */}
                      <TableCell>
                        {isEditing ? (
                          <TextField
                            autoFocus
                            size="small"
                            variant="outlined"
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            onKeyDown={(e) => handleEditKeyDown(e, dealer.dealer_id)}
                            placeholder="Enter town"
                            className={classes.editInput}
                            style={{ width: 200 }}
                          />
                        ) : (
                          <Typography
                            variant="body2"
                            style={{
                              color: dealer.town ? 'inherit' : '#bdbdbd',
                              fontStyle: dealer.town ? 'normal' : 'italic',
                            }}
                          >
                            {dealer.town || 'Not set'}
                          </Typography>
                        )}
                      </TableCell>

                      {/* Actions */}
                      <TableCell>
                        {isEditing ? (
                          <Box display="flex" alignItems="center" style={{ gap: 4 }}>
                            <Tooltip title="Save (Enter)">
                              <IconButton
                                size="small"
                                onClick={() => saveEdit(dealer.dealer_id)}
                                disabled={isSaving}
                                style={{ color: '#2e7d32' }}
                              >
                                {isSaving
                                  ? <CircularProgress size={14} />
                                  : <IconDeviceFloppy size={16} />}
                              </IconButton>
                            </Tooltip>
                            <Tooltip title="Cancel (Esc)">
                              <IconButton
                                size="small"
                                onClick={cancelEdit}
                                disabled={isSaving}
                                style={{ color: '#c62828' }}
                              >
                                <IconX size={16} />
                              </IconButton>
                            </Tooltip>
                          </Box>
                        ) : (
                          <Tooltip title="Edit town">
                            <IconButton
                              size="small"
                              onClick={() => startEdit(dealer)}
                              style={{ color: '#1565c0' }}
                            >
                              <IconPencil size={16} />
                            </IconButton>
                          </Tooltip>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Box>

      {/* Snackbar */}
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

export default DealerTownUpload;
