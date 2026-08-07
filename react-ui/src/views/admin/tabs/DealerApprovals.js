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
  Snackbar,
  TextField,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconCheck, IconX, IconRefresh, IconBuildingStore } from '@tabler/icons';
import api from '../../../services/api';

/**
 * Dealer approvals — the dealer RECORD, as opposed to its location.
 *
 * A rep proposing a dealer from the field creates it `inactive` together with a pending
 * location submission carrying the shopfront photo. Until an admin decides, the dealer
 * is invisible to the mobile app (its dealer list filters on status = 'active'), so it
 * cannot be checked into or ordered against.
 *
 * Approving a dealer that still has a photo waiting delegates to the location approval,
 * so the coordinates are written and the photo cleaned up in one step — which is why
 * such a row says so on its button rather than pretending the two are unrelated.
 */

const useStyles = makeStyles((theme) => ({
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: theme.spacing(2),
  },
  card: { padding: theme.spacing(2.5), marginBottom: theme.spacing(2) },
  empty: {
    padding: theme.spacing(6),
    textAlign: 'center',
    color: theme.palette.text.secondary,
  },
  meta: { color: theme.palette.text.secondary, fontSize: 13 },
}));

export default function DealerApprovals({ onChanged }) {
  const classes = useStyles();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState(null);
  const [toast, setToast] = useState('');
  const [notes, setNotes] = useState({});

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await api.get('admin/dealers/pending');
      setRows(res.data.dealers || []);
    } catch (e) {
      setError(e?.response?.data?.msg || e.message || 'Failed to load dealers');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const decide = async (row, approve) => {
    setBusyId(row.dealer_id);
    try {
      const body = approve ? {} : { note: notes[row.dealer_id] || '' };
      const res = await api.post(
        `admin/dealers/${row.dealer_id}/${approve ? 'approve' : 'reject'}`,
        body
      );
      setToast(
        approve
          ? res.data?.located === false
            ? `${row.name} is now active. No location on file — a rep can still capture one.`
            : `${row.name} is now active, with the submitted coordinates saved.`
          : `${row.name} was rejected.`
      );
      setRows((prev) => prev.filter((r) => r.dealer_id !== row.dealer_id));
      // The location queue changes too when a dealer carries a pending photo.
      if (onChanged) onChanged();
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
          Dealers awaiting approval {rows.length > 0 && `(${rows.length})`}
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
          <IconBuildingStore size={28} />
          <Typography variant="h5" sx={{ mt: 1 }}>
            No dealers waiting
          </Typography>
          <Typography variant="body2">
            Dealers proposed by sales reps in the mobile app appear here before they go live.
          </Typography>
        </Paper>
      ) : (
        rows.map((r) => (
          <Paper key={r.dealer_id} className={classes.card}>
            <Grid container spacing={2} alignItems="center">
              <Grid item xs={12} md={5}>
                <Typography variant="h5">{r.name}</Typography>
                <Typography className={classes.meta}>
                  {[r.dealer_code, r.town, r.phone].filter(Boolean).join(' · ') || 'No code, town or phone yet'}
                </Typography>
                <Typography className={classes.meta}>
                  {r.company || 'No company'} · proposed by {r.sales_executive || 'unknown'}
                  {r.created_at ? ` · ${new Date(r.created_at).toLocaleDateString()}` : ''}
                </Typography>
                <Box mt={1} display="flex" style={{ gap: 8 }} flexWrap="wrap">
                  <Chip size="small" label={r.status} />
                  {r.pending_location ? (
                    <Chip size="small" color="primary" label="Photo waiting in Locations" />
                  ) : (
                    <Chip size="small" variant="outlined" label="No location on file" />
                  )}
                </Box>
              </Grid>

              <Grid item xs={12} md={4}>
                <TextField
                  fullWidth
                  size="small"
                  label="Reason (only needed to reject)"
                  value={notes[r.dealer_id] || ''}
                  onChange={(e) => setNotes((n) => ({ ...n, [r.dealer_id]: e.target.value }))}
                />
              </Grid>

              <Grid item xs={12} md={3}>
                <Box display="flex" style={{ gap: 8 }} justifyContent="flex-end" flexWrap="wrap">
                  <Button
                    variant="contained"
                    color="primary"
                    disabled={busyId === r.dealer_id}
                    startIcon={<IconCheck size={16} />}
                    onClick={() => decide(r, true)}
                  >
                    {r.pending_location ? 'Approve with location' : 'Approve'}
                  </Button>
                  <Button
                    variant="outlined"
                    color="secondary"
                    disabled={busyId === r.dealer_id}
                    startIcon={<IconX size={16} />}
                    onClick={() => decide(r, false)}
                  >
                    Reject
                  </Button>
                </Box>
              </Grid>
            </Grid>
          </Paper>
        ))
      )}

      <Snackbar
        open={Boolean(toast)}
        autoHideDuration={4000}
        onClose={() => setToast('')}
        message={toast}
      />
    </Box>
  );
}
