import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  CircularProgress,
  IconButton,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconCheck, IconDownload, IconPencil, IconPlus, IconTrash, IconUpload, IconX } from '@tabler/icons';
import { getExecBeats, parseExecBeatsFile, saveExecBeats } from '../../services/beatOutstandingService';

// Beat Outstanding -> Executive Beats: every beat each sales executive owns, kept by hand
// here (not an upload). Each executive's Beat Outstanding Excel gets a second sheet with
// the bills past the cash-discount period on all of these beats, not just the day's.

const useStyles = makeStyles(() => ({
  muted: { color: '#7a869a' },
}));

const errMsg = (e, fallback) => e?.response?.data?.msg || fallback;

// Executive -> every beat they own, kept by hand here (not an upload). The Excel's second
// sheet lists the bills past the cash-discount period on all of an executive's beats.
let nextRowId = 1;
const withIds = (rows) => rows.map((r) => ({ ...r, id: nextRowId++ }));
const sameRows = (a, b) =>
  a.length === b.length && a.every((r, i) => r.se_name === b[i].se_name && r.beat_name === b[i].beat_name);

// This MUI version fires a 'reset' input change, to '', whenever the box is not focused and
// no option is picked — i.e. on every row that appears (a loaded file) and after typing
// and clicking away. Only typing, clearing and picking an option change the name.
const NameCell = ({ value, options, placeholder, onChange }) => (
  <Autocomplete
    freeSolo
    size="small"
    options={options}
    inputValue={value}
    onInputChange={(_, v, reason) => {
      if (reason !== 'reset') onChange(v || '');
    }}
    onChange={(_, v) => {
      if (typeof v === 'string') onChange(v);
    }}
    renderInput={(params) => <TextField {...params} placeholder={placeholder} variant="standard" />}
  />
);

// A blank file to fill in, with the two columns the upload reads.
const downloadTemplate = () => {
  const url = URL.createObjectURL(new Blob(['User,Beat\r\n'], { type: 'text/csv' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = 'executive_beats.csv';
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
};

const rowKey = (r) => `${r.se_name.trim().toLowerCase()}|${r.beat_name.trim().toLowerCase()}`;

const ExecBeatsTable = ({ saved, executiveNames, beatNames, onSaved }) => {
  const classes = useStyles();
  const [rows, setRows] = useState(() => withIds(saved));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  // A read file waiting for Replace / Add: {filename, rows, warnings, warning_count}
  const [pending, setPending] = useState(null);
  const [reading, setReading] = useState(false);
  const [editing, setEditing] = useState(null); // {id, se_name, beat_name, isNew}
  const [filter, setFilter] = useState({ se_name: '', beat_name: '' });

  // Reloading the report (another date, an upload) must not throw away unsaved edits —
  // only a change to what is stored resets the table.
  const savedKey = JSON.stringify(saved);
  useEffect(() => {
    setRows(withIds(JSON.parse(savedKey)));
    setEditing(null);
  }, [savedKey]);

  const dirty = !sameRows(rows, saved);
  // Rows are read-only; one row at a time is edited, through its pencil. The edit is a
  // draft until its tick — the cross puts the row back (or drops a row just added).
  const startEdit = (r, isNew = false) => setEditing({ id: r.id, se_name: r.se_name, beat_name: r.beat_name, isNew });
  const doneEdit = () => {
    const se = editing.se_name.trim();
    const beat = editing.beat_name.trim();
    if (!se || !beat) {
      setMsg({ type: 'error', text: 'Give both the user and the beat.' });
      return;
    }
    setRows((rs) => rs.map((r) => (r.id === editing.id ? { ...r, se_name: se, beat_name: beat } : r)));
    setEditing(null);
    setMsg(null);
  };
  const cancelEdit = () => {
    if (editing.isNew) setRows((rs) => rs.filter((r) => r.id !== editing.id));
    setEditing(null);
    setMsg(null);
  };
  const add = () => {
    const r = { id: nextRowId++, se_name: rows.length ? rows[rows.length - 1].se_name : '', beat_name: '' };
    setRows((rs) => [...rs, r]);
    startEdit(r, true);
  };
  const remove = (id) => setRows((rs) => rs.filter((r) => r.id !== id));

  // Column filters: a row shows when each column contains what is typed above it. The row
  // being edited always shows, so a filter cannot hide an open edit.
  const filtering = Boolean(filter.se_name.trim() || filter.beat_name.trim());
  const matches = (r) =>
    ['se_name', 'beat_name'].every((k) => r[k].toLowerCase().includes(filter[k].trim().toLowerCase()));
  const shown = rows.filter((r) => editing?.id === r.id || matches(r));

  const readFile = async (file) => {
    setReading(true);
    setMsg(null);
    setPending(null);
    try {
      const res = await parseExecBeatsFile(file);
      setPending({ filename: file.name, ...res });
    } catch (e) {
      setMsg({ type: 'error', text: errMsg(e, 'Could not read this file.') });
    } finally {
      setReading(false);
    }
  };

  // The file's rows go into the table only; Save stores them.
  const applyFile = (replace) => {
    setEditing(null);
    setRows((rs) => {
      const keep = replace ? [] : rs.filter((r) => r.se_name.trim() || r.beat_name.trim());
      const have = new Set(keep.map(rowKey));
      const added = pending.rows.filter((r) => !have.has(rowKey(r)));
      return [...keep, ...withIds(added)];
    });
    setMsg({ type: 'info', text: `${pending.filename} is in the table below — check it and press Save to keep it.` });
    setPending(null);
  };

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const res = await saveExecBeats(rows.map(({ se_name, beat_name }) => ({ se_name, beat_name })));
      setMsg({ type: res.warnings.length ? 'warning' : 'success', text: `Saved ${res.saved} beat(s).`, warnings: res.warnings });
      onSaved();
    } catch (e) {
      setMsg({ type: 'error', text: errMsg(e, 'Could not save — nothing was changed.') });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Paper variant="outlined" style={{ padding: 16 }}>
      <Box display="flex" alignItems="center" flexWrap="wrap" style={{ gap: 8, marginBottom: 8 }}>
        <Typography variant="subtitle2">Bulk upload</Typography>
        <Typography variant="caption" className={classes.muted}>
          .csv or .xlsx with two columns, User and Beat — one row per beat
        </Typography>
        <Box flexGrow={1} />
        <Button size="small" startIcon={<IconDownload size={14} />} onClick={downloadTemplate}>
          Template
        </Button>
        <label htmlFor="exec-beats-file">
          <input
            id="exec-beats-file"
            type="file"
            accept=".csv,.xlsx"
            style={{ display: 'none' }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = '';
              if (f) readFile(f);
            }}
          />
          <Button
            component="span"
            size="small"
            variant="outlined"
            disabled={reading || busy}
            startIcon={reading ? <CircularProgress size={14} /> : <IconUpload size={14} />}
          >
            Upload file
          </Button>
        </label>
      </Box>
      {pending && (
        <Alert
          severity={pending.warning_count ? 'warning' : 'info'}
          style={{ marginBottom: 8 }}
          action={
            <Box display="flex" style={{ gap: 4 }}>
              <Button size="small" variant="contained" onClick={() => applyFile(true)}>
                Replace table
              </Button>
              <Button size="small" variant="outlined" onClick={() => applyFile(false)}>
                Add to table
              </Button>
              <Button size="small" onClick={() => setPending(null)}>
                Cancel
              </Button>
            </Box>
          }
        >
          {pending.filename}: {pending.rows.length} user / beat row(s) read.
          {pending.warning_count ? ` ${pending.warning_count} row(s) skipped:` : ''}
          {pending.warnings.slice(0, 10).map((w) => (
            <div key={w}>{w}</div>
          ))}
        </Alert>
      )}
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell style={{ width: '40%' }}>User</TableCell>
            <TableCell>Beat</TableCell>
            <TableCell />
          </TableRow>
          <TableRow>
            {['se_name', 'beat_name'].map((k) => (
              <TableCell key={k} style={{ paddingTop: 0 }}>
                <TextField
                  size="small"
                  variant="standard"
                  fullWidth
                  placeholder="Filter…"
                  value={filter[k]}
                  onChange={(e) => setFilter((f) => ({ ...f, [k]: e.target.value }))}
                  InputProps={{
                    endAdornment: filter[k] ? (
                      <IconButton size="small" onClick={() => setFilter((f) => ({ ...f, [k]: '' }))} aria-label="Clear filter">
                        <IconX size={14} />
                      </IconButton>
                    ) : null,
                  }}
                />
              </TableCell>
            ))}
            <TableCell style={{ paddingTop: 0, whiteSpace: 'nowrap' }} className={classes.muted}>
              {filtering ? `${shown.length} of ${rows.length}` : ''}
            </TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {shown.map((r) =>
            editing?.id === r.id ? (
              <TableRow key={r.id} style={{ background: '#fafbfc' }}>
                <TableCell>
                  <NameCell
                    value={editing.se_name}
                    options={executiveNames}
                    placeholder="Executive"
                    onChange={(v) => setEditing((d) => ({ ...d, se_name: v }))}
                  />
                </TableCell>
                <TableCell>
                  <NameCell
                    value={editing.beat_name}
                    options={beatNames}
                    placeholder="Beat"
                    onChange={(v) => setEditing((d) => ({ ...d, beat_name: v }))}
                  />
                </TableCell>
                <TableCell style={{ whiteSpace: 'nowrap', width: 1 }}>
                  <IconButton size="small" color="primary" onClick={doneEdit} aria-label="Done">
                    <IconCheck size={16} />
                  </IconButton>
                  <IconButton size="small" onClick={cancelEdit} aria-label="Cancel">
                    <IconX size={16} />
                  </IconButton>
                </TableCell>
              </TableRow>
            ) : (
              <TableRow key={r.id} hover>
                <TableCell>{r.se_name}</TableCell>
                <TableCell>{r.beat_name}</TableCell>
                <TableCell style={{ whiteSpace: 'nowrap', width: 1 }}>
                  <IconButton size="small" onClick={() => startEdit(r)} disabled={Boolean(editing)} aria-label="Edit row">
                    <IconPencil size={16} />
                  </IconButton>
                  <IconButton size="small" onClick={() => remove(r.id)} disabled={Boolean(editing)} aria-label="Remove row">
                    <IconTrash size={16} />
                  </IconButton>
                </TableCell>
              </TableRow>
            )
          )}
          {!shown.length && (
            <TableRow>
              <TableCell colSpan={3} className={classes.muted}>
                {rows.length ? 'No rows match the filter.' : 'No beats mapped yet — add a row for each executive and beat.'}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      <Box display="flex" alignItems="center" style={{ gap: 8, marginTop: 12 }}>
        <Button size="small" variant="outlined" startIcon={<IconPlus size={14} />} onClick={add} disabled={Boolean(editing)}>
          Add row
        </Button>
        <Box flexGrow={1} />
        {dirty && (
          <Button
            size="small"
            onClick={() => {
              setRows(withIds(saved));
              setEditing(null);
            }}
            disabled={busy}
          >
            Undo changes
          </Button>
        )}
        <Button
          size="small"
          variant="contained"
          disabled={!dirty || busy || Boolean(editing)}
          onClick={save}
          startIcon={busy ? <CircularProgress size={14} /> : null}
        >
          Save
        </Button>
      </Box>
      {msg && (
        <Alert severity={msg.type} style={{ marginTop: 8 }}>
          {msg.text}
          {msg.warnings?.map((w) => (
            <div key={w}>{w}</div>
          ))}
        </Alert>
      )}
    </Paper>
  );
};


const ExecutiveBeats = () => {
  const classes = useStyles();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    getExecBeats()
      .then((res) => {
        setData(res);
        setError(null);
      })
      .catch((e) => setError(errMsg(e, 'Could not load the executive beats.')));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Executive Beats
      </Typography>
      <Typography variant="body2" className={classes.muted} style={{ marginBottom: 16 }}>
        Every beat that belongs to each executive. Their Beat Outstanding Excel gets a second sheet with the bills older
        than {data?.cd_days ?? 20} days (cash discount lapsed) on all these beats, not just the day's.
      </Typography>
      {error && (
        <Alert severity="error" style={{ marginBottom: 16 }}>
          {error}
        </Alert>
      )}
      {!data && !error && <CircularProgress size={24} />}
      {data && (
        <ExecBeatsTable
          saved={data.exec_beats}
          executiveNames={data.executive_names}
          beatNames={data.beat_names}
          onSaved={load}
        />
      )}
    </Box>
  );
};

export default ExecutiveBeats;
