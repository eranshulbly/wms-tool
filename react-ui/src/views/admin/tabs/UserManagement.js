import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Button,
  Typography,
  CircularProgress,
  Paper,
  Chip,
  Alert,
  TextField,
  MenuItem,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Snackbar,
  Grid
} from '@material-ui/core';
import { IconUserPlus, IconKey, IconRefresh } from '@tabler/icons';
import api from '../../../services/api';

// Create and manage logins from the web app.
//
// Before this, the only ways into the users table were self-registration (which lands a
// person 'pending' with the 'viewer' role) and the mobile API, which needs a mobile JWT.
// An admin could approve an account but never create one.
//
// Two details that decide whether a new login actually works:
//   * status must be 'active' — the order app refuses anything else outright, and the
//     web app refuses 'pending'. Anything other than active is a login that silently
//     fails on one of the two apps.
//   * a sales executive needs a warehouse + company grant, or their scope is empty and
//     the order app has nothing to write against.

const STATUSES = ['active', 'pending', 'blocked'];

// Roles that act in the field and therefore need a warehouse/company grant to function.
const NEEDS_SCOPE = ['sales_executive', 'warehouse_staff', 'dispatcher', 'manager'];

const UserManagement = () => {
  const [users, setUsers] = useState([]);
  const [roles, setRoles] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [snack, setSnack] = useState(null);

  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    name: '', email: '', password: '', role: 'viewer', status: 'active',
    warehouse_id: '', company_id: ''
  });
  const [pwUser, setPwUser] = useState(null);
  const [newPw, setNewPw] = useState('');

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([
      api.get('admin/users').then((r) => r.data),
      api.get('warehouses').then((r) => r.data).catch(() => ({ warehouses: [] })),
      api.get('companies').then((r) => r.data).catch(() => ({ companies: [] }))
    ])
      .then(([u, w, c]) => {
        if (u.success) {
          setUsers(u.users);
          setRoles(u.roles);
        } else {
          setError(u.msg || 'Could not load users');
        }
        setWarehouses(w.warehouses || []);
        setCompanies(c.companies || []);
      })
      .catch((e) => setError(e?.response?.data?.msg || 'Could not load users'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));

  const create = () => {
    setSaving(true);
    const body = { ...form };
    if (body.warehouse_id && body.company_id) {
      body.grants = [{ warehouse_id: body.warehouse_id, company_id: body.company_id }];
    }
    delete body.warehouse_id;
    delete body.company_id;
    api
      .post('admin/users', body)
      .then((r) => {
        setSnack({ sev: 'success', msg: r.data.msg });
        setOpen(false);
        setForm({ name: '', email: '', password: '', role: 'viewer', status: 'active', warehouse_id: '', company_id: '' });
        load();
      })
      .catch((e) => setSnack({ sev: 'error', msg: e?.response?.data?.msg || 'Could not create user' }))
      .finally(() => setSaving(false));
  };

  const update = (id, patch, okMsg) =>
    api
      .put(`admin/users/${id}`, patch)
      .then((r) => {
        setSnack({ sev: 'success', msg: okMsg || r.data.msg });
        load();
      })
      .catch((e) => setSnack({ sev: 'error', msg: e?.response?.data?.msg || 'Update failed' }));

  const scopeNeeded = NEEDS_SCOPE.includes(form.role);
  const canCreate =
    form.name.trim().length >= 3 &&
    form.email.includes('@') &&
    form.password.length >= 8 &&
    form.password.length <= 16 &&
    !saving;

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 2, mb: 2 }}>
        <Box>
          <Typography variant="h4" gutterBottom>Users &amp; Logins</Typography>
          <Typography variant="body2" color="textSecondary">
            Create an account for anyone — field executives, warehouse staff or another admin.
            Email is the login on both the web app and the order app; the name is display only.
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button startIcon={<IconRefresh size={16} />} onClick={load}>Refresh</Button>
          <Button variant="contained" startIcon={<IconUserPlus size={16} />} onClick={() => setOpen(true)}>
            New user
          </Button>
        </Box>
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', p: 5 }}><CircularProgress /></Box>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>User</TableCell>
                <TableCell>Role</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Scope grants</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id} hover>
                  <TableCell>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>{u.name}</Typography>
                    <Typography variant="caption" color="textSecondary">{u.email}</Typography>
                  </TableCell>
                  <TableCell>
                    <TextField
                      select
                      size="small"
                      value={u.role}
                      onChange={(e) => update(u.id, { role: e.target.value })}
                      sx={{ minWidth: 150 }}
                    >
                      {roles.map((r) => <MenuItem key={r.id} value={r.name}>{r.name}</MenuItem>)}
                    </TextField>
                  </TableCell>
                  <TableCell>
                    <TextField
                      select
                      size="small"
                      value={u.status}
                      onChange={(e) => update(u.id, { status: e.target.value })}
                      sx={{ minWidth: 120 }}
                    >
                      {STATUSES.map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
                    </TextField>
                  </TableCell>
                  <TableCell align="right">
                    {/* A field role with no grant cannot see anything in the order app —
                        worth calling out rather than showing a bare 0. */}
                    {u.grants ? (
                      <Chip size="small" label={`${u.grants} grant${u.grants === 1 ? '' : 's'}`} variant="outlined" />
                    ) : NEEDS_SCOPE.includes(u.role) ? (
                      <Chip size="small" label="no scope" color="warning" variant="outlined" />
                    ) : (
                      <Typography variant="caption" color="textSecondary">—</Typography>
                    )}
                  </TableCell>
                  <TableCell align="right">
                    <Button
                      size="small"
                      startIcon={<IconKey size={14} />}
                      onClick={() => { setPwUser(u); setNewPw(''); }}
                    >
                      Password
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {!users.length && (
                <TableRow>
                  <TableCell colSpan={5}>
                    <Typography variant="body2" color="textSecondary">No users yet.</Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* ---- create ---- */}
      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New user</DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 0.5 }}>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                size="small"
                label="Name"
                helperText="The person's display name. Not a login."
                value={form.name}
                onChange={(e) => set({ name: e.target.value })}
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                size="small"
                label="Email"
                required
                helperText="The login — for the web app and the order app alike."
                value={form.email}
                onChange={(e) => set({ email: e.target.value })}
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                size="small"
                label="Password"
                helperText="8–16 characters"
                value={form.password}
                onChange={(e) => set({ password: e.target.value })}
              />
            </Grid>
            <Grid item xs={12} sm={3}>
              <TextField fullWidth select size="small" label="Role" value={form.role} onChange={(e) => set({ role: e.target.value })}>
                {roles.map((r) => <MenuItem key={r.id} value={r.name}>{r.name}</MenuItem>)}
              </TextField>
            </Grid>
            <Grid item xs={12} sm={3}>
              <TextField fullWidth select size="small" label="Status" value={form.status} onChange={(e) => set({ status: e.target.value })}>
                {STATUSES.map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
              </TextField>
            </Grid>

            {scopeNeeded && (
              <>
                <Grid item xs={12}>
                  <Alert severity="info">
                    A <strong>{form.role}</strong> needs a warehouse and company, or their scope is
                    empty and the order app shows them nothing.
                  </Alert>
                </Grid>
                <Grid item xs={12} sm={6}>
                  <TextField fullWidth select size="small" label="Warehouse" value={form.warehouse_id} onChange={(e) => set({ warehouse_id: e.target.value })}>
                    {warehouses.map((w) => <MenuItem key={w.id} value={w.id}>{w.name}</MenuItem>)}
                  </TextField>
                </Grid>
                <Grid item xs={12} sm={6}>
                  <TextField fullWidth select size="small" label="Company" value={form.company_id} onChange={(e) => set({ company_id: e.target.value })}>
                    {companies.map((c) => <MenuItem key={c.id} value={c.id}>{c.name}</MenuItem>)}
                  </TextField>
                </Grid>
              </>
            )}

            {form.status !== 'active' && (
              <Grid item xs={12}>
                <Alert severity="warning">
                  Only <strong>active</strong> can sign in to the order app; the web app also
                  refuses <strong>pending</strong>.
                </Alert>
              </Grid>
            )}
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="contained" disabled={!canCreate} onClick={create}>
            {saving ? 'Creating…' : 'Create user'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* ---- password reset ---- */}
      <Dialog open={Boolean(pwUser)} onClose={() => setPwUser(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Set password — {pwUser?.name}</DialogTitle>
        <DialogContent>
          <TextField
            fullWidth
            size="small"
            label="New password"
            helperText="8–16 characters"
            value={newPw}
            sx={{ mt: 1 }}
            onChange={(e) => setNewPw(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPwUser(null)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={newPw.length < 8 || newPw.length > 16}
            onClick={() => {
              update(pwUser.id, { password: newPw }, `Password set for "${pwUser.name}".`);
              setPwUser(null);
            }}
          >
            Set password
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={Boolean(snack)}
        autoHideDuration={5000}
        onClose={() => setSnack(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        {snack ? <Alert severity={snack.sev} onClose={() => setSnack(null)}>{snack.msg}</Alert> : undefined}
      </Snackbar>
    </Box>
  );
};

export default UserManagement;
