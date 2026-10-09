import React, { useMemo, useState } from 'react';
import {
  Box,
  Button,
  Typography,
  CircularProgress,
  Grid,
  TextField,
  Paper,
  Alert,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Snackbar,
  Chip,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconUpload, IconCashBanknote } from '@tabler/icons';
import api from '../../services/api';

// Outstanding Check — upload a Tally "Pending Bills" export and see what each dealer
// owes, and for how long. Nothing is saved: the backend reads the file in memory and
// returns figures only, so the same (or a fresher) export can be checked any number of
// times without side effects.

const OVER_30_DAYS = 30;

const useStyles = makeStyles((theme) => ({
  section: { marginBottom: theme.spacing(3) },
  drop: {
    border: '2px dashed #c4cdd5',
    borderRadius: 8,
    padding: theme.spacing(3),
    textAlign: 'center',
    background: '#fafbfc',
  },
  muted: { color: '#7a869a' },
  mono: { fontFamily: 'monospace', fontSize: '0.8rem' },
  num: { whiteSpace: 'nowrap' },
  tileValue: { fontWeight: 600, lineHeight: 1.2 },
  overdueRow: { background: '#fef2f2' },
  overdueText: { color: '#b91c1c', fontWeight: 600 },
}));

const money = (v) =>
  v === null || v === undefined
    ? '—'
    : `₹${Number(v).toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
const nf0 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });

const BILL_COLUMNS = [
  { key: 'dealer_name', label: 'Dealer' },
  { key: 'town', label: 'Town' },
  { key: 'bill_date', label: 'Bill date' },
  { key: 'ref_no', label: 'Ref #' },
  { key: 'due_on', label: 'Due on' },
  { key: 'days_overdue', label: 'Days overdue', align: 'right' },
  { key: 'amount', label: 'Amount', align: 'right' },
];

const OutstandingCheck = () => {
  const classes = useStyles();

  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [toast, setToast] = useState(null);

  const [daysFilter, setDaysFilter] = useState('');
  const [dealerFilter, setDealerFilter] = useState('');

  const check = async () => {
    if (!file) return;
    setBusy(true);
    setResult(null);
    try {
      const form = new FormData();
      form.append('file', file);
      const { data } = await api.post('admin/outstanding-check', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      if (data.success) setResult(data);
      else setToast({ severity: 'error', msg: data.msg || 'Outstanding check failed' });
    } catch (e) {
      setToast({ severity: 'error', msg: e?.response?.data?.msg || 'Outstanding check failed' });
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setFile(null);
    setResult(null);
    setDaysFilter('');
    setDealerFilter('');
  };

  const minDays = daysFilter.trim() === '' ? null : Number(daysFilter);
  const dealerTerm = dealerFilter.trim().toLowerCase();

  const matchesDealerTerm = (name, town) =>
    !dealerTerm || `${name || ''} ${town || ''}`.toLowerCase().includes(dealerTerm);

  const filteredBills = useMemo(() => {
    if (!result) return [];
    return result.bills
      .filter((b) => {
        if (!matchesDealerTerm(b.dealer_name, b.town)) return false;
        if (minDays !== null && !Number.isNaN(minDays) && b.days_overdue < minDays) return false;
        return true;
      })
      .sort((a, b) => b.days_overdue - a.days_overdue || b.amount - a.amount);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, dealerTerm, minDays]);

  const filteredTotal = useMemo(
    () => filteredBills.reduce((sum, b) => sum + (b.amount || 0), 0),
    [filteredBills]
  );

  const s = result?.summary;
  const tiles = s
    ? [
        { label: 'Dealers', value: nf0.format(s.dealer_count) },
        { label: 'Bills', value: nf0.format(s.bill_count) },
        { label: 'Total outstanding', value: money(s.total_outstanding) },
        {
          label: `Over ${OVER_30_DAYS} days`,
          value: `${nf0.format(s.over_30_dealer_count)} dealer${s.over_30_dealer_count === 1 ? '' : 's'}`,
          hint: money(s.over_30_amount),
          color: s.over_30_dealer_count > 0 ? '#b91c1c' : undefined,
        },
      ]
    : [];

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Outstanding Check
      </Typography>
      <Typography variant="body2" className={classes.muted} style={{ marginBottom: 16 }}>
        Upload the "Pending Bills" / outstanding statement you export from Tally to see what each
        dealer owes and for how long. Days outstanding is worked out fresh from each bill&apos;s due
        date against today — not the age printed in the file, which goes stale the moment the clock
        moves on. Nothing from this check is saved.
      </Typography>

      <Paper variant="outlined" className={classes.section} style={{ padding: 16 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12}>
            <label htmlFor="outstanding-check-file">
              <input
                id="outstanding-check-file"
                type="file"
                accept=".xlsx"
                style={{ display: 'none' }}
                onChange={(e) => {
                  setFile(e.target.files?.[0] || null);
                  setResult(null);
                }}
              />
              <Box className={classes.drop}>
                <IconCashBanknote size={28} />
                <Typography variant="body2" className={classes.muted}>
                  Choose a Tally outstanding / pending bills export (.xlsx)
                </Typography>
                {file && (
                  <Typography variant="body2" className={classes.mono} style={{ marginTop: 6 }}>
                    {file.name}
                  </Typography>
                )}
                <Button component="span" size="small" style={{ marginTop: 8 }}>
                  Browse
                </Button>
              </Box>
            </label>
          </Grid>
        </Grid>

        <Box mt={2} display="flex" alignItems="center">
          <Button
            variant="contained"
            startIcon={busy ? <CircularProgress size={16} /> : <IconUpload size={16} />}
            disabled={!file || busy}
            onClick={check}
          >
            {busy ? 'Checking…' : 'Check outstanding'}
          </Button>
          {result && (
            <Button size="small" onClick={reset} style={{ marginLeft: 12 }}>
              Upload another file
            </Button>
          )}
        </Box>
      </Paper>

      {result && (
        <>
          {tiles.length > 0 && (
            <Grid container spacing={2} className={classes.section}>
              {tiles.map((t) => (
                <Grid item xs={6} sm={3} key={t.label}>
                  <Paper variant="outlined" style={{ padding: 12, height: '100%' }}>
                    <Typography variant="body2" className={classes.muted}>
                      {t.label}
                    </Typography>
                    <Typography variant="h4" className={classes.tileValue} style={{ color: t.color }}>
                      {t.value}
                    </Typography>
                    {t.hint && (
                      <Typography variant="caption" className={classes.muted}>
                        {t.hint}
                      </Typography>
                    )}
                  </Paper>
                </Grid>
              ))}
            </Grid>
          )}

          <Paper variant="outlined" className={classes.section} style={{ padding: 16 }}>
            <Grid container spacing={2} alignItems="center">
              <Grid item xs={12} sm={4}>
                <TextField
                  fullWidth
                  size="small"
                  type="number"
                  label="Days outstanding (at least)"
                  placeholder="e.g. 30"
                  value={daysFilter}
                  onChange={(e) => setDaysFilter(e.target.value)}
                  inputProps={{ min: 0 }}
                />
              </Grid>
              <Grid item xs={12} sm={5}>
                <TextField
                  fullWidth
                  size="small"
                  label="Search dealer"
                  placeholder="Dealer name or town"
                  value={dealerFilter}
                  onChange={(e) => setDealerFilter(e.target.value)}
                />
              </Grid>
              <Grid item xs={12} sm={3}>
                {(daysFilter || dealerFilter) && (
                  <Button
                    size="small"
                    onClick={() => {
                      setDaysFilter('');
                      setDealerFilter('');
                    }}
                  >
                    Clear filters
                  </Button>
                )}
              </Grid>
            </Grid>
          </Paper>

          <TableContainer component={Paper} variant="outlined" style={{ maxHeight: '62vh' }}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  {BILL_COLUMNS.map((c) => (
                    <TableCell key={c.key} align={c.align || 'left'}>
                      {c.label}
                    </TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {filteredBills.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={BILL_COLUMNS.length} align="center" className={classes.muted}>
                      No bills match the current filter.
                    </TableCell>
                  </TableRow>
                )}
                {filteredBills.map((b) => {
                  const overdue = b.amount > 0 && b.days_overdue > OVER_30_DAYS;
                  return (
                    <TableRow
                      key={`${b.dealer_name}|${b.town}|${b.ref_no}|${b.bill_date}`}
                      hover
                      className={overdue ? classes.overdueRow : ''}
                    >
                      <TableCell>{b.dealer_name}</TableCell>
                      <TableCell>{b.town || '—'}</TableCell>
                      <TableCell>{b.bill_date}</TableCell>
                      <TableCell className={classes.mono}>
                        {b.ref_no}
                        {b.amount < 0 && (
                          <Chip label="Credit" size="small" style={{ marginLeft: 6 }} />
                        )}
                      </TableCell>
                      <TableCell>{b.due_on}</TableCell>
                      <TableCell align="right" className={`${classes.num} ${overdue ? classes.overdueText : ''}`}>
                        {b.days_overdue}
                      </TableCell>
                      <TableCell align="right" className={`${classes.num} ${overdue ? classes.overdueText : ''}`}>
                        {money(b.amount)}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
              {filteredBills.length > 0 && (
                <TableBody>
                  <TableRow>
                    <TableCell colSpan={BILL_COLUMNS.length - 1} style={{ fontWeight: 600 }}>
                      Total (filtered)
                    </TableCell>
                    <TableCell align="right" className={classes.num} style={{ fontWeight: 600 }}>
                      {money(filteredTotal)}
                    </TableCell>
                  </TableRow>
                </TableBody>
              )}
            </Table>
          </TableContainer>
        </>
      )}

      <Snackbar
        open={!!toast}
        autoHideDuration={5000}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity={toast?.severity || 'info'} onClose={() => setToast(null)}>
          {toast?.msg}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default OutstandingCheck;
