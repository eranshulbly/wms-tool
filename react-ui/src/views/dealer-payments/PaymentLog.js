import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  MenuItem,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@material-ui/core';
import { cancelPayment, errMsg, getPayments, getProof } from '../../services/dealerPaymentsService';
import PaymentForm from './PaymentForm';

// Log a payment, and the log itself: every payment with its status. OPEN until Tally posts
// it (matched automatically), CANCELLED by hand, BOUNCED when Tally reverses it.

const inr = (v) => `₹${Number(v || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
const fmtDate = (iso) =>
  iso ? new Date(`${String(iso).slice(0, 10)}T00:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: '2-digit' }) : '—';
const STATUS_COLOR = { OPEN: 'warning', POSTED: 'success', CANCELLED: 'default', BOUNCED: 'error' };

export const LogPaymentPage = () => (
  <Box maxWidth={560}>
    <Typography variant="h3" gutterBottom>Log payment</Typography>
    <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
      <PaymentForm />
    </Paper>
  </Box>
);

const PaymentLog = () => {
  const [status, setStatus] = useState('');
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setRows((await getPayments(status || undefined)).payments || []);
    } catch (e) {
      setError(errMsg(e, 'Could not load payments.'));
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    load();
  }, [load]);

  const cancel = async (p) => {
    if (!window.confirm(`Cancel the ${p.mode} payment of ${inr(p.amount)} from ${p.dealer_name}?`)) return;
    try {
      await cancelPayment(p.id);
      load();
    } catch (e) {
      setError(errMsg(e, 'Could not cancel.'));
    }
  };

  const showProof = async (p) => {
    try {
      const blob = await getProof(p.id);
      window.open(URL.createObjectURL(blob), '_blank');
    } catch (e) {
      setError(errMsg(e, 'Could not open the proof image.'));
    }
  };

  return (
    <Box>
      <Box display="flex" alignItems="center" flexWrap="wrap" sx={{ gap: 1, mb: 1 }}>
        <Typography variant="h3" sx={{ flexGrow: 1 }}>Payment log</Typography>
        <TextField select size="small" label="Status" value={status} onChange={(e) => setStatus(e.target.value)} sx={{ minWidth: 140 }}
          SelectProps={{ displayEmpty: true }} InputLabelProps={{ shrink: true }}>
          <MenuItem value="">All</MenuItem>
          {['OPEN', 'POSTED', 'BOUNCED', 'CANCELLED'].map((s) => (
            <MenuItem key={s} value={s}>{s}</MenuItem>
          ))}
        </TextField>
      </Box>
      {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}
      <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              {['Date', 'Dealer', 'Mode', 'Amount', 'Reference', 'Status', 'Tally receipt', 'Logged by', 'Proof', ''].map((h, i) => (
                <TableCell key={`${h}-${i}`} sx={{ fontWeight: 600 }} align={h === 'Amount' ? 'right' : 'left'}>{h}</TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {loading && (
              <TableRow><TableCell colSpan={10} align="center" sx={{ py: 4 }}><CircularProgress size={24} /></TableCell></TableRow>
            )}
            {!loading && !rows.length && (
              <TableRow><TableCell colSpan={10} align="center" sx={{ py: 4, color: 'text.secondary' }}>No payments logged.</TableCell></TableRow>
            )}
            {!loading && rows.map((p) => (
              <TableRow key={p.id} hover>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>{fmtDate(p.payment_date)}</TableCell>
                <TableCell>{p.dealer_name}{p.town ? ` (${p.town})` : ''}</TableCell>
                <TableCell>{p.mode}</TableCell>
                <TableCell align="right">{inr(p.amount)}</TableCell>
                <TableCell>{p.reference || '—'}{p.note ? <Typography variant="caption" component="div" color="textSecondary">{p.note}</Typography> : null}</TableCell>
                <TableCell><Chip size="small" color={STATUS_COLOR[p.status]} label={p.status} /></TableCell>
                <TableCell sx={{ whiteSpace: 'nowrap' }}>
                  {p.matched_vch_no ? `${p.matched_vch_no} · ${fmtDate(p.matched_vch_date)}` : p.bounced_by_ref || '—'}
                </TableCell>
                <TableCell>{p.created_by}</TableCell>
                <TableCell sx={{ width: 80 }}>
                  {p.has_proof ? <Button size="small" onClick={() => showProof(p)}>View</Button> : '—'}
                </TableCell>
                <TableCell sx={{ width: 90 }}>
                  {p.status === 'OPEN' && <Button size="small" color="error" onClick={() => cancel(p)}>Cancel</Button>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
};

export default PaymentLog;
