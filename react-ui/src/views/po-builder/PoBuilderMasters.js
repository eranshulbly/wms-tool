import React, { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Grid,
  IconButton,
  MenuItem,
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
  ToggleButton,
  ToggleButtonGroup,
  Typography
} from '@material-ui/core';
import { IconFileSpreadsheet, IconX } from '@tabler/icons';

import poBuilderService, { errorMessage } from '../../services/poBuilderService';
import { money, num, pct } from './pricing';

// PO Builder master data: SKU master versions, quarterly schemes, the SKU → scheme
// group mapping (read-only), and the settings.

// One page per sidebar item. SKU Master and Schemes are in the Admin menu (menu-items/admin.js)
// and pass `section`; the rest are in menu-items/poBuilder.js and take it from the route.
const PAGES = {
  'sku-master': {
    title: 'SKU Master',
    intro: 'The product list POs are priced from: every SKU with its MRP, GST and SPU. Upload a fresh export whenever Ebco revises prices — each upload is kept as a version, and a PO keeps the prices of the version it was started on.',
    Body: (p) => <SkuMasterTab {...p} />
  },
  schemes: {
    title: 'Schemes',
    intro: 'The scheme: which scheme group each SKU belongs to and the slabs (minimum qty or ₹ → discount %) of each group. The latest upload is in force until the next one replaces it — no dates to enter.',
    Body: (p) => <SchemesTab {...p} />
  },
  'sku-mapping': {
    title: 'SKU → Scheme Mapping',
    intro: 'Which scheme group each SKU falls in, exactly as the uploaded scheme file says. Use “Unmapped” to see active SKUs that are in no scheme group — they always get 0% scheme.',
    Body: (p) => <MappingTab {...p} />
  },
  settings: {
    title: 'Settings',
    intro: 'The discounts every price is built from.',
    Body: (p) => <SettingsTab {...p} />
  }
};

const PoBuilderMasters = ({ section: fixedSection }) => {
  const params = useParams();
  const section = fixedSection || params.section;
  const [toast, setToast] = useState(null);
  const notify = (severity, msg) => setToast({ severity, msg });
  const page = PAGES[section] || PAGES['sku-master'];
  const { Body } = page;

  return (
    <Box>
      <Box display="flex" alignItems="flex-start" justifyContent="space-between" flexWrap="wrap" style={{ gap: 12 }} mb={2}>
        <Box maxWidth={900}>
          <Typography variant="h3" gutterBottom>
            {page.title}
          </Typography>
          <Typography variant="body2" color="textSecondary">
            {page.intro}
          </Typography>
        </Box>
      </Box>
      <Paper variant="outlined">
        <Box p={2}>
          <Body key={section} notify={notify} />
        </Box>
      </Paper>
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

const FilePick = ({ id, file, onFile, hint }) => (
  <label htmlFor={id}>
    <input id={id} type="file" accept=".xlsx,.xls,.csv" style={{ display: 'none' }} onChange={(e) => onFile(e.target.files?.[0] || null)} />
    <Box border="2px dashed #c4cdd5" borderRadius={2} p={2} textAlign="center" style={{ cursor: 'pointer', background: '#fafbfc' }}>
      <IconFileSpreadsheet size={24} />
      <Typography variant="body2" color="textSecondary">
        {hint}
      </Typography>
      {file && (
        <Typography variant="body2" style={{ fontFamily: 'monospace', marginTop: 4 }}>
          {file.name}
        </Typography>
      )}
      <Button component="span" size="small">
        Browse
      </Button>
    </Box>
  </label>
);

const Stat = ({ label, value, warn }) => (
  <Box minWidth={110}>
    <Typography variant="caption" color="textSecondary">
      {label}
    </Typography>
    <Typography variant="h5" style={{ color: warn ? '#b45309' : undefined }}>
      {value}
    </Typography>
  </Box>
);

// --------------------------------------------------------------------------- upload formats

const SKU_MASTER_FORMAT = {
  intro: 'Bizom → Reports → “Category Wise SKU Master”, exported as CSV or Excel, uploaded as it is. One row per SKU; the header row can sit below a title block.',
  note: 'A file missing a required column is rejected. A row with a required value blank is skipped and listed in the preview — it is not loaded with a guessed value.',
  columns: [
    ['SKU_Code', 'Required', 'HTD1-SC-NP', 'The full code including the finish. Finish is read from the end of the code.'],
    ['Sku_Id', 'Required', '464', 'Bizom’s SKU id.'],
    ['Sku Name', 'Required', 'Thick Door Hinge - Full Overlay - Soft C', 'Shown on lines and used by search.'],
    ['Category', 'Required', 'FG-Hinges', 'Shown as Segment in the Order Book.'],
    ['Mrp', 'Required', '454', 'Must be more than 0.'],
    ['(%)GST', 'Required', '18', 'IGST rate of the SKU.'],
    ['SPU', 'Required', '25', 'Standard pack — must be more than 0.'],
    ['UOM', 'Optional', 'Set / Nos / Mtr', 'Unit the qty is entered in.'],
    ['Is Active ?', 'Optional', 'Active / Inactive', 'Blank = active. Inactive SKUs are kept but cannot be searched or matched. If a code appears twice, the active row wins.']
  ]
};

const SCHEME_FORMAT = {
  intro: 'One row per SKU (the same SKU list as the SKU master), with its scheme group and that group’s slabs repeated on every row of the group.',
  columns: [
    ['SKU Code', 'Required', 'ABH-128-AQ', 'Each SKU may appear in only one scheme — a SKU in two schemes blocks the upload.'],
    ['Category', 'Required', 'FG-Aluminium', 'Needed on every SKU that is in a scheme.'],
    ['Scheme No', 'Required', 'SG33', '“No scheme” (or blank) = the SKU is in no group.'],
    ['Scheme Description', 'Recommended', 'Aluminium Handles & Knobs…', 'The group name shown in the scheme panel.'],
    ['Basis', 'Required', 'Qty / Value', 'Qty = group total in nos/sets; Value = ₹ at price after the 51.2% and 12% discounts.'],
    ['Slab 1 %, Slab 1 Min', 'Required', '3%, 52500', '% as 0.03 or 3. Min in nos (Qty) or ₹ (Value).'],
    ['Slab 2 % … Slab N Min', 'Optional', '5%, 105000', 'As many slabs as the group has; blank slabs are ignored.']
  ],
  note: 'Every row of one Scheme No must carry the same basis and slabs. The newly uploaded scheme replaces the previous one.'
};

const FormatGuide = ({ format }) => (
  <Paper variant="outlined" style={{ padding: 12, marginBottom: 16, background: '#fafbfc' }}>
    <Typography variant="h6" gutterBottom>
      File format
    </Typography>
    <Typography variant="body2" color="textSecondary" paragraph>
      {format.intro}
    </Typography>
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>Column</TableCell>
          <TableCell>Needed?</TableCell>
          <TableCell>Example</TableCell>
          <TableCell>Notes</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {format.columns.map(([col, need, ex, note]) => (
          <TableRow key={col}>
            <TableCell style={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>{col}</TableCell>
            <TableCell style={{ whiteSpace: 'nowrap', fontWeight: need === 'Required' ? 600 : 400 }}>{need}</TableCell>
            <TableCell style={{ fontSize: 12 }}>{ex}</TableCell>
            <TableCell style={{ fontSize: 12 }}>{note}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
    {format.note && (
      <Typography variant="caption" display="block" color="textSecondary" style={{ marginTop: 8 }}>
        {format.note}
      </Typography>
    )}
    <Typography variant="caption" display="block" color="textSecondary" style={{ marginTop: 4 }}>
      Column names are matched loosely (case, spaces and symbols are ignored).
    </Typography>
  </Paper>
);

// --------------------------------------------------------------------------- SKU master

const SkuMasterTab = ({ notify }) => {
  const [masters, setMasters] = useState(null);
  const [file, setFile] = useState(null);
  const [name, setName] = useState('');
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    poBuilderService.listMasters().then((r) => setMasters(r.masters)).catch((e) => notify('error', errorMessage(e, 'Could not load')));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(load, [load]);

  const send = async (commit) => {
    setBusy(true);
    try {
      const r = await poBuilderService.uploadMaster(file, name, commit);
      if (commit) {
        notify('success', `SKU master loaded: ${num(r.master.row_count)} SKUs (${num(r.master.active_count)} active). New drafts use it from now on.`);
        setFile(null);
        setName('');
        setPreview(null);
        load();
      } else {
        setPreview(r.preview);
      }
    } catch (e) {
      notify('error', errorMessage(e, 'Upload failed'));
    } finally {
      setBusy(false);
    }
  };

  const d = preview?.diff;
  return (
    <Grid container spacing={3}>
      <Grid item xs={12}>
        <FormatGuide format={SKU_MASTER_FORMAT} />
      </Grid>
      <Grid item xs={12} md={5}>
        <Typography variant="h5" gutterBottom>
          Upload a new version
        </Typography>
        <FilePick
          id="pob-master-file"
          file={file}
          onFile={(f) => {
            setFile(f);
            setPreview(null);
          }}
          hint="CSV or Excel"
        />
        <TextField fullWidth size="small" margin="normal" label="Version name (optional)" placeholder="e.g. SKU master Oct 2026" value={name} onChange={(e) => setName(e.target.value)} />
        <Box display="flex" style={{ gap: 8 }}>
          <Button variant="outlined" disabled={!file || busy} onClick={() => send(false)}>
            Preview
          </Button>
          <Button variant="contained" disabled={!file || busy || !preview} onClick={() => send(true)}>
            Load as new version
          </Button>
          {busy && <CircularProgress size={22} />}
        </Box>
        {preview && (
          <Paper variant="outlined" style={{ padding: 12, marginTop: 16 }}>
            <Box display="flex" flexWrap="wrap" style={{ gap: 16 }}>
              <Stat label="SKUs" value={num(preview.sku_count)} />
              <Stat label="Active" value={num(preview.active_count)} />
              <Stat label="Duplicate codes merged" value={num(preview.duplicates)} />
              <Stat label="Rows skipped" value={num(preview.skipped_count)} warn={preview.skipped_count > 0} />
            </Box>
            <Typography variant="body2" style={{ marginTop: 8 }}>
              GST: {Object.entries(preview.gst_rates).map(([k, v]) => `${k} × ${num(v)}`).join(', ')}
            </Typography>
            {d ? (
              <Alert severity={d.mrp_changed || d.removed ? 'warning' : 'info'} style={{ marginTop: 8 }}>
                Compared with the current version: {num(d.new)} new, {num(d.removed)} removed, {num(d.mrp_changed)} MRP changes, {num(d.gst_changed)} GST changes, {num(d.activated)} re-activated,{' '}
                {num(d.deactivated)} deactivated.
                {d.mrp_samples.length > 0 && (
                  <Box mt={1} style={{ fontFamily: 'monospace', fontSize: 12 }}>
                    {d.mrp_samples.map((s) => (
                      <div key={s.sku_code}>
                        {s.sku_code}: {money(s.old)} → {money(s.new)}
                      </div>
                    ))}
                  </Box>
                )}
              </Alert>
            ) : (
              <Alert severity="info" style={{ marginTop: 8 }}>
                This will be the first SKU master.
              </Alert>
            )}
            {preview.skipped.length > 0 && (
              <Box mt={1} style={{ fontSize: 12 }}>
                {preview.skipped.slice(0, 10).map((s) => (
                  <div key={`${s.row}-${s.sku_code}`}>
                    Row {s.row} {s.sku_code}: {s.reason}
                  </div>
                ))}
              </Box>
            )}
          </Paper>
        )}
      </Grid>
      <Grid item xs={12} md={7}>
        <Typography variant="h5" gutterBottom>
          Versions
        </Typography>
        {masters === null ? (
          <CircularProgress size={20} />
        ) : masters.length === 0 ? (
          <Typography color="textSecondary">None uploaded yet.</Typography>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Version</TableCell>
                <TableCell>File</TableCell>
                <TableCell align="right">SKUs</TableCell>
                <TableCell align="right">Active</TableCell>
                <TableCell align="right">POs using it</TableCell>
                <TableCell>Uploaded</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {masters.map((m, i) => (
                <TableRow key={m.id}>
                  <TableCell>
                    {m.name} {i === 0 && <Chip size="small" color="success" label="current" />}
                  </TableCell>
                  <TableCell style={{ fontSize: 12 }}>{m.filename}</TableCell>
                  <TableCell align="right">{num(m.row_count)}</TableCell>
                  <TableCell align="right">{num(m.active_count)}</TableCell>
                  <TableCell align="right">{m.po_count}</TableCell>
                  <TableCell style={{ fontSize: 12, ...(i === 0 ? { color: '#b91c1c', fontWeight: 600 } : {}) }}>
                    {(m.uploaded_on || '').slice(0, 16).replace('T', ' ')}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Grid>
    </Grid>
  );
};

// --------------------------------------------------------------------------- schemes

const emptyScheme = { name: '' };

// Default scheme name: scheme_ddmmyyyy, the upload date. Editable before saving.
const defaultSchemeName = () => {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `scheme_${pad(d.getDate())}${pad(d.getMonth() + 1)}${d.getFullYear()}`;
};

const SchemesTab = ({ notify }) => {
  const [schemes, setSchemes] = useState(null);
  const [file, setFile] = useState(null);
  const [fields, setFields] = useState(emptyScheme);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState(null);
  const [editing, setEditing] = useState(null);

  const load = useCallback(() => {
    poBuilderService.listSchemes().then((r) => setSchemes(r.schemes)).catch((e) => notify('error', errorMessage(e, 'Could not load')));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(load, [load]);

  const send = async (commit) => {
    setBusy(true);
    try {
      const r = await poBuilderService.uploadScheme(file, fields, commit);
      setPreview(r.preview);
      if (commit) {
        notify('success', `Scheme “${r.scheme.name}” saved: ${r.scheme.group_count} groups, ${num(r.scheme.sku_count)} SKUs.`);
        setFile(null);
        setFields(emptyScheme);
        setPreview(null);
        load();
      }
    } catch (e) {
      notify('error', errorMessage(e, 'Upload failed'));
    } finally {
      setBusy(false);
    }
  };

  const saveEdit = async () => {
    try {
      await poBuilderService.updateScheme(editing.id, editing);
      setEditing(null);
      load();
      notify('success', 'Scheme updated');
    } catch (e) {
      notify('error', errorMessage(e, 'Could not save'));
    }
  };

  return (
    <Grid container spacing={3}>
      <Grid item xs={12}>
        <FormatGuide format={SCHEME_FORMAT} />
      </Grid>
      <Grid item xs={12} md={5}>
        <Typography variant="h5" gutterBottom>
          Upload a new scheme
        </Typography>
        <FilePick
          id="pob-scheme-file"
          file={file}
          onFile={(f) => {
            setFile(f);
            setPreview(null);
            // Fill the name unless one was typed by hand.
            if (f && (!fields.name.trim() || /^scheme_\d{8}$/.test(fields.name))) setFields({ ...fields, name: defaultSchemeName() });
          }}
          hint="Excel or CSV"
        />
        <TextField fullWidth size="small" margin="dense" label="Name" placeholder="scheme_ddmmyyyy" value={fields.name} onChange={(e) => setFields({ ...fields, name: e.target.value })} />
        <Typography variant="caption" color="textSecondary" display="block">
          Once saved, this scheme replaces the current one for every draft PO. Finalised POs keep the scheme they were finalised with.
        </Typography>
        <Box display="flex" style={{ gap: 8 }} mt={1}>
          <Button variant="outlined" disabled={!file || busy} onClick={() => send(false)}>
            Preview
          </Button>
          <Button
            variant="contained"
            disabled={!file || busy || !preview || preview.errors.length > 0}
            onClick={() => send(true)}
          >
            Save scheme
          </Button>
          {busy && <CircularProgress size={22} />}
        </Box>
        {preview && (
          <Paper variant="outlined" style={{ padding: 12, marginTop: 16 }}>
            <Box display="flex" flexWrap="wrap" style={{ gap: 16 }}>
              <Stat label="Scheme groups" value={preview.group_count} />
              <Stat label="SKUs mapped" value={num(preview.sku_count)} />
              <Stat label='"No scheme" SKUs' value={num(preview.no_scheme_count)} />
              <Stat label="Qty / Value groups" value={`${preview.basis_counts.QTY || 0} / ${preview.basis_counts.VALUE || 0}`} />
              <Stat label="Not in SKU master" value={num(preview.unknown_sku_count)} warn={preview.unknown_sku_count > 0} />
            </Box>
            {preview.errors.map((e) => (
              <Alert key={e} severity="error" style={{ marginTop: 6 }}>
                {e}
              </Alert>
            ))}
            {preview.warnings.map((w) => (
              <Alert key={w} severity="warning" style={{ marginTop: 6 }}>
                {w}
              </Alert>
            ))}
            {preview.unknown_skus.length > 0 && (
              <Typography variant="caption" display="block" style={{ marginTop: 6 }}>
                Not in SKU master: {preview.unknown_skus.join(', ')}
              </Typography>
            )}
          </Paper>
        )}
      </Grid>
      <Grid item xs={12} md={7}>
        <Typography variant="h5" gutterBottom>
          Schemes
        </Typography>
        {schemes === null ? (
          <CircularProgress size={20} />
        ) : schemes.length === 0 ? (
          <Typography color="textSecondary">None uploaded yet.</Typography>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Uploaded</TableCell>
                <TableCell align="right">Groups</TableCell>
                <TableCell align="right">SKUs</TableCell>
                <TableCell />
              </TableRow>
            </TableHead>
            <TableBody>
              {schemes.map((s) => (
                <TableRow key={s.id} hover>
                  <TableCell>
                    {s.name} {s.current && <Chip size="small" color="success" label="in force" />}
                  </TableCell>
                  <TableCell style={{ fontSize: 12, whiteSpace: 'nowrap', ...(s.current ? { color: '#b91c1c', fontWeight: 600 } : {}) }}>
                    {(s.uploaded_on || '').slice(0, 16).replace('T', ' ')}
                  </TableCell>
                  <TableCell align="right">{s.group_count}</TableCell>
                  <TableCell align="right">{num(s.sku_count)}</TableCell>
                  <TableCell>
                    <Button size="small" onClick={() => poBuilderService.getScheme(s.id).then(setDetail)}>
                      Groups
                    </Button>
                    <Button size="small" onClick={() => setEditing({ ...s })}>
                      Rename
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Grid>

      <Dialog open={!!detail} onClose={() => setDetail(null)} maxWidth="md" fullWidth>
        <DialogTitle>
          {detail?.scheme.name} — scheme groups
          <IconButton size="small" onClick={() => setDetail(null)} style={{ position: 'absolute', right: 12, top: 12 }}>
            <IconX size={18} />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Scheme</TableCell>
                <TableCell>Group</TableCell>
                <TableCell>Basis</TableCell>
                <TableCell>Slabs</TableCell>
                <TableCell align="right">SKUs</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {detail?.groups.map((g) => (
                <TableRow key={g.id}>
                  <TableCell style={{ fontWeight: 600 }}>{g.scheme_no}</TableCell>
                  <TableCell style={{ fontSize: 12 }}>{g.name}</TableCell>
                  <TableCell>{g.basis === 'QTY' ? 'Qty' : 'Value'}</TableCell>
                  <TableCell style={{ whiteSpace: 'nowrap', fontSize: 12 }}>
                    {g.slabs.map((s) => (
                      <div key={s.slab_no}>
                        {pct(s.discount_pct)} from {g.basis === 'VALUE' ? money(s.min_threshold) : `${num(s.min_threshold)} nos`}
                      </div>
                    ))}
                  </TableCell>
                  <TableCell align="right">{g.sku_count}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DialogContent>
      </Dialog>

      <Dialog open={!!editing} onClose={() => setEditing(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Rename scheme</DialogTitle>
        <DialogContent>
          {editing && <TextField fullWidth margin="dense" label="Name" value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} />}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditing(null)}>Cancel</Button>
          <Button variant="contained" onClick={saveEdit}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Grid>
  );
};

// --------------------------------------------------------------------------- mapping

const MappingTab = ({ notify }) => {
  const [schemes, setSchemes] = useState([]);
  const [schemeId, setSchemeId] = useState('');
  const [view, setView] = useState('unmapped');
  const [q, setQ] = useState('');
  const [data, setData] = useState(null);

  useEffect(() => {
    poBuilderService.listSchemes().then((r) => {
      setSchemes(r.schemes);
      if (r.schemes.length) setSchemeId(r.schemes[0].id);
    });
  }, []);

  const load = useCallback(() => {
    if (!schemeId) return;
    setData(null);
    poBuilderService
      .getMapping(schemeId, view, q)
      .then(setData)
      .catch((e) => notify('error', errorMessage(e, 'Could not load')));
  }, [schemeId, view, q]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const t = setTimeout(load, 300);
    return () => clearTimeout(t);
  }, [load]);

  if (!schemes.length) return <Typography color="textSecondary">Upload a scheme first.</Typography>;

  return (
    <Box>
      <Box display="flex" flexWrap="wrap" alignItems="center" style={{ gap: 12 }} mb={2}>
        <TextField select size="small" label="Scheme" value={schemeId} onChange={(e) => setSchemeId(e.target.value)} style={{ minWidth: 200 }}>
          {schemes.map((s) => (
            <MenuItem key={s.id} value={s.id}>
              {s.name}
            </MenuItem>
          ))}
        </TextField>
        <ToggleButtonGroup size="small" exclusive value={view} onChange={(_, v) => v && setView(v)}>
          <ToggleButton value="unmapped">Unmapped {data ? `(${num(data.counts.unmapped)})` : ''}</ToggleButton>
          <ToggleButton value="all">All active SKUs {data ? `(${num(data.counts.all)})` : ''}</ToggleButton>
        </ToggleButtonGroup>
        <TextField size="small" placeholder="Search code or description" value={q} onChange={(e) => setQ(e.target.value)} />
      </Box>
      <Typography variant="body2" color="textSecondary" paragraph>
        &quot;Unmapped&quot; = active SKUs in the current SKU master that this scheme puts in no group — they get 0% scheme. To change a mapping, correct the scheme file and upload it again.
      </Typography>
      {data === null ? (
        <CircularProgress size={20} />
      ) : (
        <TableContainer style={{ maxHeight: '65vh' }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell>SKU</TableCell>
                <TableCell>Description</TableCell>
                <TableCell>Category</TableCell>
                <TableCell>Scheme</TableCell>
                <TableCell>Scheme group</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {data.rows.map((r) => (
                <TableRow key={r.sku_code} hover>
                  <TableCell style={{ fontFamily: 'monospace' }}>{r.sku_code}</TableCell>
                  <TableCell style={{ fontSize: 12 }}>{r.description}</TableCell>
                  <TableCell style={{ fontSize: 12 }}>{r.category}</TableCell>
                  <TableCell style={{ fontWeight: 600 }}>{r.group || <i>none</i>}</TableCell>
                  <TableCell style={{ fontSize: 12 }}>{r.group_name || ''}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {data.total > data.rows.length && (
            <Typography variant="caption" color="textSecondary" style={{ padding: 8, display: 'block' }}>
              Showing {data.rows.length} of {num(data.total)} — search to narrow down.
            </Typography>
          )}
        </TableContainer>
      )}
    </Box>
  );
};

// --------------------------------------------------------------------------- settings

const SettingsTab = ({ notify }) => {
  const [s, setS] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    poBuilderService.getSettings().then((r) => setS(r.settings));
  }, []);

  const save = async () => {
    setBusy(true);
    try {
      const r = await poBuilderService.saveSettings(s);
      setS(r.settings);
      notify('success', 'Settings saved — drafts re-price with them; finalised POs keep theirs.');
    } catch (e) {
      notify('error', errorMessage(e, 'Could not save'));
    } finally {
      setBusy(false);
    }
  };

  if (!s) return <CircularProgress size={20} />;
  const ex = 1000 * (1 - s.dtr_discount_pct / 100);
  return (
    <Grid container spacing={3}>
      <Grid item xs={12} md={6}>
        <Typography variant="h5" gutterBottom>
          Price build-up
        </Typography>
        <Box display="flex" style={{ gap: 12 }}>
          <TextField label="DTR discount on MRP (%)" type="number" size="small" value={s.dtr_discount_pct} onChange={(e) => setS({ ...s, dtr_discount_pct: e.target.value })} />
          <TextField label="Standard discount (%)" type="number" size="small" value={s.std_discount_pct} onChange={(e) => setS({ ...s, std_discount_pct: e.target.value })} />
        </Box>
        <Typography variant="body2" color="textSecondary" style={{ marginTop: 8 }}>
          Example on MRP ₹1,000: DTR basic {money(ex)} → after standard {money(ex * (1 - s.std_discount_pct / 100))} → less the scheme % of its group = landing price. Value-basis
          schemes count the after-standard price × qty.
        </Typography>
        <FormControlLabel
          style={{ marginTop: 12 }}
          control={<Switch checked={s.show_case_helper} onChange={(e) => setS({ ...s, show_case_helper: e.target.checked })} />}
          label="Show SPU / case equivalents on POs by default"
        />
      </Grid>
      <Grid item xs={12} md={6}>
        <Typography variant="h5" gutterBottom>
          DMS order upload
        </Typography>
        <Box display="flex" flexWrap="wrap" style={{ gap: 12 }}>
          <TextField label="DMS user id" size="small" value={s.dms_user_id} onChange={(e) => setS({ ...s, dms_user_id: e.target.value })} />
          <TextField label="DMS outlet id" size="small" value={s.dms_outlet_id} onChange={(e) => setS({ ...s, dms_outlet_id: e.target.value })} />
          <TextField label="DMS warehouse id" size="small" value={s.dms_warehouse_id} onChange={(e) => setS({ ...s, dms_warehouse_id: e.target.value })} />
        </Box>
        <Typography variant="body2" color="textSecondary" style={{ marginTop: 8 }}>
          The PO&apos;s DMS Order (.csv) is raised under these — the user_id, *outlet_id and *warehouse_id columns of the DMS order upload file. They default to the ids on Ebco&apos;s sample upload file (171, 4962, 1); a cleared field goes back to its default. Each SKU goes by its DMS Sku_Id, quantities in units, dated the PO date, with Auto Scheme Apply on.
        </Typography>
      </Grid>
      <Grid item xs={12}>
        <Button variant="contained" onClick={save} disabled={busy}>
          Save settings
        </Button>
      </Grid>
    </Grid>
  );
};

export default PoBuilderMasters;
