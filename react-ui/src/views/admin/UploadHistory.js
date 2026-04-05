import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import {
    Grid, Card, CardContent, Typography, Table, TableBody, TableCell,
    TableContainer, TableHead, TableRow, Paper, Chip, Button, CircularProgress,
    Dialog, DialogTitle, DialogContent, DialogContentText, DialogActions,
    FormControl, InputLabel, Select, MenuItem, Box, Alert
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconTrash, IconPackage, IconFileInvoice } from '@tabler/icons';
import config from '../../config';

const useStyles = makeStyles((theme) => ({
    header: { marginBottom: theme.spacing(3) },
    filters: { marginBottom: theme.spacing(2) },
    chipActive: { backgroundColor: '#e8f5e9', color: '#2e7d32' },
    chipReverted: { backgroundColor: '#fce4ec', color: '#c62828' },
    typeOrders: { backgroundColor: '#e3f2fd', color: '#1565c0' },
    typeInvoices: { backgroundColor: '#f3e5f5', color: '#6a1b9a' },
    revertBtn: { color: '#d32f2f', borderColor: '#d32f2f' },
    noData: { textAlign: 'center', padding: theme.spacing(4), color: theme.palette.text.secondary },
    warningBox: { marginTop: theme.spacing(1) }
}));

const API = config.API_SERVER.replace(/\/$/, '');

const UploadHistory = () => {
    const classes = useStyles();
    const [batches, setBatches] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filterType, setFilterType] = useState('');
    const [confirmOpen, setConfirmOpen] = useState(false);
    const [selectedBatch, setSelectedBatch] = useState(null);
    const [reverting, setReverting] = useState(false);
    const [toast, setToast] = useState(null); // { severity, msg }

    const fetchBatches = useCallback(async () => {
        setLoading(true);
        try {
            const params = filterType ? { upload_type: filterType } : {};
            const res = await axios.get(`${API}/api/admin/upload-batches`, { params });
            if (res.data.success) setBatches(res.data.batches);
        } catch (e) {
            setToast({ severity: 'error', msg: 'Failed to load upload history.' });
        } finally {
            setLoading(false);
        }
    }, [filterType]);

    useEffect(() => { fetchBatches(); }, [fetchBatches]);

    const openConfirm = (batch) => {
        setSelectedBatch(batch);
        setConfirmOpen(true);
    };

    const handleRevert = async () => {
        if (!selectedBatch) return;
        setReverting(true);
        try {
            const res = await axios.post(`${API}/api/admin/upload-batches/${selectedBatch.id}/revert`);
            if (res.data.success) {
                setToast({ severity: 'success', msg: res.data.msg });
                fetchBatches();
            } else {
                setToast({ severity: 'error', msg: res.data.msg });
            }
        } catch (e) {
            setToast({ severity: 'error', msg: e.response?.data?.msg || 'Revert failed.' });
        } finally {
            setReverting(false);
            setConfirmOpen(false);
            setSelectedBatch(null);
        }
    };

    const nonOpenCount = selectedBatch?.upload_type === 'orders'
        ? null  // We don't pre-fetch this; the API will warn in the response
        : null;

    return (
        <Grid container spacing={2}>
            <Grid item xs={12}>
                <Typography variant="h3" className={classes.header}>Upload History</Typography>
            </Grid>

            {toast && (
                <Grid item xs={12}>
                    <Alert severity={toast.severity} onClose={() => setToast(null)}>
                        {toast.msg}
                    </Alert>
                </Grid>
            )}

            {/* Filters */}
            <Grid item xs={12}>
                <Card>
                    <CardContent>
                        <Grid container spacing={2} alignItems="center">
                            <Grid item xs={12} sm={4} md={3}>
                                <FormControl variant="outlined" fullWidth size="small">
                                    <InputLabel>Upload Type</InputLabel>
                                    <Select
                                        value={filterType}
                                        onChange={(e) => setFilterType(e.target.value)}
                                        label="Upload Type"
                                    >
                                        <MenuItem value="">All Types</MenuItem>
                                        <MenuItem value="orders">Orders</MenuItem>
                                        <MenuItem value="invoices">Invoices</MenuItem>
                                    </Select>
                                </FormControl>
                            </Grid>
                            <Grid item>
                                <Button variant="outlined" onClick={fetchBatches} disabled={loading}>
                                    Refresh
                                </Button>
                            </Grid>
                        </Grid>
                    </CardContent>
                </Card>
            </Grid>

            {/* Table */}
            <Grid item xs={12}>
                <Card>
                    <CardContent style={{ padding: 0 }}>
                        {loading ? (
                            <Box display="flex" justifyContent="center" p={4}>
                                <CircularProgress />
                            </Box>
                        ) : batches.length === 0 ? (
                            <Typography className={classes.noData}>
                                No upload history found.
                            </Typography>
                        ) : (
                            <TableContainer>
                                <Table>
                                    <TableHead>
                                        <TableRow>
                                            <TableCell>#</TableCell>
                                            <TableCell>Type</TableCell>
                                            <TableCell>File</TableCell>
                                            <TableCell>Warehouse</TableCell>
                                            <TableCell>Company</TableCell>
                                            <TableCell>Uploaded By</TableCell>
                                            <TableCell>Date</TableCell>
                                            <TableCell align="center">Records</TableCell>
                                            <TableCell>Status</TableCell>
                                            <TableCell>Action</TableCell>
                                        </TableRow>
                                    </TableHead>
                                    <TableBody>
                                        {batches.map((b) => (
                                            <TableRow key={b.id} hover>
                                                <TableCell>{b.id}</TableCell>
                                                <TableCell>
                                                    <Chip
                                                        size="small"
                                                        icon={b.upload_type === 'orders'
                                                            ? <IconPackage size={14} />
                                                            : <IconFileInvoice size={14} />}
                                                        label={b.upload_type}
                                                        className={b.upload_type === 'orders'
                                                            ? classes.typeOrders
                                                            : classes.typeInvoices}
                                                    />
                                                </TableCell>
                                                <TableCell>
                                                    <Typography variant="body2">{b.filename || '—'}</Typography>
                                                </TableCell>
                                                <TableCell>{b.warehouse_name || '—'}</TableCell>
                                                <TableCell>{b.company_name || '—'}</TableCell>
                                                <TableCell>{b.uploaded_by || '—'}</TableCell>
                                                <TableCell>
                                                    <Typography variant="body2">
                                                        {b.uploaded_at
                                                            ? new Date(b.uploaded_at).toLocaleString()
                                                            : '—'}
                                                    </Typography>
                                                    {b.status === 'reverted' && b.reverted_at && (
                                                        <Typography variant="caption" color="textSecondary">
                                                            Reverted by {b.reverted_by || '?'} on{' '}
                                                            {new Date(b.reverted_at).toLocaleDateString()}
                                                        </Typography>
                                                    )}
                                                </TableCell>
                                                <TableCell align="center">
                                                    <Typography variant="h6">{b.record_count ?? '—'}</Typography>
                                                </TableCell>
                                                <TableCell>
                                                    <Chip
                                                        size="small"
                                                        label={b.status}
                                                        className={b.status === 'active'
                                                            ? classes.chipActive
                                                            : classes.chipReverted}
                                                    />
                                                </TableCell>
                                                <TableCell>
                                                    {b.status === 'active' ? (
                                                        <Button
                                                            size="small"
                                                            variant="outlined"
                                                            className={classes.revertBtn}
                                                            startIcon={<IconTrash size={14} />}
                                                            onClick={() => openConfirm(b)}
                                                        >
                                                            Revert
                                                        </Button>
                                                    ) : (
                                                        <Typography variant="caption" color="textSecondary">
                                                            Reverted
                                                        </Typography>
                                                    )}
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            </TableContainer>
                        )}
                    </CardContent>
                </Card>
            </Grid>

            {/* Confirm Dialog */}
            <Dialog open={confirmOpen} onClose={() => !reverting && setConfirmOpen(false)} maxWidth="sm" fullWidth>
                <DialogTitle>Confirm Revert</DialogTitle>
                <DialogContent>
                    <DialogContentText>
                        This will permanently delete all{' '}
                        <strong>{selectedBatch?.record_count} {selectedBatch?.upload_type}</strong>{' '}
                        record(s) from <strong>{selectedBatch?.filename}</strong>.
                        This action cannot be undone.
                    </DialogContentText>
                    {selectedBatch?.upload_type === 'orders' && (
                        <Alert severity="warning" className={classes.warningBox}>
                            Orders already in Picking, Packing, or Dispatch state will also be deleted.
                        </Alert>
                    )}
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setConfirmOpen(false)} disabled={reverting}>
                        Cancel
                    </Button>
                    <Button
                        onClick={handleRevert}
                        color="secondary"
                        variant="contained"
                        disabled={reverting}
                        startIcon={reverting ? <CircularProgress size={14} /> : <IconTrash size={14} />}
                    >
                        {reverting ? 'Reverting...' : 'Confirm Revert'}
                    </Button>
                </DialogActions>
            </Dialog>
        </Grid>
    );
};

export default UploadHistory;
