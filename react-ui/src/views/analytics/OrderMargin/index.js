import React, { useState, useEffect, useCallback } from 'react';
import {
  Box,
  Button,
  IconButton,
  Typography,
  CircularProgress,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TableFooter,
  Paper,
  Grid,
  MenuItem,
  TextField,
  Tooltip,
  Snackbar,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconRefresh, IconDownload, IconAlertTriangle, IconX } from '@tabler/icons';
import api from '../../../services/api';
import { useWarehouse } from '../../../context/WarehouseContext';

const BASE = 'admin/order-margin';

const ORDER_COLUMNS = [
  { key: 'order_number', label: 'Order #', type: 'text' },
  { key: 'invoice_number', label: 'Invoice #', type: 'text' },
  { key: 'invoice_date', label: 'Invoice Date', type: 'date' },
  { key: 'dealer_name', label: 'Dealer', type: 'text' },
  { key: 'order_total', label: 'Sale Value', type: 'money' },
  { key: 'landing_cost', label: 'Landing Cost', type: 'money' },
  { key: 'margin', label: 'Margin', type: 'money' },
  { key: 'margin_pct', label: 'Margin %', type: 'pct' },
];

const LINE_COLUMNS = [
  { key: 'product_name', label: 'Product', type: 'text' },
  { key: 'sku_code', label: 'SKU', type: 'text' },
  { key: 'batch_number', label: 'Batch', type: 'text' },
  { key: 'quantity', label: 'Qty', type: 'int' },
  { key: 'sale_rate', label: 'Sale Rate', type: 'money' },
  { key: 'sale_value', label: 'Sale Value', type: 'money' },
  { key: 'cost_rate', label: 'Cost Rate', type: 'money' },
  { key: 'cost_value', label: 'Cost Value', type: 'money' },
  { key: 'margin_value', label: 'Margin', type: 'money' },
  { key: 'margin_pct', label: 'Margin %', type: 'pct' },
];

const LINE_STATUS_NOTE = {
  no_rate: "This line wasn't priced when the order was uploaded — no sale rate to work from.",
  no_cost: 'No landing price on file for the batch this line shipped against.',
};

const useStyles = makeStyles((theme) => ({
  section: { marginBottom: theme.spacing(2) },
  muted: { color: '#7a869a' },
  num: { whiteSpace: 'nowrap' },
  head: {
    whiteSpace: 'nowrap',
    fontWeight: 600,
    position: 'sticky',
    top: 0,
    zIndex: 3,
    background: '#fff',
  },
  scroll: { maxHeight: '60vh' },
  warn: { color: '#b26a00', display: 'inline-flex', alignItems: 'center', gap: 4 },
  statCard: { padding: 16, height: '100%' },
  statLabel: { color: '#7a869a', fontSize: 13 },
  statValue: { fontWeight: 600, marginTop: 4 },
  positive: { color: '#1b873f' },
  negative: { color: '#c0392b' },
}));

const nf2 = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const dt = (v) => {
  if (!v) return '—';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
};

const render = (type, v) => {
  if (v === null || v === undefined || v === '') return '—';
  if (type === 'money') return nf2.format(Number(v));
  if (type === 'pct') return `${nf2.format(Number(v))}%`;
  if (type === 'int') return Number(v).toLocaleString('en-IN');
  if (type === 'date') return dt(v);
  return String(v);
};

const isNumeric = (t) => t === 'money' || t === 'pct' || t === 'int';

const StatCard = ({ label, value, sub, tone }) => {
  const classes = useStyles();
  return (
    <Paper variant="outlined" className={classes.statCard}>
      <Typography className={classes.statLabel}>{label}</Typography>
      <Typography
        variant="h5"
        className={`${classes.statValue} ${tone === 'positive' ? classes.positive : tone === 'negative' ? classes.negative : ''}`}
      >
        {value}
      </Typography>
      {sub && (
        <Typography variant="caption" className={classes.muted}>
          {sub}
        </Typography>
      )}
    </Paper>
  );
};

const emptyTotals = {
  order_total: null,
  landing_cost: null,
  margin: null,
  margin_pct: null,
  costed_lines: 0,
  lines: 0,
};

// No default date window: "till date" means every invoiced order on file until the
// user deliberately narrows it, not the last 30 days.
const OrderMargin = () => {
  const classes = useStyles();
  const { companies, selectedCompany, setSelectedCompany } = useWarehouse();

  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [orders, setOrders] = useState([]);
  const [periodTotals, setPeriodTotals] = useState(emptyTotals);
  const [overall, setOverall] = useState(emptyTotals);
  const [orderCount, setOrderCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState(null);

  const [detailOrderId, setDetailOrderId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const load = useCallback(async () => {
    if (!selectedCompany) {
      setOrders([]);
      setPeriodTotals(emptyTotals);
      setOverall(emptyTotals);
      setOrderCount(0);
      return;
    }
    setLoading(true);
    try {
      const params = { company_id: selectedCompany };
      if (from) params.from = from;
      if (to) params.to = to;
      const res = await api.get(BASE, { params });
      setOrders(res.data.orders || []);
      setPeriodTotals(res.data.period_totals || emptyTotals);
      setOverall(res.data.overall || emptyTotals);
      setOrderCount(res.data.order_count || 0);
    } catch (e) {
      setToast({
        severity: 'error',
        msg: e?.response?.data?.msg || 'Could not load the order margin report',
      });
    } finally {
      setLoading(false);
    }
  }, [selectedCompany, from, to]);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = !!(from || to);

  const openOrder = async (order) => {
    setDetailOrderId(order.potential_order_id);
    setDetail(null);
    setDetailLoading(true);
    try {
      const res = await api.get(`${BASE}/${order.potential_order_id}`, {
        params: { company_id: selectedCompany },
      });
      setDetail(res.data);
    } catch (e) {
      setToast({
        severity: 'error',
        msg: e?.response?.data?.msg || 'Could not load this order',
      });
      setDetailOrderId(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const closeOrder = () => {
    setDetailOrderId(null);
    setDetail(null);
  };

  const exportCsv = () => {
    const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const csv = [
      ORDER_COLUMNS.map((c) => esc(c.label)).join(','),
      ...orders.map((r) => ORDER_COLUMNS.map((c) => esc(r[c.key])).join(',')),
    ].join('\n');
    const company = companies.find((c) => c.id === selectedCompany);
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(company?.name || 'orders').replace(/\s+/g, '_')}_Order_Margin_${from || 'all'}_to_${to || 'date'}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Order Margin
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
                  : `${orderCount} invoiced order${orderCount === 1 ? '' : 's'} on file`}
              </Typography>
              <Box flexGrow={1} />
              {filtered && (
                <Button size="small" onClick={() => { setFrom(''); setTo(''); }}>
                  Clear dates
                </Button>
              )}
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
                onClick={exportCsv}
                disabled={!orders.length}
              >
                Export
              </Button>
            </Box>
          </Grid>
        </Grid>
      </Paper>

      <Grid container spacing={2} className={classes.section}>
        <Grid item xs={12} sm={4}>
          <StatCard
            label="Overall margin — till date"
            value={overall.margin !== null ? `₹ ${nf2.format(overall.margin)}` : '—'}
            sub={
              overall.order_total !== null
                ? `on ₹ ${nf2.format(overall.order_total)} sold${
                    overall.margin_pct !== null ? ` · ${nf2.format(overall.margin_pct)}%` : ''
                  }`
                : 'No costed lines yet'
            }
            tone={overall.margin === null ? undefined : overall.margin >= 0 ? 'positive' : 'negative'}
          />
        </Grid>
        <Grid item xs={12} sm={4}>
          <StatCard
            label={filtered ? 'Margin — selected period' : 'Margin — all orders shown'}
            value={periodTotals.margin !== null ? `₹ ${nf2.format(periodTotals.margin)}` : '—'}
            sub={
              periodTotals.order_total !== null
                ? `on ₹ ${nf2.format(periodTotals.order_total)} sold${
                    periodTotals.margin_pct !== null ? ` · ${nf2.format(periodTotals.margin_pct)}%` : ''
                  }`
                : 'No costed lines in this window'
            }
            tone={periodTotals.margin === null ? undefined : periodTotals.margin >= 0 ? 'positive' : 'negative'}
          />
        </Grid>
        <Grid item xs={12} sm={4}>
          <StatCard
            label="Cost coverage — selected period"
            value={periodTotals.lines ? `${periodTotals.costed_lines} / ${periodTotals.lines} lines` : '—'}
            sub="Lines whose batch has a recorded landing price"
          />
        </Grid>
      </Grid>

      {loading && !orders.length ? (
        <Box display="flex" justifyContent="center" p={4}>
          <CircularProgress />
        </Box>
      ) : (
        <TableContainer component={Paper} variant="outlined" className={classes.scroll}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                {ORDER_COLUMNS.map((c) => (
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
              {!orders.length && (
                <TableRow>
                  <TableCell colSpan={ORDER_COLUMNS.length} align="center">
                    <Typography variant="body2" className={classes.muted}>
                      {selectedCompany ? 'No invoiced orders in this window.' : 'Select a company.'}
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
              {orders.map((r) => (
                <TableRow
                  key={r.potential_order_id}
                  hover
                  onClick={() => openOrder(r)}
                  style={{ cursor: 'pointer' }}
                >
                  {ORDER_COLUMNS.map((c) => (
                    <TableCell
                      key={c.key}
                      align={isNumeric(c.type) ? 'right' : 'left'}
                      className={isNumeric(c.type) ? classes.num : undefined}
                    >
                      {render(c.type, r[c.key])}
                      {c.key === 'margin' && r.lines > 0 && r.costed_lines < r.lines && (
                        <Tooltip
                          title={`Only ${r.costed_lines} of ${r.lines} line${
                            r.lines === 1 ? '' : 's'
                          } on this order carry a landing price — the margin above covers just those.`}
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
      )}

      <Dialog open={!!detailOrderId} onClose={closeOrder} maxWidth="lg" fullWidth>
        <DialogTitle disableTypography>
          <Box display="flex" alignItems="center">
            <Box>
              <Typography variant="h6">
                {detail ? detail.order_number : 'Order'}
                {detail?.invoice_number ? ` · Invoice ${detail.invoice_number}` : ''}
              </Typography>
              {detail && (
                <Typography variant="body2" className={classes.muted}>
                  {detail.dealer_name || 'Unknown dealer'}
                  {detail.invoice_date ? ` · ${dt(detail.invoice_date)}` : ''}
                </Typography>
              )}
            </Box>
            <Box flexGrow={1} />
            <IconButton size="small" onClick={closeOrder}>
              <IconX size={18} />
            </IconButton>
          </Box>
        </DialogTitle>
        <DialogContent dividers>
          {detailLoading ? (
            <Box display="flex" justifyContent="center" p={4}>
              <CircularProgress />
            </Box>
          ) : (
            detail && (
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      {LINE_COLUMNS.map((c) => (
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
                    {!detail.lines.length && (
                      <TableRow>
                        <TableCell colSpan={LINE_COLUMNS.length} align="center">
                          <Typography variant="body2" className={classes.muted}>
                            This order has no line items.
                          </Typography>
                        </TableCell>
                      </TableRow>
                    )}
                    {detail.lines.map((l) => (
                      <TableRow key={l.product_id + (l.batch_number || '')} hover>
                        {LINE_COLUMNS.map((c) => (
                          <TableCell
                            key={c.key}
                            align={isNumeric(c.type) ? 'right' : 'left'}
                            className={isNumeric(c.type) ? classes.num : undefined}
                          >
                            {render(c.type, l[c.key])}
                            {c.key === 'margin_value' && l.status !== 'ok' && (
                              <Tooltip title={LINE_STATUS_NOTE[l.status] || ''}>
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
                  {detail.totals && (
                    <TableFooter>
                      <TableRow>
                        <TableCell colSpan={4} style={{ fontWeight: 600 }}>
                          Total ({detail.totals.costed_lines} / {detail.totals.lines} lines costed)
                        </TableCell>
                        <TableCell />
                        <TableCell align="right" className={classes.num} style={{ fontWeight: 600 }}>
                          {render('money', detail.totals.order_total)}
                        </TableCell>
                        <TableCell />
                        <TableCell align="right" className={classes.num} style={{ fontWeight: 600 }}>
                          {render('money', detail.totals.landing_cost)}
                        </TableCell>
                        <TableCell align="right" className={classes.num} style={{ fontWeight: 600 }}>
                          {render('money', detail.totals.margin)}
                        </TableCell>
                        <TableCell align="right" className={classes.num} style={{ fontWeight: 600 }}>
                          {render('pct', detail.totals.margin_pct)}
                        </TableCell>
                      </TableRow>
                    </TableFooter>
                  )}
                </Table>
              </TableContainer>
            )
          )}
        </DialogContent>
      </Dialog>

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

export default OrderMargin;
