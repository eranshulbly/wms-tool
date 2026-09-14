// Delete Orders — remove orders that were uploaded in error.
//
// The neighbouring "Delete Uploads" tab reverts a whole upload batch. That is the right
// tool when the wrong FILE was uploaded; this one is for when one order inside an
// otherwise good batch is wrong, which a batch revert cannot express.
//
// Deletion is permanent and the reason is mandatory, because both facts are the point: a
// soft delete would keep the order number occupied and block re-uploading the corrected
// challan, and a hard delete with no record is how an order silently vanishes.

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Chip,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogContentText,
    DialogTitle,
    FormControl,
    Grid,
    InputLabel,
    MenuItem,
    Paper,
    Select,
    Snackbar,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    TextField,
    Typography
} from '@material-ui/core';
import { IconTrash, IconRefresh, IconHistory, IconSearch } from '@tabler/icons';

import adminService from '../../../services/adminService';

const STATUSES = ['all', 'Open', 'Picking', 'Packed', 'Invoiced', 'Dispatch Ready', 'Completed'];

// Statuses the server refuses to delete without an explicit confirmation. Mirrored here
// only to colour the chip — the server decides, and is asked again on every attempt.
const BLOCKING = ['Invoiced', 'Dispatch Ready', 'Completed', 'Partially Completed'];

const fmtDate = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('en-IN', { dateStyle: 'medium' });
};

const DeleteOrders = () => {
    const [orders, setOrders] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [selected, setSelected] = useState([]);
    const [status, setStatus] = useState('all');
    const [search, setSearch] = useState('');
    const [query, setQuery] = useState('');

    const [confirmOpen, setConfirmOpen] = useState(false);
    const [reason, setReason] = useState('');
    const [deleting, setDeleting] = useState(false);
    const [blocked, setBlocked] = useState(null);

    const [logOpen, setLogOpen] = useState(false);
    const [log, setLog] = useState([]);

    const [snack, setSnack] = useState({ open: false, message: '', severity: 'success' });
    const notify = (message, severity = 'success') => setSnack({ open: true, message, severity });

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await adminService.getDeletableOrders({ status, search: query });
            if (data.success) {
                setOrders(data.orders || []);
                // Drop anything that has since disappeared, so the count on the button
                // cannot promise more than the server will accept.
                const live = new Set((data.orders || []).map((o) => o.potential_order_id));
                setSelected((prev) => prev.filter((id) => live.has(id)));
            } else {
                setError(data.msg || 'Could not load orders.');
            }
        } catch (e) {
            setError(e?.response?.data?.msg || 'Could not load orders.');
        } finally {
            setLoading(false);
        }
    }, [status, query]);

    useEffect(() => {
        load();
    }, [load]);

    const toggle = (id) =>
        setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

    const selectedOrders = useMemo(
        () => orders.filter((o) => selected.includes(o.potential_order_id)),
        [orders, selected]
    );

    const openConfirm = () => {
        setReason('');
        setBlocked(null);
        setConfirmOpen(true);
    };

    const runDelete = async (force) => {
        if (!reason.trim()) return;
        setDeleting(true);
        try {
            const data = await adminService.deleteOrders(selected, reason.trim(), force);
            if (data.success) {
                notify(data.msg || `Deleted ${data.deleted_count} order(s).`);
                setConfirmOpen(false);
                setSelected([]);
                load();
            } else {
                notify(data.msg || 'Could not delete the orders.', 'error');
            }
        } catch (e) {
            const body = e?.response?.data;
            // 409 means some orders are invoiced or dispatched. The dialog stays open and
            // asks again, naming what would go with them.
            if (body?.needs_confirmation) {
                setBlocked(body);
            } else {
                notify(body?.msg || 'Could not delete the orders.', 'error');
            }
        } finally {
            setDeleting(false);
        }
    };

    const openLog = async () => {
        setLogOpen(true);
        try {
            const data = await adminService.getOrderDeletionLog();
            setLog(data.success ? data.entries || [] : []);
        } catch (e) {
            setLog([]);
        }
    };

    return (
        <Box>
            <Typography variant="body2" color="textSecondary" gutterBottom>
                Permanently remove orders that were uploaded in error. The order, its line items,
                its history and any invoice against it are deleted; products, dealers and stock are
                left untouched. Every deletion is recorded with its reason.
            </Typography>

            <Grid container spacing={2} alignItems="center" style={{ marginTop: 8, marginBottom: 8 }}>
                <Grid item xs={12} sm={3}>
                    <FormControl fullWidth size="small">
                        <InputLabel>Status</InputLabel>
                        <Select value={status} label="Status" onChange={(e) => setStatus(e.target.value)}>
                            {STATUSES.map((s) => (
                                <MenuItem key={s} value={s}>
                                    {s === 'all' ? 'All statuses' : s}
                                </MenuItem>
                            ))}
                        </Select>
                    </FormControl>
                </Grid>
                <Grid item xs={12} sm={4}>
                    <TextField
                        fullWidth
                        size="small"
                        label="Order number or dealer"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') setQuery(search);
                        }}
                    />
                </Grid>
                <Grid item>
                    <Button
                        variant="outlined"
                        startIcon={<IconSearch size={16} />}
                        onClick={() => setQuery(search)}
                    >
                        Search
                    </Button>
                </Grid>
                <Grid item xs />
                <Grid item>
                    <Button variant="outlined" startIcon={<IconHistory size={16} />} onClick={openLog}>
                        Deletion log
                    </Button>
                </Grid>
                <Grid item>
                    <Button variant="outlined" startIcon={<IconRefresh size={16} />} onClick={load}>
                        Refresh
                    </Button>
                </Grid>
                <Grid item>
                    <Button
                        variant="contained"
                        color="secondary"
                        startIcon={<IconTrash size={16} />}
                        disabled={!selected.length}
                        onClick={openConfirm}
                    >
                        {selected.length ? `Delete ${selected.length} order(s)` : 'Delete orders'}
                    </Button>
                </Grid>
            </Grid>

            {error && <Alert severity="error" style={{ marginBottom: 12 }}>{error}</Alert>}

            {loading ? (
                <Box display="flex" justifyContent="center" py={5}>
                    <CircularProgress />
                </Box>
            ) : orders.length === 0 ? (
                <Alert severity="info">No orders match these filters.</Alert>
            ) : (
                <TableContainer component={Paper} variant="outlined">
                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell padding="checkbox" />
                                <TableCell>Order No</TableCell>
                                <TableCell>Dealer</TableCell>
                                <TableCell>Type</TableCell>
                                <TableCell>Status</TableCell>
                                <TableCell>Order Date</TableCell>
                                <TableCell align="right">Lines</TableCell>
                                <TableCell align="right">Invoices</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {orders.map((o) => (
                                <TableRow
                                    key={o.potential_order_id}
                                    hover
                                    selected={selected.includes(o.potential_order_id)}
                                    onClick={() => toggle(o.potential_order_id)}
                                    style={{ cursor: 'pointer' }}
                                >
                                    <TableCell padding="checkbox">
                                        <input
                                            type="checkbox"
                                            readOnly
                                            checked={selected.includes(o.potential_order_id)}
                                        />
                                    </TableCell>
                                    <TableCell>{o.order_number}</TableCell>
                                    <TableCell>{o.dealer_name || '—'}</TableCell>
                                    <TableCell>{o.order_type || '—'}</TableCell>
                                    <TableCell>
                                        <Chip
                                            size="small"
                                            label={o.status}
                                            color={BLOCKING.includes(o.status) ? 'secondary' : 'default'}
                                        />
                                    </TableCell>
                                    <TableCell>{fmtDate(o.order_date)}</TableCell>
                                    <TableCell align="right">{o.line_count}</TableCell>
                                    <TableCell align="right">{o.invoice_count || '—'}</TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </TableContainer>
            )}

            {/* Confirmation — reason is mandatory, and a second pass is needed for invoiced orders. */}
            <Dialog open={confirmOpen} onClose={() => !deleting && setConfirmOpen(false)} maxWidth="sm" fullWidth>
                <DialogTitle>Delete {selected.length} order(s)?</DialogTitle>
                <DialogContent>
                    <DialogContentText component="div">
                        This cannot be undone. The following will be permanently removed:
                        <ul style={{ marginTop: 8 }}>
                            {selectedOrders.slice(0, 10).map((o) => (
                                <li key={o.potential_order_id}>
                                    <strong>{o.order_number}</strong> — {o.dealer_name || 'no dealer'} ·{' '}
                                    {o.status} · {o.line_count} line(s)
                                    {o.invoice_count ? ` · ${o.invoice_count} invoice(s)` : ''}
                                </li>
                            ))}
                            {selectedOrders.length > 10 && <li>…and {selectedOrders.length - 10} more</li>}
                        </ul>
                    </DialogContentText>

                    {blocked && (
                        <Alert severity="warning" style={{ marginBottom: 12 }}>
                            {blocked.msg}
                        </Alert>
                    )}

                    <TextField
                        autoFocus
                        fullWidth
                        required
                        label="Reason for deleting"
                        placeholder="e.g. uploaded the wrong challan file"
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        helperText="Recorded in the deletion log against every order removed."
                    />
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setConfirmOpen(false)} disabled={deleting}>
                        Cancel
                    </Button>
                    <Button
                        variant="contained"
                        color="secondary"
                        disabled={!reason.trim() || deleting}
                        onClick={() => runDelete(!!blocked)}
                        startIcon={deleting ? <CircularProgress size={16} color="inherit" /> : <IconTrash size={16} />}
                    >
                        {blocked ? 'Delete anyway' : 'Delete permanently'}
                    </Button>
                </DialogActions>
            </Dialog>

            {/* Audit trail */}
            <Dialog open={logOpen} onClose={() => setLogOpen(false)} maxWidth="md" fullWidth>
                <DialogTitle>Deletion log</DialogTitle>
                <DialogContent>
                    {log.length === 0 ? (
                        <Alert severity="info">Nothing has been deleted yet.</Alert>
                    ) : (
                        <TableContainer>
                            <Table size="small">
                                <TableHead>
                                    <TableRow>
                                        <TableCell>Order No</TableCell>
                                        <TableCell>Status when deleted</TableCell>
                                        <TableCell>Dealer</TableCell>
                                        <TableCell align="right">Lines</TableCell>
                                        <TableCell>Reason</TableCell>
                                        <TableCell>By</TableCell>
                                        <TableCell>When</TableCell>
                                    </TableRow>
                                </TableHead>
                                <TableBody>
                                    {log.map((e, i) => (
                                        <TableRow key={i}>
                                            <TableCell>{e.order_number}</TableCell>
                                            <TableCell>{e.status_at_deletion}</TableCell>
                                            <TableCell>{e.purchaser_name || '—'}</TableCell>
                                            <TableCell align="right">{e.line_count}</TableCell>
                                            <TableCell>{e.reason}</TableCell>
                                            <TableCell>{e.deleted_by}</TableCell>
                                            <TableCell>{fmtDate(e.deleted_at)}</TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </TableContainer>
                    )}
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setLogOpen(false)}>Close</Button>
                </DialogActions>
            </Dialog>

            <Snackbar
                open={snack.open}
                autoHideDuration={6000}
                onClose={() => setSnack((s) => ({ ...s, open: false }))}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
            >
                <Alert onClose={() => setSnack((s) => ({ ...s, open: false }))} severity={snack.severity}>
                    {snack.message}
                </Alert>
            </Snackbar>
        </Box>
    );
};

export default DeleteOrders;
