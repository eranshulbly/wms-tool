import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Grid,
  IconButton,
  MenuItem,
  Paper,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
  useMediaQuery,
  useTheme,
} from '@material-ui/core';
import { IconDownload, IconFileInvoice, IconPlus, IconRefresh, IconUpload, IconX } from '@tabler/icons';
import {
  downloadOutstanding,
  errMsg,
  getScreen,
  reprocess,
  setReviewed,
  uploadTallyExport,
} from '../../services/dealerPaymentsService';
import PaymentForm from './PaymentForm';
import DealerDetail, {
  ACTION_COLOR, actionLabel, ChequeStatusChip, CHEQUE_STATUS, countedIn, OverdueList, pdcs, Received
} from './DealerDetail';

// The daily dealer screen (spec 4): who to chase, who to wait for (PDC), who is not due yet,
// who is clear.
// Tally O/S comes from the latest Outstanding export; Received, not in Tally from payments
// logged here and still OPEN; PDCs from the cheque system. Flags in Manual check never
// change a balance.

const inr = (v) =>
  v === null || v === undefined ? '—' : `₹${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
const fmtTime = (iso) => String(iso).slice(11, 16);
const fmtDate = (iso) =>
  iso ? new Date(`${String(iso).slice(0, 10)}T00:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: '2-digit' }) : '—';
const fmtWhen = (iso) =>
  iso ? new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';

// ── Column filters for the dealer table ─────────────────────────────────────────────────────
// A money column (and Overdue, by days) takes a comparison: >50000, >=50000, <1000, <=1000,
// =0, or a range 10000-50000 (₹ and commas ignored). Anything else is looked for in the text
// the cell shows. Every filled-in filter must match.
const toNum = (t) => Number(String(t).replace(/[₹,\s]/g, ''));
const COMPARE = /^(>=|<=|>|<|=)\s*(-?[\d.,₹\s]+)$/;
const RANGE = /^(-?[\d.,₹]+)\s*(?:-|to)\s*(-?[\d.,₹]+)$/i;

export const matchesFilter = (value, text, filter) => {
  const f = (filter || '').trim();
  if (!f) return true;
  const cmp = f.match(COMPARE);
  const rng = !cmp && f.match(RANGE);
  if (cmp || rng) {
    if (value === null || value === undefined) return false;
    const v = Number(value);
    if (rng) return v >= Math.min(toNum(rng[1]), toNum(rng[2])) && v <= Math.max(toNum(rng[1]), toNum(rng[2]));
    const n = toNum(cmp[2]);
    return { '>': v > n, '>=': v >= n, '<': v < n, '<=': v <= n, '=': v === n }[cmp[1]];
  }
  const plain = (x) => String(x).toLowerCase().replace(/[,.]/g, '');   // "sas" finds S.A.S
  return plain(f).split(/\s+/).every((w) => plain(text).includes(w));
};

// key, the value compared, and the text searched, per column of the dealer table.
const COLUMN_FILTERS = [
  { key: 'dealer', placeholder: 'Name, town or ID', value: () => null, text: (r) => `${r.dealer} ${r.dealer_id}` },
  { key: 'tally_os', placeholder: 'e.g. >50000', value: (r) => r.tally_os, text: (r) => inr(r.tally_os) },
  { key: 'received', placeholder: 'e.g. >0', value: (r) => r.received_not_in_tally || 0,
    text: (r) => `${inr(r.received_not_in_tally)} ${r.cleared_cheques ? 'cleared cheque' : ''}` },
  { key: 'pdc', placeholder: 'e.g. >0', value: (r) => r.pdc_amount || 0,
    text: (r) => (r.pdc_count ? `${r.pdc_count} PDC ${inr(r.pdc_amount)} ${fmtDate(r.next_pdc_date)}` : '—') },
  { key: 'effective', placeholder: 'e.g. 10000-50000', value: (r) => r.effective_os, text: (r) => inr(r.effective_os) },
  // Overdue compares the oldest overdue days: >30 = something overdue more than 30 days.
  { key: 'overdue', placeholder: 'Days, e.g. >30', value: (r) => (r.overdue?.length ? r.overdue[0].days : null),
    text: (r) => (r.overdue || []).map((o) => `${inr(o.amount)} ${o.days} days`).join(' ') || '—' }
];

const FILES = [
  {
    key: 'outstanding',
    title: 'Tally Outstanding (Export 1)',
    hint: 'Group "Cadila Dist", pending bills with bill-wise voucher detail, 1-Apr to today',
    accept: '.xlsx',
    upload: (f) => uploadTallyExport('outstanding', f),
    describe: (u) => `as of ${fmtDate(u.as_of)} · ${u.row_count} bills`,
    done: (r) => `Loaded ${r.bills} pending bills as of ${fmtDate(r.as_of)} (grand total ${inr(r.grand_total)}).`,
  },
  {
    key: 'receipts',
    title: 'Receipt Register (Export 2)',
    hint: 'Last 60 days to today (first time: 1-Apr). Replaces every receipt dated in the file’s period.',
    accept: '.xlsx',
    upload: (f) => uploadTallyExport('receipts', f),
    describe: (u) => `${fmtDate(u.period_from)} to ${fmtDate(u.period_to)} · ${u.row_count} receipts`,
    done: (r) =>
      `Replaced receipts ${fmtDate(r.period_from)} to ${fmtDate(r.period_to)}: removed ${r.deleted}, loaded ${r.inserted}.`,
  },
];

const FileRow = ({ def, last, onDone }) => {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const pick = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await def.upload(f);
      const r = res.result || {};
      const extra = [];
      if (r.new_dealers?.length) extra.push(`New dealers added from this file: ${r.new_dealers.join(', ')}.`);
      (r.warnings || []).forEach((w) => extra.push(w));
      setMsg({ severity: extra.length ? 'warning' : 'success', text: def.done(r), extra });
      onDone();
    } catch (err) {
      setMsg({ severity: 'error', text: errMsg(err, 'Upload failed — nothing was changed.'), extra: [] });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Box py={1.25} sx={{ borderBottom: '1px solid #eef0f3' }}>
      <Box display="flex" alignItems="center" flexWrap="wrap" sx={{ gap: 1 }}>
        <Box flexGrow={1} minWidth={220}>
          <Typography variant="subtitle2">{def.title}</Typography>
          <Typography variant="caption" color="textSecondary" component="div">
            {last ? (
              <>
                <span style={{ color: '#b91c1c', fontWeight: 600 }}>Last: {def.describe(last)}</span> · {fmtWhen(last.uploaded_on)} by{' '}
                {last.uploaded_by}
              </>
            ) : (
              'Not uploaded yet'
            )}
            {' · '}
            {def.hint}
          </Typography>
        </Box>
        <Button component="label" size="small" variant="outlined" disabled={busy}
          startIcon={busy ? <CircularProgress size={14} /> : <IconUpload size={16} />}>
          {busy ? 'Loading…' : 'Upload'}
          <input hidden type="file" accept={def.accept} onChange={pick} />
        </Button>
      </Box>
      {msg && (
        <Alert severity={msg.severity} onClose={() => setMsg(null)} sx={{ mt: 1 }}>
          {msg.text}
          {msg.extra.map((t) => (
            <div key={t}>{t}</div>
          ))}
        </Alert>
      )}
    </Box>
  );
};

const ReviewCell = ({ item, onChanged }) => {
  const [note, setNote] = useState(item.review_note || '');
  const [busy, setBusy] = useState(false);
  const toggle = async (reviewed) => {
    setBusy(true);
    try {
      await setReviewed(item.id, reviewed, note);
      onChanged();
    } finally {
      setBusy(false);
    }
  };
  return (
    <Box display="flex" alignItems="center" sx={{ gap: 1 }}>
      <TextField size="small" placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)}
        inputProps={{ maxLength: 500 }} sx={{ minWidth: 140 }} />
      <FormControlLabel
        control={<Switch size="small" checked={item.reviewed} disabled={busy} onChange={(e) => toggle(e.target.checked)} />}
        label="Reviewed"
      />
    </Box>
  );
};

const List = ({ title, empty, children, count }) => (
  <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, height: '100%' }}>
    <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
      {title} {count ? <Chip size="small" label={count} sx={{ ml: 0.5 }} /> : null}
    </Typography>
    {count ? children : <Typography variant="body2" color="textSecondary">{empty}</Typography>}
  </Paper>
);

const DealerPayments = () => {
  const theme = useTheme();
  const phone = useMediaQuery(theme.breakpoints.down('sm'));
  const [screen, setScreen] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showReviewed, setShowReviewed] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  const [detail, setDetail] = useState(null); // {id, label} of the dealer opened
  const [chequesOpen, setChequesOpen] = useState(false);
  const [chequeStatus, setChequeStatus] = useState('');
  const [downloading, setDownloading] = useState(false);
  const [filters, setFilters] = useState({});   // column key -> what is typed; action -> chosen action
  const setFilter = (key, v) => setFilters((f) => ({ ...f, [key]: v }));

  const download = async () => {
    setDownloading(true);
    try {
      await downloadOutstanding();
    } catch (e) {
      setError(errMsg(e, 'Could not download the Outstanding file.'));
    } finally {
      setDownloading(false);
    }
  };

  // wareops (the cheque system) is read only on the first load, when the tile is opened;
  // later reloads reuse the cheques read then.
  const firstLoad = useRef(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    const readCheques = firstLoad.current;
    firstLoad.current = false;
    try {
      setScreen(await getScreen(showReviewed, readCheques));
    } catch (e) {
      setError(errMsg(e, 'Could not load the dealer screen.'));
    } finally {
      setLoading(false);
    }
  }, [showReviewed]);

  useEffect(() => {
    load();
  }, [load]);

  const refresh = async () => {
    setLoading(true);
    try {
      await reprocess();
    } catch (e) {
      setError(errMsg(e, 'Could not re-run the matching.'));
    }
    load();
  };

  const s = screen || {};
  const rows = s.rows || [];
  const filtersOn = Object.values(filters).some((v) => (v || '').trim());
  const shownRows = rows.filter(
    (r) =>
      COLUMN_FILTERS.every((c) => matchesFilter(c.value(r), c.text(r), filters[c.key])) &&
      (!filters.action || r.action === filters.action)
  );
  const uploads = s.uploads || {};
  const cheque = s.cheque_system || {};

  return (
    <Box>
      <Box display="flex" alignItems="center" flexWrap="wrap" sx={{ gap: 1, mb: 1 }}>
        <Box flexGrow={1}>
          <Typography variant="h3">Dealer Payments</Typography>
          <Typography variant="body2" sx={{ color: '#b91c1c', fontWeight: 600 }}>
            Tally as of: {fmtDate(s.tally_as_of)} · Vouchers loaded to: {fmtDate(s.vouchers_loaded_to)}
          </Typography>
        </Box>
        <Button variant="contained" disableElevation startIcon={<IconPlus size={16} />} onClick={() => setLogOpen(true)}>
          Log payment
        </Button>
        <Button variant="outlined" startIcon={<IconFileInvoice size={16} />} onClick={() => setChequesOpen(true)}>
          PDC cheques{s.cheques ? ` (${s.cheques.length})` : ''}
        </Button>
        <Button variant="outlined" startIcon={downloading ? <CircularProgress size={14} /> : <IconDownload size={16} />}
          onClick={download} disabled={downloading || !s.tally_as_of}>
          Download outstanding
        </Button>
        <Button variant="outlined" startIcon={loading ? <CircularProgress size={14} /> : <IconRefresh size={16} />}
          onClick={refresh} disabled={loading}>
          Refresh
        </Button>
      </Box>
      {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}

      <Paper variant="outlined" sx={{ p: 2, mb: 2, borderRadius: 2 }}>
        <Typography variant="subtitle2">Files</Typography>
        {FILES.map((def) => (
          <FileRow key={def.key} def={def} last={uploads[def.key]} onDone={load} />
        ))}
      </Paper>

      <Grid container spacing={2} sx={{ mb: 2 }}>
        <Grid item xs={12} md={6}>
          <List title="PDCs due today / tomorrow (to deposit)" count={(s.pdcs_due || []).length}
            empty={cheque.connected === false ? 'The cheque system could not be read, so no PDCs are shown.' : 'None.'}>
            {(s.pdcs_due || []).map((c) => (
              <Typography key={`${c.cheque_no}-${c.bank}`} variant="body2">
                {fmtDate(c.cheque_date)} · {c.dealer} · {inr(c.amount)} · {c.bank} #{c.cheque_no}
              </Typography>
            ))}
          </List>
        </Grid>
        <Grid item xs={12} md={6}>
          <List title="Stale payments (logged over 5 days ago, not in Tally)" count={(s.stale_payments || []).length} empty="None.">
            {(s.stale_payments || []).map((p) => (
              <Typography key={p.id} variant="body2">
                {fmtDate(p.payment_date)} · {p.dealer} · {inr(p.amount)} · {p.mode}
                {p.reference ? ` · ${p.reference}` : ''} · {p.days_open} days
              </Typography>
            ))}
          </List>
        </Grid>
      </Grid>
      {cheque.error && <Alert severity="warning" sx={{ mb: 1 }}>{cheque.error}</Alert>}

      {filtersOn && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1 }}>
          <Typography variant="body2" color="textSecondary">{shownRows.length} of {rows.length} dealers</Typography>
          <Button size="small" onClick={() => setFilters({})}>Clear filters</Button>
        </Box>
      )}

      <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2, mb: 2 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell sx={{ fontWeight: 600 }}>Dealer</TableCell>
              <TableCell align="right" sx={{ fontWeight: 600 }}>Tally O/S</TableCell>
              <TableCell align="right" sx={{ fontWeight: 600 }}>Received, not in Tally</TableCell>
              <TableCell align="right" sx={{ fontWeight: 600 }}>
                PDCs held{cheque.connected === false ? ' *' : ''}
              </TableCell>
              <TableCell align="right" sx={{ fontWeight: 600 }}>Effective O/S</TableCell>
              <TableCell align="right" sx={{ fontWeight: 600 }}>Overdue (amount · days)</TableCell>
              <TableCell sx={{ fontWeight: 600 }}>Action</TableCell>
            </TableRow>
            <TableRow>
              {COLUMN_FILTERS.map((c) => (
                <TableCell key={c.key} sx={{ py: 0.5 }}>
                  <TextField variant="standard" size="small" fullWidth placeholder={c.placeholder}
                    value={filters[c.key] || ''} onChange={(e) => setFilter(c.key, e.target.value)}
                    inputProps={{ 'aria-label': `Filter ${c.key}`, style: { fontSize: 13 } }} />
                </TableCell>
              ))}
              <TableCell sx={{ py: 0.5 }}>
                <TextField select variant="standard" size="small" fullWidth value={filters.action || ''}
                  onChange={(e) => setFilter('action', e.target.value)}
                  SelectProps={{ displayEmpty: true }} inputProps={{ 'aria-label': 'Filter action', style: { fontSize: 13 } }}>
                  <MenuItem value="">All</MenuItem>
                  {['CHASE', 'WAIT', 'NOT_DUE', 'CLEAR'].map((a) => (
                    <MenuItem key={a} value={a}>{a === 'NOT_DUE' ? 'NOT DUE' : a}</MenuItem>
                  ))}
                </TextField>
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading && !screen && (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 4 }}><CircularProgress size={24} /></TableCell>
              </TableRow>
            )}
            {screen && !rows.length && (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 4, color: 'text.secondary' }}>
                  {s.dealer_count ? 'No active dealers to show.' : 'Upload the Tally Outstanding export to start: dealers are created from it.'}
                </TableCell>
              </TableRow>
            )}
            {screen && rows.length > 0 && !shownRows.length && (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 4, color: 'text.secondary' }}>
                  No dealer matches the filters.
                </TableCell>
              </TableRow>
            )}
            {shownRows.map((r) => (
              <TableRow key={r.dealer_id} hover sx={{ cursor: 'pointer' }}
                onClick={() => setDetail({ id: r.dealer_id, label: r.dealer })}>
                <TableCell>
                  <Box component="span" sx={{ color: 'primary.main', fontWeight: 500 }}>{r.dealer}</Box>
                </TableCell>
                <TableCell align="right">{inr(r.tally_os)}</TableCell>
                <TableCell align="right"><Received s={r} /></TableCell>
                <TableCell align="right">
                  {r.pdc_count ? (
                    <>
                      <Box component="span" sx={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{pdcs(r.pdc_count)} · {inr(r.pdc_amount)}</Box>
                      <Typography variant="caption" color="textSecondary" component="div">next {fmtDate(r.next_pdc_date)}</Typography>
                    </>
                  ) : '—'}
                </TableCell>
                <TableCell align="right" sx={{ fontWeight: 600 }}>{inr(r.effective_os)}</TableCell>
                <TableCell align="right"><OverdueList overdue={r.overdue} /></TableCell>
                <TableCell>
                  <Chip size="small" color={ACTION_COLOR[r.action]} label={actionLabel(r)} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      {cheque.connected === false && (
        <Typography variant="caption" color="textSecondary" component="div" sx={{ mb: 2 }}>
          * The cheque system could not be read, so PDCs held is empty for every dealer.
        </Typography>
      )}
      {cheque.connected && (
        <Typography variant="caption" color="textSecondary" component="div" sx={{ mb: 2 }}>
          PDCs from {cheque.name}{cheque.read_at ? `, read at ${fmtTime(cheque.read_at)} when this page was opened` : ''}:{' '}
          {cheque.cheques || 0} cheque(s) matched to Cadila dealers
          {cheque.other_parties ? `; cheques from ${cheque.other_parties} other parties (not Cadila dealers) skipped` : ''}.
        </Typography>
      )}

      <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
        <Box display="flex" alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600, flexGrow: 1 }}>
            Manual check {(s.manual_checks || []).length ? <Chip size="small" label={(s.manual_checks || []).length} /> : null}
          </Typography>
          <FormControlLabel control={<Switch size="small" checked={showReviewed} onChange={(e) => setShowReviewed(e.target.checked)} />}
            label="Show reviewed" />
        </Box>
        <Typography variant="caption" color="textSecondary" component="div" sx={{ mb: 1 }}>
          Flags for a person to look at. They never change a balance.
        </Typography>
        {!(s.manual_checks || []).length ? (
          <Typography variant="body2" color="textSecondary">Nothing to check.</Typography>
        ) : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell sx={{ fontWeight: 600 }}>Type</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Dealer</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Voucher(s)</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Dates</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Amounts</TableCell>
                  <TableCell sx={{ fontWeight: 600 }}>Reason</TableCell>
                  <TableCell />
                </TableRow>
              </TableHead>
              <TableBody>
                {(s.manual_checks || []).map((m) => (
                  <TableRow key={m.id} sx={m.reviewed ? { opacity: 0.6 } : undefined}>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{m.type_label}</TableCell>
                    <TableCell>
                      {m.dealer_name ? `${m.dealer_name}${m.town ? ` (${m.town})` : ''}` : m.details.party_name || '—'}
                    </TableCell>
                    <TableCell>{(m.details.vouchers || []).join(', ') || '—'}</TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{(m.details.dates || []).filter(Boolean).map(fmtDate).join(', ') || '—'}</TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{(m.details.amounts || []).filter((a) => a !== null).map(inr).join(', ') || '—'}</TableCell>
                    <TableCell>{m.reason}</TableCell>
                    <TableCell><ReviewCell item={m} onChanged={load} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Paper>

      <Dialog open={!!detail} onClose={() => setDetail(null)} fullScreen={phone} fullWidth maxWidth="lg">
        <DialogTitle sx={{ display: 'flex', alignItems: 'center' }}>
          <Box flexGrow={1}>{detail?.label}</Box>
          <IconButton onClick={() => setDetail(null)} size="small"><IconX size={18} /></IconButton>
        </DialogTitle>
        <DialogContent>{detail && <DealerDetail dealerId={detail.id} />}</DialogContent>
      </Dialog>

      <Dialog open={chequesOpen} onClose={() => setChequesOpen(false)} fullScreen={phone} fullWidth maxWidth="lg">
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Box flexGrow={1}>PDC cheques of Cadila dealers</Box>
          <TextField select size="small" label="Status" value={chequeStatus} onChange={(e) => setChequeStatus(e.target.value)}
            sx={{ minWidth: 140 }} SelectProps={{ displayEmpty: true }} InputLabelProps={{ shrink: true }}>
            <MenuItem value="">All</MenuItem>
            {Object.entries(CHEQUE_STATUS).map(([k, v]) => <MenuItem key={k} value={k}>{v.label}</MenuItem>)}
          </TextField>
          <IconButton onClick={() => setChequesOpen(false)} size="small"><IconX size={18} /></IconButton>
        </DialogTitle>
        <DialogContent>
          <Typography variant="caption" color="textSecondary" component="div" sx={{ mb: 1 }}>
            {cheque.error || (cheque.read_at ? `Read from ${cheque.name} at ${fmtTime(cheque.read_at)} when this page was opened.` : '')}
            {' '}Click a dealer to open it.
          </Typography>
          <TableContainer component={Paper} variant="outlined" sx={{ borderRadius: 2 }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  {['Cheque date', 'Dealer', 'Cheque no.', 'Bank', 'Amount', 'Status', 'Counted in'].map((h) => (
                    <TableCell key={h} align={h === 'Amount' ? 'right' : 'left'} sx={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{h}</TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {(s.cheques || []).filter((c) => !chequeStatus || c.status === chequeStatus).map((c) => (
                  <TableRow key={`${c.cheque_no}-${c.bank}`} hover sx={{ cursor: 'pointer' }}
                    onClick={() => setDetail({ id: c.dealer_id, label: c.dealer })}>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{fmtDate(c.cheque_date)}</TableCell>
                    <TableCell sx={{ color: 'primary.main' }}>{c.dealer}</TableCell>
                    <TableCell>{c.cheque_no}</TableCell>
                    <TableCell>{c.bank || '—'}</TableCell>
                    <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>{inr(c.amount)}</TableCell>
                    <TableCell><ChequeStatusChip c={c} /></TableCell>
                    <TableCell>
                      {countedIn(c)}
                      {c.boo_ref && <Typography variant="caption" color="error" component="div">Reversed in Tally by {c.boo_ref}</Typography>}
                    </TableCell>
                  </TableRow>
                ))}
                {!(s.cheques || []).filter((c) => !chequeStatus || c.status === chequeStatus).length && (
                  <TableRow><TableCell colSpan={7} sx={{ color: 'text.secondary' }}>No cheques.</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </DialogContent>
      </Dialog>

      <Dialog open={logOpen} onClose={() => setLogOpen(false)} fullScreen={phone} fullWidth maxWidth="sm">
        <DialogTitle sx={{ display: 'flex', alignItems: 'center' }}>
          <Box flexGrow={1}>Log payment</Box>
          <IconButton onClick={() => setLogOpen(false)} size="small"><IconX size={18} /></IconButton>
        </DialogTitle>
        <DialogContent>
          <Box pt={1}>
            <PaymentForm onSaved={load} />
          </Box>
        </DialogContent>
      </Dialog>
    </Box>
  );
};

export default DealerPayments;
