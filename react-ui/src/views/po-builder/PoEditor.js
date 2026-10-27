import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControlLabel,
  IconButton,
  InputAdornment,
  InputBase,
  Paper,
  Snackbar,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import {
  IconArrowUp,
  IconCheck,
  IconDownload,
  IconFileImport,
  IconPlus,
  IconLock,
  IconLockOpen,
  IconSearch,
  IconTrash
} from '@tabler/icons';

import poBuilderService, { blobErrorMessage, errorMessage } from '../../services/poBuilderService';
import BulkImportDialog, { SkuPicker } from './BulkImportDialog';
import { basisAmount, money, num, pct, pricePo } from './pricing';

const NO_SCHEME = 'none';

const useStyles = makeStyles((theme) => ({
  muted: { color: theme.palette.text.secondary },
  panel: { marginBottom: theme.spacing(2) },
  panelHead: { padding: theme.spacing(1.5, 2), borderBottom: `1px solid ${theme.palette.divider}` },
  cardHead: { padding: theme.spacing(1.5, 2), background: theme.palette.grey[50], borderBottom: `1px solid ${theme.palette.divider}` },
  cardStats: { display: 'flex', alignItems: 'flex-start', gap: theme.spacing(3) },
  qtyInput: {
    width: 80,
    fontSize: '0.875rem',
    '& input': { textAlign: 'right', padding: '2px 4px', borderBottom: '1px solid transparent' },
    '& input:hover, & input:focus': { borderBottom: `1px solid ${theme.palette.primary.main}` },
    '& input::-webkit-outer-spin-button, & input::-webkit-inner-spin-button': { WebkitAppearance: 'none', margin: 0 },
    '& input[type=number]': { MozAppearance: 'textfield' }
  },
  nowrap: { whiteSpace: 'nowrap' },
  mono: { fontFamily: 'monospace', fontSize: '0.8rem', whiteSpace: 'nowrap' },
  stickyHead: { '& th': { background: theme.palette.background.paper, whiteSpace: 'nowrap' } },
  colHead: { '& th': { fontWeight: 700, color: theme.palette.text.primary, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } },
  footer: { '& td': { fontWeight: 700, fontSize: '0.85rem', color: theme.palette.text.primary } },
  totals: { display: 'flex', flexWrap: 'wrap', gap: theme.spacing(3), padding: theme.spacing(2) }
}));

// The PO being built. `poId` comes from BuildPo; `onNewPo(id)` swaps in a fresh PO when
// this one is discarded or, once finalised, replaced by a new one.
const PoEditor = ({ poId, onNewPo }) => {
  const classes = useStyles();
  const id = String(poId);

  const [view, setView] = useState(null);
  const [toast, setToast] = useState(null);
  const [edits, setEdits] = useState({}); // lineId -> qty string being typed
  const [lineFilter, setLineFilter] = useState('');
  // Scheme group chosen in the filter next to the product dropdown: '' = all, NO_SCHEME, or a scheme no.
  const [groupFilter, setGroupFilter] = useState('');
  const [showCases, setShowCases] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [reviewImportId, setReviewImportId] = useState(null);
  const [busy, setBusy] = useState(false);
  const casesInit = useRef(false);

  const fail = (e, msg) => setToast({ severity: 'error', msg: errorMessage(e, msg) });

  const load = useCallback(() => {
    poBuilderService
      .getPo(id)
      .then((v) => setView(v))
      .catch((e) => setToast({ severity: 'error', msg: errorMessage(e, 'Could not load the PO') }));
  }, [id]);

  useEffect(load, [load]);
  useEffect(() => {
    if (view && !casesInit.current) {
      casesInit.current = true;
      setShowCases(!!view.settings.show_case_helper);
    }
  }, [view]);

  const isDraft = view?.po.status === 'draft';

  // Re-price with the quantities being typed, so the scheme panel moves as you type.
  const priced = useMemo(() => {
    if (!view) return null;
    if (!isDraft) {
      return {
        lines: Object.fromEntries(view.lines.map((l) => [l.id, l])),
        groups: view.summary.groups,
        totals: view.summary.totals
      };
    }
    const lines = view.lines.map((l) => {
      const typed = edits[l.id];
      const q = typed === undefined ? l.qty : Number(typed);
      return { ...l, qty: Number.isFinite(q) && q >= 0 ? q : l.qty };
    });
    return pricePo(lines, view.groups, view.settings);
  }, [view, edits, isDraft]);

  // Stable callbacks (they read the typed quantities through a ref), so a keystroke only
  // re-renders the rows whose numbers actually change — see LineRow.
  const editsRef = useRef(edits);
  editsRef.current = edits;

  const run = useCallback(async (fn, okMsg) => {
    setBusy(true);
    try {
      const res = await fn();
      if (res && res.lines) setView(res);
      if (okMsg) setToast({ severity: 'success', msg: okMsg });
      return res;
    } catch (e) {
      setToast({ severity: 'error', msg: errorMessage(e, 'Something went wrong') });
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const typeQty = useCallback((lineId, value) => setEdits((e) => ({ ...e, [lineId]: value })), []);

  const cancelQty = useCallback(
    (lineId) =>
      setEdits((e) => {
        const n = { ...e };
        delete n[lineId];
        return n;
      }),
    []
  );

  const saveQty = useCallback(
    async (line) => {
      const typed = editsRef.current[line.id];
      if (typed === undefined) return;
      const q = Number(typed);
      if (!Number.isFinite(q) || q < 0) {
        setToast({ severity: 'warning', msg: 'Qty must be 0 or more — use the bin icon to remove a line.' });
        cancelQty(line.id);
        return;
      }
      if (q === line.qty) {
        cancelQty(line.id);
        return;
      }
      const res = await run(() => poBuilderService.setQty(id, line.id, q));
      if (res) cancelQty(line.id);
    },
    [id, run, cancelQty]
  );

  const roundUp = useCallback(
    (line) => {
      const q = Math.ceil(line.qty / line.spu) * line.spu;
      run(() => poBuilderService.setQty(id, line.id, q), `${line.sku_code}: rounded up to ${num(q)}`);
    },
    [id, run]
  );

  const deleteLine = useCallback(
    (line) => run(() => poBuilderService.deleteLine(id, line.id), `${line.sku_code} removed`),
    [id, run]
  );

  const exportOrderBook = async () => {
    setBusy(true);
    try {
      await poBuilderService.exportOrderBook(id);
    } catch (e) {
      setToast({ severity: 'error', msg: await blobErrorMessage(e, 'Export failed') });
    } finally {
      setBusy(false);
    }
  };

  // Discard (a draft) or move on from (a finalised PO) to a fresh draft.
  const startNew = async (discard) => {
    // eslint-disable-next-line no-alert
    if (discard && !window.confirm(`Discard draft ${view.po.po_no} and all its lines, and start a new PO?`)) return;
    setBusy(true);
    try {
      if (discard) await poBuilderService.deletePo(id);
      const res = await poBuilderService.createPo({});
      onNewPo(res.id);
    } catch (e) {
      fail(e, 'Could not start a new PO');
      setBusy(false);
    }
  };

  const saveHeader = (field, value) => {
    if (!view || view.po[field] === value) return;
    run(() => poBuilderService.updatePo(id, { [field]: value }));
  };

  if (!view || !priced) {
    return (
      <Box p={6} textAlign="center">
        {toast ? <Alert severity="error">{toast.msg}</Alert> : <CircularProgress />}
      </Box>
    );
  }

  const { po } = view;
  // Lines grouped by scheme group (scheme_no is set on draft and finalised lines alike).
  const term = lineFilter.trim().toLowerCase();
  const matches = (l) => !term || `${l.sku_code} ${l.description}`.toLowerCase().includes(term);
  const linesByGroup = {};
  view.lines.forEach((l) => {
    const k = l.scheme_no || NO_SCHEME;
    if (!linesByGroup[k]) linesByGroup[k] = [];
    linesByGroup[k].push(l);
  });
  const noSchemeLines = linesByGroup[NO_SCHEME] || [];
  const noSchemeValue = noSchemeLines.reduce((s, l) => s + (priced.lines[l.id]?.line_value || 0), 0);
  const cards = [
    ...priced.groups.map((g) => ({ key: g.scheme_no, g, lines: (linesByGroup[g.scheme_no] || []).filter(matches) })),
    ...(noSchemeLines.length ? [{ key: NO_SCHEME, g: null, lines: noSchemeLines.filter(matches) }] : [])
  ]
    .filter((c) => !groupFilter || c.key === groupFilter)
    .filter((c) => c.lines.length > 0);
  const rowProps = {
    priced,
    edits,
    showCases,
    isDraft,
    busy,
    classes,
    onType: typeQty,
    onSave: saveQty,
    onCancel: cancelQty,
    onRoundUp: roundUp,
    onDelete: deleteLine
  };
  // Imports whose review was closed without adding its matched rows.
  const notAdded = view.imports.filter((i) => i.status === 'review' && i.ready > 0);
  const t = priced.totals;

  return (
    <Box>
      {/* ---------------- header ---------------- */}
      <Box display="flex" alignItems="flex-start" justifyContent="space-between" flexWrap="wrap" style={{ gap: 12 }} mb={2}>
        <Box display="flex" alignItems="center" style={{ gap: 8 }}>
          <Box>
            <Box display="flex" alignItems="center" style={{ gap: 8 }}>
              <Typography variant="h3">{po.po_no}</Typography>
              <Chip size="small" label={po.status} color={isDraft ? 'default' : 'success'} />
            </Box>
            <Typography variant="body2" className={classes.muted}>
              {po.scheme ? (
                <>
                  Scheme <b>{po.scheme.name}</b>
                </>
              ) : (
                <b style={{ color: '#b45309' }}>No scheme uploaded — every line is at 0% scheme</b>
              )}
              {' · '}SKU master <b>{po.master?.name}</b>
              {!isDraft && ` · finalised by ${po.finalised_by} on ${(po.finalised_on || '').slice(0, 10)}`}
            </Typography>
          </Box>
        </Box>
        <Box display="flex" flexWrap="wrap" style={{ gap: 8 }}>
          {isDraft && (
            <Button variant="outlined" startIcon={<IconFileImport size={16} />} onClick={() => setImportOpen(true)} disabled={busy}>
              Bulk add
            </Button>
          )}
          <Button variant="outlined" startIcon={<IconDownload size={16} />} onClick={exportOrderBook} disabled={busy || !view.lines.length}>
            Order Book (.xlsx)
          </Button>
          {isDraft ? (
            <Button
              variant="contained"
              color="success"
              startIcon={<IconLock size={16} />}
              disabled={busy || !view.lines.length || Object.keys(edits).length > 0}
              onClick={() => run(() => poBuilderService.finalise(id), 'PO finalised — prices and scheme % are now frozen.')}
            >
              Finalise
            </Button>
          ) : (
            <>
              <Button variant="outlined" startIcon={<IconLockOpen size={16} />} disabled={busy} onClick={() => run(() => poBuilderService.reopen(id), 'Reopened as draft')}>
                Reopen
              </Button>
              <Button variant="contained" startIcon={<IconPlus size={16} />} disabled={busy} onClick={() => startNew(false)}>
                Start new PO
              </Button>
            </>
          )}
          {isDraft && (
            <Tooltip title="Discard this draft and start a new PO">
              <IconButton disabled={busy} onClick={() => startNew(true)}>
                <IconTrash size={18} />
              </IconButton>
            </Tooltip>
          )}
        </Box>
      </Box>

      {/* ---------------- PO details ---------------- */}
      <Paper variant="outlined" className={classes.panel} style={{ padding: 16 }}>
        <Box display="flex" flexWrap="wrap" style={{ gap: 16 }}>
          <TextField
            size="small"
            type="date"
            label="PO date"
            InputLabelProps={{ shrink: true }}
            defaultValue={po.po_date}
            key={`d${po.po_date}`}
            disabled={!isDraft}
            onBlur={(e) => e.target.value && saveHeader('po_date', e.target.value)}
          />
          <TextField size="small" label="Title" defaultValue={po.title} key={`t${po.title}`} disabled={!isDraft} onBlur={(e) => saveHeader('title', e.target.value)} style={{ minWidth: 240 }} />
          <TextField size="small" label="Remarks (Order Book)" defaultValue={po.remarks} key={`r${po.remarks}`} disabled={!isDraft} onBlur={(e) => saveHeader('remarks', e.target.value)} style={{ minWidth: 240 }} />
        </Box>
        {po.newer_master && isDraft && (
          <Alert severity="info" style={{ marginTop: 12 }}>
            A newer SKU master ({po.newer_master.name}) has been uploaded. This draft keeps the MRPs of <b>{po.master?.name}</b>, which was current when it was started.
          </Alert>
        )}
      </Paper>

      {notAdded.map((i) => (
        <Alert
          key={i.id}
          severity="warning"
          className={classes.panel}
          action={
            <Button color="inherit" size="small" onClick={() => setReviewImportId(i.id)}>
              Review
            </Button>
          }
        >
          <b>{i.source_tag}</b>: {i.ready} matched row(s) were read but not added to the PO yet.
        </Alert>
      ))}

      {isDraft && view.unrecognised.length > 0 && (
        <UnrecognisedCodes poId={id} rows={view.unrecognised} onView={setView} onReload={load} onError={fail} />
      )}

      {isDraft && <SearchAdd poId={id} onAdded={(v) => setView(v)} onError={fail} onGroupChange={setGroupFilter} />}

      {/* ---------------- lines, one card per scheme group ---------------- */}
      <Paper variant="outlined" className={classes.panel}>
        <Box className={classes.panelHead} display="flex" alignItems="center" flexWrap="wrap" style={{ gap: 12, borderBottom: 0 }}>
          <TextField
            size="small"
            placeholder="Filter lines…"
            value={lineFilter}
            onChange={(e) => setLineFilter(e.target.value)}
            InputProps={{ startAdornment: <InputAdornment position="start"><IconSearch size={16} /></InputAdornment> }}
          />
          <Box flexGrow={1} />
          <FormControlLabel
            control={<Switch size="small" checked={showCases} onChange={(e) => setShowCases(e.target.checked)} />}
            label={<Typography variant="body2">Show SPU / case equivalents</Typography>}
          />
        </Box>
      </Paper>

      {cards.map((c) => (
        <GroupCard key={c.key} g={c.g} lines={c.lines} rowProps={rowProps} />
      ))}
      {!cards.length && (
        <Paper variant="outlined" className={classes.panel} style={{ padding: 24, textAlign: 'center' }}>
          <Typography className={classes.muted}>
            {groupFilter
              ? `No lines in ${groupFilter === NO_SCHEME ? 'this group' : groupFilter} yet — pick a product above to add one.`
              : view.lines.length
              ? 'No lines match the filter.'
              : 'No lines yet — pick a product above or use Bulk add.'}
          </Typography>
        </Paper>
      )}

      <Paper variant="outlined" className={classes.panel}>
        <Box className={classes.totals}>
          <Total label="SKUs" value={num(t.line_count)} />
          <Total label="Value before scheme" value={money(t.pre_scheme_value)} />
          <Total label="Total scheme saving" value={money(t.scheme_saving)} color="#15803d" />
          <Total label="Total value (pre-GST)" value={money(t.value)} />
          <Total label="Grand total (incl. GST)" value={money(t.grand_total)} strong />
          {noSchemeValue > 0 && <Total label="of which not in any scheme" value={money(noSchemeValue)} muted />}
        </Box>
      </Paper>

      {(importOpen || reviewImportId) && (
        <BulkImportDialog
          poId={id}
          importId={reviewImportId}
          onClose={() => {
            setImportOpen(false);
            setReviewImportId(null);
            load();
          }}
          onApplied={(v, msg) => {
            if (v) setView(v);
            setToast({ severity: 'success', msg });
          }}
        />
      )}

      <Snackbar open={!!toast} autoHideDuration={6000} onClose={() => setToast(null)}>
        {toast ? (
          <Alert severity={toast.severity} onClose={() => setToast(null)}>
            {toast.msg}
          </Alert>
        ) : (
          <span />
        )}
      </Snackbar>
    </Box>
  );
};

// One scheme group: its group-level figures once in the header, then only its lines.
// `g` is null for the card of lines that are in no scheme group.
const GroupCard = ({ g, lines, rowProps }) => {
  const { classes, priced, edits, showCases, isDraft } = rowProps;
  return (
    <Paper variant="outlined" className={classes.panel}>
      <Box className={classes.cardHead}>
        <Box display="flex" justifyContent="space-between" alignItems="flex-start" style={{ gap: 16 }}>
          <Box minWidth={0}>
            <Box display="flex" alignItems="center" style={{ gap: 8 }}>
              <Typography variant="h4">{g ? g.scheme_no : 'Not in any scheme group'}</Typography>
            </Box>
            {g && (
              <Typography variant="body2" className={classes.muted}>
                {g.name}
              </Typography>
            )}
          </Box>
          {g && (
            <Box className={classes.cardStats} flexShrink={0} textAlign="right">
              <CardStat label="Current total" value={basisAmount(g.basis, g.total)} />
              {(g.slabs || []).map((s) => {
                const reached = g.total + 1e-9 >= s.min_threshold;
                const applied = reached && s.slab_no === g.slab_no;
                return (
                  <CardStat
                    key={s.slab_no}
                    label={pct(s.discount_pct)}
                    value={basisAmount(g.basis, s.min_threshold)}
                    strong={applied}
                    color={reached ? '#15803d' : undefined}
                    title={applied ? 'Slab applied' : reached ? 'Reached' : `${basisAmount(g.basis, s.min_threshold - g.total)} more to reach`}
                  />
                );
              })}
            </Box>
          )}
        </Box>
      </Box>
      <TableContainer>
        {/* Fixed layout + the same column widths in every card, so columns line up from
            one scheme group to the next whatever each card's content is. */}
        <Table size="small" style={{ tableLayout: 'fixed', minWidth: 880 }}>
          <colgroup>
            <col style={{ width: 170 }} />
            <col />
            <col style={{ width: 90 }} />
            {showCases && <col style={{ width: 90 }} />}
            <col style={{ width: 150 }} />
            <col style={{ width: 90 }} />
            <col style={{ width: 140 }} />
            <col style={{ width: 170 }} />
            {isDraft && <col style={{ width: 48 }} />}
          </colgroup>
          <TableHead className={classes.colHead}>
            <TableRow>
              <TableCell>SKU</TableCell>
              <TableCell>Description</TableCell>
              <TableCell align="right">Qty</TableCell>
              {showCases && <TableCell align="right">Cases</TableCell>}
              <TableCell align="right">After std. discount</TableCell>
              <TableCell align="right">Scheme %</TableCell>
              <TableCell align="right">After scheme</TableCell>
              <TableCell align="right">Line total (incl. GST)</TableCell>
              {isDraft && <TableCell />}
            </TableRow>
          </TableHead>
          <TableBody>
            {lines.map((l) => (
              <LineRow
                key={l.id}
                l={l}
                p={priced.lines[l.id]}
                typed={edits[l.id]}
                showCases={showCases}
                isDraft={isDraft}
                busy={rowProps.busy}
                classes={classes}
                onType={rowProps.onType}
                onSave={rowProps.onSave}
                onCancel={rowProps.onCancel}
                onRoundUp={rowProps.onRoundUp}
                onDelete={rowProps.onDelete}
              />
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
};

const CardStat = ({ label, value, strong, color, title }) => (
  <Box title={title}>
    <Typography variant="caption" display="block" style={{ color: color || '#6b7280', fontWeight: strong ? 700 : 400 }}>
      {label}
    </Typography>
    <Typography variant="body2" style={{ fontWeight: strong ? 700 : 500, whiteSpace: 'nowrap', color }}>
      {value}
    </Typography>
  </Box>
);

const PRICE_KEYS = ['pre_scheme_value', 'scheme_pct', 'line_value', 'gst', 'line_total'];

// One PO line. Memoised on its values: typing a qty re-prices the whole PO, but only the
// rows of the scheme group whose slab moved (and the row being typed in) re-render.
const LineRow = React.memo(
  function LineRow({ l, p = {}, typed, showCases, isDraft, busy, classes, onType, onSave, onCancel, onRoundUp, onDelete }) {
    const qtyNow = typed === undefined ? l.qty : Number(typed) || 0;
    const cases = l.spu ? qtyNow / l.spu : null;
    return (
      <TableRow hover>
        <TableCell className={classes.mono} style={{ overflow: 'hidden', textOverflow: 'ellipsis' }} title={l.sku_code}>
          {l.sku_code}
        </TableCell>
        <TableCell>
          <Tooltip title={`${l.description}${l.category ? ` · ${l.category}` : ''}`}>
            <Typography variant="body2" noWrap>
              {l.description}
            </Typography>
          </Tooltip>
        </TableCell>
        <TableCell align="right" className={classes.nowrap}>
          {isDraft ? (
            <InputBase
              type="number"
              className={classes.qtyInput}
              value={typed === undefined ? l.qty : typed}
              onChange={(e) => onType(l.id, e.target.value)}
              onBlur={() => onSave(l)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') e.target.blur();
                if (e.key === 'Escape') onCancel(l.id);
              }}
            />
          ) : (
            num(l.qty)
          )}
        </TableCell>
        {showCases && (
          <TableCell align="right" className={classes.nowrap}>
            {cases === null ? '—' : num(Math.round(cases * 100) / 100)}
            {isDraft && cases !== null && !Number.isInteger(Math.round(cases * 1000) / 1000) && (
              <Tooltip title={`Round up to ${num(Math.ceil(cases) * l.spu)} (${Math.ceil(cases)} full case${Math.ceil(cases) === 1 ? '' : 's'})`}>
                <span>
                  <IconButton size="small" onClick={() => onRoundUp(l)} disabled={busy || typed !== undefined}>
                    <IconArrowUp size={14} />
                  </IconButton>
                </span>
              </Tooltip>
            )}
          </TableCell>
        )}
        <TableCell align="right">{money(p.pre_scheme_value)}</TableCell>
        <TableCell align="right">{pct(p.scheme_pct)}</TableCell>
        <TableCell align="right">{money(p.line_value)}</TableCell>
        <TableCell align="right" style={{ fontWeight: 600 }}>
          {money(p.line_total)}
        </TableCell>
        {isDraft && (
          <TableCell>
            <IconButton size="small" disabled={busy} onClick={() => onDelete(l)}>
              <IconTrash size={16} />
            </IconButton>
          </TableCell>
        )}
      </TableRow>
    );
  },
  (a, b) =>
    a.l === b.l &&
    a.typed === b.typed &&
    a.showCases === b.showCases &&
    a.isDraft === b.isDraft &&
    a.busy === b.busy &&
    a.classes === b.classes &&
    a.onSave === b.onSave &&
    PRICE_KEYS.every((k) => (a.p || {})[k] === (b.p || {})[k])
);

// Codes from bulk imports that could not be settled on one SKU. Each stays here — not in
// the PO and not lost — until it is added under the SKU you pick, or dismissed.
const UnrecognisedCodes = ({ poId, rows, onView, onReload, onError }) => {
  const [picked, setPicked] = useState({}); // rowId -> sku item
  const [qtys, setQtys] = useState({}); // rowId -> qty string
  const [busyRow, setBusyRow] = useState(null);

  const add = async (r) => {
    const sku = picked[r.id];
    if (!sku) return;
    setBusyRow(r.id);
    try {
      onView(await poBuilderService.addImportRow(poId, r.import_id, r.id, sku.sku_code, qtys[r.id] || undefined));
    } catch (e) {
      onError(e, 'Could not add the row');
    } finally {
      setBusyRow(null);
    }
  };

  const dismiss = async (r) => {
    setBusyRow(r.id);
    try {
      await poBuilderService.resolveRow(poId, r.import_id, r.id, { dismiss: true });
      onReload();
    } catch (e) {
      onError(e, 'Could not dismiss');
    } finally {
      setBusyRow(null);
    }
  };

  return (
    <Paper variant="outlined" style={{ marginBottom: 16, borderColor: '#f59e0b' }}>
      <Box px={2} py={1.5} style={{ borderBottom: '1px solid #fde68a', background: '#fffbeb' }}>
        <Typography variant="h5">Codes not recognised ({rows.length})</Typography>
        <Typography variant="body2" color="textSecondary">
          These rows from your lists are <b>not in the PO</b>. Pick the right SKU (suggestions first, or type to search) and add it, or dismiss the row. The PO cannot be finalised while
          any are left.
        </Typography>
      </Box>
      <TableContainer style={{ maxHeight: 420 }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell>From</TableCell>
              <TableCell>Code in list</TableCell>
              <TableCell>Finish</TableCell>
              <TableCell>Why</TableCell>
              <TableCell style={{ minWidth: 320 }}>SKU</TableCell>
              <TableCell align="right">Qty</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id} hover>
                <TableCell style={{ fontSize: 12 }}>
                  {r.source_tag}
                  <Typography variant="caption" display="block" color="textSecondary">
                    row {r.row_no}
                  </Typography>
                </TableCell>
                <TableCell style={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                  {r.raw_code}
                  {r.raw_desc && (
                    <Typography variant="caption" display="block" color="textSecondary" noWrap style={{ maxWidth: 220, fontFamily: 'inherit' }}>
                      {r.raw_desc}
                    </Typography>
                  )}
                </TableCell>
                <TableCell>{r.raw_finish || '—'}</TableCell>
                <TableCell style={{ fontSize: 12 }}>{r.reason}</TableCell>
                <TableCell>
                  <SkuPicker
                    poId={poId}
                    options={r.candidates}
                    value={picked[r.id] || null}
                    disabled={busyRow === r.id}
                    onPick={(s) => setPicked({ ...picked, [r.id]: s })}
                  />
                </TableCell>
                <TableCell align="right">
                  <TextField
                    size="small"
                    type="number"
                    style={{ width: 90 }}
                    value={qtys[r.id] !== undefined ? qtys[r.id] : r.qty || ''}
                    error={r.match_status === 'bad_qty' && !(Number(qtys[r.id]) > 0)}
                    onChange={(e) => setQtys({ ...qtys, [r.id]: e.target.value })}
                  />
                </TableCell>
                <TableCell style={{ whiteSpace: 'nowrap' }}>
                  <Button
                    size="small"
                    variant="contained"
                    disabled={busyRow === r.id || !picked[r.id] || Number(qtys[r.id] !== undefined ? qtys[r.id] : r.qty) < 0}
                    onClick={() => add(r)}
                  >
                    Add to PO
                  </Button>
                  <Button size="small" color="inherit" disabled={busyRow === r.id} onClick={() => dismiss(r)}>
                    Dismiss
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
};

const Total = ({ label, value, strong, color, muted }) => (
  <Box>
    <Typography variant="caption" color="textSecondary">
      {label}
    </Typography>
    <Typography variant={strong ? 'h4' : 'h5'} style={{ color: color || (muted ? '#6b7280' : undefined) }}>
      {value}
    </Typography>
  </Box>
);

// Searchable product dropdown over the PO's SKU master. Opening it lists products straight
// away (browse, optionally within one scheme group); typing filters by code or description.
// The chosen scheme group also narrows the PO page to that group's card (onGroupChange).
const BROWSE_LIMIT = 200;
const productLabel = (o) => `${o.sku_code} — ${o.description}`;

// Module-level on purpose: this MUI version resets an Autocomplete's typed text whenever
// its getOptionLabel changes identity, i.e. on every render if defined inline.
const groupLabel = (o) => (o.id === 'none' ? o.name : `${o.scheme_no} · ${o.category || '—'}`);
const sameGroup = (o, v) => String(o.id) === String(v.id);
const filterGroups = (opts, { inputValue }) => {
  const words = inputValue.toLowerCase().split(/\s+/).filter(Boolean);
  return opts.filter((o) => words.every((w) => `${o.scheme_no} ${o.category} ${o.name}`.toLowerCase().includes(w)));
};

const SearchAdd = ({ poId, onAdded, onError, onGroupChange }) => {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const [group, setGroup] = useState('');
  const [groupOpts, setGroupOpts] = useState({ groups: [], none_count: null });
  const [options, setOptions] = useState([]);
  const [total, setTotal] = useState(null);
  const [loading, setLoading] = useState(false);
  const [picked, setPicked] = useState(null);
  const [qty, setQty] = useState('');
  const qtyRef = useRef(null);

  useEffect(() => {
    poBuilderService
      .groupOptions(poId)
      .then((r) => setGroupOpts(r))
      .catch(() => setGroupOpts({ groups: [], none_count: null }));
  }, [poId]);

  // The text typed, or nothing while the box just shows the picked product.
  const query = picked && input === productLabel(picked) ? '' : input.trim();

  useEffect(() => {
    if (!open) return undefined;
    setLoading(true);
    const timer = setTimeout(() => {
      poBuilderService
        .search(poId, query, group, BROWSE_LIMIT)
        .then((r) => {
          setOptions(r.results);
          setTotal(r.total);
        })
        .catch(() => setOptions([]))
        .finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(timer);
  }, [open, query, group, poId]);

  // Qty is optional here: blank adds the line at 0, to be filled in on the line later.
  const add = async () => {
    const q = qty === '' ? 0 : Number(qty);
    if (!picked || !(q >= 0)) return;
    try {
      const v = await poBuilderService.addLine(poId, picked.sku_code, q);
      onAdded(v);
      setPicked(null);
      setInput('');
      setQty('');
    } catch (e) {
      onError(e, 'Could not add the line');
    }
  };

  const browsing = !query;
  const groupList = [
    ...groupOpts.groups,
    ...(groupOpts.none_count ? [{ id: 'none', scheme_no: '', category: '', name: 'Not in any scheme group', count: groupOpts.none_count }] : [])
  ];
  return (
    <Paper variant="outlined" style={{ padding: 16, marginBottom: 16 }}>
      <Box display="flex" alignItems="flex-start" flexWrap="wrap" style={{ gap: 12 }}>
        <Autocomplete
          style={{ width: 320 }}
          size="small"
          options={groupList}
          value={groupList.find((o) => String(o.id) === String(group)) || null}
          onChange={(_, o) => {
            setGroup(o ? o.id : '');
            onGroupChange(!o ? '' : o.id === 'none' ? NO_SCHEME : o.scheme_no);
          }}
          getOptionLabel={groupLabel}
          isOptionEqualToValue={sameGroup}
          filterOptions={filterGroups}
          noOptionsText="No scheme group matches"
          ListboxProps={{ style: { maxHeight: 420 } }}
          renderOption={(props, o) => (
            <li {...props} key={o.id}>
              <Box>
                {o.id === 'none' ? (
                  <b>{o.name}</b>
                ) : (
                  <>
                    <b>{o.scheme_no}</b> · {o.category || '—'}
                  </>
                )}
                {o.id !== 'none' && (
                  <Typography variant="caption" display="block" color="textSecondary">
                    {o.name}
                  </Typography>
                )}
              </Box>
            </li>
          )}
          renderInput={(params) => (
            <TextField {...params} label="Scheme group + category" placeholder="All scheme groups" helperText=" " InputLabelProps={{ shrink: true }} />
          )}
        />
        <Autocomplete
          style={{ flex: '1 1 420px' }}
          open={open}
          onOpen={() => setOpen(true)}
          onClose={() => setOpen(false)}
          openOnFocus
          options={options}
          loading={loading}
          filterOptions={(x) => x}
          groupBy={browsing ? (o) => o.category || '(no category)' : undefined}
          value={picked}
          inputValue={input}
          onInputChange={(_, v) => setInput(v)}
          onChange={(_, v) => {
            setPicked(v);
            if (v) setTimeout(() => qtyRef.current && qtyRef.current.focus(), 0);
          }}
          getOptionLabel={productLabel}
          isOptionEqualToValue={(o, v) => o.sku_code === v.sku_code}
          noOptionsText="No active SKU matches"
          renderOption={(props, o) => (
            <li {...props} key={o.sku_code}>
              <Box width="100%">
                <Box display="flex" justifyContent="space-between" style={{ gap: 8 }}>
                  <b style={{ fontFamily: 'monospace' }}>{o.sku_code}</b>
                  <span>{money(o.mrp)}</span>
                </Box>
                <Typography variant="caption" color="textSecondary">
                  {o.description}
                </Typography>
              </Box>
            </li>
          )}
          renderInput={(params) => (
            <TextField
              {...params}
              size="small"
              label="Product"
              helperText={
                open && total !== null && total > options.length
                  ? `Showing ${num(options.length)} of ${num(total)} — type or pick a scheme group to narrow the list`
                  : ' '
              }
            />
          )}
        />
        <TextField
          inputRef={qtyRef}
          size="small"
          type="number"
          label={picked ? `Qty (${picked.uom || 'units'})` : 'Qty'}
          value={qty}
          onChange={(e) => setQty(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          style={{ width: 130 }}
          helperText={picked ? `SPU ${num(picked.spu)}` : ' '}
        />
        <Button variant="contained" startIcon={<IconCheck size={16} />} disabled={!picked || Number(qty) < 0} onClick={add}>
          Add
        </Button>
      </Box>
    </Paper>
  );
};

export default PoEditor;
