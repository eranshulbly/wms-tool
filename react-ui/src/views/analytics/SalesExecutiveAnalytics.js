import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Grid,
  Box,
  Stack,
  Typography,
  Button,
  Card,
  CardContent,
  Autocomplete,
  TextField,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Collapse,
  Chip,
  Tabs,
  Tab,
  CircularProgress
} from '@material-ui/core';
import { IconChevronRight, IconChevronDown } from '@tabler/icons';

import MainCard from '../../ui-component/cards/MainCard';
import { gridSpacing } from '../../store/constant';
import { getAnalyticsFilters, getSalesAnalytics, getDealerSuggestions } from '../../services/analyticsService';
import { groupSuggestions } from './suggestionGrouping';

// Sales Executive Analytics — a filtered explorer over this month's Busy sales: sales by
// executive and by dealer against their rupee targets, plus, once a dealer is chosen,
// part suggestions for a visit (from company part-qty targets + sales history).

const inr = (n) =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n || 0);
const num = (n) => new Intl.NumberFormat('en-IN').format(n || 0);
// Minutes -> "1h 05m" / "24 min" / "—" (null = no completed visits).
const dur = (m) => (m == null ? '—' : m >= 60 ? `${Math.floor(m / 60)}h ${String(Math.round(m % 60)).padStart(2, '0')}m` : `${Math.round(m)} min`);

const StatCard = ({ label, value }) => (
  <MainCard>
    <Typography variant="subtitle2" color="textSecondary">
      {label}
    </Typography>
    <Typography variant="h3" sx={{ fontWeight: 700, mt: 0.5 }}>
      {value}
    </Typography>
  </MainCard>
);

// % of target achieved, colour-coded (green ≥100%, amber ≥50%, red below).
const PctCell = ({ pct }) => {
  if (pct == null) {
    return (
      <Typography variant="body2" color="textSecondary">
        —
      </Typography>
    );
  }
  const color = pct >= 100 ? 'success.main' : pct >= 50 ? 'warning.main' : 'error.main';
  return (
    <Typography variant="body2" sx={{ fontWeight: 600, color }}>
      {num(pct)}%
    </Typography>
  );
};

// Latest sale_date loaded vs today. Sales are batch-imported and lag; once 2+ days
// behind we flag it amber so a part-month figure isn't read as live.
const freshness = (dt) => {
  if (!dt) return null;
  const days = Math.floor((Date.now() - new Date(`${dt}T00:00:00`).getTime()) / 86400000);
  return { date: dt, days, stale: days >= 2 };
};

// One collapsible card for a scheme (or a part group, when the scheme is 'PG').
// Collapsed: name + card totals. Expanded: the parts, description over item_code.
const SuggestionCard = ({ group, grow }) => {
  const [open, setOpen] = useState(false);
  return (
    <Paper variant="outlined" sx={{ mb: 1 }}>
      <Box
        onClick={() => setOpen((o) => !o)}
        sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 1.5, cursor: 'pointer', '&:hover': { bgcolor: 'action.hover' } }}
      >
        {open ? <IconChevronDown size={18} /> : <IconChevronRight size={18} />}
        <Box sx={{ flexGrow: 1, minWidth: 0 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            {group.name}
          </Typography>
          {group.partGroupCount > 1 && (
            <Typography variant="caption" color="textSecondary">
              {group.partGroupCount} part groups behind target — subtotal of this scheme, not the whole scheme
            </Typography>
          )}
        </Box>
        <Box sx={{ textAlign: 'right', flexShrink: 0 }}>
          <Typography variant="body2" sx={{ fontWeight: 600 }}>
            Sold {num(group.groupSold)} · Target {num(group.groupTarget)}
          </Typography>
          <PctCell pct={group.groupPct} />
        </Box>
      </Box>
      <Collapse in={open} unmountOnExit>
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Part</TableCell>
                {grow ? (
                  <>
                    <TableCell align="right">This mo</TableCell>
                    <TableCell align="right">Last 6 mo</TableCell>
                  </>
                ) : (
                  <TableCell align="right">Dealers</TableCell>
                )}
              </TableRow>
            </TableHead>
            <TableBody>
              {group.parts.map((p) => (
                <TableRow key={p.item_code} hover>
                  <TableCell>
                    <Typography variant="body2">{p.description || p.item_code}</Typography>
                    {p.description ? (
                      <Typography variant="caption" color="textSecondary" sx={{ fontFamily: 'monospace' }}>
                        {p.item_code}
                      </Typography>
                    ) : null}
                  </TableCell>
                  {grow ? (
                    <>
                      <TableCell align="right">{num(p.dealer_qty)}</TableCell>
                      <TableCell align="right">{num(p.dealer_last6m)}</TableCell>
                    </>
                  ) : (
                    <TableCell align="right">{num(p.peer_dealers)}</TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </Collapse>
    </Paper>
  );
};

// Time-period filter options for the sales window (value must match the backend).
const PERIODS = [
  { value: 'last_24h', label: 'Last 24 hours' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: 'last_7d', label: 'Last 7 days' },
  { value: 'this_month', label: 'This month' },
  { value: 'last_month', label: 'Last month' },
  { value: 'last_6m', label: 'Last 6 months' }
];
const DEFAULT_PERIOD = 'this_month';

const EMPTY = { executive_id: null, dealer_id: null, part_group: null, part: null, period: DEFAULT_PERIOD };
const ALL_EXEC = { user_id: null, username: 'All Executives' };
const ALL_DEALER = { dealer_id: null, dealer: 'All Dealers' };
const ALL_PART = { item_code: null, description: 'All Parts' };
const ALL_PG = 'All Part Groups';

const SalesExecutiveAnalytics = () => {
  const [options, setOptions] = useState({ executives: [], dealers: [], part_groups: [], parts: [] });
  const [filters, setFilters] = useState(EMPTY);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Dealer-visit suggestions (loaded only when a specific dealer is selected).
  const [sugg, setSugg] = useState(null);
  const [suggLoading, setSuggLoading] = useState(false);
  const [suggTab, setSuggTab] = useState(0); // 0 = Target (grow), 1 = New opportunity

  useEffect(() => {
    (async () => {
      try {
        const d = await getAnalyticsFilters();
        if (d.success) setOptions(d);
      } catch (e) {
        /* filter lists just stay empty */
      }
    })();
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await getSalesAnalytics(filters);
      if (d.success) {
        setData(d);
      } else {
        setError(d.msg || 'Failed to load analytics');
      }
    } catch (e) {
      setError(e?.response?.data?.msg || 'Failed to load analytics');
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    load();
  }, [load]);

  // Load part suggestions when a specific dealer is chosen.
  useEffect(() => {
    if (!filters.dealer_id) {
      setSugg(null);
      return;
    }
    let mounted = true;
    setSuggLoading(true);
    getDealerSuggestions(filters.dealer_id)
      .then((d) => {
        if (mounted && d.success) setSugg(d);
      })
      .catch(() => {})
      .finally(() => mounted && setSuggLoading(false));
    return () => {
      mounted = false;
    };
  }, [filters.dealer_id]);

  const dealerOptions = useMemo(
    () =>
      filters.executive_id
        ? options.dealers.filter((d) => d.executive_id === filters.executive_id)
        : options.dealers,
    [options.dealers, filters.executive_id]
  );

  const set = (patch) => setFilters((f) => ({ ...f, ...patch }));
  const selectedExec = options.executives.find((e) => e.user_id === filters.executive_id) || null;
  const selectedDealer = options.dealers.find((d) => d.dealer_id === filters.dealer_id) || null;
  const selectedPart = options.parts.find((p) => p.item_code === filters.part) || null;
  const hasFilters = filters.executive_id || filters.dealer_id || filters.part_group || filters.part;
  const periodLabel = (PERIODS.find((p) => p.value === filters.period) || PERIODS[3]).label;

  // Group the flat suggestion lists into collapsible cards (see suggestionGrouping.js).
  const growGroups = useMemo(() => (sugg ? groupSuggestions(sugg.grow) : []), [sugg]);
  const oppGroups = useMemo(() => (sugg ? groupSuggestions(sugg.new_opportunity) : []), [sugg]);
  const fresh = freshness(data?.data_through);

  return (
    <Grid container spacing={gridSpacing}>
      <Grid item xs={12}>
        <Box>
          <Typography variant="h2" sx={{ fontWeight: 700 }}>
            Target Tracker Analytics
          </Typography>
          <Typography variant="body1" color="textSecondary">
            {periodLabel} Busy sales vs targets — filter by time period, executive, dealer, part group or part.
          </Typography>
        </Box>
      </Grid>

      {/* Filter bar */}
      <Grid item xs={12}>
        <Card>
          <CardContent>
            <Grid container spacing={2} alignItems="center">
              <Grid item xs={12} sm={6} md={2.4}>
                <Autocomplete
                  size="small"
                  disableClearable
                  options={PERIODS}
                  getOptionLabel={(o) => o.label}
                  value={PERIODS.find((p) => p.value === filters.period) || PERIODS[3]}
                  isOptionEqualToValue={(o, v) => o.value === v.value}
                  onChange={(e, val) => set({ period: val ? val.value : DEFAULT_PERIOD })}
                  renderInput={(p) => <TextField {...p} label="Time period" />}
                />
              </Grid>
              <Grid item xs={12} sm={6} md={2.4}>
                <Autocomplete
                  size="small"
                  disableClearable
                  options={[ALL_EXEC, ...options.executives]}
                  getOptionLabel={(o) => o.username}
                  value={selectedExec || ALL_EXEC}
                  isOptionEqualToValue={(o, v) => o.user_id === v.user_id}
                  onChange={(e, val) => set({ executive_id: val && val.user_id ? val.user_id : null, dealer_id: null })}
                  renderInput={(p) => <TextField {...p} label="Sales Executive" />}
                />
              </Grid>
              <Grid item xs={12} sm={6} md={2.4}>
                <Autocomplete
                  size="small"
                  disableClearable
                  options={[ALL_DEALER, ...dealerOptions]}
                  getOptionLabel={(o) => o.dealer}
                  value={selectedDealer || ALL_DEALER}
                  isOptionEqualToValue={(o, v) => o.dealer_id === v.dealer_id}
                  onChange={(e, val) => set({ dealer_id: val && val.dealer_id ? val.dealer_id : null })}
                  renderInput={(p) => <TextField {...p} label="Dealer" />}
                />
              </Grid>
              <Grid item xs={12} sm={6} md={2.4}>
                <Autocomplete
                  size="small"
                  disableClearable
                  options={[ALL_PG, ...options.part_groups]}
                  value={filters.part_group || ALL_PG}
                  onChange={(e, val) => set({ part_group: val && val !== ALL_PG ? val : null })}
                  renderInput={(p) => <TextField {...p} label="Part Group" />}
                />
              </Grid>
              <Grid item xs={12} sm={6} md={2.4}>
                <Autocomplete
                  size="small"
                  disableClearable
                  options={[ALL_PART, ...options.parts]}
                  getOptionLabel={(o) =>
                    o.item_code ? (o.description ? `${o.item_code} — ${o.description}` : o.item_code) : o.description || 'All Parts'
                  }
                  value={selectedPart || ALL_PART}
                  isOptionEqualToValue={(o, v) => o.item_code === v.item_code}
                  onChange={(e, val) => set({ part: val && val.item_code ? val.item_code : null })}
                  renderInput={(p) => <TextField {...p} label="Part" />}
                />
              </Grid>
            </Grid>
            {hasFilters && (
              <Box sx={{ mt: 1.5 }}>
                <Button size="small" onClick={() => setFilters((f) => ({ ...EMPTY, period: f.period }))}>
                  Clear filters
                </Button>
              </Box>
            )}
          </CardContent>
        </Card>
      </Grid>

      {loading ? (
        <Grid item xs={12}>
          <Box sx={{ display: 'flex', justifyContent: 'center', p: 6 }}>
            <CircularProgress />
          </Box>
        </Grid>
      ) : error ? (
        <Grid item xs={12}>
          <MainCard>
            <Typography color="error">{error}</Typography>
          </MainCard>
        </Grid>
      ) : data ? (
        <>
          {/* Summary */}
          <Grid item xs={12}>
            <Box
              sx={{
                display: 'grid',
                gap: gridSpacing,
                gridTemplateColumns: { xs: 'repeat(1, 1fr)', sm: 'repeat(2, 1fr)', md: 'repeat(4, 1fr)' }
              }}
            >
              <StatCard label="Total sales" value={inr(data.summary.total_sales)} />
              <StatCard label="Total qty" value={num(data.summary.total_qty)} />
              <StatCard label="Dealers" value={num(data.summary.dealers)} />
              <StatCard
                label={`Avg time at dealer (${num(data.summary.visits)} visits)`}
                value={dur(data.summary.avg_visit_minutes)}
              />
            </Box>
          </Grid>

          {/* Sales by executive */}
          <Grid item xs={12} md={6}>
            <MainCard title="Sales by executive" content={false}>
              <TableContainer component={Paper} elevation={0} sx={{ maxHeight: 420 }}>
                <Table stickyHeader size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Executive</TableCell>
                      <TableCell align="right">Sales</TableCell>
                      <TableCell align="right">Target</TableCell>
                      <TableCell align="right">% Achieved</TableCell>
                      <TableCell align="right">Visits</TableCell>
                      <TableCell align="right">Avg time</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {data.by_executive.map((e) => (
                      <TableRow key={e.user_id} hover>
                        <TableCell sx={{ textTransform: 'capitalize' }}>{e.username}</TableCell>
                        <TableCell align="right">{inr(e.sales)}</TableCell>
                        <TableCell align="right">{inr(e.target)}</TableCell>
                        <TableCell align="right">
                          <PctCell pct={e.pct} />
                        </TableCell>
                        <TableCell align="right">{num(e.visits)}</TableCell>
                        <TableCell align="right">{dur(e.avg_visit_minutes)}</TableCell>
                      </TableRow>
                    ))}
                    {data.by_executive.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={6}>
                          <Typography variant="body2" color="textSecondary">
                            No data for these filters.
                          </Typography>
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            </MainCard>
          </Grid>

          {/* Sales by dealer */}
          <Grid item xs={12} md={6}>
            <MainCard title="Sales by dealer" content={false}>
              <TableContainer component={Paper} elevation={0} sx={{ maxHeight: 420 }}>
                <Table stickyHeader size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Dealer</TableCell>
                      <TableCell align="right">Sales</TableCell>
                      <TableCell align="right">Target</TableCell>
                      <TableCell align="right">% Achieved</TableCell>
                      <TableCell align="right">Visits</TableCell>
                      <TableCell align="right">Avg time</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {data.by_dealer.map((d) => (
                      <TableRow key={d.dealer_id} hover>
                        <TableCell>{d.dealer}</TableCell>
                        <TableCell align="right">{inr(d.sales)}</TableCell>
                        <TableCell align="right">{inr(d.target)}</TableCell>
                        <TableCell align="right">
                          <PctCell pct={d.pct} />
                        </TableCell>
                        <TableCell align="right">{num(d.visits)}</TableCell>
                        <TableCell align="right">{dur(d.avg_visit_minutes)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </MainCard>
          </Grid>

          {/* Target by dealer & part group (quantity) */}
          <Grid item xs={12}>
            <MainCard title="Target by dealer & part group (qty)" content={false}>
              <TableContainer component={Paper} elevation={0} sx={{ maxHeight: 460 }}>
                <Table stickyHeader size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Dealer</TableCell>
                      <TableCell>Part Group</TableCell>
                      <TableCell align="right">Target Qty</TableCell>
                      <TableCell align="right">Sold</TableCell>
                      <TableCell align="right">% Achieved</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {data.by_dealer_group.map((r) => (
                      <TableRow key={`${r.dealer_id}-${r.part_group}`} hover>
                        <TableCell>{r.dealer}</TableCell>
                        <TableCell>{r.part_group}</TableCell>
                        <TableCell align="right">{num(r.target_qty)}</TableCell>
                        <TableCell align="right">{num(r.sold)}</TableCell>
                        <TableCell align="right">
                          <PctCell pct={r.pct} />
                        </TableCell>
                      </TableRow>
                    ))}
                    {data.by_dealer_group.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={5}>
                          <Typography variant="body2" color="textSecondary">
                            No dealer / part-group targets for these filters.
                          </Typography>
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            </MainCard>
          </Grid>

          {/* Part suggestions — only for a specific dealer */}
          <Grid item xs={12}>
            <Stack direction="row" spacing={2} alignItems="baseline" flexWrap="wrap">
              <Typography variant="h3" sx={{ fontWeight: 700 }}>
                Part suggestions
              </Typography>
              {fresh && (
                <Chip
                  size="small"
                  label={`Sales data through ${fresh.date}`}
                  color={fresh.stale ? 'warning' : 'default'}
                  variant={fresh.stale ? 'filled' : 'outlined'}
                />
              )}
            </Stack>
            <Typography variant="body2" color="textSecondary">
              {selectedDealer
                ? `What to push at ${selectedDealer.dealer} — from the dealer's part-group targets and sales history.`
                : 'Pick a dealer above to see part suggestions for a visit.'}
            </Typography>
          </Grid>

          {!filters.dealer_id ? null : suggLoading ? (
            <Grid item xs={12}>
              <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
                <CircularProgress />
              </Box>
            </Grid>
          ) : sugg ? (
            <Grid item xs={12}>
              <MainCard content={false}>
                <Box sx={{ borderBottom: 1, borderColor: 'divider', px: 2, pt: 1 }}>
                  <Tabs value={suggTab} onChange={(_, v) => setSuggTab(v)}>
                    <Tab label={`Target (${growGroups.length})`} />
                    <Tab label={`New opportunity (${oppGroups.length})`} />
                  </Tabs>
                </Box>
                <Box sx={{ p: 2 }}>
                  {suggTab === 0 ? (
                    growGroups.length ? (
                      growGroups.map((g) => <SuggestionCard key={g.schemeKey} group={g} grow />)
                    ) : (
                      <Typography variant="body2" color="textSecondary">
                        Nothing to grow — every part this dealer buys is already at target.
                      </Typography>
                    )
                  ) : oppGroups.length ? (
                    oppGroups.map((g) => <SuggestionCard key={g.schemeKey} group={g} grow={false} />)
                  ) : (
                    <Typography variant="body2" color="textSecondary">
                      No new opportunities for this dealer.
                    </Typography>
                  )}
                </Box>
              </MainCard>
            </Grid>
          ) : null}
        </>
      ) : null}
    </Grid>
  );
};

export default SalesExecutiveAnalytics;
