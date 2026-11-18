import React, { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Collapse,
  Grid,
  IconButton,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@material-ui/core';
import { IconChevronDown, IconChevronRight } from '@tabler/icons';
import { errMsg, getDealerDetail } from '../../services/dealerPaymentsService';

// One dealer in detail (opened from a row of the dealer screen): the screen line's numbers,
// every pending bill in Tally with the voucher lines under it, PDC cheques of any status,
// and payments logged in the app. Cheques are the ones read when the
// tile was opened — this never reads the cheque system itself.

export const inr = (v) =>
  v === null || v === undefined ? '—' : `₹${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
// Tally style: 1,234.00 Dr / 1,234.00 Cr
export const drcr = (v) => {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (!n) return '0';
  return `${Math.abs(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${n < 0 ? 'Cr' : 'Dr'}`;
};
export const fmtDate = (iso) =>
  iso ? new Date(`${String(iso).slice(0, 10)}T00:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: '2-digit' }) : '—';

export const pdcs = (n) => `${n} PDC${n === 1 ? '' : 's'}`;

export const CHEQUE_STATUS = {
  HOLDING: { label: 'Held', color: 'warning' },
  DEPOSITED: { label: 'Deposited', color: 'info' },
  CLEARED: { label: 'Cleared', color: 'success' },
  BOUNCED: { label: 'Bounced', color: 'error' },
};
const PAY_COLOR = { OPEN: 'warning', POSTED: 'success', CANCELLED: 'default', BOUNCED: 'error' };
const KIND = { invoice: 'Invoice', bounce: 'Bounced receipt', credit_note: 'Credit note', other: 'Other' };
const ACTION_COLOR = { CHASE: 'error', WAIT: 'warning', CLEAR: 'success' };
const H = { fontWeight: 600, whiteSpace: 'nowrap' };

const Section = ({ title, count, children }) => (
  <Box sx={{ mt: 2 }}>
    <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 0.5 }}>
      {title}{count !== undefined ? ` (${count})` : ''}
    </Typography>
    {children}
  </Box>
);

const Stat = ({ label, value, strong }) => (
  <Grid item xs={6} sm={4} md={2}>
    <Typography variant="caption" color="textSecondary" component="div">{label}</Typography>
    <Typography variant="body1" sx={{ fontWeight: strong ? 700 : 500 }}>{value}</Typography>
  </Grid>
);

export const ChequeStatusChip = ({ c }) => (
  <Chip size="small" color={CHEQUE_STATUS[c.status]?.color || 'default'} label={CHEQUE_STATUS[c.status]?.label || c.status} />
);

const BillRow = ({ b }) => {
  const [open, setOpen] = useState(false);
  const lines = b.adjustments || [];
  return (
    <>
      <TableRow hover>
        <TableCell padding="none" sx={{ width: 32 }}>
          {lines.length > 0 && (
            <IconButton size="small" onClick={() => setOpen(!open)} aria-label="voucher lines">
              {open ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />}
            </IconButton>
          )}
        </TableCell>
        <TableCell sx={{ whiteSpace: 'nowrap' }}>{fmtDate(b.bill_date)}</TableCell>
        <TableCell sx={{ whiteSpace: 'nowrap' }}>{b.ref_no}</TableCell>
        <TableCell>
          {KIND[b.kind] || b.kind}
          {b.label && <Typography variant="caption" color="error" component="div">{b.label}</Typography>}
        </TableCell>
        <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>{drcr(b.opening_amt)}</TableCell>
        <TableCell align="right" sx={{ whiteSpace: 'nowrap', fontWeight: 600 }}>{drcr(b.pending_amt)}</TableCell>
        <TableCell sx={{ whiteSpace: 'nowrap' }}>{fmtDate(b.due_on)}</TableCell>
        <TableCell align="right">{b.overdue_days ?? '—'}</TableCell>
      </TableRow>
      {lines.length > 0 && (
        <TableRow>
          <TableCell colSpan={8} sx={{ py: 0, borderBottom: open ? undefined : 'none' }}>
            <Collapse in={open} unmountOnExit>
              <Table size="small" sx={{ my: 1, ml: 4, width: 'auto' }}>
                <TableBody>
                  {lines.map((a, i) => (
                    <TableRow key={`${a.vch_no}-${i}`}>
                      <TableCell sx={{ whiteSpace: 'nowrap' }}>{fmtDate(a.vch_date)}</TableCell>
                      <TableCell>{a.vch_type} {a.vch_no}</TableCell>
                      <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>{drcr(a.amount)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Collapse>
          </TableCell>
        </TableRow>
      )}
    </>
  );
};

const DealerDetail = ({ dealerId }) => {
  const [d, setD] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    setD(null);
    setError('');
    getDealerDetail(dealerId)
      .then((res) => live && setD(res))
      .catch((e) => live && setError(errMsg(e, 'Could not load the dealer.')));
    return () => {
      live = false;
    };
  }, [dealerId]);

  if (error) return <Alert severity="error">{error}</Alert>;
  if (!d) return <Box sx={{ py: 6, textAlign: 'center' }}><CircularProgress size={28} /></Box>;

  const s = d.summary;
  const held = d.cheques.filter((c) => c.counted);
  return (
    <Box>
      <Typography variant="body2" color="textSecondary">
        {d.dealer.dealer_id} · Tally ledger: {d.dealer.tally_ledger_name}
        {d.dealer.exclude_from_chase ? ' · Excluded from chase' : ''}
      </Typography>

      <Paper variant="outlined" sx={{ p: 1.5, mt: 1, borderRadius: 2 }}>
        <Grid container spacing={1}>
          <Stat label={`Tally O/S (as of ${fmtDate(d.tally_as_of)})`} value={drcr(s.tally_os)} />
          <Stat label="Received, not in Tally" value={s.received_not_in_tally ? inr(s.received_not_in_tally) : '—'} />
          <Stat label="Effective O/S" value={drcr(s.effective_os)} strong />
          <Stat label="PDCs held" value={s.pdc_count ? `${pdcs(s.pdc_count)} · ${inr(s.pdc_amount)}` : '—'} />
          <Stat label="Oldest overdue (days)" value={s.oldest_overdue_days ?? '—'} />
          <Grid item xs={6} sm={4} md={2}>
            <Typography variant="caption" color="textSecondary" component="div">Action</Typography>
            <Chip size="small" color={ACTION_COLOR[s.action]}
              label={s.action === 'WAIT' ? `WAIT till ${fmtDate(s.wait_till)}` : s.action} />
          </Grid>
        </Grid>
      </Paper>

      <Section title="Pending bills in Tally" count={d.bills.length}>
        <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell padding="none" />
                <TableCell sx={H}>Date</TableCell>
                <TableCell sx={H}>Ref. No.</TableCell>
                <TableCell sx={H}>Type</TableCell>
                <TableCell sx={H} align="right">Opening</TableCell>
                <TableCell sx={H} align="right">Pending</TableCell>
                <TableCell sx={H}>Due on</TableCell>
                <TableCell sx={H} align="right">Overdue (days)</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {d.bills.map((b) => <BillRow key={b.ref_no} b={b} />)}
              {!d.bills.length && (
                <TableRow><TableCell colSpan={8} sx={{ color: 'text.secondary' }}>No pending bills in the latest Tally Outstanding.</TableCell></TableRow>
              )}
              {d.bills.length > 0 && (
                <TableRow>
                  <TableCell colSpan={5} sx={{ fontWeight: 700 }}>Total</TableCell>
                  <TableCell align="right" sx={{ fontWeight: 700, whiteSpace: 'nowrap' }}>{drcr(s.tally_os)}</TableCell>
                  <TableCell colSpan={2} />
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Section>

      <Section title="PDC cheques" count={d.cheques.length}>
        <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
          PDCs held: {held.length ? `${pdcs(held.length)} · ${inr(s.pdc_amount)}` : 'none'}
        </Typography>
        <Typography variant="caption" color="textSecondary" component="div" sx={{ mb: 0.5 }}>
          Cheques {d.cheques_note}.
        </Typography>
        <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={H}>Cheque date</TableCell>
                <TableCell sx={H}>Cheque no.</TableCell>
                <TableCell sx={H}>Bank</TableCell>
                <TableCell sx={H} align="right">Amount</TableCell>
                <TableCell sx={H}>Status</TableCell>
                <TableCell sx={H}>Counted as held</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {d.cheques.map((c) => (
                <TableRow key={`${c.cheque_no}-${c.bank}`} hover>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>{fmtDate(c.cheque_date)}</TableCell>
                  <TableCell>{c.cheque_no}</TableCell>
                  <TableCell>{c.bank || '—'}</TableCell>
                  <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>{inr(c.amount)}</TableCell>
                  <TableCell><ChequeStatusChip c={c} /></TableCell>
                  <TableCell>
                    {c.counted ? 'Yes' : 'No'}
                    {c.boo_ref && <Typography variant="caption" color="error" component="div">Reversed in Tally by {c.boo_ref}</Typography>}
                  </TableCell>
                </TableRow>
              ))}
              {!d.cheques.length && (
                <TableRow><TableCell colSpan={6} sx={{ color: 'text.secondary' }}>No cheques from this dealer.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Section>

      <Section title="Payments logged in the app" count={d.payments.length}>
        <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={H}>Date</TableCell>
                <TableCell sx={H}>Mode</TableCell>
                <TableCell sx={H} align="right">Amount</TableCell>
                <TableCell sx={H}>Reference</TableCell>
                <TableCell sx={H}>Status</TableCell>
                <TableCell sx={H}>Tally receipt</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {d.payments.map((p) => (
                <TableRow key={p.id} hover>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>{fmtDate(p.payment_date)}</TableCell>
                  <TableCell>{p.mode}</TableCell>
                  <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>{inr(p.amount)}</TableCell>
                  <TableCell>{p.reference || '—'}</TableCell>
                  <TableCell><Chip size="small" color={PAY_COLOR[p.status]} label={p.status} /></TableCell>
                  <TableCell sx={{ whiteSpace: 'nowrap' }}>
                    {p.matched_vch_no ? `${p.matched_vch_no} · ${fmtDate(p.matched_vch_date)}` : p.bounced_by_ref || '—'}
                  </TableCell>
                </TableRow>
              ))}
              {!d.payments.length && (
                <TableRow><TableCell colSpan={6} sx={{ color: 'text.secondary' }}>No payments logged.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Section>

    </Box>
  );
};

export default DealerDetail;
