import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  IconButton,
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
import { makeStyles } from '@material-ui/styles';
import { IconChevronDown, IconChevronRight, IconDownload, IconFileZip } from '@tabler/icons';
import { downloadAll, downloadExecutive, getBeatReport } from '../../services/beatOutstandingService';
import { readBlobError } from '../../services/orderService';
import { BEAT_FEEDS, UploadRow } from '../dms-uploads/DmsFeedUpload';

// Beat Outstanding — a distributor's Tally outstanding split by the beats each sales
// executive covers on a day, to hand to them as an Excel file. Built from three uploads:
// the Outlet Master (outlet -> beat; Admin -> Outlet Master Upload) and, on this page,
// the day's Beat Plan (executive x day -> beats) and the Tally Outstanding Report. Parties the Outlet Master cannot place on one beat are
// listed separately so none of the outstanding goes unseen.

const OVER_30_DAYS = 30;

const useStyles = makeStyles((theme) => ({
  section: { marginBottom: theme.spacing(3) },
  muted: { color: '#7a869a' },
  num: { whiteSpace: 'nowrap' },
  red: { color: '#b91c1c', fontWeight: 600 },
}));

const money = (v) =>
  v === null || v === undefined ? '—' : `₹${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
const fmtDate = (iso, opts = { day: '2-digit', month: 'short', year: 'numeric' }) => {
  if (!iso) return '—';
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-IN', opts);
};
const fmtDateTime = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
};
const errMsg = (e, fallback) => e?.response?.data?.msg || fallback;

const Days = ({ days }) => {
  const classes = useStyles();
  if (days === null || days === undefined) return '—';
  return <span className={days > OVER_30_DAYS ? classes.red : undefined}>{days}</span>;
};

// The feeds uploaded on this page; the Outlet Master is only shown, from Admin.
const PAGE_FEEDS = BEAT_FEEDS.filter((f) => f.feed !== 'outlets');

const FilesPanel = ({ feeds, onUploaded }) => {
  const classes = useStyles();
  const master = feeds.find((f) => f.feed === 'outlets');
  const last = master?.last_upload;
  return (
    <Paper variant="outlined" className={classes.section} style={{ padding: 16 }}>
      <Typography variant="subtitle2">Files</Typography>
      <Box py={1.5} style={{ borderBottom: '1px solid #eef0f3' }}>
        <Typography variant="subtitle2">Outlet Master</Typography>
        {last ? (
          <Typography variant="caption" component="div">
            <span style={{ color: '#b91c1c', fontWeight: 600 }}>
              Last Updated: {fmtDateTime(last.uploaded_on)}
            </span>
            <span className={classes.muted}> · update from Admin → Outlet Master Upload</span>
          </Typography>
        ) : (
          <Typography variant="caption" className={classes.red} component="div">
            Not uploaded yet — upload it from Admin → Outlet Master Upload
          </Typography>
        )}
      </Box>
      {PAGE_FEEDS.map((def) => (
        <UploadRow
          key={def.feed}
          def={def}
          statuses={feeds.filter((f) => f.feed === def.feed)}
          onUploaded={() => onUploaded(def.feed)}
        />
      ))}
    </Paper>
  );
};

const DealerTable = ({ dealers }) => {
  const classes = useStyles();
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>Dealer</TableCell>
          <TableCell>Beat</TableCell>
          <TableCell>City</TableCell>
          <TableCell>Bills</TableCell>
          <TableCell align="right">Days overdue</TableCell>
          <TableCell align="right">Outstanding</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {dealers.map((d) => (
          <TableRow key={d.party_name}>
            <TableCell>{d.party_name}</TableCell>
            <TableCell>{d.beat_name}</TableCell>
            <TableCell>{d.city || '—'}</TableCell>
            <TableCell>
              {d.bills.map((b) => (
                <div key={b.ref_no} className={classes.num}>
                  {b.ref_no} <span className={classes.muted}>· due {fmtDate(b.due_on, { day: '2-digit', month: 'short' })} · {money(b.amount)}</span>
                </div>
              ))}
            </TableCell>
            <TableCell align="right">
              <Days days={d.max_days_overdue} />
            </TableCell>
            <TableCell align="right" className={classes.num}>
              {money(d.amount)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
};

const ExecutiveRow = ({ exec, planDate, onError }) => {
  const classes = useStyles();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const has = exec.dealers.length > 0;

  const download = async () => {
    setBusy(true);
    try {
      await downloadExecutive(planDate, exec);
    } catch (e) {
      onError((await readBlobError(e)) || 'Download failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <TableRow hover>
        <TableCell padding="checkbox">
          {has && (
            <IconButton size="small" onClick={() => setOpen(!open)} aria-label="Show dealers">
              {open ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />}
            </IconButton>
          )}
        </TableCell>
        <TableCell style={{ fontWeight: 600 }}>{exec.se_name}</TableCell>
        <TableCell>
          <Box display="flex" flexWrap="wrap" style={{ gap: 4 }}>
            {exec.beats.map((b) => (
              <Chip
                key={b.beat_id}
                size="small"
                variant="outlined"
                label={`${b.beat_name}${b.dealer_count ? ` · ${money(b.amount)}` : ''}`}
              />
            ))}
          </Box>
        </TableCell>
        <TableCell align="right">{exec.dealer_count}</TableCell>
        <TableCell align="right" className={classes.num} style={{ fontWeight: 600 }}>
          {has ? money(exec.amount) : <span className={classes.muted}>Nothing due</span>}
        </TableCell>
        <TableCell align="right">
          <Days days={exec.max_days_overdue} />
        </TableCell>
        <TableCell align="right">
          <Button
            size="small"
            variant="outlined"
            disabled={!has || busy}
            onClick={download}
            startIcon={busy ? <CircularProgress size={14} /> : <IconDownload size={14} />}
          >
            Excel
          </Button>
        </TableCell>
      </TableRow>
      {has && (
        <TableRow>
          <TableCell colSpan={7} style={{ padding: 0, borderBottom: open ? undefined : 'none' }}>
            <Collapse in={open} unmountOnExit>
              <Box px={2} py={1} style={{ background: '#fafbfc' }}>
                <DealerTable dealers={exec.dealers} />
              </Box>
            </Collapse>
          </TableCell>
        </TableRow>
      )}
    </>
  );
};

const BeatOutstanding = () => {
  const classes = useStyles();
  const [rep, setRep] = useState(null);
  const [date, setDate] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [zipping, setZipping] = useState(false);

  const load = useCallback((d) => {
    setLoading(true);
    setError(null);
    getBeatReport(d)
      .then((res) => {
        setRep(res);
        setDate(res.plan_date || '');
      })
      .catch((e) => setError(errMsg(e, 'Could not load the report.')))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const downloadZip = async () => {
    setZipping(true);
    setError(null);
    try {
      await downloadAll(date);
    } catch (e) {
      setError((await readBlobError(e)) || 'Download failed.');
    } finally {
      setZipping(false);
    }
  };

  const execs = rep?.executives || [];
  // Today is always offered (and is the default) even before its plan is uploaded.
  const dateOptions = rep ? [...new Set([rep.today, ...rep.plan_dates])].sort().reverse() : [];
  const onPlan = execs.reduce((s, e) => s + e.amount, 0);
  const withDues = execs.filter((e) => e.dealers.length > 0).length;

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Beat Outstanding
      </Typography>
      <Typography variant="body2" className={classes.muted} style={{ marginBottom: 16 }}>
        Each executive gets the outstanding of the dealers on the beats they cover that day.
      </Typography>

      {rep?.feeds && (
        // A new beat plan reopens on today; a new outstanding report keeps the date
        // being looked at.
        <FilesPanel feeds={rep.feeds} onUploaded={(feed) => load(feed === 'beat_plan' ? undefined : date)} />
      )}

      {error && (
        <Alert severity="error" className={classes.section}>
          {error}
        </Alert>
      )}

      {loading && !rep && <CircularProgress size={24} />}

      {rep && (
        <>
          <Paper variant="outlined" className={classes.section} style={{ padding: 16 }}>
            <Box display="flex" alignItems="center" flexWrap="wrap" style={{ gap: 16 }}>
              <TextField
                select
                size="small"
                label="Beat plan date"
                value={date}
                onChange={(e) => load(e.target.value)}
                style={{ minWidth: 260 }}
              >
                {dateOptions.map((d) => (
                  <MenuItem key={d} value={d}>
                    {fmtDate(d, { weekday: 'long', day: '2-digit', month: 'short', year: 'numeric' })}
                    {d === rep.today ? ' (today)' : ''}
                  </MenuItem>
                ))}
              </TextField>
              <Box flexGrow={1}>
                <Typography variant="body2">
                  <b>{money(onPlan)}</b> on this day's beats <span className={classes.muted}>of {money(rep.total_outstanding)} total outstanding</span>
                </Typography>
                <Typography variant="caption" className={classes.muted}>
                  Days overdue as of {fmtDate(rep.as_of)}, counted from each bill's due date.
                </Typography>
              </Box>
              <Button
                variant="contained"
                disabled={!withDues || zipping || loading}
                onClick={downloadZip}
                startIcon={zipping ? <CircularProgress size={14} /> : <IconFileZip size={16} />}
              >
                Download all ({withDues})
              </Button>
            </Box>
          </Paper>

          {rep.plan_missing && (
            <Alert severity="warning" className={classes.section}>
              No beat plan uploaded for {fmtDate(rep.plan_date, { weekday: 'long', day: '2-digit', month: 'short', year: 'numeric' })}
              {rep.plan_date === rep.today ? ' (today)' : ''}. Upload it under Files above to see each executive's
              outstanding.
            </Alert>
          )}

          <Paper variant="outlined" className={classes.section}>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell padding="checkbox" />
                    <TableCell>Executive</TableCell>
                    <TableCell>Beats this day</TableCell>
                    <TableCell align="right">Dealers</TableCell>
                    <TableCell align="right">Outstanding</TableCell>
                    <TableCell align="right">Oldest (days)</TableCell>
                    <TableCell />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {execs.map((e) => (
                    <ExecutiveRow key={`${e.user_id}-${e.se_name}`} exec={e} planDate={date} onError={setError} />
                  ))}
                  {!execs.length && (
                    <TableRow>
                      <TableCell colSpan={7} className={classes.muted}>
                        {rep.plan_missing ? 'No beat plan for this day.' : 'No executives on this day\'s plan.'}
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>

          {rep.unplaced.length > 0 && (
            <Paper variant="outlined" className={classes.section} style={{ padding: 16 }}>
              <Typography variant="subtitle2">Not on any beat ({rep.unplaced.length})</Typography>
              <Typography variant="caption" className={classes.muted} component="div" style={{ marginBottom: 8 }}>
                These parties' outstanding goes to nobody. Fix the outlet in the DMS (same name as in Tally, on one beat) and upload the Outlet Master again.
              </Typography>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Party (Tally)</TableCell>
                    <TableCell>Why</TableCell>
                    <TableCell align="right">Bills</TableCell>
                    <TableCell align="right">Outstanding</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rep.unplaced.map((u) => (
                    <TableRow key={u.party_name}>
                      <TableCell>{u.party_name}</TableCell>
                      <TableCell>
                        {u.reason}
                        {u.beats ? <span className={classes.muted}> ({u.beats.join(', ')})</span> : null}
                      </TableCell>
                      <TableCell align="right">{u.bill_count}</TableCell>
                      <TableCell align="right" className={classes.num}>
                        {money(u.amount)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Paper>
          )}

          {rep.off_plan.length > 0 && (
            <Paper variant="outlined" className={classes.section} style={{ padding: 16 }}>
              <Typography variant="subtitle2" gutterBottom>
                Beats nobody covers this day
              </Typography>
              {rep.off_plan.map((b, i) => (
                <Box
                  key={b.beat_id}
                  display="flex"
                  flexWrap="wrap"
                  style={{ gap: 8, padding: '6px 0', borderTop: i ? '1px solid #eef0f3' : 'none' }}
                >
                  <Typography variant="body2" style={{ minWidth: 220, fontWeight: 600 }}>
                    {b.beat_name}
                  </Typography>
                  <Typography variant="body2">
                    {money(b.amount)}
                    <span className={classes.muted}>
                      {' '}· {b.dealer_count} dealer{b.dealer_count === 1 ? '' : 's'}
                    </span>
                  </Typography>
                </Box>
              ))}
            </Paper>
          )}
        </>
      )}
    </Box>
  );
};

export default BeatOutstanding;
