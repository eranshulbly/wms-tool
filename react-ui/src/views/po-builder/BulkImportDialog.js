import React, { useEffect, useState } from 'react';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Typography
} from '@material-ui/core';
import { IconFileSpreadsheet } from '@tabler/icons';

import poBuilderService, { errorMessage } from '../../services/poBuilderService';
import { money, num } from './pricing';

// Bulk add: a file (CSV / Excel) or cells pasted from a sheet → a review screen that
// sorts every row into Matched / Needs choice / Unmatched before anything reaches the
// PO. Rows that cannot be matched are listed on the PO page ("Codes not recognised")
// until they are added under the right SKU or dismissed — never dropped.

const STATUS_LABEL = {
  exact: 'Exact code',
  finish_added: 'Finish added',
  base_single: 'Only finish',
  needs_choice: 'Pick a finish',
  fuzzy: 'Suggestion',
  unmatched: 'Not found',
  bad_qty: 'Bad qty',
  dismissed: 'Dismissed'
};

const TABS = [
  { key: 'matched', label: 'Matched' },
  { key: 'needs_choice', label: 'Needs choice' },
  { key: 'unmatched', label: 'Unmatched' },
  { key: 'applied', label: 'Already in PO' },
  { key: 'dismissed', label: 'Dismissed' }
];

const BulkImportDialog = ({ poId, importId, onClose, onApplied }) => {
  const [step, setStep] = useState(importId ? 'review' : 'input');
  const [mode, setMode] = useState('file');
  const [file, setFile] = useState(null);
  const [text, setText] = useState('');
  const [sheet, setSheet] = useState('');
  const [sheets, setSheets] = useState([]);
  const [data, setData] = useState(null);
  const [tab, setTab] = useState('needs_choice');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const pickTab = (d) => {
    const c = d.counts || {};
    setTab(c.needs_choice ? 'needs_choice' : c.unmatched ? 'unmatched' : c.matched ? 'matched' : 'applied');
  };

  useEffect(() => {
    if (!importId) return;
    poBuilderService
      .getImport(poId, importId)
      .then((d) => {
        setData(d);
        pickTab(d);
      })
      .catch((e) => setError(errorMessage(e, 'Could not load the import')));
  }, [poId, importId]);

  const read = async () => {
    setBusy(true);
    setError(null);
    try {
      const d = await poBuilderService.createImport(poId, {
        file: mode === 'file' ? file : undefined,
        text: mode === 'paste' ? text : undefined,
        sheet: sheet || undefined
      });
      setData(d);
      setSheets(d.sheets || []);
      pickTab(d);
      setStep('review');
    } catch (e) {
      setError(errorMessage(e, 'Could not read the list'));
    } finally {
      setBusy(false);
    }
  };

  // Re-read the same file from another sheet: discard this review and import again.
  const switchSheet = async (name) => {
    setSheet(name);
    if (!data) return;
    setBusy(true);
    try {
      await poBuilderService.discardImport(poId, data.import.id);
      const d = await poBuilderService.createImport(poId, { file, sheet: name });
      setData(d);
      pickTab(d);
    } catch (e) {
      setError(errorMessage(e, 'Could not read that sheet'));
    } finally {
      setBusy(false);
    }
  };

  const resolve = async (row, body) => {
    setBusy(true);
    setError(null);
    try {
      const d = await poBuilderService.resolveRow(poId, data.import.id, row.id, body);
      setData(d);
    } catch (e) {
      setError(errorMessage(e, 'Could not update the row'));
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await poBuilderService.applyImport(poId, data.import.id);
      const r = res.result;
      onApplied(
        res,
        `${r.applied_rows} row(s) added to ${r.lines_touched} line(s)` +
          (r.left ? ` — ${r.left} code(s) not recognised are listed on the PO.` : '.')
      );
      onClose();
    } catch (e) {
      setError(errorMessage(e, 'Could not add the rows'));
    } finally {
      setBusy(false);
    }
  };

  const discard = async () => {
    setBusy(true);
    try {
      await poBuilderService.discardImport(poId, data.import.id);
      onClose();
    } catch (e) {
      setError(errorMessage(e, 'Could not discard'));
      setBusy(false);
    }
  };

  const counts = data?.counts || {};
  const rows = data ? data.rows.filter((r) => r.bucket === tab) : [];
  const ready = counts.matched || 0;

  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="lg" fullWidth>
      <DialogTitle>
        {step === 'input' ? 'Bulk add products' : 'Review import'}
      </DialogTitle>
      <DialogContent dividers style={{ minHeight: 420 }}>
        {error && (
          <Alert severity="error" style={{ marginBottom: 12 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {step === 'input' && (
          <Box>
            <Tabs value={mode} onChange={(_, v) => setMode(v)}>
              <Tab value="file" label="Upload a file" />
              <Tab value="paste" label="Paste from a sheet" />
            </Tabs>
            {mode === 'file' ? (
              <Box mt={2}>
                <label htmlFor="pob-import-file">
                  <input
                    id="pob-import-file"
                    type="file"
                    accept=".xlsx,.xls,.csv"
                    style={{ display: 'none' }}
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                  />
                  <Box border="2px dashed #c4cdd5" borderRadius={2} p={3} textAlign="center" style={{ cursor: 'pointer', background: '#fafbfc' }}>
                    <IconFileSpreadsheet size={28} />
                    <Typography variant="body2" color="textSecondary">
                      A CSV or Excel file with columns <b>SKU Code</b> and <b>Quantity</b>, and optionally <b>Finish</b>. The first
                      sheet with these headers is used — you can switch sheet on the next screen.
                    </Typography>
                    {file && (
                      <Typography variant="body2" style={{ marginTop: 6, fontFamily: 'monospace' }}>
                        {file.name}
                      </Typography>
                    )}
                    <Button component="span" size="small" style={{ marginTop: 8 }}>
                      Browse
                    </Button>
                  </Box>
                </label>
              </Box>
            ) : (
              <TextField
                multiline
                minRows={10}
                fullWidth
                margin="normal"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={'Paste columns copied from Excel / Google Sheets: SKU code, quantity and (optional) finish.\nA header row (SKU Code, Quantity, Finish) is optional.\n\nCDSS250-SP\t5\tZW\nHTD1-SC-NP\t4'}
                inputProps={{ style: { fontFamily: 'monospace', fontSize: 13 } }}
              />
            )}
          </Box>
        )}

        {step === 'review' && !data && (
          <Box p={6} textAlign="center">
            <CircularProgress />
          </Box>
        )}

        {step === 'review' && data && (
          <Box>
            <Box display="flex" flexWrap="wrap" alignItems="center" style={{ gap: 12 }} mb={1}>
              <Typography variant="body2" color="textSecondary">
                {data.import.filename}
                {data.import.sheet_name && ` · sheet “${data.import.sheet_name}”`} · read{' '}
                {Object.entries(data.import.columns_used)
                  .map(([k, v]) => `${k} from “${v}”`)
                  .join(', ')}{' '}
                · {data.import.row_count} rows
              </Typography>
              {sheets.length > 1 && file && (
                <TextField select size="small" label="Sheet" value={sheet || data.import.sheet_name} onChange={(e) => switchSheet(e.target.value)} disabled={busy || (counts.applied || 0) > 0}>
                  {sheets.map((s) => (
                    <MenuItem key={s} value={s}>
                      {s}
                    </MenuItem>
                  ))}
                </TextField>
              )}
            </Box>
            <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable">
              {TABS.filter((t) => t.key !== 'applied' || counts.applied).map((t) => (
                <Tab
                  key={t.key}
                  value={t.key}
                  label={
                    <Box display="flex" alignItems="center" style={{ gap: 6 }}>
                      {t.label}
                      <Chip
                        size="small"
                        label={counts[t.key] || 0}
                        color={t.key === 'matched' ? 'success' : (counts[t.key] || 0) && t.key !== 'dismissed' && t.key !== 'applied' ? 'warning' : 'default'}
                      />
                    </Box>
                  }
                />
              ))}
            </Tabs>
            <TableContainer style={{ maxHeight: 420 }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell>Row</TableCell>
                    <TableCell>Code in list</TableCell>
                    <TableCell>Finish</TableCell>
                    <TableCell align="right">Qty</TableCell>
                    <TableCell>How it matched</TableCell>
                    <TableCell style={{ minWidth: 340 }}>SKU</TableCell>
                    <TableCell />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.map((r) => (
                    <ImportRow key={r.id} row={r} poId={poId} busy={busy} readOnly={r.applied} onResolve={(body) => resolve(r, body)} />
                  ))}
                  {!rows.length && (
                    <TableRow>
                      <TableCell colSpan={7} align="center" style={{ padding: 24, color: '#6b7280' }}>
                        Nothing here.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        {step === 'input' ? (
          <>
            <Button onClick={onClose}>Cancel</Button>
            <Button
              variant="contained"
              disabled={busy || (mode === 'file' ? !file : !text.trim())}
              onClick={read}
              startIcon={busy ? <CircularProgress size={16} /> : null}
            >
              Read &amp; match
            </Button>
          </>
        ) : (
          <>
            {data && !(counts.applied || 0) && (
              <Button color="error" onClick={discard} disabled={busy}>
                Discard import
              </Button>
            )}
            <Box flexGrow={1} />
            <Typography variant="body2" color="textSecondary" style={{ marginRight: 12 }}>
              {(counts.needs_choice || 0) + (counts.unmatched || 0)} row(s) need a decision — pick them here, or add the matched rows now and they will be listed on the PO.
            </Typography>
            <Button onClick={onClose} disabled={busy}>
              Close
            </Button>
            <Button variant="contained" disabled={busy || !ready} onClick={apply}>
              Add {ready} matched row(s) to PO
            </Button>
          </>
        )}
      </DialogActions>
    </Dialog>
  );
};

const skuLabel = (s) => `${s.sku_code} — ${s.description}`;

const ImportRow = ({ row, poId, busy, readOnly, onResolve }) => {
  const [qtyEdit, setQtyEdit] = useState('');
  const options = row.candidates;
  const chosen = row.resolved;

  return (
    <TableRow hover>
      <TableCell>{row.row_no}</TableCell>
      <TableCell style={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
        {row.raw_code}
        {row.raw_desc && (
          <Typography variant="caption" display="block" color="textSecondary" noWrap style={{ maxWidth: 220, fontFamily: 'inherit' }}>
            {row.raw_desc}
          </Typography>
        )}
      </TableCell>
      <TableCell>{row.raw_finish || '—'}</TableCell>
      <TableCell align="right">
        {row.match_status === 'bad_qty' && !readOnly ? (
          <TextField
            size="small"
            type="number"
            placeholder="Qty"
            value={qtyEdit}
            onChange={(e) => setQtyEdit(e.target.value)}
            onBlur={() => Number(qtyEdit) > 0 && onResolve({ qty: Number(qtyEdit) })}
            style={{ width: 80 }}
          />
        ) : (
          num(row.qty)
        )}
      </TableCell>
      <TableCell>
        <Chip size="small" variant="outlined" label={STATUS_LABEL[row.match_status] || row.match_status} />
        <Typography variant="caption" display="block" color="textSecondary">
          {row.match_note}
        </Typography>
      </TableCell>
      <TableCell>
        {readOnly || (row.bucket === 'matched' && (row.match_status === 'exact' || row.match_status === 'alias')) ? (
          chosen ? (
            <Box>
              <b style={{ fontFamily: 'monospace' }}>{chosen.sku_code}</b>
              <Typography variant="caption" display="block" color="textSecondary">
                {chosen.description} · {money(chosen.mrp)}
              </Typography>
            </Box>
          ) : (
            '—'
          )
        ) : row.bucket === 'dismissed' ? (
          <i>Dismissed</i>
        ) : (
          <SkuPicker poId={poId} options={options} value={chosen} disabled={busy} onPick={(s) => onResolve({ sku_code: s ? s.sku_code : '' })} />
        )}
      </TableCell>
      <TableCell>
        {!readOnly && row.bucket !== 'dismissed' && (
          <Button size="small" color="inherit" disabled={busy} onClick={() => onResolve({ dismiss: true })}>
            Dismiss
          </Button>
        )}
        {!readOnly && row.bucket === 'dismissed' && (
          <Typography variant="caption" color="textSecondary">
            Pick a SKU to restore
          </Typography>
        )}
      </TableCell>
    </TableRow>
  );
};

// The row's candidates first; typing searches the whole SKU master for anything else.
export const SkuPicker = ({ poId, options, value, disabled, onPick }) => {
  const [input, setInput] = useState('');
  const [found, setFound] = useState([]);

  useEffect(() => {
    const q = input.trim();
    if (q.length < 2 || (value && input === skuLabel(value))) {
      setFound([]);
      return undefined;
    }
    const timer = setTimeout(() => {
      poBuilderService
        .search(poId, q)
        .then((r) => setFound(r.results))
        .catch(() => setFound([]));
    }, 250);
    return () => clearTimeout(timer);
  }, [input, poId, value]);

  const seen = new Set(options.map((o) => o.sku_code));
  const all = [...options.map((o) => ({ ...o, group: 'Suggested' })), ...found.filter((f) => !seen.has(f.sku_code)).map((f) => ({ ...f, group: 'Search results' }))];

  return (
    <Autocomplete
      size="small"
      options={all}
      groupBy={(o) => o.group}
      value={value ? all.find((o) => o.sku_code === value.sku_code) || { ...value, group: 'Suggested' } : null}
      onChange={(_, v) => onPick(v)}
      inputValue={input}
      onInputChange={(_, v) => setInput(v)}
      filterOptions={(x) => x}
      getOptionLabel={skuLabel}
      isOptionEqualToValue={(o, v) => o.sku_code === v.sku_code}
      disabled={disabled}
      renderOption={(props, o) => (
        <li {...props} key={`${o.group}-${o.sku_code}`}>
          <Box>
            <b style={{ fontFamily: 'monospace' }}>{o.sku_code}</b>
            <Typography variant="caption" display="block" color="textSecondary">
              {o.description} · {money(o.mrp)}
            </Typography>
          </Box>
        </li>
      )}
      renderInput={(params) => <TextField {...params} placeholder={options.length ? 'Pick one, or type to search' : 'Type to search the SKU master'} />}
    />
  );
};

export default BulkImportDialog;
