import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Collapse,
  IconButton,
  Grid,
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
import { IconChevronDown, IconChevronRight, IconDownload, IconFileZip, IconUpload } from '@tabler/icons';
import { downloadAll, downloadExecutive, downloadUnassigned, getBeatReport, setDayBeats } from '../../services/beatOutstandingService';
import { readBlobError } from '../../services/orderService';
import { BEAT_FEEDS, UploadRow } from '../dms-uploads/DmsFeedUpload';

// Beat Outstanding — a distributor's Tally outstanding split by the beats each sales
// executive covers on a day, to hand to them as an Excel file. Built from three uploads:
// the Outlet Master (outlet -> beat; Admin -> Outlet Master Upload) and, on this page,
// the day's Beat Plan (executive x day -> beats) and the Tally Outstanding Report. Parties the Outlet Master cannot place on one beat are
// listed separately so none of the outstanding goes unseen.

const OVER_30_DAYS = 30;

// '2026-11-07' -> 'Saturday, 7th Nov 2026'
const dayLabel = (iso) => {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  const n = d.getDate();
  const th = n % 10 === 1 && n !== 11 ? 'st' : n % 10 === 2 && n !== 12 ? 'nd' : n % 10 === 3 && n !== 13 ? 'rd' : 'th';
  const weekday = d.toLocaleDateString('en-IN', { weekday: 'long' });
  const month = d.toLocaleDateString('en-IN', { month: 'short' });
  return `${weekday}, ${n}${th} ${month} ${d.getFullYear()}`;
};

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

// The Tally outstanding report is never stored: the file picked here stays in this browser
// tab and goes with every request that shows or downloads amounts. Reloading the page
// drops it, and with it every amount.
const OutstandingRow = ({ file, loaded, onPick }) => {
  const classes = useStyles();
  return (
    <Box py={1.5}>
      <Grid container spacing={1} alignItems="center">
        <Grid item xs={12} sm={5}>
          <Typography variant="subtitle2">Outstanding Report</Typography>
          <Typography variant="caption" className={classes.muted} component="div">
            Tally → Bills Receivable
          </Typography>
          <Typography variant="caption" component="div" style={{ color: '#b91c1c', fontWeight: 600 }}>
            {loaded
              ? `Loaded: ${loaded.distributor || loaded.filename}${loaded.report_to ? ` (up to ${loaded.report_to})` : ''} · ${loaded.bill_count} bills · ${money(loaded.total)}`
              : 'Not loaded — pick it to see amounts. It is not saved: after a reload, pick it again.'}
          </Typography>
        </Grid>
        <Grid item xs={12} sm={7}>
          <Box display="flex" alignItems="center" style={{ gap: 8 }} flexWrap="wrap">
            <label htmlFor="outstanding-file">
              <input
                id="outstanding-file"
                type="file"
                accept=".xlsx"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = '';
                  if (f) onPick(f);
                }}
              />
              <Button component="span" size="small" variant="outlined" startIcon={<IconUpload size={14} />}>
                Choose file
              </Button>
            </label>
            {file && (
              <Typography variant="body2" style={{ fontFamily: 'monospace', fontSize: '0.85rem' }}>
                {file.name}
              </Typography>
            )}
          </Box>
        </Grid>
      </Grid>
    </Box>
  );
};

const FilesPanel = ({ feeds, onUploaded, outstandingFile, outstanding, onPickOutstanding }) => {
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
            <span className={classes.muted}> · DMS → Analytics → New Outlets Addition Master Report (uploaded in Admin → Outlet Master Upload)</span>
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
      <OutstandingRow file={outstandingFile} loaded={outstanding} onPick={onPickOutstanding} />
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
            <TableCell>{d.beat_name || <span className={classes.muted}>{d.reason}</span>}</TableCell>
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

// One executive — or, with `other`, the 'Other' row: every dealer no executive covers.
// `outstanding` is the picked Tally file, sent with the download; none, no download.
// The day's beats can be set by hand here (a day with no beat plan file, or to change
// it): the beats cell is a multi-select — ticking or unticking a beat saves it for today.
const ExecutiveRow = ({ exec, planDate, onError, outstanding, beatNames = [], onBeatsChanged, other = false }) => {
  const classes = useStyles();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  // The ticked beats show at once and are saved behind them; the list stays open (a
  // disabled or remounted Autocomplete closes it). A failed save puts the row back.
  const saved = other ? [] : exec.beats.map((b) => b.beat_name);
  const savedKey = saved.join('|');
  const [current, setCurrent] = useState(saved);
  // Saves still in flight: while any is, a reload from an earlier one must not undo a
  // tick made since.
  const pending = useRef(0);
  useEffect(() => {
    if (!pending.current) setCurrent(savedKey ? savedKey.split('|') : []);
  }, [savedKey]);
  const saveBeats = async (names) => {
    setCurrent(names);
    pending.current += 1;
    try {
      await setDayBeats(exec.se_name, names);
    } catch (e) {
      setCurrent(savedKey ? savedKey.split('|') : []);
      onError(errMsg(e, 'Could not save the beats.'));
    } finally {
      pending.current -= 1;
      // the amounts for the beats now saved
      if (!pending.current) onBeatsChanged();
    }
  };
  const amountOf = Object.fromEntries((other ? [] : exec.beats).map((b) => [b.beat_name, b]));
  // The executive's own beats (Executive Beats) first, then every other beat.
  const beatOptions = other
    ? []
    : [...new Set([...current, ...exec.mapped_beats, ...beatNames])];
  const has = exec.dealers.length > 0;
  const canDownload = Boolean(outstanding) && (has || exec.cd_dealers.length > 0);

  const download = async () => {
    setBusy(true);
    try {
      await (other ? downloadUnassigned(outstanding) : downloadExecutive(planDate, exec, outstanding));
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
        <TableCell style={{ fontWeight: 600 }}>{other ? 'Other' : exec.se_name}</TableCell>
        <TableCell>
          {other ? (
            'Other'
          ) : (
            <Autocomplete
              multiple
              disableCloseOnSelect
              disableClearable
              size="small"
              options={beatOptions}
              value={current}
              onChange={(_, v) => saveBeats(v)}
              renderOption={(props, option, { selected }) => (
                <li {...props}>
                  <Checkbox size="small" checked={selected} style={{ marginRight: 4, padding: 2 }} />
                  {option}
                </li>
              )}
              renderTags={(value, getTagProps) =>
                value.map((name, index) => {
                  const b = amountOf[name];
                  return (
                    <Chip
                      {...getTagProps({ index })}
                      key={name}
                      size="small"
                      variant="outlined"
                      label={`${name}${b?.dealer_count ? ` · ${money(b.amount)}` : ''}`}
                    />
                  );
                })
              }
              style={{ width: 240 }}
              renderInput={(params) => (
                <TextField {...params} variant="standard" placeholder={current.length ? '' : 'Select beats'} />
              )}
            />
          )}
        </TableCell>
        <TableCell align="right">{other ? 'Other' : exec.dealer_count}</TableCell>
        <TableCell align="right" className={classes.num}>
          {exec.cd_dealers.length ? (
            <span className={classes.red}>{money(exec.cd_amount)}</span>
          ) : (
            <span className={classes.muted}>{other || exec.mapped_beats.length ? '—' : 'No beats mapped'}</span>
          )}
        </TableCell>
        <TableCell align="right">
          <Button
            size="small"
            variant="outlined"
            disabled={!canDownload || busy}
            onClick={download}
            startIcon={busy ? <CircularProgress size={14} /> : <IconDownload size={14} />}
          >
            Excel
          </Button>
        </TableCell>
      </TableRow>
      {has && (
        <TableRow>
          <TableCell colSpan={6} style={{ padding: 0, borderBottom: open ? undefined : 'none' }}>
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
  // The picked Tally report — kept only in this tab, sent with each request, never stored.
  const [outstandingFile, setOutstandingFile] = useState(null);

  // Always today's beat plan — the server's default when no date is asked for — with the
  // amounts of `file` when one is picked. A file the server cannot read is not kept.
  const load = useCallback((file) => {
    setLoading(true);
    setError(null);
    getBeatReport(file)
      .then((res) => {
        setRep(res);
        setDate(res.plan_date || '');
        setOutstandingFile(file || null);
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
      await downloadAll(date, outstandingFile);
    } catch (e) {
      setError((await readBlobError(e)) || 'Download failed.');
    } finally {
      setZipping(false);
    }
  };

  const execs = rep?.executives || [];
  const withDues = execs.filter((e) => e.dealers.length > 0 || e.cd_dealers.length > 0).length;
  const other = rep?.other;
  const otherHas = Boolean(other && (other.dealers.length || other.cd_dealers.length));
  // Download all: one file per executive with dues, plus the Other row's file.
  const zipFiles = withDues + (otherHas ? 1 : 0);
  // Every download needs a Tally outstanding report uploaded today.
  const allowed = Boolean(outstandingFile);

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Beat Outstanding
      </Typography>
      <Typography variant="body2" className={classes.muted} style={{ marginBottom: 16 }}>
        Each executive in Executive Beats gets the outstanding of the dealers on the beats they cover that day. Dealers
        no executive covers are under Other.
      </Typography>

      {rep?.feeds && (
        <FilesPanel
          feeds={rep.feeds}
          onUploaded={() => load(outstandingFile)}
          outstandingFile={outstandingFile}
          outstanding={rep.outstanding}
          onPickOutstanding={(f) => load(f)}
        />
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
              <Box style={{ flexGrow: 1 }}>
                <Typography variant="h5">{dayLabel(rep.plan_date)}</Typography>
                {!allowed && (
                  <Typography variant="caption" className={classes.red}>
                    Pick the Tally outstanding report (Files above) to see amounts and download.
                  </Typography>
                )}
              </Box>
              <Button
                variant="contained"
                disabled={!allowed || !zipFiles || zipping || loading}
                onClick={downloadZip}
                startIcon={zipping ? <CircularProgress size={14} /> : <IconFileZip size={16} />}
              >
                Download all ({zipFiles})
              </Button>
            </Box>
          </Paper>

          <Paper variant="outlined" className={classes.section}>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell padding="checkbox" />
                    <TableCell>Executive</TableCell>
                    <TableCell style={{ width: 260 }}>Beats this day</TableCell>
                    <TableCell align="right">Dealers</TableCell>
                    <TableCell align="right">Past CD ({rep.cd_days}+ days)</TableCell>
                    <TableCell />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {execs.map((e) => (
                    <ExecutiveRow
                      key={e.se_name}
                      exec={e}
                      planDate={date}
                      onError={setError}
                      outstanding={outstandingFile}
                      beatNames={rep.beat_names}
                      onBeatsChanged={() => load(outstandingFile)}
                    />
                  ))}
                  {otherHas && <ExecutiveRow other exec={other} planDate={date} onError={setError} outstanding={outstandingFile} />}
                  {!execs.length && (
                    <TableRow>
                      <TableCell colSpan={6} className={classes.muted}>
                        No executives yet — add them and their beats under Beat Outstanding → Executive Beats.
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

        </>
      )}
    </Box>
  );
};

export default BeatOutstanding;
