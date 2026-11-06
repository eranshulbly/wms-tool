// Cancel Picklist — void a picklist that was issued in error.
//
// Downloading a picklist moves its order Open -> Picking and records the issue. A sheet
// printed by mistake cannot be recalled from the warehouse floor, so an admin cancels it
// here: the picklist is marked cancelled (and kept, with its reason) and the order goes
// back to Open, where it can be issued again.
//
// Only a picklist whose order is still in Picking can be cancelled. Once the order has
// been packed or invoiced the goods have moved, and sending it back to Open would offer it
// for picking a second time.

import React, { useCallback, useEffect, useState } from 'react';
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
    Tooltip,
    Typography
} from '@material-ui/core';
import { IconRefresh, IconSearch, IconX } from '@tabler/icons';

import adminService from '../../../services/adminService';

const fmtDateTime = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return Number.isNaN(d.getTime())
        ? '—'
        : d.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
};

const CancelPicklist = () => {
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [status, setStatus] = useState('issued');
    const [search, setSearch] = useState('');
    const [query, setQuery] = useState('');

    const [target, setTarget] = useState(null);
    const [reason, setReason] = useState('');
    const [cancelling, setCancelling] = useState(false);

    const [snack, setSnack] = useState({ open: false, message: '', severity: 'success' });
    const notify = (message, severity = 'success') => setSnack({ open: true, message, severity });

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await adminService.getPicklists({ status, search: query });
            if (data.success) setRows(data.picklists || []);
            else setError(data.msg || 'Could not load picklists.');
        } catch (e) {
            setError(e?.response?.data?.msg || 'Could not load picklists.');
        } finally {
            setLoading(false);
        }
    }, [status, query]);

    useEffect(() => {
        load();
    }, [load]);

    const openCancel = (row) => {
        setReason('');
        setTarget(row);
    };

    const confirmCancel = async () => {
        if (!target || !reason.trim()) return;
        setCancelling(true);
        try {
            const data = await adminService.cancelPicklist(target.picklist_issue_id, reason.trim());
            if (data.success) {
                notify(data.msg || 'Picklist cancelled.');
                setTarget(null);
                load();
            } else {
                notify(data.msg || 'Could not cancel the picklist.', 'error');
            }
        } catch (e) {
            // A 409 carries a specific reason — already cancelled, or the order has moved on.
            notify(e?.response?.data?.msg || 'Could not cancel the picklist.', 'error');
            load();
        } finally {
            setCancelling(false);
        }
    };

    // Why a row cannot be cancelled, so the disabled button explains itself.
    const blockedReason = (row) => {
        if (row.status === 'cancelled') return 'Already cancelled';
        if (!row.order_status) return 'The order no longer exists';
        if (row.order_status !== 'Picking') return `Order is already ${row.order_status}`;
        return '';
    };

    return (
        <Box>
            <Typography variant="body2" color="textSecondary" gutterBottom>
                Cancel a picklist that was issued in error. The order goes back to Open and can be
                picked again. A picklist can only be cancelled while its order is still being picked.
            </Typography>

            <Grid container spacing={2} alignItems="center" style={{ marginTop: 8, marginBottom: 8 }}>
                <Grid item xs={12} sm={3}>
                    <FormControl fullWidth size="small">
                        <InputLabel>Status</InputLabel>
                        <Select value={status} label="Status" onChange={(e) => setStatus(e.target.value)}>
                            <MenuItem value="issued">Issued</MenuItem>
                            <MenuItem value="cancelled">Cancelled</MenuItem>
                            <MenuItem value="all">All</MenuItem>
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
                    <Button variant="outlined" startIcon={<IconSearch size={16} />} onClick={() => setQuery(search)}>
                        Search
                    </Button>
                </Grid>
                <Grid item xs />
                <Grid item>
                    <Button variant="outlined" startIcon={<IconRefresh size={16} />} onClick={load}>
                        Refresh
                    </Button>
                </Grid>
            </Grid>

            {error && <Alert severity="error" style={{ marginBottom: 12 }}>{error}</Alert>}

            {loading ? (
                <Box display="flex" justifyContent="center" py={5}>
                    <CircularProgress />
                </Box>
            ) : rows.length === 0 ? (
                <Alert severity="info">No picklists match these filters.</Alert>
            ) : (
                <TableContainer component={Paper} variant="outlined">
                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell>Order No</TableCell>
                                <TableCell>Dealer</TableCell>
                                <TableCell align="right">Lines</TableCell>
                                <TableCell>Order Status</TableCell>
                                <TableCell>Issued</TableCell>
                                <TableCell>Picklist</TableCell>
                                <TableCell align="right" />
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {rows.map((r) => {
                                const blocked = blockedReason(r);
                                return (
                                    <TableRow key={r.picklist_issue_id}>
                                        <TableCell>{r.order_number}</TableCell>
                                        <TableCell>{r.dealer_name || '—'}</TableCell>
                                        <TableCell align="right">{r.line_count}</TableCell>
                                        <TableCell>{r.order_status || 'deleted'}</TableCell>
                                        <TableCell>
                                            {fmtDateTime(r.issued_at)}
                                            {r.issued_by ? ` · ${r.issued_by}` : ''}
                                        </TableCell>
                                        <TableCell>
                                            {r.status === 'cancelled' ? (
                                                <Tooltip
                                                    title={`${fmtDateTime(r.cancelled_at)}${
                                                        r.cancelled_by ? ` by ${r.cancelled_by}` : ''
                                                    } — ${r.cancel_reason}`}
                                                >
                                                    <Chip size="small" label="Cancelled" />
                                                </Tooltip>
                                            ) : (
                                                <Chip size="small" color="primary" label="Issued" />
                                            )}
                                        </TableCell>
                                        <TableCell align="right">
                                            <Tooltip title={blocked}>
                                                <span>
                                                    <Button
                                                        size="small"
                                                        color="secondary"
                                                        variant="outlined"
                                                        startIcon={<IconX size={14} />}
                                                        disabled={!r.can_cancel}
                                                        onClick={() => openCancel(r)}
                                                    >
                                                        Cancel
                                                    </Button>
                                                </span>
                                            </Tooltip>
                                        </TableCell>
                                    </TableRow>
                                );
                            })}
                        </TableBody>
                    </Table>
                </TableContainer>
            )}

            <Dialog open={!!target} onClose={() => !cancelling && setTarget(null)} maxWidth="sm" fullWidth>
                <DialogTitle>Cancel picklist for order {target?.order_number}?</DialogTitle>
                <DialogContent>
                    <DialogContentText>
                        {target?.dealer_name || 'This order'} — {target?.line_count} line(s). The picklist
                        will be marked cancelled and the order will go back to Open, so it can be
                        picked again. Make sure the printed sheet is withdrawn from the floor.
                    </DialogContentText>
                    <TextField
                        autoFocus
                        fullWidth
                        required
                        label="Reason for cancelling"
                        placeholder="e.g. printed before stock was confirmed"
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        style={{ marginTop: 16 }}
                    />
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setTarget(null)} disabled={cancelling}>
                        Keep picklist
                    </Button>
                    <Button
                        variant="contained"
                        color="secondary"
                        disabled={!reason.trim() || cancelling}
                        onClick={confirmCancel}
                        startIcon={cancelling ? <CircularProgress size={16} color="inherit" /> : <IconX size={16} />}
                    >
                        Cancel picklist
                    </Button>
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

export default CancelPicklist;
