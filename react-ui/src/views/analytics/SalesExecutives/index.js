import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Box,
  Button,
  Chip,
  Typography,
  CircularProgress,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Grid,
  Link,
  MenuItem,
  TextField,
  Tooltip,
  Snackbar,
  Alert,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconRefresh, IconDownload, IconMapPin, IconAlertTriangle } from '@tabler/icons';
import api from '../../../services/api';
import { useWarehouse } from '../../../context/WarehouseContext';

const BASE = 'admin/sales/analytics';

// Three separate trails, kept as three column groups rather than merged into a single
// "performance" score: being in the shop, raising the order and the money being billed
// are different things, and an executive can be strong at one and weak at the next.
const SUMMARY_COLUMNS = [
  { key: 'executive_name', label: 'Sales Executive', type: 'text' },
  { key: 'visits', label: 'Visits', type: 'int' },
  { key: 'dealers_visited', label: 'Dealers', type: 'int' },
  { key: 'minutes_on_site', label: 'Time on site', type: 'duration' },
  { key: 'avg_minutes', label: 'Avg / visit', type: 'duration' },
  { key: 'orders', label: 'Orders', type: 'int' },
  { key: 'order_value', label: 'Order value', type: 'money' },
  { key: 'invoices', label: 'Invoices', type: 'int' },
  { key: 'invoiced_sales', label: 'Sales billed', type: 'money' },
  { key: 'last_seen', label: 'Last active', type: 'datetime' },
];

const VISIT_COLUMNS = [
  { key: 'executive_name', label: 'Sales Executive', type: 'text' },
  { key: 'dealer_name', label: 'Dealer', type: 'text' },
  { key: 'town', label: 'Town', type: 'text' },
  { key: 'check_in_at', label: 'Check-in', type: 'datetime' },
  { key: 'check_out_at', label: 'Check-out', type: 'datetime' },
  { key: 'minutes', label: 'Duration', type: 'duration' },
  { key: 'location', label: 'Location', type: 'location' },
];

const useStyles = makeStyles((theme) => ({
  section: { marginBottom: theme.spacing(2) },
  muted: { color: '#7a869a' },
  num: { whiteSpace: 'nowrap' },
  clickable: { cursor: 'pointer', '&:hover': { background: '#f4f6f8' } },
  selected: { background: '#e8f0fe', '&:hover': { background: '#e8f0fe' } },
  head: {
    whiteSpace: 'nowrap',
    fontWeight: 600,
    position: 'sticky',
    top: 0,
    zIndex: 3,
    background: '#fff',
  },
  scroll: { maxHeight: '42vh' },
  warn: { color: '#b26a00', display: 'inline-flex', alignItems: 'center', gap: 4 },
}));

const nf2 = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// Minutes read as hours once there are enough of them — "3h 05m" is a shift, "185" is
// a number the reader has to divide themselves.
const duration = (mins) => {
  if (mins === null || mins === undefined) return '—';
  const m = Number(mins);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${String(m % 60).padStart(2, '0')}m`;
};

const dt = (v) => {
  if (!v) return '—';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleString('en-IN', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: true,
  });
};

const render = (type, v) => {
  if (v === null || v === undefined || v === '') return '—';
  if (type === 'money') return nf2.format(Number(v));
  if (type === 'int') return Number(v).toLocaleString('en-IN');
  if (type === 'duration') return duration(v);
  if (type === 'datetime') return dt(v);
  return String(v);
};

const isNumeric = (t) => t === 'money' || t === 'int' || t === 'duration';

// Default window: the last 30 days, so the page opens on something rather than on a
// prompt to pick dates.
const isoDay = (d) => d.toISOString().slice(0, 10);
const today = () => isoDay(new Date());
const daysAgo = (n) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return isoDay(d);
};

const SalesExecutives = () => {
  const classes = useStyles();
  const { companies, selectedCompany, setSelectedCompany } = useWarehouse();

  const [from, setFrom] = useState(daysAgo(30));
  const [to, setTo] = useState(today());
  const [execs, setExecs] = useState([]);
  const [visits, setVisits] = useState([]);
  const [focus, setFocus] = useState(null); // user_id whose visits are shown, null = all
  const [loading, setLoading] = useState(false);
  const [longVisitMins, setLongVisitMins] = useState(480);
  const [toast, setToast] = useState(null);

  const load = useCallback(async () => {
    if (!selectedCompany) {
      setExecs([]);
      setVisits([]);
      return;
    }
    setLoading(true);
    try {
      const params = { company_id: selectedCompany, from, to };
      const [summary, log] = await Promise.all([
        api.get(`${BASE}/executives`, { params }),
        api.get(`${BASE}/visits`, { params }),
      ]);
      setExecs(summary.data.executives || []);
      setVisits(log.data.visits || []);
      if (summary.data.long_visit_minutes) setLongVisitMins(summary.data.long_visit_minutes);
    } catch (e) {
      setToast({ severity: 'error', msg: 'Could not load sales executive activity' });
    } finally {
      setLoading(false);
    }
  }, [selectedCompany, from, to]);

  useEffect(() => {
    load();
  }, [load]);

  const shownVisits = useMemo(
    () => (focus ? visits.filter((v) => v.user_id === focus) : visits),
    [visits, focus]
  );

  const focusName = useMemo(
    () => execs.find((e) => e.user_id === focus)?.executive_name,
    [execs, focus]
  );

  const totals = useMemo(
    () =>
      execs.reduce(
        (a, r) => ({
          visits: a.visits + Number(r.visits || 0),
          orders: a.orders + Number(r.orders || 0),
          order_value: a.order_value + Number(r.order_value || 0),
          invoiced_sales: a.invoiced_sales + Number(r.invoiced_sales || 0),
          minutes_on_site: a.minutes_on_site + Number(r.minutes_on_site || 0),
        }),
        { visits: 0, orders: 0, order_value: 0, invoiced_sales: 0, minutes_on_site: 0 }
      ),
    [execs]
  );

  const exportCsv = (columns, rows, name) => {
    const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const csv = [
      columns.map((c) => esc(c.label)).join(','),
      ...rows.map((r) => columns.map((c) => esc(r[c.key])).join(',')),
    ].join('\n');
    const company = companies.find((c) => c.id === selectedCompany);
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(company?.name || 'sales').replace(/\s+/g, '_')}_${name}_${from}_to_${to}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Sales Executive Activity
      </Typography>

      <Paper variant="outlined" className={classes.section} style={{ padding: 12 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} sm={3}>
            <TextField
              select
              fullWidth
              size="small"
              label="Company"
              value={selectedCompany || ''}
              onChange={(e) => setSelectedCompany(e.target.value)}
            >
              {companies.map((c) => (
                <MenuItem key={c.id} value={c.id}>
                  {c.name}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid item xs={6} sm={2}>
            <TextField
              fullWidth
              size="small"
              type="date"
              label="From"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              InputLabelProps={{ shrink: true }}
            />
          </Grid>
          <Grid item xs={6} sm={2}>
            <TextField
              fullWidth
              size="small"
              type="date"
              label="To"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              InputLabelProps={{ shrink: true }}
            />
          </Grid>
          <Grid item xs={12} sm={5}>
            <Box display="flex" alignItems="center">
              <Typography variant="body2" className={classes.muted}>
                {loading
                  ? 'Loading…'
                  : `${execs.length} executive${execs.length === 1 ? '' : 's'} · ${
                      totals.visits
                    } visit${totals.visits === 1 ? '' : 's'}`}
              </Typography>
              <Box flexGrow={1} />
              <Button
                size="small"
                startIcon={<IconRefresh size={16} />}
                onClick={load}
                disabled={loading}
              >
                Refresh
              </Button>
              <Button
                size="small"
                startIcon={<IconDownload size={16} />}
                onClick={() => exportCsv(SUMMARY_COLUMNS, execs, 'Executive_Summary')}
                disabled={!execs.length}
              >
                Export
              </Button>
            </Box>
          </Grid>
        </Grid>
      </Paper>

      {loading && !execs.length ? (
        <Box display="flex" justifyContent="center" p={4}>
          <CircularProgress />
        </Box>
      ) : (
        <>
          <TableContainer component={Paper} variant="outlined" className={classes.section}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  {SUMMARY_COLUMNS.map((c) => (
                    <TableCell
                      key={c.key}
                      className={classes.head}
                      align={isNumeric(c.type) ? 'right' : 'left'}
                    >
                      {c.label}
                    </TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {!execs.length && (
                  <TableRow>
                    <TableCell colSpan={SUMMARY_COLUMNS.length} align="center">
                      <Typography variant="body2" className={classes.muted}>
                        {selectedCompany
                          ? 'No sales executives with activity in this window.'
                          : 'Select a company.'}
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
                {execs.map((r) => (
                  <TableRow
                    key={r.user_id}
                    hover
                    className={`${classes.clickable} ${focus === r.user_id ? classes.selected : ''}`}
                    onClick={() => setFocus(focus === r.user_id ? null : r.user_id)}
                  >
                    {SUMMARY_COLUMNS.map((c) => (
                      <TableCell
                        key={c.key}
                        align={isNumeric(c.type) ? 'right' : 'left'}
                        className={isNumeric(c.type) ? classes.num : undefined}
                      >
                        {render(c.type, r[c.key])}
                        {/* Time on site is the one figure with a caveat, so the caveat
                            sits on the number itself rather than in a footnote. */}
                        {c.key === 'minutes_on_site' && r.suspect_visits > 0 && (
                          <Tooltip
                            title={`${r.suspect_visits} visit${
                              r.suspect_visits === 1 ? '' : 's'
                            } ran over ${duration(longVisitMins)} — the executive did not check out, so that time is excluded here.`}
                          >
                            <span className={classes.warn}>
                              {' '}
                              <IconAlertTriangle size={14} />
                            </span>
                          </Tooltip>
                        )}
                        {c.key === 'order_value' &&
                          r.total_lines > 0 &&
                          r.valued_lines < r.total_lines && (
                            <Tooltip
                              title={`Only ${r.valued_lines} of ${r.total_lines} order lines carry a rate. The rest were raised without a price, so this total is partial.`}
                            >
                              <span className={classes.warn}>
                                {' '}
                                <IconAlertTriangle size={14} />
                              </span>
                            </Tooltip>
                          )}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          <Box display="flex" alignItems="center" className={classes.section}>
            <Typography variant="h5">
              Visit log{focusName ? ` — ${focusName}` : ''}
            </Typography>
            {focus && (
              <Chip
                size="small"
                label="Show all"
                onDelete={() => setFocus(null)}
                style={{ marginLeft: 8 }}
              />
            )}
            <Box flexGrow={1} />
            <Button
              size="small"
              startIcon={<IconDownload size={16} />}
              onClick={() => exportCsv(VISIT_COLUMNS, shownVisits, 'Visit_Log')}
              disabled={!shownVisits.length}
            >
              Export
            </Button>
          </Box>

          <TableContainer component={Paper} variant="outlined" className={classes.scroll}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  {VISIT_COLUMNS.map((c) => (
                    <TableCell
                      key={c.key}
                      className={classes.head}
                      align={isNumeric(c.type) ? 'right' : 'left'}
                    >
                      {c.label}
                    </TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {!shownVisits.length && (
                  <TableRow>
                    <TableCell colSpan={VISIT_COLUMNS.length} align="center">
                      <Typography variant="body2" className={classes.muted}>
                        No visits in this window.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
                {shownVisits.map((v) => (
                  <TableRow key={v.visit_id} hover>
                    <TableCell>{v.executive_name}</TableCell>
                    <TableCell>{v.dealer_name}</TableCell>
                    <TableCell>{v.town || '—'}</TableCell>
                    <TableCell>{dt(v.check_in_at)}</TableCell>
                    <TableCell>
                      {v.open ? (
                        <Chip size="small" color="primary" label="Still in" />
                      ) : (
                        dt(v.check_out_at)
                      )}
                    </TableCell>
                    <TableCell align="right" className={classes.num}>
                      {v.suspect ? (
                        <Tooltip title="No check-out was recorded at the shop — this ran until the next check-in, so it is not time spent with the dealer.">
                          <span className={classes.warn}>
                            <IconAlertTriangle size={14} /> {duration(v.minutes)}
                          </span>
                        </Tooltip>
                      ) : (
                        duration(v.minutes)
                      )}
                    </TableCell>
                    <TableCell>
                      {v.check_in_lat != null && v.check_in_lng != null ? (
                        <Link
                          href={`https://www.google.com/maps?q=${v.check_in_lat},${v.check_in_lng}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Box display="inline-flex" alignItems="center" style={{ gap: 4 }}>
                            <IconMapPin size={14} />
                            {v.check_in_lat.toFixed(4)}, {v.check_in_lng.toFixed(4)}
                          </Box>
                        </Link>
                      ) : (
                        '—'
                      )}
                      {v.accuracy_m != null && (
                        <Typography variant="caption" className={classes.muted}>
                          {' '}
                          ±{Math.round(v.accuracy_m)}m
                        </Typography>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </>
      )}

      <Snackbar
        open={!!toast}
        autoHideDuration={5000}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity={toast?.severity || 'info'} onClose={() => setToast(null)}>
          {toast?.msg}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default SalesExecutives;
