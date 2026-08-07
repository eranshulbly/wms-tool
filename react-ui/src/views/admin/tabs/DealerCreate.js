import React, { useState, useEffect } from 'react';
import {
  Box,
  Button,
  Typography,
  Paper,
  Alert,
  Grid,
  Snackbar,
  TextField,
  MenuItem,
  CircularProgress,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconPlus } from '@tabler/icons';
import api from '../../../services/api';

/**
 * Admin-created dealer.
 *
 * Created ACTIVE, unlike one proposed from the field: the person entering it is the
 * person who would otherwise approve it, so a pending state would be a queue of one
 * admin waiting on themselves.
 *
 * Name is the important field, not the code — sales attribution matches
 * busy_sales_data.particulars against dealer.name exactly, so a dealer whose name does
 * not match the Busy export will silently bill nothing. That warning is on the field.
 */

const useStyles = makeStyles((theme) => ({
  card: { padding: theme.spacing(3), maxWidth: 880 },
  actions: { marginTop: theme.spacing(2), display: 'flex', gap: theme.spacing(1) },
}));

const EMPTY = {
  name: '',
  dealer_code: '',
  town: '',
  phone: '',
  email: '',
  gstin: '',
  address: '',
  company_id: '',
  sales_executive_id: '',
};

export default function DealerCreate({ onCreated }) {
  const classes = useStyles();
  const [form, setForm] = useState(EMPTY);
  const [companies, setCompanies] = useState([]);
  const [execs, setExecs] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [loadingRefs, setLoadingRefs] = useState(true);

  useEffect(() => {
    let live = true;
    Promise.all([
      api.get('companies').catch(() => ({ data: {} })),
      api.get('admin/users').catch(() => ({ data: {} })),
    ])
      .then(([c, u]) => {
        if (!live) return;
        const cos = c.data?.companies || [];
        setCompanies(cos);
        const users = u.data?.users || [];
        setExecs(users.filter((x) => x.role === 'sales_executive'));
        // Only pre-select when there is no choice to make.
        if (cos.length === 1) setForm((f) => ({ ...f, company_id: cos[0].id }));
      })
      .finally(() => live && setLoadingRefs(false));
    return () => {
      live = false;
    };
  }, []);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async () => {
    setError('');
    if (form.name.trim().length < 2) {
      setError('A dealer name is required.');
      return;
    }
    if (!form.company_id) {
      setError('Pick a company — a dealer has to belong to one.');
      return;
    }
    setSaving(true);
    try {
      const res = await api.post('admin/dealers/create', {
        ...form,
        name: form.name.trim(),
        sales_executive_id: form.sales_executive_id || null,
      });
      setToast(`${res.data.name} created and active.`);
      setForm((f) => ({ ...EMPTY, company_id: f.company_id }));
      if (onCreated) onCreated();
    } catch (e) {
      setError(e?.response?.data?.msg || e.message || 'Could not create the dealer');
    } finally {
      setSaving(false);
    }
  };

  if (loadingRefs) {
    return (
      <Box p={6} textAlign="center">
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Add a dealer
      </Typography>
      <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
        Created active straight away. A dealer proposed by a rep in the mobile app goes to
        the Dealer approvals tab instead.
      </Typography>

      <Paper className={classes.card}>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
            {error}
          </Alert>
        )}
        <Grid container spacing={2}>
          <Grid item xs={12} md={7}>
            <TextField
              fullWidth
              required
              label="Dealer name"
              value={form.name}
              onChange={set('name')}
              helperText="Must match the name in the Busy sales export exactly — sales are attributed by name."
            />
          </Grid>
          <Grid item xs={12} md={5}>
            <TextField fullWidth label="Dealer code" value={form.dealer_code} onChange={set('dealer_code')}
              helperText="Optional, but must be unique if given." />
          </Grid>

          <Grid item xs={12} md={6}>
            <TextField select fullWidth required label="Company" value={form.company_id} onChange={set('company_id')}>
              {companies.map((c) => (
                <MenuItem key={c.id} value={c.id}>{c.name}</MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid item xs={12} md={6}>
            <TextField select fullWidth label="Sales executive" value={form.sales_executive_id}
              onChange={set('sales_executive_id')}
              helperText="Who owns this dealer. Can be assigned later.">
              <MenuItem value="">Unassigned</MenuItem>
              {execs.map((u) => (
                <MenuItem key={u.id} value={u.id}>{u.name}</MenuItem>
              ))}
            </TextField>
          </Grid>

          <Grid item xs={12} md={4}>
            <TextField fullWidth label="Town" value={form.town} onChange={set('town')} />
          </Grid>
          <Grid item xs={12} md={4}>
            <TextField fullWidth label="Phone" value={form.phone} onChange={set('phone')} />
          </Grid>
          <Grid item xs={12} md={4}>
            <TextField fullWidth label="GSTIN" value={form.gstin} onChange={set('gstin')} />
          </Grid>

          <Grid item xs={12} md={6}>
            <TextField fullWidth label="Email" value={form.email} onChange={set('email')} />
          </Grid>
          <Grid item xs={12}>
            <TextField fullWidth multiline minRows={2} label="Address" value={form.address} onChange={set('address')} />
          </Grid>
        </Grid>

        <Box className={classes.actions}>
          <Button variant="contained" color="primary" onClick={submit} disabled={saving}
            startIcon={saving ? <CircularProgress size={15} color="inherit" /> : <IconPlus size={16} />}>
            {saving ? 'Creating…' : 'Create dealer'}
          </Button>
          <Button onClick={() => { setForm((f) => ({ ...EMPTY, company_id: f.company_id })); setError(''); }}
            disabled={saving}>
            Clear
          </Button>
        </Box>
      </Paper>

      <Snackbar open={Boolean(toast)} autoHideDuration={4000} onClose={() => setToast('')} message={toast} />
    </Box>
  );
}
