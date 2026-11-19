import React, { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@material-ui/core';
import { IconDownload } from '@tabler/icons';
import { downloadBeatFile, errMsg, getBeats } from '../../services/dealerPaymentsService';

// Beat-wise downloads: the Outstanding file cut per sales executive, by the beats each owns in
// Dealer Payments → Executive Beats. A dealer is placed on a beat by its name in the DMS
// Outlet Master, else by its town when that town is wholly one executive's; the rest are in
// Unassigned, each with why.

const inr = (v) => `₹${Number(v || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
const UNASSIGNED = 'Unassigned';

const BeatDownloads = () => {
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(''); // which file is downloading; '*' for the zip
  const [showWhy, setShowWhy] = useState(false);

  useEffect(() => {
    getBeats()
      .then(setInfo)
      .catch((e) => setError(errMsg(e, 'Could not load the beats.')))
      .finally(() => setLoading(false));
  }, []);

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

  const btn = (se, label = 'Download') => (
    <Button size="small" onClick={() => get(se)} disabled={!!busy}
      startIcon={busy === (se || '*') ? <CircularProgress size={14} /> : <IconDownload size={16} />}>
      {label}
    </Button>
  );

  if (loading) return <Box textAlign="center" py={4}><CircularProgress size={24} /></Box>;
  if (!info) return <Alert severity="warning">{error}</Alert>;
  const un = info.unassigned || {};

  return (
    <Box>
      {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}
      <Box display="flex" alignItems="center" flexWrap="wrap" sx={{ gap: 1, mb: 1 }}>
        <Typography variant="body2" color="textSecondary" sx={{ flexGrow: 1 }}>
          One file per executive, in the Outstanding layout, with only the dealers on their beats.
        </Typography>
        <Button variant="contained" disableElevation onClick={() => get('')} disabled={!!busy}
          startIcon={busy === '*' ? <CircularProgress size={14} color="inherit" /> : <IconDownload size={16} />}>
          Download all (.zip)
        </Button>
      </Box>
      <Table size="small">
        <TableHead>
          <TableRow>
            {['Executive', 'Beats', 'Dealers', 'Tally O/S', 'Effective O/S', 'Chase', 'Remind', ''].map((h) => (
              <TableCell key={h} sx={{ fontWeight: 600 }}
                align={['Dealers', 'Tally O/S', 'Effective O/S', 'Chase', 'Remind'].includes(h) ? 'right' : 'left'}>{h}</TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {(info.executives || []).map((e) => (
            <TableRow key={e.se_name} hover>
              <TableCell sx={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{e.se_name}</TableCell>
              <TableCell sx={{ maxWidth: 360 }}>
                <Typography variant="caption">{e.beats.join(', ')}</Typography>
              </TableCell>
              <TableCell align="right">
                {e.dealers}
                {e.by_town ? <Typography variant="caption" component="div" color="textSecondary">{e.by_town} by town</Typography> : null}
              </TableCell>
              <TableCell align="right">{inr(e.tally_os)}</TableCell>
              <TableCell align="right">{inr(e.effective_os)}</TableCell>
              <TableCell align="right">{e.chase || '—'}</TableCell>
              <TableCell align="right">{e.remind || '—'}</TableCell>
              <TableCell>{btn(e.se_name)}</TableCell>
            </TableRow>
          ))}
          {un.dealers > 0 && (
            <TableRow hover sx={{ bgcolor: '#fff7ed' }}>
              <TableCell sx={{ fontWeight: 600 }}>{UNASSIGNED}</TableCell>
              <TableCell>
                <Button size="small" onClick={() => setShowWhy((v) => !v)}>{showWhy ? 'Hide why' : 'Why?'}</Button>
              </TableCell>
              <TableCell align="right">{un.dealers}</TableCell>
              <TableCell align="right">{inr(un.tally_os)}</TableCell>
              <TableCell align="right">{inr(un.effective_os)}</TableCell>
              <TableCell align="right">{un.chase || '—'}</TableCell>
              <TableCell align="right">{un.remind || '—'}</TableCell>
              <TableCell>{btn(UNASSIGNED)}</TableCell>
            </TableRow>
          )}
          {un.dealers > 0 && showWhy && (un.items || []).map((u) => (
            <TableRow key={u.dealer_id} sx={{ bgcolor: '#fffbf5' }}>
              <TableCell />
              <TableCell colSpan={2}><Typography variant="body2">{u.dealer}</Typography></TableCell>
              <TableCell align="right">{inr(u.tally_os)}</TableCell>
              <TableCell colSpan={4}><Typography variant="caption" color="textSecondary">{u.reason}</Typography></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <Typography variant="caption" color="textSecondary" component="div" sx={{ mt: 1 }}>
        Executives and their beats are kept under Dealer Payments → Executive Beats; outlets and their beats come
        from the DMS Outlet Master uploaded under Beat Outstanding. A dealer is matched by name, else by town when the whole town is one
        executive&apos;s.
      </Typography>
    </Box>
  );
};

export default BeatDownloads;
