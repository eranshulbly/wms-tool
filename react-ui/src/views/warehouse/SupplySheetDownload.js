import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Grid,
  Card,
  CardContent,
  Typography,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  TextField,
  Box,
  CircularProgress,
  Snackbar,
  Alert,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Checkbox,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  InputAdornment,
  IconButton,
  Tooltip,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import {
  IconDownload,
  IconEye,
  IconFilter,
  IconRoute,
  IconX,
  IconFileText,
  IconSearch,
  IconAlertTriangle,
} from '@tabler/icons';
import { gridSpacing } from '../../store/constant';
import { useWarehouse } from '../../context/WarehouseContext';
import { useSnackbar } from '../../hooks/useSnackbar';
import {
  getSupplySheetDealers,
  getSupplySheetRoutes,
  getRouteDealers,
  generateSupplySheet,
} from '../../services/supplySheetService';

const useStyles = makeStyles((theme) => ({
  pageHeader: {
    marginBottom: theme.spacing(3),
    padding: theme.spacing(3),
    background: 'linear-gradient(135deg, #1a237e 0%, #283593 100%)',
    color: 'white',
    borderRadius: theme.shape.borderRadius,
  },
  sectionCard: {
    marginBottom: theme.spacing(2),
  },
  sectionTitle: {
    fontWeight: 600,
    marginBottom: theme.spacing(2),
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(1),
  },
  formControl: {
    minWidth: 220,
  },
  dealerChip: {
    margin: theme.spacing(0.25),
  },
  chipBox: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 4,
    padding: theme.spacing(1),
    minHeight: 48,
    border: `1px solid ${theme.palette.divider}`,
    borderRadius: theme.shape.borderRadius,
    backgroundColor: theme.palette.background.paper,
  },
  actionArea: {
    display: 'flex',
    gap: theme.spacing(2),
    justifyContent: 'center',
    padding: theme.spacing(3),
  },
  previewButton: {
    backgroundColor: '#1565c0',
    color: 'white',
    minWidth: 180,
    height: 52,
    '&:hover': { backgroundColor: '#0d47a1' },
    '&:disabled': { backgroundColor: theme.palette.action.disabledBackground },
  },
  downloadButton: {
    backgroundColor: '#2e7d32',
    color: 'white',
    minWidth: 180,
    height: 52,
    '&:hover': { backgroundColor: '#1b5e20' },
    '&:disabled': { backgroundColor: theme.palette.action.disabledBackground },
  },
  pdfFrame: {
    width: '100%',
    height: '75vh',
    border: 'none',
  },
  routeHint: {
    fontSize: '0.75rem',
    color: theme.palette.text.secondary,
    marginTop: theme.spacing(0.5),
  },
  selectedCount: {
    fontSize: '0.75rem',
    color: theme.palette.primary.main,
    fontWeight: 600,
    marginTop: theme.spacing(0.5),
  },
  clearBtn: {
    fontSize: '0.7rem',
    padding: '2px 8px',
    color: theme.palette.error.main,
  },
  dealerTableContainer: {
    maxHeight: 360,
    border: `1px solid ${theme.palette.divider}`,
    borderRadius: theme.shape.borderRadius,
  },
  dealerRow: {
    cursor: 'pointer',
    '&:hover': {
      backgroundColor: theme.palette.action.hover,
    },
  },
  dealerRowSelected: {
    backgroundColor: theme.palette.primary.light + '22',
    '&:hover': {
      backgroundColor: theme.palette.primary.light + '44',
    },
  },
  searchField: {
    marginBottom: theme.spacing(1),
  },
  tableToolbar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: theme.spacing(1),
    gap: theme.spacing(1),
    flexWrap: 'wrap',
  },
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildDealerMap(dealers) {
  const map = {};
  dealers.forEach((d) => { map[d.dealer_id] = d; });
  return map;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const SupplySheetDownload = () => {
  const classes = useStyles();
  const { selectedWarehouse: warehouse, selectedCompany: company } = useWarehouse();
  const { snackbar, showSnackbar, hideSnackbar } = useSnackbar();

  // Reference data
  const [allDealers, setAllDealers]         = useState([]);
  const [routes, setRoutes]                 = useState([]);
  const [dealerMap, setDealerMap]           = useState({});
  const [loadingDealers, setLoadingDealers] = useState(false);

  // Form state
  const [selectedRoute, setSelectedRoute] = useState('');
  const [selectedIds, setSelectedIds]     = useState([]);  // dealer_id[]
  const [dealerSearch, setDealerSearch]   = useState('');

  // PDF state
  const [pdfObjectUrl, setPdfObjectUrl] = useState(null);
  const [generating, setGenerating]     = useState(false);
  const [previewOpen, setPreviewOpen]   = useState(false);
  const [confirmOpen, setConfirmOpen]   = useState(false);
  const prevUrlRef = useRef(null);

  // ── Load routes once ───────────────────────────────────────────────────
  useEffect(() => {
    getSupplySheetRoutes()
      .then((data) => { if (data.success) setRoutes(data.routes); })
      .catch(() => {});
  }, []);

  // ── Load dealers when warehouse/company change ─────────────────────────
  useEffect(() => {
    if (!warehouse || !company) return;
    setLoadingDealers(true);
    setSelectedIds([]);
    setSelectedRoute('');
    setDealerSearch('');
    setPdfObjectUrl(null);

    getSupplySheetDealers(warehouse, company)
      .then((data) => {
        if (data.success) {
          setAllDealers(data.dealers);
          setDealerMap(buildDealerMap(data.dealers));
        }
      })
      .catch(() => showSnackbar('Failed to load dealers', 'error'))
      .finally(() => setLoadingDealers(false));
  }, [warehouse, company]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Route selected → auto-populate dealers ─────────────────────────────
  const handleRouteChange = useCallback(
    async (routeId) => {
      setSelectedRoute(routeId);
      if (!routeId) return;

      try {
        const data = await getRouteDealers(routeId, warehouse, company);
        if (data.success) {
          const routeDealerIds = data.dealers.map((d) => d.dealer_id);
          setSelectedIds((prev) => {
            const merged = new Set([...prev, ...routeDealerIds]);
            return Array.from(merged);
          });
          setDealerMap((prev) => ({ ...prev, ...buildDealerMap(data.dealers) }));
        }
      } catch {
        showSnackbar('Failed to load route dealers', 'error');
      }
    },
    [warehouse, company, showSnackbar]
  );

  // ── Dealer table selection ─────────────────────────────────────────────
  const toggleDealer = (dealerId) => {
    setSelectedIds((prev) =>
      prev.includes(dealerId)
        ? prev.filter((id) => id !== dealerId)
        : [...prev, dealerId]
    );
  };

  const handleRemoveDealer = (dealerId) => {
    setSelectedIds((prev) => prev.filter((id) => id !== dealerId));
  };

  const handleClearAll = () => setSelectedIds([]);

  const handleSelectAll = () => {
    setSelectedIds(filteredDealers.map((d) => d.dealer_id));
  };

  // ── Client-side dealer search filter ──────────────────────────────────
  const filteredDealers = allDealers.filter((d) => {
    if (!dealerSearch.trim()) return true;
    const q = dealerSearch.toLowerCase();
    return (
      d.name.toLowerCase().includes(q) ||
      (d.town || '').toLowerCase().includes(q) ||
      (d.dealer_code || '').toLowerCase().includes(q)
    );
  });

  // ── Generate PDF ───────────────────────────────────────────────────────
  // finalize=false → preview only (no state changes)
  // finalize=true  → backend moves Invoiced orders to Dispatch Ready
  const generate = useCallback(async (finalize = false) => {
    if (!warehouse || !company || selectedIds.length === 0) return null;

    setGenerating(true);
    if (prevUrlRef.current) {
      URL.revokeObjectURL(prevUrlRef.current);
      prevUrlRef.current = null;
    }
    setPdfObjectUrl(null);

    try {
      const blob = await generateSupplySheet({
        warehouse_id: Number(warehouse),
        company_id:   Number(company),
        dealer_ids:   selectedIds,
        finalize,
      });
      const url = URL.createObjectURL(blob);
      // Only cache the URL for preview (not for finalized downloads)
      if (!finalize) {
        prevUrlRef.current = url;
        setPdfObjectUrl(url);
      }
      return url;
    } catch {
      showSnackbar('Failed to generate supply sheet', 'error');
      return null;
    } finally {
      setGenerating(false);
    }
  }, [warehouse, company, selectedIds, showSnackbar]);

  const handlePreview = async () => {
    const url = pdfObjectUrl || (await generate(false));
    if (url) setPreviewOpen(true);
  };

  // Opens the warning dialog — actual download happens in handleConfirmDownload
  const handleDownloadClick = () => {
    setPreviewOpen(false); // close preview dialog if open
    setConfirmOpen(true);
  };

  const handleConfirmDownload = async () => {
    setConfirmOpen(false);
    const url = await generate(true); // finalize=true: always fresh + transitions orders
    if (!url) return;

    const link = document.createElement('a');
    link.href = url;
    link.download = `supply_sheet_${new Date().toISOString().split('T')[0]}.pdf`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url); // finalized URL — not cached

    showSnackbar(
      `Supply sheet downloaded. Orders for ${selectedIds.length} dealer${selectedIds.length > 1 ? 's' : ''} moved to Dispatch Ready.`,
      'success'
    );

    // Refresh dealer list — finalized orders are now Dispatch Ready (no longer Invoiced)
    setSelectedIds([]);
    setSelectedRoute('');
    setDealerSearch('');
    if (warehouse && company) {
      setLoadingDealers(true);
      getSupplySheetDealers(warehouse, company)
        .then((data) => {
          if (data.success) {
            setAllDealers(data.dealers);
            setDealerMap(buildDealerMap(data.dealers));
          }
        })
        .catch(() => {})
        .finally(() => setLoadingDealers(false));
    }
  };

  // Cleanup object URL on unmount
  useEffect(() => {
    return () => {
      if (prevUrlRef.current) URL.revokeObjectURL(prevUrlRef.current);
    };
  }, []);

  // Invalidate cached PDF whenever inputs change
  useEffect(() => {
    if (prevUrlRef.current) {
      URL.revokeObjectURL(prevUrlRef.current);
      prevUrlRef.current = null;
    }
    setPdfObjectUrl(null);
  }, [warehouse, company, selectedIds]);

  const canGenerate = !!warehouse && !!company && selectedIds.length > 0;

  const allFilteredSelected =
    filteredDealers.length > 0 &&
    filteredDealers.every((d) => selectedIds.includes(d.dealer_id));

  const someFilteredSelected =
    filteredDealers.some((d) => selectedIds.includes(d.dealer_id)) &&
    !allFilteredSelected;

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <Grid container spacing={gridSpacing}>

      {/* Header */}
      <Grid item xs={12}>
        <Box className={classes.pageHeader}>
          <Typography variant="h3" style={{ color: 'white', fontWeight: 700 }}>
            Marketing Supply Sheet
          </Typography>
          <Typography variant="subtitle1" style={{ color: 'rgba(255,255,255,0.8)', marginTop: 4 }}>
            Select dealers and generate a PDF supply sheet for invoiced orders
          </Typography>
        </Box>
      </Grid>

      {/* ── Section: Route + Dealer Selection ───────────────────────── */}
      <Grid item xs={12}>
        <Card className={classes.sectionCard}>
          <CardContent>
            <Typography variant="h4" className={classes.sectionTitle}>
              <IconFilter size={18} />
              Dealer Selection
            </Typography>

            <Grid container spacing={2} alignItems="flex-start">

              {/* Route selector */}
              <Grid item xs={12} sm={6} md={4}>
                <FormControl variant="outlined" fullWidth className={classes.formControl}>
                  <InputLabel>Route (optional)</InputLabel>
                  <Select
                    value={selectedRoute}
                    onChange={(e) => handleRouteChange(e.target.value)}
                    label="Route (optional)"
                    startAdornment={<IconRoute size={16} style={{ marginRight: 8 }} />}
                  >
                    <MenuItem value="">
                      <em>No route filter</em>
                    </MenuItem>
                    {routes.map((r) => (
                      <MenuItem key={r.route_id} value={r.route_id}>
                        {r.name}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <Typography className={classes.routeHint}>
                  Selecting a route auto-adds its dealers to the selection below
                </Typography>
              </Grid>

              {/* Dealer searchable table */}
              <Grid item xs={12} md={8}>
                {/* Toolbar */}
                <Box className={classes.tableToolbar}>
                  <TextField
                    size="small"
                    variant="outlined"
                    placeholder="Search dealers by name, code or town…"
                    value={dealerSearch}
                    onChange={(e) => setDealerSearch(e.target.value)}
                    className={classes.searchField}
                    style={{ flex: 1, maxWidth: 380 }}
                    InputProps={{
                      startAdornment: (
                        <InputAdornment position="start">
                          <IconSearch size={16} />
                        </InputAdornment>
                      ),
                      endAdornment: dealerSearch ? (
                        <InputAdornment position="end">
                          <IconButton size="small" onClick={() => setDealerSearch('')}>
                            <IconX size={14} />
                          </IconButton>
                        </InputAdornment>
                      ) : null,
                    }}
                  />
                  <Box display="flex" alignItems="center" style={{ gap: 8 }}>
                    <Typography className={classes.selectedCount}>
                      {selectedIds.length} / {allDealers.length} selected
                    </Typography>
                    {selectedIds.length > 0 && (
                      <Button
                        size="small"
                        className={classes.clearBtn}
                        onClick={handleClearAll}
                      >
                        Clear all
                      </Button>
                    )}
                  </Box>
                </Box>

                <TableContainer component={Paper} variant="outlined" className={classes.dealerTableContainer}>
                  <Table stickyHeader size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell padding="checkbox" style={{ width: 48 }}>
                          <Checkbox
                            size="small"
                            checked={allFilteredSelected}
                            indeterminate={someFilteredSelected}
                            onChange={() =>
                              allFilteredSelected ? handleClearAll() : handleSelectAll()
                            }
                            disabled={loadingDealers || filteredDealers.length === 0}
                          />
                        </TableCell>
                        <TableCell style={{ fontWeight: 600 }}>Dealer Name</TableCell>
                        <TableCell style={{ fontWeight: 600 }}>Code</TableCell>
                        <TableCell style={{ fontWeight: 600 }}>Town</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {loadingDealers ? (
                        Array.from({ length: 5 }).map((_, i) => (
                          <TableRow key={i}>
                            {[1, 2, 3, 4].map((c) => (
                              <TableCell key={c}>
                                <Box style={{ height: 14, background: '#e0e0e0', borderRadius: 4, width: '75%' }} />
                              </TableCell>
                            ))}
                          </TableRow>
                        ))
                      ) : filteredDealers.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={4} align="center" style={{ padding: 24 }}>
                            <Typography variant="body2" color="textSecondary">
                              {dealerSearch
                                ? `No dealers matching "${dealerSearch}"`
                                : 'No dealers available for this warehouse / company'}
                            </Typography>
                          </TableCell>
                        </TableRow>
                      ) : (
                        filteredDealers.map((d) => {
                          const isSelected = selectedIds.includes(d.dealer_id);
                          return (
                            <TableRow
                              key={d.dealer_id}
                              hover
                              onClick={() => toggleDealer(d.dealer_id)}
                              className={isSelected ? classes.dealerRowSelected : classes.dealerRow}
                            >
                              <TableCell padding="checkbox">
                                <Checkbox
                                  size="small"
                                  checked={isSelected}
                                  onChange={() => toggleDealer(d.dealer_id)}
                                  onClick={(e) => e.stopPropagation()}
                                />
                              </TableCell>
                              <TableCell>{d.name}</TableCell>
                              <TableCell>
                                {d.dealer_code
                                  ? <code style={{ fontSize: '0.8rem' }}>{d.dealer_code}</code>
                                  : <span style={{ color: '#bdbdbd' }}>—</span>}
                              </TableCell>
                              <TableCell>
                                <Typography variant="body2" color="textSecondary">
                                  {d.town || '—'}
                                </Typography>
                              </TableCell>
                            </TableRow>
                          );
                        })
                      )}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Grid>
            </Grid>

            {/* Selected dealer chips */}
            {selectedIds.length > 0 && (
              <Box mt={2}>
                <Typography variant="caption" color="textSecondary" display="block" gutterBottom>
                  Selected dealers — click × to remove
                </Typography>
                <Box className={classes.chipBox}>
                  {selectedIds.map((id) => {
                    const d = dealerMap[id];
                    return d ? (
                      <Chip
                        key={id}
                        label={`${d.name}${d.town ? ` (${d.town})` : ''}`}
                        size="small"
                        className={classes.dealerChip}
                        onDelete={() => handleRemoveDealer(id)}
                        deleteIcon={<IconX size={12} />}
                        color="primary"
                        variant="outlined"
                      />
                    ) : null;
                  })}
                </Box>
              </Box>
            )}
          </CardContent>
        </Card>
      </Grid>

      {/* ── Section: Actions ──────────────────────────────────────────── */}
      <Grid item xs={12}>
        <Card>
          <Box className={classes.actionArea}>
            <Tooltip
              title={
                !canGenerate
                  ? 'Select at least one dealer'
                  : 'Preview supply sheet PDF in browser'
              }
            >
              <span>
                <Button
                  variant="contained"
                  className={classes.previewButton}
                  onClick={handlePreview}
                  disabled={!canGenerate || generating}
                  startIcon={
                    generating ? <CircularProgress size={18} color="inherit" /> : <IconEye size={20} />
                  }
                >
                  {generating ? 'Generating…' : 'Preview PDF'}
                </Button>
              </span>
            </Tooltip>

            <Tooltip
              title={
                !canGenerate
                  ? 'Select at least one dealer'
                  : 'Download supply sheet — moves orders to Dispatch Ready'
              }
            >
              <span>
                <Button
                  variant="contained"
                  className={classes.downloadButton}
                  onClick={handleDownloadClick}
                  disabled={!canGenerate || generating}
                  startIcon={<IconDownload size={20} />}
                >
                  Download PDF
                </Button>
              </span>
            </Tooltip>
          </Box>

          {!canGenerate && (
            <Box pb={2} textAlign="center">
              <Typography variant="caption" color="textSecondary">
                {selectedIds.length === 0
                  ? 'Select at least one dealer above'
                  : 'Select a warehouse and company'}
              </Typography>
            </Box>
          )}
        </Card>
      </Grid>

      {/* ── PDF Preview Dialog ─────────────────────────────────────────── */}
      <Dialog
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        maxWidth="xl"
        fullWidth
        PaperProps={{ style: { height: '90vh' } }}
      >
        <DialogTitle>
          <Box display="flex" alignItems="center" justifyContent="space-between">
            <Box display="flex" alignItems="center" style={{ gap: 8 }}>
              <IconFileText size={20} />
              <Typography variant="h4">Supply Sheet Preview</Typography>
            </Box>
            <IconButton size="small" onClick={() => setPreviewOpen(false)}>
              <IconX size={18} />
            </IconButton>
          </Box>
        </DialogTitle>

        <DialogContent dividers style={{ padding: 0 }}>
          {pdfObjectUrl ? (
            <iframe
              src={pdfObjectUrl}
              title="Supply Sheet Preview"
              className={classes.pdfFrame}
            />
          ) : (
            <Box display="flex" alignItems="center" justifyContent="center" height="100%">
              <CircularProgress />
            </Box>
          )}
        </DialogContent>

        <DialogActions>
          <Button onClick={() => setPreviewOpen(false)}>Close</Button>
          <Button
            variant="contained"
            color="primary"
            onClick={handleDownloadClick}
            startIcon={<IconDownload size={16} />}
          >
            Download PDF
          </Button>
        </DialogActions>
      </Dialog>

      {/* ── Confirm Download & Dispatch Dialog ────────────────────────── */}
      <Dialog
        open={confirmOpen}
        onClose={() => !generating && setConfirmOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          <Box display="flex" alignItems="center" style={{ gap: 8 }}>
            <IconAlertTriangle size={22} color="#f57c00" />
            <Typography variant="h4">Confirm Download & Dispatch</Typography>
          </Box>
        </DialogTitle>

        <DialogContent dividers>
          <Typography variant="body1" gutterBottom>
            Downloading this supply sheet will <strong>move all Invoiced orders</strong> for
            the {selectedIds.length === 1 ? 'selected dealer' : `selected ${selectedIds.length} dealers`} to{' '}
            <strong>Dispatch Ready</strong> status.
          </Typography>
          <Typography variant="body2" style={{ color: '#d32f2f', marginBottom: 12 }}>
            This action cannot be undone. These orders will no longer appear in future supply
            sheet selections.
          </Typography>

          {selectedIds.length > 0 && (
            <Box
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 4,
                padding: 8,
                border: '1px solid #e0e0e0',
                borderRadius: 4,
                maxHeight: 140,
                overflowY: 'auto',
              }}
            >
              {selectedIds.slice(0, 20).map((id) => {
                const d = dealerMap[id];
                return d ? (
                  <Chip
                    key={id}
                    label={d.name}
                    size="small"
                    variant="outlined"
                    color="default"
                  />
                ) : null;
              })}
              {selectedIds.length > 20 && (
                <Typography variant="caption" color="textSecondary" style={{ alignSelf: 'center', paddingLeft: 4 }}>
                  +{selectedIds.length - 20} more
                </Typography>
              )}
            </Box>
          )}
        </DialogContent>

        <DialogActions>
          <Button onClick={() => setConfirmOpen(false)} disabled={generating}>
            Cancel
          </Button>
          <Button
            variant="contained"
            style={{ backgroundColor: '#2e7d32', color: 'white' }}
            onClick={handleConfirmDownload}
            disabled={generating}
            startIcon={
              generating ? <CircularProgress size={16} color="inherit" /> : <IconDownload size={16} />
            }
          >
            {generating ? 'Processing…' : 'Confirm & Download'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Snackbar */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={5000}
        onClose={hideSnackbar}
        anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <Alert onClose={hideSnackbar} severity={snackbar.severity} variant="filled">
          {snackbar.message}
        </Alert>
      </Snackbar>
    </Grid>
  );
};

export default SupplySheetDownload;
