import React, { useState, useEffect, useCallback } from 'react';
import {
    Box,
    Grid,
    Card,
    CardContent,
    Typography,
    Button,
    CircularProgress,
    Alert,
    FormControl,
    InputLabel,
    Select,
    MenuItem,
    TextField,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Chip,
    Tooltip,
    Dialog,
    DialogTitle,
    DialogContent,
    DialogContentText,
    DialogActions,
    Divider,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import {
    IconSearch,
    IconTrash,
    IconPackage,
    IconFileInvoice,
    IconAlertCircle,
    IconInfoCircle,
} from '@tabler/icons';

import adminService   from '../../../services/adminService';
import dashboardService from '../../../services/dashboardService';

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------
const useStyles = makeStyles((theme) => ({
    filterCard: {
        marginBottom: theme.spacing(2),
    },
    filterGrid: {
        alignItems: 'flex-end',
    },
    tableCard: {
        overflow: 'hidden',
    },
    tableRow: {
        cursor: 'pointer',
        '&:hover': {
            backgroundColor: theme.palette.action.hover,
        },
    },
    chipOrders: {
        backgroundColor: '#e3f2fd',
        color:           '#1565c0',
        fontWeight:      600,
    },
    chipInvoices: {
        backgroundColor: '#f3e5f5',
        color:           '#6a1b9a',
        fontWeight:      600,
    },
    chipActive: {
        backgroundColor: '#e8f5e9',
        color:           '#2e7d32',
        fontWeight:      600,
    },
    chipReverted: {
        backgroundColor: '#fce4ec',
        color:           '#c62828',
        fontWeight:      600,
    },
    noData: {
        textAlign: 'center',
        padding:   theme.spacing(5),
        color:     theme.palette.text.secondary,
    },
    deleteBtn: {
        color:       '#d32f2f',
        borderColor: '#d32f2f',
        '&:hover': {
            backgroundColor: '#fce4ec',
            borderColor:     '#b71c1c',
        },
    },

    // Detail modal
    modalSection: {
        marginBottom: theme.spacing(2),
    },
    modalMeta: {
        display:              'grid',
        gridTemplateColumns:  'repeat(auto-fill, minmax(200px, 1fr))',
        gap:                  theme.spacing(1.5),
        padding:              theme.spacing(2),
        backgroundColor:      theme.palette.grey[50],
        borderRadius:         theme.shape.borderRadius,
        marginBottom:         theme.spacing(2),
    },
    metaItem: {
        display:       'flex',
        flexDirection: 'column',
    },
    metaLabel: {
        fontSize:    11,
        fontWeight:  600,
        color:       theme.palette.text.secondary,
        textTransform: 'uppercase',
        letterSpacing: 0.5,
    },
    metaValue: {
        fontSize:   13,
        fontWeight: 500,
        marginTop:  2,
    },
    detailTable: {
        '& th': {
            backgroundColor: theme.palette.grey[100],
            fontWeight:      600,
            fontSize:        12,
            whiteSpace:      'nowrap',
        },
        '& td': {
            fontSize:  12,
            whiteSpace: 'nowrap',
        },
    },
    scrollableTable: {
        maxHeight: 380,
        overflow:  'auto',
    },
    deleteBlockedAlert: {
        marginTop: theme.spacing(1),
    },
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const fmt = (dateStr) =>
    dateStr ? new Date(dateStr).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—';

const fmtDate = (dateStr) =>
    dateStr ? new Date(dateStr).toLocaleDateString('en-IN', { dateStyle: 'medium' }) : '—';

const currency = (val) =>
    val != null ? `₹${Number(val).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—';

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Renders rows for an order-type batch detail table */
function OrderDetailTable({ records, classes }) {
    if (!records.length) return <Typography className={classes.noData}>No records found.</Typography>;
    return (
        <Box className={classes.scrollableTable}>
            <Table size="small" stickyHeader className={classes.detailTable}>
                <TableHead>
                    <TableRow>
                        <TableCell>Order ID</TableCell>
                        <TableCell>Original Order ID</TableCell>
                        <TableCell>Dealer</TableCell>
                        <TableCell>Dealer Code</TableCell>
                        <TableCell>Status</TableCell>
                        <TableCell>Order Type</TableCell>
                        <TableCell>Purchaser</TableCell>
                        <TableCell>SAP Code</TableCell>
                        <TableCell>VIN</TableCell>
                        <TableCell align="center">Products</TableCell>
                        <TableCell align="center">Total Qty</TableCell>
                        <TableCell>Invoice Submitted</TableCell>
                        <TableCell>Order Date</TableCell>
                    </TableRow>
                </TableHead>
                <TableBody>
                    {records.map((r) => (
                        <TableRow key={r.potential_order_id} hover>
                            <TableCell>{r.potential_order_id}</TableCell>
                            <TableCell>{r.original_order_id || '—'}</TableCell>
                            <TableCell>{r.dealer_name || '—'}</TableCell>
                            <TableCell>{r.dealer_code || '—'}</TableCell>
                            <TableCell>
                                <Chip size="small" label={r.status || '—'} style={{ fontSize: 11 }} />
                            </TableCell>
                            <TableCell>{r.order_type || '—'}</TableCell>
                            <TableCell>{r.purchaser_name || '—'}</TableCell>
                            <TableCell>{r.purchaser_sap_code || '—'}</TableCell>
                            <TableCell>{r.vin_number || '—'}</TableCell>
                            <TableCell align="center">{r.product_count}</TableCell>
                            <TableCell align="center">{r.total_quantity}</TableCell>
                            <TableCell>{r.invoice_submitted ? 'Yes' : 'No'}</TableCell>
                            <TableCell>{fmtDate(r.order_date)}</TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </Box>
    );
}

/** Renders rows for an invoice-type batch detail table */
function InvoiceDetailTable({ records, classes }) {
    if (!records.length) return <Typography className={classes.noData}>No records found.</Typography>;
    return (
        <Box className={classes.scrollableTable}>
            <Table size="small" stickyHeader className={classes.detailTable}>
                <TableHead>
                    <TableRow>
                        <TableCell>Invoice #</TableCell>
                        <TableCell>Original Order ID</TableCell>
                        <TableCell>Invoice Date</TableCell>
                        <TableCell>Type</TableCell>
                        <TableCell>Header Type</TableCell>
                        <TableCell>Amount</TableCell>
                        <TableCell>Dealer</TableCell>
                        <TableCell>Dealer Code</TableCell>
                        <TableCell>Warehouse</TableCell>
                        <TableCell>Company</TableCell>
                        <TableCell>Order Status</TableCell>
                        <TableCell>Customer</TableCell>
                        <TableCell>Category</TableCell>
                        <TableCell>B2B PO #</TableCell>
                        <TableCell>TIN</TableCell>
                        <TableCell>IRN #</TableCell>
                        <TableCell>IRN Status</TableCell>
                        <TableCell>Round Off</TableCell>
                        <TableCell>Cancellation Date</TableCell>
                    </TableRow>
                </TableHead>
                <TableBody>
                    {records.map((r) => (
                        <TableRow key={r.invoice_id} hover>
                            <TableCell>{r.invoice_number || '—'}</TableCell>
                            <TableCell>{r.original_order_id || '—'}</TableCell>
                            <TableCell>{fmtDate(r.invoice_date)}</TableCell>
                            <TableCell>{r.invoice_type || '—'}</TableCell>
                            <TableCell>{r.invoice_header_type || '—'}</TableCell>
                            <TableCell>{currency(r.total_invoice_amount)}</TableCell>
                            <TableCell>{r.dealer_name || '—'}</TableCell>
                            <TableCell>{r.dealer_code || '—'}</TableCell>
                            <TableCell>{r.warehouse_name || '—'}</TableCell>
                            <TableCell>{r.company_name || '—'}</TableCell>
                            <TableCell>
                                <Chip size="small" label={r.order_status || '—'} style={{ fontSize: 11 }} />
                            </TableCell>
                            <TableCell>
                                {[r.contact_first_name, r.contact_last_name].filter(Boolean).join(' ') ||
                                    r.cash_customer_name ||
                                    '—'}
                            </TableCell>
                            <TableCell>{r.customer_category || '—'}</TableCell>
                            <TableCell>{r.b2b_purchase_order_number || '—'}</TableCell>
                            <TableCell>{r.account_tin || '—'}</TableCell>
                            <TableCell>{r.irn_number || '—'}</TableCell>
                            <TableCell>{r.irn_status || '—'}</TableCell>
                            <TableCell>{currency(r.round_off_amount)}</TableCell>
                            <TableCell>{fmtDate(r.cancellation_date)}</TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </Box>
    );
}

// ---------------------------------------------------------------------------
// DeleteUploads (main tab component)
// ---------------------------------------------------------------------------
const DeleteUploads = () => {
    const classes = useStyles();

    // Filter state
    const [filters, setFilters] = useState({
        upload_type:  '',
        warehouse_id: '',
        company_id:   '',
        date_from:    '',
        date_to:      '',
    });

    // Data state
    const [batches,    setBatches]    = useState([]);
    const [warehouses, setWarehouses] = useState([]);
    const [companies,  setCompanies]  = useState([]);
    const [loading,    setLoading]    = useState(false);
    const [alert,      setAlert]      = useState(null); // { severity, msg }

    // Detail modal state
    const [detailOpen,    setDetailOpen]    = useState(false);
    const [detailBatch,   setDetailBatch]   = useState(null);  // batch meta from list
    const [detailRecords, setDetailRecords] = useState([]);
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError,   setDetailError]   = useState(null);

    // Delete confirmation state
    const [confirmOpen,   setConfirmOpen]   = useState(false);
    const [deleting,      setDeleting]      = useState(false);
    const [deleteError,   setDeleteError]   = useState(null);

    // Load warehouses + companies once on mount
    useEffect(() => {
        dashboardService.getWarehouses().then((d) => setWarehouses(d.warehouses || [])).catch(() => {});
        dashboardService.getCompanies().then((d)  => setCompanies(d.companies || [])).catch(()  => {});
    }, []);

    // Search
    const handleSearch = useCallback(async () => {
        setLoading(true);
        setAlert(null);
        try {
            const data = await adminService.getUploadBatches({
                upload_type:  filters.upload_type  || undefined,
                warehouse_id: filters.warehouse_id || undefined,
                company_id:   filters.company_id   || undefined,
                date_from:    filters.date_from     || undefined,
                date_to:      filters.date_to       || undefined,
            });
            if (data.success) {
                setBatches(data.batches);
                if (!data.batches.length) {
                    setAlert({ severity: 'info', msg: 'No uploads found for the selected filters.' });
                }
            } else {
                setAlert({ severity: 'error', msg: data.msg || 'Failed to load uploads.' });
            }
        } catch (e) {
            setAlert({ severity: 'error', msg: e.response?.data?.msg || 'Failed to load uploads.' });
        } finally {
            setLoading(false);
        }
    }, [filters]);

    // Open detail modal
    const openDetail = async (batch) => {
        setDetailBatch(batch);
        setDetailRecords([]);
        setDetailError(null);
        setDetailLoading(true);
        setDetailOpen(true);
        setDeleteError(null);
        try {
            const data = await adminService.getBatchDetails(batch.id);
            if (data.success) {
                setDetailRecords(data.records);
            } else {
                setDetailError(data.msg || 'Failed to load batch details.');
            }
        } catch (e) {
            setDetailError(e.response?.data?.msg || 'Failed to load batch details.');
        } finally {
            setDetailLoading(false);
        }
    };

    const closeDetail = () => {
        if (deleting) return;
        setDetailOpen(false);
        setDetailBatch(null);
        setDetailRecords([]);
        setDetailError(null);
        setDeleteError(null);
    };

    // Open confirm-delete dialog (triggered from within detail modal)
    const openConfirm = () => {
        setDeleteError(null);
        setConfirmOpen(true);
    };

    // Execute delete
    const handleDelete = async () => {
        if (!detailBatch) return;
        setDeleting(true);
        setDeleteError(null);
        try {
            const data = await adminService.deleteUploadBatch(detailBatch.id);
            if (data.success) {
                setAlert({ severity: 'success', msg: data.msg });
                setConfirmOpen(false);
                setDetailOpen(false);
                // Refresh list
                handleSearch();
            } else {
                setDeleteError(data.msg || 'Delete failed.');
                setConfirmOpen(false);
            }
        } catch (e) {
            const msg = e.response?.data?.msg || 'Delete failed.';
            setDeleteError(msg);
            setConfirmOpen(false);
        } finally {
            setDeleting(false);
        }
    };

    // ---------------------------------------------------------------------------
    // Render
    // ---------------------------------------------------------------------------
    return (
        <Box p={2}>
            {/* Filters */}
            <Card className={classes.filterCard} variant="outlined">
                <CardContent>
                    <Grid container spacing={2} className={classes.filterGrid}>
                        <Grid item xs={12} sm={6} md={2}>
                            <FormControl variant="outlined" size="small" fullWidth>
                                <InputLabel>Upload Type</InputLabel>
                                <Select
                                    value={filters.upload_type}
                                    onChange={(e) => setFilters((f) => ({ ...f, upload_type: e.target.value }))}
                                    label="Upload Type"
                                >
                                    <MenuItem value="">All</MenuItem>
                                    <MenuItem value="orders">Orders</MenuItem>
                                    <MenuItem value="invoices">Invoices</MenuItem>
                                </Select>
                            </FormControl>
                        </Grid>

                        <Grid item xs={12} sm={6} md={2}>
                            <FormControl variant="outlined" size="small" fullWidth>
                                <InputLabel>Warehouse</InputLabel>
                                <Select
                                    value={filters.warehouse_id}
                                    onChange={(e) => setFilters((f) => ({ ...f, warehouse_id: e.target.value }))}
                                    label="Warehouse"
                                >
                                    <MenuItem value="">All Warehouses</MenuItem>
                                    {warehouses.map((w) => (
                                        <MenuItem key={w.warehouse_id} value={w.warehouse_id}>
                                            {w.name}
                                        </MenuItem>
                                    ))}
                                </Select>
                            </FormControl>
                        </Grid>

                        <Grid item xs={12} sm={6} md={2}>
                            <FormControl variant="outlined" size="small" fullWidth>
                                <InputLabel>Company</InputLabel>
                                <Select
                                    value={filters.company_id}
                                    onChange={(e) => setFilters((f) => ({ ...f, company_id: e.target.value }))}
                                    label="Company"
                                >
                                    <MenuItem value="">All Companies</MenuItem>
                                    {companies.map((c) => (
                                        <MenuItem key={c.company_id} value={c.company_id}>
                                            {c.name}
                                        </MenuItem>
                                    ))}
                                </Select>
                            </FormControl>
                        </Grid>

                        <Grid item xs={12} sm={6} md={2}>
                            <TextField
                                label="From Date"
                                type="date"
                                variant="outlined"
                                size="small"
                                fullWidth
                                InputLabelProps={{ shrink: true }}
                                value={filters.date_from}
                                onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))}
                            />
                        </Grid>

                        <Grid item xs={12} sm={6} md={2}>
                            <TextField
                                label="To Date"
                                type="date"
                                variant="outlined"
                                size="small"
                                fullWidth
                                InputLabelProps={{ shrink: true }}
                                value={filters.date_to}
                                onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))}
                            />
                        </Grid>

                        <Grid item xs={12} sm={6} md={2}>
                            <Button
                                variant="contained"
                                color="primary"
                                fullWidth
                                startIcon={loading ? <CircularProgress size={14} color="inherit" /> : <IconSearch size={16} />}
                                onClick={handleSearch}
                                disabled={loading}
                            >
                                {loading ? 'Searching…' : 'Search'}
                            </Button>
                        </Grid>
                    </Grid>
                </CardContent>
            </Card>

            {/* Alert bar */}
            {alert && (
                <Box mb={2}>
                    <Alert severity={alert.severity} onClose={() => setAlert(null)}>
                        {alert.msg}
                    </Alert>
                </Box>
            )}

            {/* Results table */}
            {batches.length > 0 && (
                <Card className={classes.tableCard} variant="outlined">
                    <TableContainer>
                        <Table size="small">
                            <TableHead>
                                <TableRow>
                                    <TableCell>Upload ID</TableCell>
                                    <TableCell>Type</TableCell>
                                    <TableCell>File</TableCell>
                                    <TableCell>Warehouse</TableCell>
                                    <TableCell>Company</TableCell>
                                    <TableCell>Uploaded By</TableCell>
                                    <TableCell>Uploaded At</TableCell>
                                    <TableCell align="center">Records</TableCell>
                                    <TableCell>Status</TableCell>
                                </TableRow>
                            </TableHead>
                            <TableBody>
                                {batches.map((b) => (
                                    <Tooltip
                                        key={b.id}
                                        title="Click to view details"
                                        placement="top"
                                        arrow
                                    >
                                        <TableRow
                                            className={classes.tableRow}
                                            onClick={() => openDetail(b)}
                                        >
                                            <TableCell>
                                                <Typography variant="body2" style={{ fontWeight: 600 }}>
                                                    #{b.id}
                                                </Typography>
                                            </TableCell>
                                            <TableCell>
                                                <Chip
                                                    size="small"
                                                    icon={
                                                        b.upload_type === 'orders'
                                                            ? <IconPackage size={13} />
                                                            : <IconFileInvoice size={13} />
                                                    }
                                                    label={b.upload_type}
                                                    className={
                                                        b.upload_type === 'orders'
                                                            ? classes.chipOrders
                                                            : classes.chipInvoices
                                                    }
                                                />
                                            </TableCell>
                                            <TableCell>
                                                <Typography variant="body2">{b.filename || '—'}</Typography>
                                            </TableCell>
                                            <TableCell>{b.warehouse_name || '—'}</TableCell>
                                            <TableCell>{b.company_name || '—'}</TableCell>
                                            <TableCell>{b.uploaded_by || '—'}</TableCell>
                                            <TableCell>
                                                <Typography variant="body2">{fmt(b.uploaded_at)}</Typography>
                                                {b.status === 'reverted' && b.reverted_at && (
                                                    <Typography variant="caption" color="textSecondary" display="block">
                                                        Deleted by {b.reverted_by || '?'} on {fmtDate(b.reverted_at)}
                                                    </Typography>
                                                )}
                                            </TableCell>
                                            <TableCell align="center">
                                                <Typography variant="h6">{b.record_count ?? '—'}</Typography>
                                            </TableCell>
                                            <TableCell>
                                                <Chip
                                                    size="small"
                                                    label={b.status === 'active' ? 'Active' : 'Deleted'}
                                                    className={b.status === 'active' ? classes.chipActive : classes.chipReverted}
                                                />
                                            </TableCell>
                                        </TableRow>
                                    </Tooltip>
                                ))}
                            </TableBody>
                        </Table>
                    </TableContainer>
                </Card>
            )}

            {/* ----------------------------------------------------------------
                Detail Modal
            ---------------------------------------------------------------- */}
            <Dialog
                open={detailOpen}
                onClose={closeDetail}
                maxWidth="xl"
                fullWidth
                scroll="paper"
            >
                <DialogTitle>
                    <Box display="flex" alignItems="center" justifyContent="space-between">
                        <Box display="flex" alignItems="center" style={{ gap: 8 }}>
                            {detailBatch?.upload_type === 'orders'
                                ? <IconPackage size={20} />
                                : <IconFileInvoice size={20} />}
                            <Typography variant="h4">
                                Upload #{detailBatch?.id} — {detailBatch?.upload_type}
                            </Typography>
                        </Box>
                        <Chip
                            size="small"
                            label={detailBatch?.status === 'active' ? 'Active' : 'Deleted'}
                            className={detailBatch?.status === 'active' ? classes.chipActive : classes.chipReverted}
                        />
                    </Box>
                </DialogTitle>

                <DialogContent dividers>
                    {/* Batch meta */}
                    {detailBatch && (
                        <Box className={classes.modalMeta}>
                            {[
                                { label: 'Upload ID',   value: `#${detailBatch.id}` },
                                { label: 'File',        value: detailBatch.filename || '—' },
                                { label: 'Warehouse',   value: detailBatch.warehouse_name || '—' },
                                { label: 'Company',     value: detailBatch.company_name || '—' },
                                { label: 'Uploaded By', value: detailBatch.uploaded_by || '—' },
                                { label: 'Uploaded At', value: fmt(detailBatch.uploaded_at) },
                                { label: 'Records',     value: detailBatch.record_count },
                                ...(detailBatch.status === 'reverted'
                                    ? [
                                          { label: 'Deleted By', value: detailBatch.reverted_by || '—' },
                                          { label: 'Deleted At', value: fmt(detailBatch.reverted_at) },
                                      ]
                                    : []),
                            ].map(({ label, value }) => (
                                <Box key={label} className={classes.metaItem}>
                                    <Typography className={classes.metaLabel}>{label}</Typography>
                                    <Typography className={classes.metaValue}>{value}</Typography>
                                </Box>
                            ))}
                        </Box>
                    )}

                    <Divider style={{ marginBottom: 16 }} />

                    {/* Record details */}
                    {detailLoading ? (
                        <Box display="flex" justifyContent="center" p={4}>
                            <CircularProgress />
                        </Box>
                    ) : detailError ? (
                        <Alert severity="error" icon={<IconAlertCircle size={18} />}>
                            {detailError}
                        </Alert>
                    ) : (
                        <>
                            <Typography variant="subtitle1" style={{ fontWeight: 600, marginBottom: 8 }}>
                                {detailBatch?.upload_type === 'orders' ? 'Order Records' : 'Invoice Records'}{' '}
                                <Typography component="span" variant="caption" color="textSecondary">
                                    ({detailRecords.length} rows)
                                </Typography>
                            </Typography>

                            {detailBatch?.upload_type === 'orders' ? (
                                <OrderDetailTable records={detailRecords} classes={classes} />
                            ) : (
                                <InvoiceDetailTable records={detailRecords} classes={classes} />
                            )}
                        </>
                    )}

                    {/* Delete-blocked error shown inside modal */}
                    {deleteError && (
                        <Alert
                            severity="error"
                            icon={<IconAlertCircle size={18} />}
                            className={classes.deleteBlockedAlert}
                        >
                            {deleteError}
                        </Alert>
                    )}

                    {/* Invoice-revert info notice */}
                    {detailBatch?.status === 'active' &&
                        detailBatch?.upload_type === 'invoices' && (
                            <Alert
                                severity="info"
                                icon={<IconInfoCircle size={18} />}
                                style={{ marginTop: 16 }}
                            >
                                Deleting this invoice upload will revert all affected orders back to the
                                state they held before invoicing (using order history). Invoice records will
                                be permanently removed.
                            </Alert>
                        )}
                </DialogContent>

                <DialogActions style={{ padding: '12px 24px' }}>
                    <Button onClick={closeDetail} disabled={deleting}>
                        Close
                    </Button>
                    {detailBatch?.status === 'active' && (
                        <Button
                            variant="contained"
                            className={classes.deleteBtn}
                            startIcon={<IconTrash size={16} />}
                            onClick={openConfirm}
                            disabled={detailLoading || deleting}
                            style={{ backgroundColor: '#d32f2f', color: '#fff' }}
                        >
                            Delete This Upload
                        </Button>
                    )}
                </DialogActions>
            </Dialog>

            {/* ----------------------------------------------------------------
                Confirm Delete Dialog
            ---------------------------------------------------------------- */}
            <Dialog
                open={confirmOpen}
                onClose={() => !deleting && setConfirmOpen(false)}
                maxWidth="sm"
                fullWidth
            >
                <DialogTitle>Confirm Delete</DialogTitle>
                <DialogContent>
                    <DialogContentText>
                        You are about to permanently delete{' '}
                        <strong>{detailBatch?.record_count} {detailBatch?.upload_type} record(s)</strong>{' '}
                        from <strong>{detailBatch?.filename || `Upload #${detailBatch?.id}`}</strong>.
                        <br />
                        <strong>This action cannot be undone.</strong>
                    </DialogContentText>

                    {detailBatch?.upload_type === 'orders' && (
                        <Alert severity="warning" style={{ marginTop: 12 }}>
                            Orders in <strong>Open</strong>, <strong>Picking</strong>, or{' '}
                            <strong>Packed</strong> state will be permanently removed. Orders already at
                            Invoiced or beyond will block this operation.
                        </Alert>
                    )}

                    {detailBatch?.upload_type === 'invoices' && (
                        <Alert severity="warning" style={{ marginTop: 12 }}>
                            All invoice records in this batch will be deleted and the linked orders will be
                            rolled back to their pre-invoiced state.
                        </Alert>
                    )}
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setConfirmOpen(false)} disabled={deleting}>
                        Cancel
                    </Button>
                    <Button
                        variant="contained"
                        onClick={handleDelete}
                        disabled={deleting}
                        startIcon={
                            deleting ? <CircularProgress size={14} color="inherit" /> : <IconTrash size={14} />
                        }
                        style={{ backgroundColor: '#d32f2f', color: '#fff' }}
                    >
                        {deleting ? 'Deleting…' : 'Yes, Delete Permanently'}
                    </Button>
                </DialogActions>
            </Dialog>
        </Box>
    );
};

export default DeleteUploads;
