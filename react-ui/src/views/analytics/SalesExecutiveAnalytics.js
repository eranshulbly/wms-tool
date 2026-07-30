import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Grid,
  Box,
  Stack,
  Typography,
  Chip,
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
  CircularProgress
} from '@material-ui/core';
import { IconTargetArrow, IconBulb } from '@tabler/icons';

import MainCard from '../../ui-component/cards/MainCard';
import { gridSpacing } from '../../store/constant';
import { getAnalyticsFilters, getSalesAnalytics, getDealerSuggestions } from '../../services/analyticsService';

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

// The dealer's progress toward this part's GROUP target (used in the suggestion tables).
const GroupCell = ({ sold, target, pct }) => {
  const color = pct == null ? 'text.secondary' : pct >= 100 ? 'success.main' : pct >= 50 ? 'warning.main' : 'error.main';
  return (
    <Box>
      <Typography variant="body2" sx={{ fontWeight: 600, color }}>
        {pct == null ? '—' : `${num(pct)}%`}
      </Typography>
      <Typography variant="caption" color="textSecondary">
        {num(sold)} / {num(target)}
      </Typography>
    </Box>
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
  const [month, setMonth] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Dealer-visit suggestions (loaded only when a specific dealer is selected).
  const [sugg, setSugg] = useState(null);
  const [suggLoading, setSuggLoading] = useState(false);

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
        setMonth(d.month);
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

  return (
    <Grid container spacing={gridSpacing}>
      <Grid item xs={12}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" flexWrap="wrap">
          <Box>
            <Typography variant="h2" sx={{ fontWeight: 700 }}>
              Target Tracker Analytics
            </Typography>
            <Typography variant="body1" color="textSecondary">
              {periodLabel} Busy sales vs targets — filter by executive, dealer, part group or part.
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Autocomplete
              size="small"
              disableClearable
              sx={{ width: 200 }}
              options={PERIODS}
              getOptionLabel={(o) => o.label}
              value={PERIODS.find((p) => p.value === filters.period) || PERIODS[3]}
              isOptionEqualToValue={(o, v) => o.value === v.value}
              onChange={(e, val) => set({ period: val ? val.value : DEFAULT_PERIOD })}
              renderInput={(p) => <TextField {...p} label="Time period" />}
            />
            {month && <Chip color="primary" label={periodLabel} />}
          </Box>
        </Stack>
      </Grid>

      {/* Filter bar */}
      <Grid item xs={12}>
        <Card>
          <CardContent>
            <Grid container spacing={2} alignItems="center">
              <Grid item xs={12} sm={6} md={3}>
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
              <Grid item xs={12} sm={6} md={3}>
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
              <Grid item xs={12} sm={6} md={3}>
                <Autocomplete
                  size="small"
                  disableClearable
                  options={[ALL_PG, ...options.part_groups]}
                  value={filters.part_group || ALL_PG}
                  onChange={(e, val) => set({ part_group: val && val !== ALL_PG ? val : null })}
                  renderInput={(p) => <TextField {...p} label="Part Group" />}
                />
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
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
            <Typography variant="h3" sx={{ fontWeight: 700 }}>
              Part suggestions
            </Typography>
            <Typography variant="body2" color="textSecondary">
              {selectedDealer
                ? `What to push at ${selectedDealer.dealer} — from company part-quantity targets and sales history.`
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
            <>
              <Grid item xs={12} md={6}>
                <MainCard
                  title={
                    <Stack direction="row" spacing={1} alignItems="center">
                      <IconTargetArrow size={20} />
                      <span>Grow — parts they already buy</span>
                    </Stack>
                  }
                  content={false}
                >
                  <TableContainer component={Paper} elevation={0}>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>Part #</TableCell>
                          <TableCell>Part Group</TableCell>
                          <TableCell align="right">Sold here</TableCell>
                          <TableCell align="right">Group vs target</TableCell>
                          <TableCell align="right">Group last 6 mo</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {sugg.grow.map((g) => (
                          <TableRow key={g.item_code} hover>
                            <TableCell>{g.item_code}</TableCell>
                            <TableCell>{g.part_group || '—'}</TableCell>
                            <TableCell align="right">{num(g.dealer_qty)}</TableCell>
                            <TableCell align="right">
                              <GroupCell sold={g.group_sold} target={g.group_target} pct={g.group_pct} />
                            </TableCell>
                            <TableCell align="right">{num(g.group_last6m)}</TableCell>
                          </TableRow>
                        ))}
                        {sugg.grow.length === 0 && (
                          <TableRow>
                            <TableCell colSpan={5}>
                              <Typography variant="body2" color="textSecondary">
                                Nothing to grow — every part this dealer buys is already at target.
                              </Typography>
                            </TableCell>
                          </TableRow>
                        )}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </MainCard>
              </Grid>

              <Grid item xs={12} md={6}>
                <MainCard
                  title={
                    <Stack direction="row" spacing={1} alignItems="center">
                      <IconBulb size={20} />
                      <span>New opportunity — peers buy, they don&apos;t</span>
                    </Stack>
                  }
                  content={false}
                >
                  <TableContainer component={Paper} elevation={0}>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>Part #</TableCell>
                          <TableCell>Part Group</TableCell>
                          <TableCell align="right">Peer dealers</TableCell>
                          <TableCell align="right">Peer qty</TableCell>
                          <TableCell align="right">Group vs target</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {sugg.new_opportunity.map((n) => (
                          <TableRow key={n.item_code} hover>
                            <TableCell>{n.item_code}</TableCell>
                            <TableCell>{n.part_group || '—'}</TableCell>
                            <TableCell align="right">{num(n.peer_dealers)}</TableCell>
                            <TableCell align="right">{num(n.peer_qty)}</TableCell>
                            <TableCell align="right">
                              <GroupCell sold={n.group_sold} target={n.group_target} pct={n.group_pct} />
                            </TableCell>
                          </TableRow>
                        ))}
                        {sugg.new_opportunity.length === 0 && (
                          <TableRow>
                            <TableCell colSpan={5}>
                              <Typography variant="body2" color="textSecondary">
                                No new opportunities for this dealer.
                              </Typography>
                            </TableCell>
                          </TableRow>
                        )}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </MainCard>
              </Grid>
            </>
          ) : null}
        </>
      ) : null}
    </Grid>
  );
};

export default SalesExecutiveAnalytics;
