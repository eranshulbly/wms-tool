import React, { useState, useEffect, useMemo } from 'react';
import PropTypes from 'prop-types';
import { Box, Typography, CircularProgress } from '@material-ui/core';
import { IconAlertTriangle, IconChevronRight } from '@tabler/icons';

import { getDealerOverview, getDealerNotes } from '../../services/analyticsService';

// Dealer Overview — the admin twin of the mobile app's dealer-visit Overview tab
// (dealer-overview-spec.md). One dealer, one month, answering in order: can I trust
// these numbers, how is the dealer doing overall, and where is the gap.
//
// Differences from the phone, per spec §7: the dealer is chosen rather than fixed by an
// active check-in, there is no check-in strip or order action, and notes are read-only
// (the write endpoint is owner-only and 403s for anyone else).

// Spec §5.4 — the mobile palette, so the two views read as one product.
const INK = '#191B1A';
const BODY = '#4A4D48';
const LABEL = '#76796F';
const PAPER = '#EFEDE7';
const CARD = '#FFFFFF';
const BORDER = '#DCD9D0';
const DIVIDER = '#EBE8E1';
// IBM Plex Mono is the mobile face; fall back through what a desktop actually has so
// figures still line up in a column.
const MONO = '"IBM Plex Mono", "SFMono-Regular", Menlo, Consolas, monospace';

// Spec §5.2 — one achievement scale for every percentage, bar and figure here.
const pctColor = (pct) => {
  if (pct == null) return '#9A9C92';
  if (pct < 60) return '#A32B1F';
  if (pct < 90) return '#8A5A00';
  return '#2F6B3D';
};

// Spec §5.3 — en-IN throughout (lakh/crore grouping), money without decimals.
const inr = (n) =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n || 0);
// 0 dp when whole, 1 dp otherwise. null is "no target", never 0%.
const pctText = (pct) => (pct == null ? '—' : `${Number.isInteger(pct) ? pct : pct.toFixed(1)}%`);
const shortDate = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ''
    : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
};

// Whole calendar days between the last loaded sale and today.
const daysBehind = (dataThrough) => {
  if (!dataThrough) return null;
  const then = new Date(`${dataThrough}T00:00:00`);
  if (Number.isNaN(then.getTime())) return null;
  const today = new Date();
  return Math.floor((new Date(today.getFullYear(), today.getMonth(), today.getDate()) - then) / 86400000);
};

const Num = ({ children, sx }) => (
  <Box component="span" sx={{ fontFamily: MONO, ...sx }}>
    {children}
  </Box>
);
Num.propTypes = { children: PropTypes.node, sx: PropTypes.object };

// A progress bar clamped to 0–100. An empty track when there is no target to measure.
const Bar = ({ pct, height = 3 }) => (
  <Box sx={{ height, bgcolor: DIVIDER, borderRadius: height / 2, overflow: 'hidden' }}>
    <Box
      sx={{
        height: '100%',
        width: `${Math.max(0, Math.min(100, pct || 0))}%`,
        bgcolor: pctColor(pct),
        transition: 'width .3s'
      }}
    />
  </Box>
);
Bar.propTypes = { pct: PropTypes.number, height: PropTypes.number };

const SectionHead = ({ children, right }) => (
  <Box sx={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', mb: 1 }}>
    <Typography sx={{ fontSize: 11, letterSpacing: '0.13em', textTransform: 'uppercase', color: LABEL, fontWeight: 600 }}>
      {children}
    </Typography>
    {right && (
      <Typography sx={{ fontSize: 11, color: LABEL, fontFamily: MONO }}>{right}</Typography>
    )}
  </Box>
);
SectionHead.propTypes = { children: PropTypes.node, right: PropTypes.node };

// §4.1 — qualifies every figure below it, so it sits above them and goes edge to edge.
const LagBanner = ({ dataThrough }) => {
  const days = daysBehind(dataThrough);
  if (days == null) return null;
  const stale = days >= 2;
  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 1,
        px: 2,
        py: 1.25,
        bgcolor: stale ? '#FDF3E0' : DIVIDER,
        borderBottom: `1px solid ${stale ? '#E8CFA0' : BORDER}`
      }}
    >
      {stale && <IconAlertTriangle size={16} style={{ color: '#8A5A00', flexShrink: 0, marginTop: 1 }} />}
      <Typography sx={{ fontSize: 12.5, color: stale ? '#6B4700' : BODY }}>
        Sales data through <Num>{shortDate(dataThrough)}</Num>
        {stale && (
          <>
            {' · '}
            <Num>{days}</Num> days behind. Anything billed since then isn&apos;t counted yet.
          </>
        )}
        {!stale && '.'}
      </Typography>
    </Box>
  );
};
LagBanner.propTypes = { dataThrough: PropTypes.string };

// §4.2 — sales here is the SUM of categories[] (Parts + Pro Parts), measured against the
// dealer's own top-level target. Per §6.1 that target is not the sum of the category
// targets, so this percentage is deliberately not the weighted average of the rows below.
const MonthSummary = ({ month, sales, target }) => {
  const pct = target ? (sales / target) * 100 : null;
  return (
    <Box sx={{ p: 2, borderBottom: `1px solid ${DIVIDER}` }}>
      <Box sx={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', mb: 1 }}>
        <Typography
          sx={{ fontSize: 11, letterSpacing: '0.13em', textTransform: 'uppercase', color: LABEL, fontWeight: 600 }}
        >
          {month} · Parts &amp; Pro Parts
        </Typography>
        <Num sx={{ fontSize: 20, fontWeight: 700, color: pctColor(pct) }}>{pctText(pct)}</Num>
      </Box>
      <Bar pct={pct} height={6} />
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 1.5 }}>
        <Box>
          <Typography sx={{ fontSize: 11, color: LABEL, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Sales
          </Typography>
          <Num sx={{ fontSize: 18, fontWeight: 600, color: INK }}>{inr(sales)}</Num>
        </Box>
        <Box sx={{ textAlign: 'right' }}>
          <Typography sx={{ fontSize: 11, color: LABEL, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Dealer target
          </Typography>
          {target ? (
            <Num sx={{ fontSize: 18, fontWeight: 600, color: INK }}>{inr(target)}</Num>
          ) : (
            <Typography sx={{ fontSize: 15, color: LABEL }}>No target set</Typography>
          )}
        </Box>
      </Box>
    </Box>
  );
};
MonthSummary.propTypes = { month: PropTypes.string, sales: PropTypes.number, target: PropTypes.number };

// §4.3 — one row per category. The chevron is the drill-down affordance; only Parts and
// Pro Parts carry detail (§6.2), so it is shown only where there is something to open.
const CategoryRow = ({ name, sales, target, pct, drillable, onOpen }) => (
  <Box
    onClick={drillable && onOpen ? onOpen : undefined}
    sx={{
      p: 1.75,
      borderBottom: `1px solid ${DIVIDER}`,
      cursor: drillable && onOpen ? 'pointer' : 'default',
      '&:last-of-type': { borderBottom: 'none' },
      '&:hover': drillable && onOpen ? { bgcolor: '#FAF9F6' } : {}
    }}
  >
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
      <Typography sx={{ fontSize: 14.5, fontWeight: 600, color: INK }}>{name}</Typography>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
        <Num sx={{ fontSize: 14.5, fontWeight: 600, color: INK }}>{inr(sales)}</Num>
        {drillable && <IconChevronRight size={15} style={{ color: LABEL }} />}
      </Box>
    </Box>
    <Box sx={{ display: 'flex', justifyContent: 'space-between', mt: 0.25, mb: 0.75 }}>
      <Typography sx={{ fontSize: 12, color: LABEL }}>
        Target <Num>{inr(target)}</Num>
      </Typography>
      {/* Omitted entirely when there is no target — "0% achieved" would be a lie. */}
      {pct != null && (
        <Num sx={{ fontSize: 12, color: pctColor(pct) }}>{pctText(pct)} achieved</Num>
      )}
    </Box>
    <Bar pct={pct} />
  </Box>
);
CategoryRow.propTypes = {
  name: PropTypes.string,
  sales: PropTypes.number,
  target: PropTypes.number,
  pct: PropTypes.number,
  drillable: PropTypes.bool,
  onOpen: PropTypes.func
};

const DealerOverview = ({ dealerId, dealerName, onOpenCategory }) => {
  const [data, setData] = useState(null);
  const [notes, setNotes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!dealerId) {
      setData(null);
      setNotes([]);
      return undefined;
    }
    let live = true;
    setLoading(true);
    setError(null);
    Promise.all([getDealerOverview(dealerId), getDealerNotes(dealerId).catch(() => ({ notes: [] }))])
      .then(([overview, noteRes]) => {
        if (!live) return;
        if (overview && overview.success === false) {
          setError(overview.msg || 'Failed to load dealer overview');
          setData(null);
        } else {
          setData(overview);
          setNotes(noteRes?.notes || []);
        }
      })
      .catch((e) => live && setError(e?.response?.data?.msg || 'Failed to load dealer overview'))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [dealerId]);

  // §4.3 order: categories[] in API order, then any category_sales[] entry not already
  // listed. Matching on name because that is the identity the two lists share.
  const rows = useMemo(() => {
    if (!data) return [];
    const detailed = (data.categories || []).map((c) => ({
      key: `d-${c.category_id}`,
      name: c.category,
      categoryId: c.category_id,
      sales: c.sales,
      target: c.target,
      pct: c.pct,
      drillable: true
    }));
    const seen = new Set(detailed.map((r) => r.name));
    const rest = (data.category_sales || [])
      .filter((c) => !seen.has(c.category))
      .map((c) => ({
        key: `s-${c.category_id}`,
        name: c.category,
        categoryId: c.category_id,
        sales: c.this_month,
        target: c.target,
        pct: c.pct,
        drillable: false
      }));
    return [...detailed, ...rest];
  }, [data]);

  // §4.2 — the combined figure is the sum of the detailed categories, not of every row.
  const combinedSales = useMemo(
    () => (data?.categories || []).reduce((sum, c) => sum + (c.sales || 0), 0),
    [data]
  );

  const lastNote = notes.length ? notes[0] : null;

  if (!dealerId) return null;
  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
        <CircularProgress size={26} />
      </Box>
    );
  }
  if (error) {
    return (
      <Box sx={{ p: 2 }}>
        <Typography color="error">{error}</Typography>
      </Box>
    );
  }
  if (!data) return null;

  return (
    <Box sx={{ bgcolor: PAPER, border: `1px solid ${BORDER}`, borderRadius: 1, overflow: 'hidden' }}>
      <LagBanner dataThrough={data.data_through} />

      <Box sx={{ bgcolor: CARD }}>
        <MonthSummary month={data.month} sales={combinedSales} target={data.target} />
      </Box>

      <Box sx={{ p: 2 }}>
        <SectionHead right={data.month}>By category</SectionHead>
        <Box sx={{ bgcolor: CARD, border: `1px solid ${BORDER}`, borderRadius: 1, overflow: 'hidden' }}>
          {rows.map((r) => (
            <CategoryRow
              key={r.key}
              name={r.name}
              sales={r.sales}
              target={r.target}
              pct={r.pct}
              drillable={r.drillable}
              onOpen={onOpenCategory ? () => onOpenCategory(r) : undefined}
            />
          ))}
          {rows.length === 0 && (
            <Box sx={{ p: 2 }}>
              <Typography sx={{ fontSize: 13, color: LABEL }}>
                No category sales or targets for {dealerName || 'this dealer'} this month.
              </Typography>
            </Box>
          )}
        </Box>
      </Box>

      {/* §4.4 — the whole block, heading included, is omitted when there is no note. */}
      {lastNote && (
        <Box sx={{ px: 2, pb: 2 }}>
          <SectionHead right={shortDate(lastNote.check_in_at)}>Last visit</SectionHead>
          <Box sx={{ bgcolor: CARD, border: `1px solid ${BORDER}`, borderRadius: 1, p: 1.75 }}>
            <Typography sx={{ fontSize: 13.5, color: BODY, whiteSpace: 'pre-wrap' }}>{lastNote.notes}</Typography>
            {lastNote.author && (
              <Typography sx={{ fontSize: 11, color: LABEL, mt: 0.75 }}>— {lastNote.author}</Typography>
            )}
          </Box>
        </Box>
      )}
    </Box>
  );
};

DealerOverview.propTypes = {
  dealerId: PropTypes.number,
  dealerName: PropTypes.string,
  onOpenCategory: PropTypes.func
};

export default DealerOverview;
