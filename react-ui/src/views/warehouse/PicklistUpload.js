import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Grid,
  Box,
  Stack,
  Typography,
  Card,
  CardContent,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  Paper,
  Chip,
  Checkbox,
  CircularProgress,
  Button,
  ToggleButton,
  ToggleButtonGroup,
  List,
  ListItem,
  ListItemText,
  Snackbar,
  Alert,
  Divider
} from '@material-ui/core';
import { IconUpload, IconDownload, IconQrcode, IconRefresh } from '@tabler/icons';

import MainCard from '../../ui-component/cards/MainCard';
import { gridSpacing } from '../../store/constant';
import { useWarehouse } from '../../context/WarehouseContext';
import { uploadPicklist, getPicklists, downloadPicklists } from '../../services/picklistService';
import { readBlobError } from '../../services/orderService';

// Matches MAX_DOWNLOAD in the pick-list router: the API draws every page in the one
// gunicorn process it has, so an unbounded selection would hold it for a long time.
const MAX_DOWNLOAD = 100;

const STATE_COLOURS = { open: 'primary', closed: 'default' };

const saveBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
};

const PicklistUpload = () => {
  const { selectedWarehouse, selectedCompany } = useWarehouse();

  const [uploading, setUploading] = useState(false);
  const [uploadLog, setUploadLog] = useState([]);

  const [state, setState] = useState('open');
  const [picklists, setPicklists] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState([]);
  const [downloading, setDownloading] = useState(false);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);
  const [snack, setSnack] = useState(null);

  const notify = (message, severity = 'info') => setSnack({ message, severity });

  const load = useCallback(() => {
    setLoading(true);
    getPicklists(state, selectedWarehouse, selectedCompany)
      .then((data) => {
        if (data.success) {
          setPicklists(data.picklists || []);
          // Drop anything that just left the filter, so a stale id cannot ride along
          // into a download the user did not intend.
          const visible = new Set((data.picklists || []).map((p) => p.picklist_id));
          setSelected((prev) => prev.filter((id) => visible.has(id)));
        } else {
          notify(data.msg || 'Could not load pick lists', 'error');
        }
      })
      .catch(() => notify('Could not load pick lists', 'error'))
      .finally(() => setLoading(false));
  }, [state, selectedWarehouse, selectedCompany]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    setPage(0);
  }, [state, picklists.length]);

  // ── Upload ────────────────────────────────────────────────────────────────
  // Sequential, not Promise.all: the API takes one PDF per request, and firing forty
  // at once would queue them all against a single worker anyway while making the
  // per-file progress meaningless.
  const handleFiles = async (event) => {
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    if (!files.length) return;

    if (!selectedWarehouse || !selectedCompany) {
      notify('Select a warehouse and company first', 'warning');
      return;
    }

    setUploading(true);
    setUploadLog(files.map((f) => ({ filename: f.name, status: 'pending' })));

    let imported = 0;
    for (let i = 0; i < files.length; i += 1) {
      const file = files[i];
      setUploadLog((prev) =>
        prev.map((row, idx) => (idx === i ? { ...row, status: 'uploading' } : row))
      );

      // eslint-disable-next-line no-await-in-loop
      const result = await uploadPicklist(file, selectedWarehouse, selectedCompany);
      if (result.success) imported += 1;

      setUploadLog((prev) =>
        prev.map((row, idx) =>
          idx === i
            ? {
                ...row,
                status: result.success ? 'done' : 'failed',
                msg: result.success
                  ? `${result.original_order_id} — ${result.line_count} line(s)` +
                    (result.replaced ? ' (replaced earlier upload)' : '') +
                    (result.unresolved_parts?.length
                      ? ` — ${result.unresolved_parts.length} part(s) unresolved`
                      : '')
                  : result.msg || 'Failed'
              }
            : row
        )
      );
    }

    setUploading(false);
    notify(
      `Imported ${imported} of ${files.length} pick list(s)`,
      imported === files.length ? 'success' : 'warning'
    );
    load();
  };

  // ── Selection ─────────────────────────────────────────────────────────────
  const pageRows = useMemo(
    () => picklists.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage),
    [picklists, page, rowsPerPage]
  );

  const allOnPageSelected =
    pageRows.length > 0 && pageRows.every((r) => selected.includes(r.picklist_id));

  const toggleAllOnPage = () => {
    const ids = pageRows.map((r) => r.picklist_id);
    setSelected((prev) =>
      allOnPageSelected
        ? prev.filter((id) => !ids.includes(id))
        : Array.from(new Set([...prev, ...ids]))
    );
  };

  const toggleOne = (id) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const handleDownload = () => {
    if (!selected.length) {
      notify('Select at least one pick list', 'warning');
      return;
    }
    if (selected.length > MAX_DOWNLOAD) {
      notify(`Select at most ${MAX_DOWNLOAD} pick lists per download`, 'warning');
      return;
    }

    setDownloading(true);
    downloadPicklists(selected, selectedCompany)
      .then((blob) => {
        const name =
          selected.length === 1 ? 'picklist.pdf' : `picklists_${selected.length}.pdf`;
        saveBlob(blob, name);
        notify(`Downloaded ${selected.length} pick list(s)`, 'success');
      })
      .catch(async (err) => {
        notify((await readBlobError(err)) || 'Could not build the PDF', 'error');
      })
      .finally(() => setDownloading(false));
  };

  return (
    <Grid container spacing={gridSpacing}>
      <Grid item xs={12}>
        <MainCard title="Upload Pick Lists">
          <Typography variant="body2" color="textSecondary" gutterBottom>
            Upload pick-list PDFs printed by the DMS. Each one is matched to the order it
            names — the order must already exist and is left in its current status. Its
            part lines are imported and a QR code is minted for it.
          </Typography>
          <Typography variant="body2" color="textSecondary" gutterBottom>
            Scanning that QR later is what moves the order along.
          </Typography>

          <Box mt={2}>
            <input
              id="picklist-file-upload"
              type="file"
              accept="application/pdf,.pdf"
              multiple
              hidden
              onChange={handleFiles}
            />
            <label htmlFor="picklist-file-upload">
              <Button
                variant="contained"
                color="primary"
                component="span"
                disabled={uploading}
                startIcon={uploading ? <CircularProgress size={16} /> : <IconUpload size={18} />}
              >
                {uploading ? 'Importing…' : 'Select PDF files'}
              </Button>
            </label>
            <Typography variant="caption" color="textSecondary" style={{ marginLeft: 12 }}>
              PDF only. You can select several at once — they are imported one at a time.
            </Typography>
          </Box>

          {uploadLog.length > 0 && (
            <Box mt={2}>
              <Divider />
              <List dense>
                {uploadLog.map((row, idx) => (
                  // eslint-disable-next-line react/no-array-index-key
                  <ListItem key={`${row.filename}-${idx}`}>
                    <ListItemText primary={row.filename} secondary={row.msg} />
                    <Chip
                      size="small"
                      label={row.status}
                      color={
                        row.status === 'done'
                          ? 'primary'
                          : row.status === 'failed'
                          ? 'secondary'
                          : 'default'
                      }
                    />
                  </ListItem>
                ))}
              </List>
            </Box>
          )}
        </MainCard>
      </Grid>

      <Grid item xs={12}>
        <MainCard
          title="Pick Lists"
          secondary={
            <Stack direction="row" spacing={1} alignItems="center">
              <ToggleButtonGroup
                size="small"
                exclusive
                value={state}
                onChange={(e, v) => v && setState(v)}
              >
                <ToggleButton value="open">Open</ToggleButton>
                <ToggleButton value="closed">Closed</ToggleButton>
                <ToggleButton value="all">All</ToggleButton>
              </ToggleButtonGroup>
              <Button size="small" onClick={load} startIcon={<IconRefresh size={16} />}>
                Refresh
              </Button>
              <Button
                size="small"
                variant="contained"
                color="primary"
                disabled={!selected.length || downloading}
                onClick={handleDownload}
                startIcon={
                  downloading ? <CircularProgress size={14} /> : <IconDownload size={16} />
                }
              >
                Download {selected.length ? `(${selected.length})` : ''}
              </Button>
            </Stack>
          }
        >
          <Typography variant="caption" color="textSecondary">
            A pick list is open while its order is Open or Picking. Status comes from the
            order itself, so it is never out of step with it.
          </Typography>

          <Card variant="outlined" style={{ marginTop: 12 }}>
            <CardContent style={{ padding: 0 }}>
              <TableContainer component={Paper} elevation={0}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell padding="checkbox">
                        <Checkbox
                          indeterminate={
                            !allOnPageSelected &&
                            pageRows.some((r) => selected.includes(r.picklist_id))
                          }
                          checked={allOnPageSelected}
                          onChange={toggleAllOnPage}
                          disabled={!pageRows.length}
                        />
                      </TableCell>
                      <TableCell>Order No</TableCell>
                      <TableCell>Pick List Code</TableCell>
                      <TableCell>Dealer</TableCell>
                      <TableCell align="right">Lines</TableCell>
                      <TableCell>Order Status</TableCell>
                      <TableCell>State</TableCell>
                      <TableCell>Uploaded</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {loading && (
                      <TableRow>
                        <TableCell colSpan={8} align="center">
                          <CircularProgress size={22} />
                        </TableCell>
                      </TableRow>
                    )}

                    {!loading && !pageRows.length && (
                      <TableRow>
                        <TableCell colSpan={8} align="center">
                          <Box py={3}>
                            <IconQrcode size={28} />
                            <Typography variant="body2" color="textSecondary">
                              No {state === 'all' ? '' : state} pick lists.
                            </Typography>
                          </Box>
                        </TableCell>
                      </TableRow>
                    )}

                    {!loading &&
                      pageRows.map((row) => (
                        <TableRow
                          key={row.picklist_id}
                          hover
                          selected={selected.includes(row.picklist_id)}
                        >
                          <TableCell padding="checkbox">
                            <Checkbox
                              checked={selected.includes(row.picklist_id)}
                              onChange={() => toggleOne(row.picklist_id)}
                            />
                          </TableCell>
                          <TableCell>{row.original_order_id}</TableCell>
                          <TableCell>{row.picklist_code || '—'}</TableCell>
                          <TableCell>{row.dealer_name || '—'}</TableCell>
                          <TableCell align="right">{row.line_count}</TableCell>
                          <TableCell>{row.order_status}</TableCell>
                          <TableCell>
                            <Chip
                              size="small"
                              label={row.state}
                              color={STATE_COLOURS[row.state] || 'default'}
                            />
                          </TableCell>
                          <TableCell>
                            {row.created_at ? new Date(row.created_at).toLocaleString() : '—'}
                          </TableCell>
                        </TableRow>
                      ))}
                  </TableBody>
                </Table>
              </TableContainer>

              <TablePagination
                component="div"
                count={picklists.length}
                page={page}
                onPageChange={(e, p) => setPage(p)}
                rowsPerPage={rowsPerPage}
                onRowsPerPageChange={(e) => {
                  setRowsPerPage(parseInt(e.target.value, 10));
                  setPage(0);
                }}
                rowsPerPageOptions={[10, 25, 50, 100]}
              />
            </CardContent>
          </Card>
        </MainCard>
      </Grid>

      <Snackbar
        open={Boolean(snack)}
        autoHideDuration={5000}
        onClose={() => setSnack(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert severity={snack?.severity || 'info'} onClose={() => setSnack(null)}>
          {snack?.message}
        </Alert>
      </Snackbar>
    </Grid>
  );
};

export default PicklistUpload;
