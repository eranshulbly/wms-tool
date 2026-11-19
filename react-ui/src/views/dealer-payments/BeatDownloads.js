import React, { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@material-ui/core';
import { IconChevronDown, IconChevronRight, IconDownload } from '@tabler/icons';
import { downloadBeatFile, errMsg, getBeats } from '../../services/dealerPaymentsService';
import { ACTION_COLOR, actionLabel, RemindChip } from './DealerDetail';

// Beat-wise: the Outstanding file cut per sales executive, by the beats each owns in
// Dealer Payments → Executive Beats. A dealer is placed on a beat by its name in the DMS
// Outlet Master, else by its town when that town is wholly one executive's; the rest are in
// Unassigned, each with why. Used on the Outstanding page and in the dealer screen's dialog.

const inr = (v) =>
  v === null || v === undefined ? '—' : `₹${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
const UNASSIGNED = 'Unassigned';
const NUM = { whiteSpace: 'nowrap' };
const H = { fontWeight: 600, whiteSpace: 'nowrap' };

// The dealers in one executive's file, worst first — as on the dealer screen.
const Dealers = ({ items, noteHead }) => (
  <Table size="small">
    <TableHead>
      <TableRow>
        {['Dealer', 'Tally O/S', 'Received, not in Tally', 'PDCs held', 'Effective O/S', 'Overdue days', 'Action', noteHead].map((h, i) => (
          <TableCell key={h} sx={H} align={i >= 1 && i <= 5 ? 'right' : 'left'}>{h}</TableCell>
        ))}
      </TableRow>
    </TableHead>
    <TableBody>
      {items.map((d) => (
        <TableRow key={d.dealer_id}>
          <TableCell>{d.dealer}</TableCell>
          <TableCell align="right" sx={NUM}>{inr(d.tally_os)}</TableCell>
          <TableCell align="right" sx={NUM}>{d.received_not_in_tally ? inr(d.received_not_in_tally) : '—'}</TableCell>
          <TableCell align="right" sx={NUM}>{d.pdc_amount ? inr(d.pdc_amount) : '—'}</TableCell>
          <TableCell align="right" sx={{ ...NUM, fontWeight: 600 }}>{inr(d.effective_os)}</TableCell>
          <TableCell align="right">{d.oldest_overdue_days > 0 ? d.oldest_overdue_days : '—'}</TableCell>
          <TableCell sx={NUM}>
            {d.action && <Chip size="small" color={ACTION_COLOR[d.action]} label={actionLabel(d)} />}
            <RemindChip r={d} />
          </TableCell>
          <TableCell><Typography variant="caption" color="textSecondary">{d.note}</Typography></TableCell>
        </TableRow>
      ))}
      {!items.length && (
        <TableRow><TableCell colSpan={8} sx={{ color: 'text.secondary' }}>No dealer with outstanding on these beats.</TableCell></TableRow>
      )}
    </TableBody>
  </Table>
);

const BeatDownloads = ({ reloadKey = 0 }) => {
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(''); // which file is downloading; '*' for the zip
  const [open, setOpen] = useState({}); // se_name -> expanded

  useEffect(() => {
    setLoading(true);
    setError('');
    getBeats()
      .then(setInfo)
      .catch((e) => {
        setInfo(null);
        setError(errMsg(e, 'Could not load the beats.'));
      })
      .finally(() => setLoading(false));
  }, [reloadKey]);

  const get = async (se) => {
    setBusy(se || '*');
    setError('');
    try {
      await downloadBeatFile(se);
    } catch (e) {
      setError(errMsg(e, 'Could not download the file.'));
    } finally {
      setBusy('');
    }
  };

  const btn = (se) => (
    <Button size="small" variant="outlined" onClick={() => get(se)} disabled={!!busy}
      startIcon={busy === se ? <CircularProgress size={14} /> : <IconDownload size={16} />}>
      Excel
    </Button>
  );
  const toggle = (k) => setOpen((o) => ({ ...o, [k]: !o[k] }));
  const chevron = (k) => (
    <IconButton size="small" onClick={() => toggle(k)} aria-label="Show dealers">
      {open[k] ? <IconChevronDown size={16} /> : <IconChevronRight size={16} />}
    </IconButton>
  );

  if (loading) return <Box textAlign="center" py={4}><CircularProgress size={24} /></Box>;
  if (!info) return <Alert severity="warning">{error}</Alert>;
  const un = info.unassigned || {};
  const rows = [...(info.executives || []), ...(un.dealers ? [{ ...un, se_name: UNASSIGNED, beats: [] }] : [])];

  return (
    <Box>
      {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}
      <Box display="flex" alignItems="center" flexWrap="wrap" sx={{ gap: 1, mb: 1 }}>
        <Typography variant="body2" color="textSecondary" sx={{ flexGrow: 1 }}>
          Each executive gets the dealers on all their beats (Executive Beats), in the Outstanding layout. PDCs: {info.cheques_note}.
        </Typography>
        <Button variant="contained" disableElevation onClick={() => get('')} disabled={!!busy}
          startIcon={busy === '*' ? <CircularProgress size={14} color="inherit" /> : <IconDownload size={16} />}>
          Download all (.zip)
        </Button>
      </Box>
      <Table size="small">
        <TableHead>
          <TableRow>
            {['', 'Executive', 'Beats', 'Dealers', 'Tally O/S', 'Effective O/S', 'Chase', 'Remind', ''].map((h, i) => (
              <TableCell key={`${h}-${i}`} sx={H} align={i >= 3 && i <= 7 ? 'right' : 'left'}>{h}</TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((e) => {
            const un2 = e.se_name === UNASSIGNED;
            return (
              <React.Fragment key={e.se_name}>
                <TableRow hover sx={un2 ? { bgcolor: '#fff7ed' } : undefined}>
                  <TableCell sx={{ width: 40 }}>{chevron(e.se_name)}</TableCell>
                  <TableCell sx={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{e.se_name}</TableCell>
                  <TableCell sx={{ maxWidth: 380 }}>
                    {un2 ? (
                      <Typography variant="caption" color="textSecondary">Not on any executive&apos;s beats — open to see why</Typography>
                    ) : (
                      <>
                        <Typography variant="caption" component="div">{e.beats.join(', ')}</Typography>
                        <Typography variant="caption" component="div" color="textSecondary">
                          Today (Beat Plan): {e.todays_beats?.length ? e.todays_beats.join(', ') : '—'}
                        </Typography>
                      </>
                    )}
                  </TableCell>
                  <TableCell align="right">
                    {e.dealers}
                    {e.by_town ? <Typography variant="caption" component="div" color="textSecondary">{e.by_town} by town</Typography> : null}
                  </TableCell>
                  <TableCell align="right" sx={NUM}>{inr(e.tally_os)}</TableCell>
                  <TableCell align="right" sx={{ ...NUM, fontWeight: 600 }}>{inr(e.effective_os)}</TableCell>
                  <TableCell align="right">{e.chase || '—'}</TableCell>
                  <TableCell align="right">{e.remind || '—'}</TableCell>
                  <TableCell>{btn(e.se_name)}</TableCell>
                </TableRow>
                <TableRow>
                  <TableCell colSpan={9} sx={{ p: 0, borderBottom: open[e.se_name] ? undefined : 'none' }}>
                    <Collapse in={!!open[e.se_name]} unmountOnExit>
                      <Box px={2} py={1} sx={{ bgcolor: '#fafbfc' }}>
                        <Dealers items={e.items || []} noteHead={un2 ? 'Why unassigned' : 'Placed'} />
                      </Box>
                    </Collapse>
                  </TableCell>
                </TableRow>
              </React.Fragment>
            );
          })}
        </TableBody>
      </Table>
      <Typography variant="caption" color="textSecondary" component="div" sx={{ mt: 1 }}>
        Executives and their beats are kept under Dealer Payments → Executive Beats. A dealer is matched to an outlet in
        the Outlet Master by name, else by town when the whole town is one executive&apos;s.
      </Typography>
    </Box>
  );
};

export default BeatDownloads;
