import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import {
  Box,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
  CircularProgress,
  Alert
} from '@material-ui/core';
import api from '../../../services/api';

// The line items behind one app-submitted order, shown when its row is expanded.
//
// Fetched on expand rather than with the list: the tab routinely shows dozens of orders
// and almost none of them get opened, so loading every order's lines up front would be
// the same mistake the products table made.

const money = (v) => {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (Number.isNaN(n)) return '—';
  return `₹${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};
const qty = (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString('en-IN'));

const SubmittedOrderItems = ({ orderId }) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    api
      .get(`orders/submitted/${orderId}/items`)
      .then((r) => {
        if (!live) return;
        if (r.data.success) setData(r.data);
        else setError(r.data.msg || 'Could not load items');
      })
      .catch((e) => live && setError(e?.response?.data?.msg || 'Could not load items'))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [orderId]);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 2 }}>
        <CircularProgress size={22} />
      </Box>
    );
  }
  if (error) return <Alert severity="error" sx={{ m: 1 }}>{error}</Alert>;
  if (!data?.items?.length) {
    return (
      <Typography variant="body2" color="textSecondary" sx={{ p: 2 }}>
        This order has no parts yet — upload the part-convertor file first.
      </Typography>
    );
  }

  const t = data.totals || {};
  return (
    <Box sx={{ p: 2, bgcolor: '#f8fafc' }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Product</TableCell>
            <TableCell align="right">Ordered</TableCell>
            <TableCell align="right">Allocated</TableCell>
            <TableCell align="right">MRP</TableCell>
            <TableCell align="right">Rate</TableCell>
            <TableCell align="right">Landing</TableCell>
            <TableCell align="right">Line total</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {data.items.map((it) => (
            <TableRow key={it.id}>
              <TableCell>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>{it.product_name}</Typography>
                <Typography variant="caption" color="textSecondary">
                  {it.sku_code}{it.uom ? ` · ${it.uom}` : ''}
                </Typography>
              </TableCell>
              <TableCell align="right">{qty(it.quantity)}</TableCell>
              {/* Null until the DMS file is generated — that is when stock is allocated
                  and the supplied quantity is stamped onto the line. */}
              <TableCell align="right">{it.dms_quantity == null ? '—' : qty(it.dms_quantity)}</TableCell>
              <TableCell align="right">{money(it.mrp)}</TableCell>
              <TableCell align="right">
                {money(it.landing_price)}
                {/* Which batches the cost came from. Shown because the figure is a
                    weighted blend across batches, not a price anyone can look up. */}
                {(it.landing_batches || []).length > 1 && (
                  <Typography variant="caption" color="textSecondary" display="block">
                    {it.landing_batches.length} batches
                  </Typography>
                )}
                {(it.landing_batches || []).map((b) => (
                  <Typography key={b.batch_number} variant="caption" color="textSecondary" display="block">
                    {b.batch_number} · {qty(b.quantity)} @ {money(b.landing_price)}
                  </Typography>
                ))}
              </TableCell>
              <TableCell align="right">{money(it.line_total)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3, mt: 2, alignItems: 'flex-end' }}>
        <Box>
          <Typography variant="body2" color="textSecondary">Order total</Typography>
          <Typography variant="h4">{money(t.order_total)}</Typography>
        </Box>
        <Box>
          <Typography variant="body2" color="textSecondary">Landing cost</Typography>
          <Typography variant="h4">{money(t.landing_cost)}</Typography>
        </Box>
        <Box>
          <Typography variant="body2" color="textSecondary">Margin</Typography>
          <Typography
            variant="h4"
            style={{ color: t.margin > 0 ? '#12805c' : t.margin < 0 ? '#e5372e' : undefined }}
          >
            {money(t.margin)}
            {t.margin_pct != null && (
              <Typography component="span" variant="body1" sx={{ ml: 0.75 }}>
                ({t.margin_pct}%)
              </Typography>
            )}
          </Typography>
        </Box>
      </Box>

      {/* Why margin is blank here, said once and plainly, rather than leaving a dash to
          be read as a bug. */}
      <Alert severity={data.landing_available ? 'info' : 'warning'} sx={{ mt: 1.5 }}>
        {data.landing_note}
      </Alert>
    </Box>
  );
};

SubmittedOrderItems.propTypes = { orderId: PropTypes.number };

export default SubmittedOrderItems;
