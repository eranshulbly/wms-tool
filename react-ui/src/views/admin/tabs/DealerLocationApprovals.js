import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Button,
  Typography,
  CircularProgress,
  Paper,
  Chip,
  Alert,
  Grid,
  Link,
  Snackbar,
  TextField,
  Dialog,
  DialogContent,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconCheck, IconX, IconRefresh, IconMapPin } from '@tabler/icons';
import api from '../../../services/api';

/**
 * Dealer location approvals.
 *
 * A sales rep photographs a dealer's shopfront in the mobile app; the device's
 * GPS fix travels with the photo. Here an admin checks the photo really is that
 * dealer and approves, which writes the coordinates onto the dealer record.
 *
 * The photo is evidence, not the record — approving or rejecting deletes the
 * image and keeps only the coordinates, so proof photos don't accumulate.
 */

const useStyles = makeStyles((theme) => ({
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: theme.spacing(2),
  },
  card: {
    padding: theme.spacing(2),
    marginBottom: theme.spacing(2),
  },
  thumb: {
    width: '100%',
    maxHeight: 220,
    objectFit: 'cover',
    borderRadius: 8,
    cursor: 'zoom-in',
    display: 'block',
    background: '#f1f3f5',
  },
  meta: {
    fontSize: 13,
    color: theme.palette.text.secondary,
    marginBottom: 4,
  },
  coords: {
    fontFamily: 'monospace',
    fontSize: 13,
  },
  actions: {
    display: 'flex',
    gap: theme.spacing(1),
    marginTop: theme.spacing(1),
    flexWrap: 'wrap',
  },
  empty: {
    padding: theme.spacing(6),
    textAlign: 'center',
    color: theme.palette.text.secondary,
  },
}));

/**
 * The photo endpoint is authenticated, so a plain <img src> (which sends no
 * Authorization header) would 401. Fetch it as a blob and hand the object URL
 * to the <img>, revoking it when the row goes away.
 */
function SubmissionPhoto({ submissionId, className, onOpen }) {
  const [url, setUrl] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let revoked = null;
    let cancelled = false;
    api
      .get(`admin/dealer-locations/${submissionId}/photo`, { responseType: 'blob' })
      .then((res) => {
        if (cancelled) return;
        revoked = URL.createObjectURL(res.data);
        setUrl(revoked);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [submissionId]);

  if (failed) return <Box className={className}>Photo unavailable</Box>;
  if (!url) {
    return (
      <Box className={className} display="flex" alignItems="center" justifyContent="center">
        <CircularProgress size={22} />
      </Box>
    );
  }
  return <img src={url} alt="Dealer shopfront" className={className} onClick={() => onOpen(url)} />;
}

export default function DealerLocationApprovals() {
  const classes = useStyles();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState(null);
  const [toast, setToast] = useState('');
  const [notes, setNotes] = useState({});
  const [zoom, setZoom] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await api.get('admin/dealer-locations', { params: { status: 'pending' } });
      setRows(res.data.submissions || []);
    } catch (e) {
      setError(e?.response?.data?.msg || e.message || 'Failed to load submissions');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const decide = async (row, approve) => {
    setBusyId(row.submission_id);
    try {
      const body = approve ? {} : { note: notes[row.submission_id] || '' };
      await api.post(
        `admin/dealer-locations/${row.submission_id}/${approve ? 'approve' : 'reject'}`,
        body
      );
      setToast(
        approve
          ? `Location saved for ${row.dealer}.`
          : `Rejected — ${row.dealer} can be captured again.`
      );
      // Drop the row locally; it is no longer pending.
      setRows((prev) => prev.filter((r) => r.submission_id !== row.submission_id));
    } catch (e) {
      setError(e?.response?.data?.msg || e.message || 'Action failed');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Box>
      <Box className={classes.header}>
        <Typography variant="h4">
          Pending dealer locations {rows.length > 0 && `(${rows.length})`}
        </Typography>
        <Button startIcon={<IconRefresh size={16} />} onClick={load} disabled={loading}>
          Refresh
        </Button>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      {loading ? (
        <Box className={classes.empty}>
          <CircularProgress />
        </Box>
      ) : rows.length === 0 ? (
        <Paper className={classes.empty}>
          <IconMapPin size={28} />
          <Typography variant="h5" sx={{ mt: 1 }}>
            Nothing waiting for approval
          </Typography>
          <Typography variant="body2">
            Location photos captured by sales reps will appear here.
          </Typography>
        </Paper>
      ) : (
        rows.map((r) => (
          <Paper key={r.submission_id} className={classes.card}>
            <Grid container spacing={2}>
              <Grid item xs={12} md={4}>
                {r.has_photo ? (
                  <SubmissionPhoto
                    submissionId={r.submission_id}
                    className={classes.thumb}
                    onOpen={setZoom}
                  />
                ) : (
                  <Box className={classes.thumb}>No photo</Box>
                )}
              </Grid>
              <Grid item xs={12} md={8}>
                <Typography variant="h5">{r.dealer}</Typography>
                <Box className={classes.meta}>
                  {r.dealer_code}
                  {r.town ? ` · ${r.town}` : ''}
                </Box>
                <Box className={classes.meta}>
                  Captured by <strong>{r.submitted_by_name || `user ${r.submitted_by}`}</strong>{' '}
                  on {new Date(r.created_at).toLocaleString()}
                </Box>
                <Box className={classes.coords}>
                  {r.latitude.toFixed(6)}, {r.longitude.toFixed(6)}
                  {r.accuracy_m != null && (
                    <Chip
                      size="small"
                      label={`±${Math.round(r.accuracy_m)} m`}
                      sx={{ ml: 1 }}
                      color={r.accuracy_m <= 30 ? 'success' : 'warning'}
                    />
                  )}
                </Box>
                <Box sx={{ mt: 0.5 }}>
                  <Link
                    href={`https://www.google.com/maps?q=${r.latitude},${r.longitude}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open in Google Maps
                  </Link>
                </Box>
                {r.note && (
                  <Box className={classes.meta} sx={{ mt: 1 }}>
                    Note: {r.note}
                  </Box>
                )}

                <Box className={classes.actions}>
                  <Button
                    variant="contained"
                    color="success"
                    startIcon={<IconCheck size={16} />}
                    disabled={busyId === r.submission_id}
                    onClick={() => decide(r, true)}
                  >
                    Approve &amp; save location
                  </Button>
                  <Button
                    variant="outlined"
                    color="error"
                    startIcon={<IconX size={16} />}
                    disabled={busyId === r.submission_id}
                    onClick={() => decide(r, false)}
                  >
                    Reject
                  </Button>
                  <TextField
                    size="small"
                    placeholder="Reason (optional)"
                    value={notes[r.submission_id] || ''}
                    onChange={(e) =>
                      setNotes((n) => ({ ...n, [r.submission_id]: e.target.value }))
                    }
                  />
                </Box>
              </Grid>
            </Grid>
          </Paper>
        ))
      )}

      <Dialog open={!!zoom} onClose={() => setZoom(null)} maxWidth="lg">
        <DialogContent sx={{ p: 0 }}>
          {zoom && <img src={zoom} alt="Dealer shopfront" style={{ maxWidth: '90vw' }} />}
        </DialogContent>
      </Dialog>

      <Snackbar
        open={!!toast}
        autoHideDuration={4000}
        onClose={() => setToast('')}
        message={toast}
      />
    </Box>
  );
}
