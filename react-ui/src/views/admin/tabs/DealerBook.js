import React, { useState, useEffect, useCallback, useMemo } from 'react';
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
  Select,
  InputAdornment,
  TablePagination,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconRefresh, IconSearch, IconTargetArrow } from '@tabler/icons';
import api from '../../../services/api';

/**
 * The dealer book — every dealer, who carries it, and what it is targeted at this month.
 *
 * The two editable things are deliberately different shapes:
 *   executive — a single value, so it edits inline and saves on change;
 *   targets   — one figure per category, so it opens a dialog and saves as a set.
 * Editing several numbers inline across a hundred rows is how half-saved rows happen.
 *
 * Filtering is server-side (the endpoint takes the same params) so it keeps working as
 * the book grows past what is comfortable to hold in the browser.
 */

const useStyles = makeStyles((theme) => ({
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: theme.spacing(2),
    gap: theme.spacing(2),
    flexWrap: 'wrap',
  },
  filters: { padding: theme.spacing(2), marginBottom: theme.spacing(2) },
  empty: { padding: theme.spacing(6), textAlign: 'center', color: theme.palette.text.secondary },
  num: { textAlign: 'right', whiteSpace: 'nowrap' },
  head: { fontWeight: 700, background: '#f1f5f9' },
  dim: { color: theme.palette.text.secondary, fontSize: 12 },
}));

const money = (n) =>
  n === null || n === undefined || n === '' ? '—' : `₹${Number(n).toLocaleString('en-IN')}`;

const EMPTY_FILTERS = { search: '', company_id: '', exec: '', status: 'all' };

const PAGE_SIZE = 25;

export default function DealerBook() {
  const classes = useStyles();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [busyId, setBusyId] = useState(null);
  const [editing, setEditing] = useState(null); // dealer whose targets are open
  const [draft, setDraft] = useState({});
  const [saving, setSaving] = useState(false);
  const [page, setPage] = useState(0);   // MUI is 0-based; the API is 1-based

  const load = useCallback(async (f, pageIndex) => {
    setLoading(true);
    setError('');
    try {
      const params = { page: pageIndex + 1, page_size: PAGE_SIZE };
      if (f.search) params.search = f.search;
      if (f.company_id) params.company_id = f.company_id;
      if (f.status && f.status !== 'all') params.status = f.status;
      // 'unassigned' is its own filter, not an executive id.
      if (f.exec === 'unassigned') params.exec = 'unassigned';
      else if (f.exec) params.exec_id = f.exec;
      const res = await api.get('admin/dealers/manage', { params });
      setData(res.data);
    } catch (e) {
      setError(e?.response?.data?.msg || e.message || 'Failed to load dealers');
    } finally {
      setLoading(false);
    }
  }, []);

  // Debounced so typing in the search box doesn't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => load(filters, page), filters.search ? 300 : 0);
    return () => clearTimeout(t);
  }, [filters, page, load]);

  // A narrower filter can leave you on a page that no longer exists; go back to the
  // first one rather than showing an empty table that reads as "nothing matches".
  useEffect(() => { setPage(0); }, [filters]);

  // Memoised so the fallback [] isn't a fresh array each render — that would make the
  // useMemo below recompute on every render, defeating the point of it.
  const categories = useMemo(() => data?.categories || [], [data]);
  const dealers = useMemo(() => data?.dealers || [], [data]);

  // Only categories targeted somewhere in the filtered book get a column. The server
  // computes this across every page, so the columns don't shift as you page through.
  const shownCats = useMemo(() => {
    const used = new Set((data?.target_categories || []).map(String));
    return categories.filter((c) => used.has(String(c.id)));
  }, [data, categories]);

  const setExec = async (dealer, value) => {
    setBusyId(dealer.dealer_id);
    try {
      const res = await api.patch(`admin/dealers/${dealer.dealer_id}/executive`, {
        sales_executive_id: value === '' ? null : Number(value),
      });
      setData((d) => ({
        ...d,
        dealers: d.dealers.map((x) =>
          x.dealer_id === dealer.dealer_id
            ? { ...x, sales_executive_id: res.data.sales_executive_id, sales_executive: res.data.sales_executive }
            : x
        ),
      }));
      setToast(
        res.data.sales_executive
          ? `${dealer.name} assigned to ${res.data.sales_executive}.`
          : `${dealer.name} is now unassigned.`
      );
    } catch (e) {
      setError(e?.response?.data?.msg || e.message || 'Could not reassign');
    } finally {
      setBusyId(null);
    }
  };

  const openTargets = (dealer) => {
    setEditing(dealer);
    setDraft(
      categories.reduce(
        (acc, c) => ({ ...acc, [c.id]: dealer.targets?.[String(c.id)] ?? '' }),
        {}
      )
    );
  };

  const saveTargets = async () => {
    setSaving(true);
    setError('');
    try {
      const res = await api.put(`admin/dealers/${editing.dealer_id}/targets`, { targets: draft });
      const next = {};
      Object.entries(draft).forEach(([cid, v]) => {
        const num = v === '' ? 0 : Number(v);
        if (num > 0) next[cid] = num;
      });
      setData((d) => ({
        ...d,
        dealers: d.dealers.map((x) =>
          x.dealer_id === editing.dealer_id
            ? {
                ...x,
                targets: next,
                target_total: Object.values(next).reduce((a, b) => a + b, 0),
              }
            : x
        ),
      }));
      setToast(
        `${editing.name}: ${res.data.set} target${res.data.set === 1 ? '' : 's'} saved` +
          (res.data.cleared ? `, ${res.data.cleared} cleared` : '') + '.'
      );
      setEditing(null);
    } catch (e) {
      setError(e?.response?.data?.msg || e.message || 'Could not save targets');
    } finally {
      setSaving(false);
    }
  };

  const monthLabel = data?.period
    ? new Date(`${data.period}T00:00:00`).toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
    : '';

  return (
    <Box>
      <Box className={classes.header}>
        <Box>
          <Typography variant="h4">Dealer book</Typography>
          <Typography variant="body2" color="textSecondary">
            {data?.total ?? 0} dealer{(data?.total ?? 0) === 1 ? '' : 's'}
            {monthLabel ? ` · targets for ${monthLabel}` : ''}
          </Typography>
        </Box>
        <Button startIcon={<IconRefresh size={16} />} onClick={() => load(filters, page)} disabled={loading}>
          Refresh
        </Button>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      <Paper className={classes.filters}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} md={4}>
            <TextField
              fullWidth
              size="small"
              placeholder="Search name, code or town"
              value={filters.search}
              onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <IconSearch size={16} />
                  </InputAdornment>
                ),
              }}
            />
          </Grid>
          <Grid item xs={6} md={3}>
            <TextField
              select fullWidth size="small" label="Sales executive"
              value={filters.exec}
              onChange={(e) => setFilters((f) => ({ ...f, exec: e.target.value }))}
            >
              <MenuItem value="">All executives</MenuItem>
              <MenuItem value="unassigned">Unassigned only</MenuItem>
              {(data?.executives || []).map((u) => (
                <MenuItem key={u.id} value={u.id}>{u.name}</MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid item xs={6} md={2}>
            <TextField
              select fullWidth size="small" label="Company"
              value={filters.company_id}
              onChange={(e) => setFilters((f) => ({ ...f, company_id: e.target.value }))}
            >
              <MenuItem value="">All</MenuItem>
              {(data?.companies || []).map((c) => (
                <MenuItem key={c.id} value={c.id}>{c.name}</MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid item xs={6} md={2}>
            <TextField
              select fullWidth size="small" label="Status"
              value={filters.status}
              onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
            >
              <MenuItem value="all">All</MenuItem>
              <MenuItem value="active">Active</MenuItem>
              <MenuItem value="inactive">Inactive</MenuItem>
              <MenuItem value="rejected">Rejected</MenuItem>
            </TextField>
          </Grid>
          <Grid item xs={6} md={1}>
            <Button fullWidth onClick={() => setFilters(EMPTY_FILTERS)}>Clear</Button>
          </Grid>
        </Grid>
      </Paper>

      {loading ? (
        <Box className={classes.empty}><CircularProgress /></Box>
      ) : dealers.length === 0 ? (
        <Paper className={classes.empty}>
          <Typography variant="h5">No dealers match these filters</Typography>
          <Typography variant="body2">Clear a filter to see more.</Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell className={classes.head}>Dealer</TableCell>
                <TableCell className={classes.head}>Sales executive</TableCell>
                {shownCats.map((c) => (
                  <TableCell key={c.id} className={`${classes.head} ${classes.num}`}>{c.name}</TableCell>
                ))}
                <TableCell className={`${classes.head} ${classes.num}`}>Total</TableCell>
                <TableCell className={classes.head} align="right">Targets</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {dealers.map((d) => (
                <TableRow key={d.dealer_id} hover>
                  <TableCell>
                    <div>{d.name}</div>
                    <div className={classes.dim}>
                      {[d.dealer_code, d.town, d.company].filter(Boolean).join(' · ')}
                      {d.status !== 'active' && (
                        <Chip size="small" label={d.status} sx={{ ml: 1 }} />
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Select
                      size="small"
                      variant="standard"
                      value={d.sales_executive_id || ''}
                      disabled={busyId === d.dealer_id}
                      onChange={(e) => setExec(d, e.target.value)}
                      displayEmpty
                      sx={{ minWidth: 130 }}
                    >
                      <MenuItem value=""><em>Unassigned</em></MenuItem>
                      {(data?.executives || []).map((u) => (
                        <MenuItem key={u.id} value={u.id}>{u.name}</MenuItem>
                      ))}
                    </Select>
                  </TableCell>
                  {shownCats.map((c) => (
                    <TableCell key={c.id} className={classes.num}>
                      {money(d.targets?.[String(c.id)])}
                    </TableCell>
                  ))}
                  <TableCell className={classes.num}>
                    <strong>{money(d.target_total || null)}</strong>
                  </TableCell>
                  <TableCell align="right">
                    <Button
                      size="small"
                      startIcon={<IconTargetArrow size={15} />}
                      onClick={() => openTargets(d)}
                    >
                      Edit
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <TablePagination
            component="div"
            count={data?.total || 0}
            page={page}
            onPageChange={(e, p) => setPage(p)}
            rowsPerPage={PAGE_SIZE}
            rowsPerPageOptions={[PAGE_SIZE]}
          />
        </TableContainer>
      )}

      <Dialog open={Boolean(editing)} onClose={() => !saving && setEditing(null)} maxWidth="xs" fullWidth>
        <DialogTitle>
          {editing?.name}
          <Typography variant="body2" color="textSecondary">
            Rupee targets for {monthLabel}. Leave a category blank or 0 to remove its target.
          </Typography>
        </DialogTitle>
        <DialogContent dividers>
          <Grid container spacing={2}>
            {categories.map((c) => (
              <Grid item xs={12} key={c.id}>
                <TextField
                  fullWidth
                  size="small"
                  label={c.name}
                  value={draft[c.id] ?? ''}
                  onChange={(e) => setDraft((s) => ({ ...s, [c.id]: e.target.value }))}
                  InputProps={{ startAdornment: <InputAdornment position="start">₹</InputAdornment> }}
                />
              </Grid>
            ))}
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditing(null)} disabled={saving}>Cancel</Button>
          <Button variant="contained" onClick={saveTargets} disabled={saving}
            startIcon={saving ? <CircularProgress size={14} color="inherit" /> : null}>
            {saving ? 'Saving…' : 'Save targets'}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar open={Boolean(toast)} autoHideDuration={4000} onClose={() => setToast('')} message={toast} />
    </Box>
  );
}
