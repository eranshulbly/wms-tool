import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useSelector } from 'react-redux';
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
import { IconUpload, IconDownload, IconPrinter, IconQrcode, IconRefresh } from '@tabler/icons';

import MainCard from '../../ui-component/cards/MainCard';
import { gridSpacing } from '../../store/constant';
import { useWarehouse } from '../../context/WarehouseContext';
import {
  uploadPicklist,
  getPicklists,
  downloadPicklists,
  setPicklistsPrinted
} from '../../services/picklistService';
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

/**
 * Send a PDF blob straight to the printer dialog.
 *
 * The whole selection is already one merged PDF, so this is one print job for the
 * stack rather than one per sheet — which is the point of selecting a batch.
 *
 * Printed from a hidden iframe rather than a new tab: a tab needs the operator to
 * find it, press Ctrl+P and then close it again, and popup blockers eat it
 * roughly half the time. The iframe route puts the print dialog up directly.
 *
 * The object URL is held until the dialog closes — revoking it earlier leaves the
 * frame printing a document the browser can no longer fetch, which prints blank.
 * If the browser refuses to print from a frame (some do), the caller falls back
 * to opening the PDF so the operator can print it by hand.
 */
const printBlob = (blob) =>
  new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const frame = document.createElement('iframe');
    frame.style.position = 'fixed';
    frame.style.right = '0';
    frame.style.bottom = '0';
    frame.style.width = '0';
    frame.style.height = '0';
    frame.style.border = '0';
    frame.src = url;

    const cleanup = () => {
      // Deferred: Chrome returns from print() before it has finished reading the
      // document, and tearing the frame down immediately cancels the job.
      setTimeout(() => {
        frame.remove();
        URL.revokeObjectURL(url);
      }, 60000);
    };

    frame.onload = () => {
      try {
        frame.contentWindow.focus();
        frame.contentWindow.print();
        cleanup();
        resolve();
      } catch (e) {
        frame.remove();
        URL.revokeObjectURL(url);
        reject(e);
      }
    };
    frame.onerror = () => {
      frame.remove();
      URL.revokeObjectURL(url);
      reject(new Error('The browser could not load the PDF for printing.'));
    };

    document.body.appendChild(frame);
  });

const PicklistUpload = () => {
  const { selectedWarehouse, selectedCompany } = useWarehouse();
  const { user } = useSelector((s) => s.account);
  const isAdmin = user?.role === 'admin';

  const [uploading, setUploading] = useState(false);
  const [uploadLog, setUploadLog] = useState([]);

  // The three filters open differently for an admin, because the two roles come
  // to this page for opposite reasons.
  //
  // Someone who uploads pick lists wants their work queue: their own sheets, not
  // yet printed, orders still live. An admin uploads nothing and has printed
  // nothing, so those same defaults would hand them an empty table and look
  // exactly like a permission fault — which is what happened. An admin is here
  // to oversee, so they open on everything and narrow down from there.
  const [state, setState] = useState(isAdmin ? 'all' : 'open');
  const [printedFilter, setPrintedFilter] = useState(isAdmin ? 'all' : 'unprinted');
  // Everyone sees their own pile. The toggle is offered to admins only, and even
  // for them this asks the server for a wider view rather than granting one —
  // the scope is decided from the token, not from this value.
  const [ownerFilter, setOwnerFilter] = useState(isAdmin ? 'all' : 'mine');
  const [picklists, setPicklists] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState([]);
  const [downloading, setDownloading] = useState(false);
  const [printing, setPrinting] = useState(false);
  const [marking, setMarking] = useState(false);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);
  const [snack, setSnack] = useState(null);

  const notify = (message, severity = 'info') => setSnack({ message, severity });

  const load = useCallback(() => {
    setLoading(true);
    getPicklists(state, selectedWarehouse, selectedCompany, printedFilter, ownerFilter)
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
  }, [state, selectedWarehouse, selectedCompany, printedFilter, ownerFilter]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    setPage(0);
  }, [state, printedFilter, ownerFilter, picklists.length]);

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
                    (result.order_created ? ' · order created' : ' · matched existing order') +
                    (result.products_created
                      ? ` · ${result.products_created} new part(s)`
                      : '') +
                    (result.replaced ? ' · replaced earlier upload' : '') +
                    (result.unresolved_parts?.length
                      ? ` · ${result.unresolved_parts.length} part(s) unresolved`
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

  // A closed sheet is finished as paper — its order has left Open, so a picker is
  // already carrying the copy that was issued. The server refuses these outright;
  // greying the buttons is just so nobody has to discover that by pressing Print.
  //
  // Closed rows can still be SELECTED, because the printed mark is still
  // correctable on them — it is only new paper that is barred.
  const closedSelected = useMemo(
    () => picklists.filter((p) => selected.includes(p.picklist_id) && p.state !== 'open'),
    [picklists, selected]
  );
  const blockedReason = closedSelected.length
    ? `${closedSelected.length} of the selected pick list(s) are closed — a sheet `
      + 'cannot be printed or downloaded once its order moves past Open.'
    : '';

  /// Both buttons fetch the same merged PDF; only what happens to it differs —
  /// and whether the server stamps the sheets as printed.
  const buildSelectedPdf = (markPrinted) => {
    if (!selected.length) {
      notify('Select at least one pick list', 'warning');
      return null;
    }
    if (selected.length > MAX_DOWNLOAD) {
      notify(`Select at most ${MAX_DOWNLOAD} pick lists at a time`, 'warning');
      return null;
    }
    return downloadPicklists(selected, selectedCompany, markPrinted);
  };

  const handleDownload = () => {
    // Saving a copy is not printing it, so this marks nothing.
    const request = buildSelectedPdf(false);
    if (!request) return;

    setDownloading(true);
    request
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

  const handlePrint = () => {
    const request = buildSelectedPdf(true);
    if (!request) return;

    setPrinting(true);
    request
      .then(async (blob) => {
        try {
          await printBlob(blob);
          notify(`Sent ${selected.length} pick list(s) to the printer`, 'success');
          // Reload so the Printed marks the server just set become visible — and
          // so the rows leave the list when the filter is "Not printed".
          load();
        } catch (e) {
          // Some browsers refuse to print from a frame. Rather than fail, hand
          // the operator the PDF so they can print it themselves — the sheets
          // are needed on the floor either way.
          const url = URL.createObjectURL(blob);
          window.open(url, '_blank', 'noopener');
          notify(
            'Your browser blocked printing directly — the PDF has been opened, '
              + 'press Ctrl+P to print it.',
            'warning'
          );
        }
      })
      .catch(async (err) => {
        notify((await readBlobError(err)) || 'Could not build the PDF', 'error');
      })
      .finally(() => setPrinting(false));
  };

  /// Correct the mark by hand — for a jam, or a Print whose dialog was cancelled.
  const handleSetPrinted = (printed) => {
    if (!selected.length) {
      notify('Select at least one pick list', 'warning');
      return;
    }
    setMarking(true);
    setPicklistsPrinted(selected, printed, selectedCompany)
      .then((data) => {
        if (data.success) {
          notify(
            `${data.updated} pick list(s) marked as ${printed ? 'printed' : 'not printed'}`,
            'success'
          );
          load();
        } else {
          notify(data.msg || 'Could not update', 'error');
        }
      })
      .catch(() => notify('Could not update the printed mark', 'error'))
      .finally(() => setMarking(false));
  };

  return (
    <Grid container spacing={gridSpacing}>
      <Grid item xs={12}>
        <MainCard title="Upload Pick Lists">
          <Typography variant="body2" color="textSecondary" gutterBottom>
            Upload pick-list PDFs printed by the DMS. Each one is matched to the order it
            names, and the order is created as Open if it does not exist yet. An order
            that already exists keeps its current status. Part lines are imported and a
            QR code is minted for the sheet.
          </Typography>
          <Typography variant="body2" color="textSecondary" gutterBottom>
            Scanning that QR later is what moves the order along. An order created from a
            pick list carries only what the sheet prints — order number, date, dealer and
            city; B2B PO#, order type, VIN and shipping address stay empty.
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
              {/* Kept separate from the Open/Closed group on purpose: they answer
                  different questions (where the ORDER is vs whether the SHEET has
                  been printed), and merging them into one dropdown would hide
                  half the combinations — "closed but never printed" is exactly
                  the anomaly worth being able to look for. */}
              <ToggleButtonGroup
                size="small"
                exclusive
                value={printedFilter}
                onChange={(e, v) => v && setPrintedFilter(v)}
              >
                <ToggleButton value="unprinted">Not printed</ToggleButton>
                <ToggleButton value="printed">Printed</ToggleButton>
                <ToggleButton value="all">Any</ToggleButton>
              </ToggleButtonGroup>
              {/* Admins only. Everyone else has no toggle because there is nothing
                  to toggle: the server scopes their list to their own uploads
                  whatever this asks for. Offering a control that does nothing
                  would read as a permission the user does not have. */}
              {isAdmin && (
                <ToggleButtonGroup
                  size="small"
                  exclusive
                  value={ownerFilter}
                  onChange={(e, v) => v && setOwnerFilter(v)}
                >
                  <ToggleButton value="mine">Mine</ToggleButton>
                  <ToggleButton value="all">Everyone</ToggleButton>
                </ToggleButtonGroup>
              )}
              <Button size="small" onClick={load} startIcon={<IconRefresh size={16} />}>
                Refresh
              </Button>
              <Button
                size="small"
                disabled={!selected.length || marking || printing || downloading}
                onClick={() => handleSetPrinted(printedFilter !== 'printed')}
              >
                {printedFilter === 'printed' ? 'Mark not printed' : 'Mark printed'}
              </Button>
              <Button
                size="small"
                disabled={
                  !selected.length || downloading || printing || Boolean(blockedReason)
                }
                title={blockedReason}
                onClick={handleDownload}
                startIcon={
                  downloading ? <CircularProgress size={14} /> : <IconDownload size={16} />
                }
              >
                Download
              </Button>
              {/* Print is the primary action: these sheets exist to be carried
                  round a warehouse on paper, and the selection is already one
                  merged PDF, so the whole batch is a single print job. */}
              <Button
                size="small"
                variant="contained"
                color="primary"
                disabled={
                  !selected.length || downloading || printing || Boolean(blockedReason)
                }
                title={blockedReason}
                onClick={handlePrint}
                startIcon={
                  printing ? <CircularProgress size={14} /> : <IconPrinter size={16} />
                }
              >
                Print {selected.length ? `(${selected.length})` : ''}
              </Button>
            </Stack>
          }
        >
          <Typography variant="caption" color="textSecondary">
            A pick list is open only while its order is Open. Once a picker scans the QR
            and the order moves to Picking, the sheet closes and cannot be printed or
            downloaded again — the paper copy is already on the floor. Status comes from
            the order itself, so it is never out of step with it.
          </Typography>

          {/* Said out loud, not left to a tooltip: a disabled MUI button swallows
              hover events, so a title attribute on it is often never seen. */}
          {blockedReason && (
            <Box mt={1}>
              <Alert severity="info">{blockedReason}</Alert>
            </Box>
          )}

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
                      <TableCell align="right" style={{ width: 48 }}>
                        S. No.
                      </TableCell>
                      <TableCell>Order No</TableCell>
                      <TableCell>Pick List Code</TableCell>
                      <TableCell>Dealer</TableCell>
                      <TableCell align="right">Lines</TableCell>
                      <TableCell>Order Status</TableCell>
                      <TableCell>State</TableCell>
                      <TableCell>Printed</TableCell>
                      <TableCell>Uploaded By</TableCell>
                      <TableCell>Uploaded</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {loading && (
                      <TableRow>
                        <TableCell colSpan={11} align="center">
                          <CircularProgress size={22} />
                        </TableCell>
                      </TableRow>
                    )}

                    {!loading && !pageRows.length && (
                      <TableRow>
                        <TableCell colSpan={11} align="center">
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
                      pageRows.map((row, idx) => (
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
                          {/* Counts DOWN the page, so the newest upload carries
                              the highest number and the first one ever uploaded
                              is 1 — the number follows the sheet rather than the
                              row it happens to occupy.

                              Numbering the top row 1 would have meant the same
                              sheet changing number every time another was
                              uploaded above it, which is the opposite of what a
                              serial number is for. Continuous across pages for
                              the same reason. */}
                          <TableCell align="right">
                            {picklists.length - (page * rowsPerPage + idx)}
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
                            {row.printed_at ? (
                              <Stack spacing={0.25}>
                                <Stack direction="row" spacing={0.5} alignItems="center">
                                <Chip
                                  size="small"
                                  color="primary"
                                  label={new Date(row.printed_at).toLocaleDateString()}
                                  title={
                                    `Printed ${new Date(row.printed_at).toLocaleString()}` +
                                    (row.printed_by_name ? ` by ${row.printed_by_name}` : '')
                                  }
                                />
                                {/* A reprint means a second paper copy of the same
                                    QR is loose on the floor, and two people can
                                    each scan it and move the same order. Flagged
                                    in the open, not buried in a tooltip. */}
                                {row.print_count > 1 && (
                                  <Chip
                                    size="small"
                                    color="secondary"
                                    label={`×${row.print_count}`}
                                    title={
                                      `Printed ${row.print_count} times — more than one ` +
                                      'paper copy of this sheet may be in circulation'
                                    }
                                  />
                                )}
                                </Stack>
                                {/* Who printed it, in the open rather than in a
                                    tooltip — a tooltip is invisible to anyone
                                    scanning down the column to see who issued
                                    what. */}
                                {row.printed_by_name && (
                                  <Typography variant="caption" color="textSecondary">
                                    by {row.printed_by_name}
                                  </Typography>
                                )}
                              </Stack>
                            ) : (
                              <Typography variant="body2" color="textSecondary">
                                —
                              </Typography>
                            )}
                          </TableCell>
                          <TableCell>{row.uploaded_by_name || '—'}</TableCell>
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
