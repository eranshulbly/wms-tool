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
import { IconUserPlus, IconKey, IconRefresh, IconBuildingWarehouse } from '@tabler/icons';
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

// Sentinel for the "All" choice in the pickers. Expanded to the real ids on save, so a
// user granted "all" today does not silently gain a company added tomorrow — grants stay
// a fact about what was decided, not a rule re-evaluated later.
const ALL_ID = '__all__';

const expand = (chosen, all) =>
  (chosen.includes(ALL_ID) ? all.map((x) => x.id) : chosen.filter((x) => x !== ALL_ID));

// Roles that act in the field and therefore need a warehouse/company grant to function.
const NEEDS_SCOPE = ['sales_executive', 'warehouse_staff', 'dispatcher', 'manager'];

// A field executive works out of exactly one depot (enforced server-side too). Companies
// are not limited — one rep may sell several principals from the same warehouse.
const SINGLE_WAREHOUSE_ROLES = ['sales_executive'];

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
    // ALL_ID is a sentinel, not a company: picking it expands to every company at save
    // time so the stored grants stay explicit (warehouse, company) pairs.
    warehouse_ids: [], company_ids: []
  });
  const [scopeUser, setScopeUser] = useState(null);
  const [scopeDraft, setScopeDraft] = useState({ warehouse_ids: [], company_ids: [] });
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
    body.warehouse_ids = expand(form.warehouse_ids, warehouses);
    body.company_ids = expand(form.company_ids, companies);
    api
      .post('admin/users', body)
      .then((r) => {
        setSnack({ sev: 'success', msg: r.data.msg });
        setOpen(false);
        setForm({ name: '', email: '', password: '', role: 'viewer', status: 'active', warehouse_ids: [], company_ids: [] });
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
  const roleHasAllCompanies = Boolean(roles.find((r) => r.name === form.role)?.all_companies);
  const oneWarehouse = SINGLE_WAREHOUSE_ROLES.includes(form.role);
  const scopeOneWarehouse = SINGLE_WAREHOUSE_ROLES.includes(scopeUser?.role);
  // Switching INTO a single-warehouse role must not carry several warehouses across —
  // the form would look valid and the server would reject it on submit.
  useEffect(() => {
    if (oneWarehouse && form.warehouse_ids.length > 1) {
      setForm((f) => ({ ...f, warehouse_ids: f.warehouse_ids.slice(0, 1) }));
    }
  }, [oneWarehouse, form.warehouse_ids]);
  // "All" collapses to one chip rather than listing every name.
  const renderScope = (vals, all) =>
    (vals.includes(ALL_ID) ? 'All' : all.filter((x) => vals.includes(x.id)).map((x) => x.name).join(', '));
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
                    {u.companies ? (
                      <Chip
                        size="small"
                        label={u.company_ids.length === companies.length && companies.length > 1
                          ? `All companies · ${u.grants} grants`
                          : `${u.companies} · ${u.grants} grants`}
                        variant="outlined"
                      />
                    ) : roles.find((r) => r.name === u.role)?.all_companies ? (
                      <Chip size="small" label="all (by role)" variant="outlined" />
                    ) : NEEDS_SCOPE.includes(u.role) ? (
                      <Chip size="small" label="no scope" color="warning" variant="outlined" />
                    ) : (
                      <Typography variant="caption" color="textSecondary">—</Typography>
                    )}
                  </TableCell>
                  <TableCell align="right">
                    <Button
                      size="small"
                      startIcon={<IconBuildingWarehouse size={14} />}
                      onClick={() => {
                        setScopeUser(u);
                        setScopeDraft({
                          // A single-warehouse role may still be carrying several from
                          // before the rule existed; show the first rather than a value
                          // the Save would bounce.
                          warehouse_ids: SINGLE_WAREHOUSE_ROLES.includes(u.role)
                            ? u.warehouse_ids.slice(0, 1)
                            : u.warehouse_ids,
                          company_ids: u.company_ids
                        });
                      }}
                    >
                      Scope
                    </Button>
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

            {/* Scope is offered for every role, not just field ones — an admin may
                still want a specific company recorded against the account. */}
            <Grid item xs={12}>
              {roleHasAllCompanies ? (
                <Alert severity="info">
                  The <strong>{form.role}</strong> role already reaches every company and
                  warehouse. Grants below are optional for it.
                </Alert>
              ) : scopeNeeded ? (
                <Alert severity="info">
                  A <strong>{form.role}</strong> needs at least one company, or their scope is
                  empty and the order app shows them nothing.
                </Alert>
              ) : null}
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                select
                size="small"
                label="Companies"
                SelectProps={{ multiple: true, renderValue: (v) => renderScope(v, companies) }}
                value={form.company_ids}
                onChange={(e) => set({ company_ids: e.target.value })}
                helperText="Which principals this person works on"
              >
                <MenuItem value={ALL_ID}>All companies</MenuItem>
                {companies.map((c) => <MenuItem key={c.id} value={c.id}>{c.name}</MenuItem>)}
              </TextField>
            </Grid>
            <Grid item xs={12} sm={6}>
              {oneWarehouse ? (
                <TextField
                  fullWidth
                  select
                  size="small"
                  label="Warehouse"
                  value={form.warehouse_ids[0] ?? ''}
                  onChange={(e) => set({ warehouse_ids: e.target.value ? [e.target.value] : [] })}
                  helperText={`A ${form.role} works out of one warehouse`}
                >
                  {warehouses.map((w) => <MenuItem key={w.id} value={w.id}>{w.name}</MenuItem>)}
                </TextField>
              ) : (
                <TextField
                  fullWidth
                  select
                  size="small"
                  label="Warehouses"
                  SelectProps={{ multiple: true, renderValue: (v) => renderScope(v, warehouses) }}
                  value={form.warehouse_ids}
                  onChange={(e) => set({ warehouse_ids: e.target.value })}
                  helperText="A grant is a warehouse + company pair"
                >
                  <MenuItem value={ALL_ID}>All warehouses</MenuItem>
                  {warehouses.map((w) => <MenuItem key={w.id} value={w.id}>{w.name}</MenuItem>)}
                </TextField>
              )}
            </Grid>

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

      {/* ---- scope (companies + warehouses) ---- */}
      <Dialog open={Boolean(scopeUser)} onClose={() => setScopeUser(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Scope — {scopeUser?.name}</DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 0.5 }}>
            <Grid item xs={12}>
              <Alert severity="info">
                Saving replaces this person&apos;s grants entirely. A grant is a warehouse +
                company pair, so both lists must have a selection for anything to be stored.
              </Alert>
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                select
                size="small"
                label="Companies"
                SelectProps={{ multiple: true, renderValue: (v) => renderScope(v, companies) }}
                value={scopeDraft.company_ids}
                onChange={(e) => setScopeDraft((d) => ({ ...d, company_ids: e.target.value }))}
              >
                <MenuItem value={ALL_ID}>All companies</MenuItem>
                {companies.map((c) => <MenuItem key={c.id} value={c.id}>{c.name}</MenuItem>)}
              </TextField>
            </Grid>
            <Grid item xs={12} sm={6}>
              {scopeOneWarehouse ? (
                <TextField
                  fullWidth
                  select
                  size="small"
                  label="Warehouse"
                  value={scopeDraft.warehouse_ids[0] ?? ''}
                  onChange={(e) => setScopeDraft((d) => ({
                    ...d, warehouse_ids: e.target.value ? [e.target.value] : []
                  }))}
                  helperText={`A ${scopeUser?.role} works out of one warehouse`}
                >
                  {warehouses.map((w) => <MenuItem key={w.id} value={w.id}>{w.name}</MenuItem>)}
                </TextField>
              ) : (
                <TextField
                  fullWidth
                  select
                  size="small"
                  label="Warehouses"
                  SelectProps={{ multiple: true, renderValue: (v) => renderScope(v, warehouses) }}
                  value={scopeDraft.warehouse_ids}
                  onChange={(e) => setScopeDraft((d) => ({ ...d, warehouse_ids: e.target.value }))}
                >
                  <MenuItem value={ALL_ID}>All warehouses</MenuItem>
                  {warehouses.map((w) => <MenuItem key={w.id} value={w.id}>{w.name}</MenuItem>)}
                </TextField>
              )}
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setScopeUser(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={() => {
              update(
                scopeUser.id,
                {
                  warehouse_ids: expand(scopeDraft.warehouse_ids, warehouses),
                  company_ids: expand(scopeDraft.company_ids, companies)
                },
                `Scope updated for "${scopeUser.name}".`
              );
              setScopeUser(null);
            }}
          >
            Save scope
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
