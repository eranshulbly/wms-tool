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
  instructions: {
    backgroundColor: theme.palette.grey[50],
    border: `1px solid ${theme.palette.divider}`,
    borderRadius: theme.shape.borderRadius,
    padding: theme.spacing(2),
    marginBottom: theme.spacing(2),
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
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    handleFile(e.dataTransfer.files[0]);
  };

  // ── Bulk upload ───────────────────────────────────────────────────────
  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setUploadResult(null);
    setUploadError(null);

    const formData = new FormData();
    formData.append('file', file);

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
      }
    } catch (err) {
      setUploadError(
        err.response?.data?.msg || 'Upload failed — check file format and try again.'
      );
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

        <Box className={classes.instructions}>
          <Typography variant="body2" color="textSecondary">
            Upload a file with columns <code>Dealer Code</code> and <code>Town</code> to
            update multiple dealers at once. Dealers that don't exist will be created.
          </Typography>
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

        <Box display="flex" justifyContent="center">
          <Button
            variant="contained"
            color="primary"
            className={classes.uploadButton}
            onClick={handleUpload}
            disabled={!file || uploading}
            startIcon={
              uploading
                ? <CircularProgress size={16} color="inherit" />
                : <IconUpload size={16} />
            }
          >
            {uploading ? 'Uploading…' : 'Upload File'}
          </Button>
        </Box>

        {uploadError && (
          <Box mt={2}><Alert severity="error">{uploadError}</Alert></Box>
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
              <Box mt={2}>
                <Box display="flex" alignItems="center" style={{ gap: 6, marginBottom: 8 }}>
                  <IconAlertTriangle size={16} color="#c62828" />
                  <Typography variant="body2" style={{ color: '#c62828', fontWeight: 600 }}>
                    Row Errors ({uploadResult.errors.length})
                  </Typography>
                </Box>
                <TableContainer component={Paper} variant="outlined">
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell><strong>Row</strong></TableCell>
                        <TableCell><strong>Dealer Code</strong></TableCell>
                        <TableCell><strong>Reason</strong></TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {uploadResult.errors.map((e, i) => (
                        <TableRow key={i}>
                          <TableCell>{e.row}</TableCell>
                          <TableCell>{e.dealer_code || '—'}</TableCell>
                          <TableCell>{e.reason}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Box>
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
                <TableCell style={{ fontWeight: 600 }}>Town</TableCell>
                <TableCell style={{ fontWeight: 600, width: 100 }}>Action</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {tableLoading ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <TableRow key={i}>
                    {[1, 2, 3, 4, 5].map((c) => (
                      <TableCell key={c}>
                        <Box
                          style={{
                            height: 14,
                            background: '#e0e0e0',
                            borderRadius: 4,
                            width: c === 5 ? 60 : '80%',
                            animation: 'pulse 1.5s infinite',
                          }}
                        />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : dealers.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} align="center" style={{ padding: 32 }}>
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
