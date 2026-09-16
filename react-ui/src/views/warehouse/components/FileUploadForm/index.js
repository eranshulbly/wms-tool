import React, { useRef, useState } from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Divider,
  FormControl,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Typography,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  ListItemSecondaryAction,
  IconButton
} from '@material-ui/core';
import { makeStyles, useTheme } from '@material-ui/styles';
import CloudUploadIcon from '@material-ui/icons/CloudUpload';
import DescriptionIcon from '@material-ui/icons/Description';
import ErrorOutlineIcon from '@material-ui/icons/ErrorOutline';
import CheckCircleOutlineIcon from '@material-ui/icons/CheckCircleOutline';
import WarningIcon from '@material-ui/icons/Warning';
import HourglassEmptyIcon from '@material-ui/icons/HourglassEmpty';
import BlockIcon from '@material-ui/icons/Block';
import CloseIcon from '@material-ui/icons/Close';
import { Snackbar, Alert } from '@material-ui/core';
import AnimateButton from '../../../../ui-component/extended/AnimateButton';
import UploadResultCard, { downloadErrorExcel } from '../../../../components/UploadResultCard';
import { useWarehouse } from '../../../../context/WarehouseContext';
import { useSnackbar } from '../../../../hooks/useSnackbar';
import api from '../../../../services/api';

const useStyles = makeStyles((theme) => ({
  uploadCard: {
    background: theme.palette.background.default,
    border: '1px dashed',
    borderColor: theme.palette.grey[300],
    borderRadius: '8px',
    padding: '16px',
    cursor: 'pointer',
    textAlign: 'center',
    transition: 'border-color 0.2s ease-in-out',
    '&:hover': { borderColor: theme.palette.primary.main }
  },
  uploadIcon: {
    fontSize: '3rem',
    color: theme.palette.grey[400],
    marginBottom: '8px'
  },
  fileInfo: {
    display: 'flex',
    alignItems: 'center',
    padding: '16px',
    background: theme.palette.primary.light,
    borderRadius: '8px',
    marginTop: '16px'
  },
  fileIcon: {
    fontSize: '2rem',
    marginRight: '8px',
    color: theme.palette.primary.dark
  },
  fileName: { wordBreak: 'break-all' },
  uploadProgress: {
    marginTop: '24px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'column'
  },
  errorIcon: {
    fontSize: '3rem',
    color: theme.palette.error.main,
    marginBottom: '8px'
  },
  dropzoneActive: {
    borderColor: theme.palette.primary.main,
    background: theme.palette.primary.light
  },
  loadingContainer: {
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    height: '100%',
    width: '100%',
    padding: '20px'
  },
  queueList: {
    marginTop: '16px',
    maxHeight: '360px',
    overflowY: 'auto',
    border: `1px solid ${theme.palette.divider}`,
    borderRadius: '8px'
  },
  queueSummary: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: '16px',
    flexWrap: 'wrap',
    gap: '8px'
  }
}));

// PDFs are accepted alongside spreadsheets: the backend renders a supplier PDF into the
// same column shape the sheets use (api/shared/pdf_upload_adapter), so every upload on
// this form takes either. All three consumers — orders, invoices, products — run through
// the same pipeline, so the list does not vary by screen.
const VALID_TYPES = [
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'text/csv',
  'application/csv',
  'application/pdf'
];

const ACCEPT_ATTR = '.xlsx,.xls,.csv,.pdf';
const SUPPORTED_LABEL = '.xlsx, .xls, .csv, .pdf';

const QUEUE_ICON = {
  pending: <HourglassEmptyIcon color="disabled" />,
  uploading: <CircularProgress size={20} />,
  success: <CheckCircleOutlineIcon style={{ color: '#4caf50' }} />,
  error: <ErrorOutlineIcon color="error" />,
  needs_approval: <WarningIcon style={{ color: '#f9a825' }} />,
  skipped: <BlockIcon color="disabled" />
};

const queueStatusLabel = (item) => {
  switch (item.status) {
    case 'pending':
      return 'Waiting to upload…';
    case 'uploading':
      return 'Uploading…';
    case 'needs_approval':
      return 'Needs your approval — see the dialog';
    case 'skipped':
      return 'Skipped — nothing was saved';
    case 'success': {
      const r = item.result || {};
      return `Processed ${r.processed_count ?? 0}` + (r.error_count > 0 ? ` · ${r.error_count} row(s) failed` : '');
    }
    case 'error':
      return item.result?.msg || 'Processing failed';
    default:
      return '';
  }
};

/**
 * Generic drag-and-drop file upload form driven by props.
 *
 * Props:
 *   endpoint          — API path (relative to config.API_SERVER), e.g. 'orders/upload'
 *   maxSizeMB         — max file size in MB (default 10)
 *   requiresWarehouse — show warehouse selector (default true)
 *   requiresCompany   — show company selector (default true)
 *   allowMultiple     — accept several files at once, uploaded one at a time against the
 *                       same endpoint (default false — unchanged single-file behaviour)
 *   successLabel      — label for processed count chip in UploadResultCard
 *   errorFilename     — base filename for downloadable error report (no date or .xlsx)
 *   processingMessage — text shown while the upload is in-flight
 *   descriptionNode    — ReactNode shown below the form title
 *   rulesNode          — ReactNode shown in the right-side rules box
 *   computeExtraStats — (responseData) => [{label, value, color}] for UploadResultCard
 *   uploadButtonLabel — default 'Process File'
 *   inputId           — unique id for the hidden file input (avoids collisions on same page)
 */
const FileUploadForm = ({
  endpoint,
  maxSizeMB = 10,
  requiresWarehouse = true,
  requiresCompany = true,
  allowMultiple = false,
  successLabel = 'Records Processed',
  errorFilename = 'upload_errors',
  processingMessage = 'Processing file…',
  descriptionNode,
  rulesNode,
  computeExtraStats,
  uploadButtonLabel = 'Process File',
  inputId = 'file-upload-input'
}) => {
  const classes = useStyles();
  const theme = useTheme();

  const {
    warehouses,
    companies,
    selectedWarehouse,
    setSelectedWarehouse,
    selectedCompany,
    setSelectedCompany,
    loading: contextLoading,
    error: contextError
  } = useWarehouse();

  const { snackbar, showSnackbar, hideSnackbar } = useSnackbar();

  // Single-file state (allowMultiple = false, the original behaviour).
  const [file, setFile] = useState(null);
  const [uploadStatus, setUploadStatus] = useState(null); // null | 'uploading' | 'success' | 'error'
  const [uploadResults, setUploadResults] = useState(null);
  const [approval, setApproval] = useState(null); // backend asked a question before writing

  // Multi-file state (allowMultiple = true) — a queue processed one file at a time so
  // each upload runs through the same duplicate-detection and business logic it would
  // if the operator uploaded it on its own.
  const [queue, setQueue] = useState([]); // [{id, file, status, result, approval}]
  const nextQueueId = useRef(0);

  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  const errorDate = new Date().toISOString().split('T')[0];

  // ── shared upload call ──────────────────────────────────────────────────────
  const postFile = (theFile, approvals) => {
    const formData = new FormData();
    formData.append('file', theFile);
    if (requiresWarehouse) formData.append('warehouse_id', selectedWarehouse);
    if (requiresCompany) formData.append('company_id', selectedCompany);
    if (approvals) Object.entries(approvals).forEach(([k, v]) => formData.append(k, v));
    return api.post(endpoint, formData, { headers: { 'Content-Type': 'multipart/form-data' } });
  };

  // ── single-file mode ────────────────────────────────────────────────────────
  const validateAndSetFile = (selectedFile) => {
    if (!VALID_TYPES.includes(selectedFile.type)) {
      showSnackbar('Please upload an Excel, CSV or PDF file', 'error');
      return;
    }
    if (selectedFile.size > maxSizeMB * 1024 * 1024) {
      showSnackbar(`File size exceeds ${maxSizeMB}MB limit`, 'error');
      return;
    }
    setFile(selectedFile);
    setUploadStatus(null);
    setUploadResults(null);
  };

  // `approvals` carries the operator's answers to anything the backend asked about — see
  // the needs_approval branch below. The same file is simply re-posted with the answer, so
  // no partially-processed upload is left waiting on the server for a decision.
  const handleUpload = (approvals = null) => {
    if (!file) { showSnackbar('Please select a file to upload', 'warning'); return; }
    if (requiresWarehouse && !selectedWarehouse) { showSnackbar('Please select a warehouse', 'warning'); return; }
    if (requiresCompany && !selectedCompany) { showSnackbar('Please select a company', 'warning'); return; }

    setIsUploading(true);
    setUploadStatus('uploading');
    setApproval(null);

    postFile(file, approvals)
      .then((response) => {
        const data = response.data;

        // The backend stopped to ask something rather than guessing. Nothing has been
        // written at this point, so declining is a genuine no-op.
        if (data.needs_approval) {
          setApproval(data);
          setUploadStatus(null);
          return;
        }

        setUploadResults(data);
        if (data.success) {
          setUploadStatus('success');
          showSnackbar(
            `Processed ${data.processed_count} record(s)` +
              (data.error_count > 0 ? ` — ${data.error_count} row(s) failed` : ''),
            data.error_count > 0 ? 'warning' : 'success'
          );
        } else {
          setUploadStatus('error');
          showSnackbar(data.msg || 'Processing failed', 'error');
        }
      })
      .catch((error) => {
        setUploadStatus('error');
        setUploadResults(error.response?.data || null);
        showSnackbar(error.response?.data?.msg || 'Error processing file', 'error');
      })
      .finally(() => {
        setIsUploading(false);
      });
  };

  const resetUpload = () => {
    setFile(null);
    setUploadStatus(null);
    setUploadResults(null);
  };

  // ── multi-file mode ─────────────────────────────────────────────────────────
  const addFiles = (fileList) => {
    const incoming = Array.from(fileList || []);
    const accepted = [];
    const rejected = [];

    incoming.forEach((f) => {
      if (!VALID_TYPES.includes(f.type)) { rejected.push(`${f.name} (unsupported type)`); return; }
      if (f.size > maxSizeMB * 1024 * 1024) { rejected.push(`${f.name} (over ${maxSizeMB}MB)`); return; }
      const already =
        queue.some((q) => q.file.name === f.name && q.file.size === f.size) ||
        accepted.some((a) => a.name === f.name && a.size === f.size);
      if (already) { rejected.push(`${f.name} (already added)`); return; }
      accepted.push(f);
    });

    if (accepted.length) {
      setQueue((q) => [
        ...q,
        ...accepted.map((f) => ({ id: nextQueueId.current++, file: f, status: 'pending', result: null, approval: null }))
      ]);
    }
    if (rejected.length) {
      showSnackbar(`Skipped: ${rejected.join(', ')}`, 'warning');
    }
  };

  const removeQueueItem = (id) => setQueue((q) => q.filter((item) => item.id !== id));
  const resetQueue = () => setQueue([]);

  const setQueueItem = (id, patch) => setQueue((q) => q.map((item) => (item.id === id ? { ...item, ...patch } : item)));

  // Walks `items` from `startIndex`, uploading each still-pending file in turn. Stops
  // (without finishing) the moment one needs approval — resumed by approveQueueItem /
  // rejectQueueItem once the operator answers, rather than guessing and writing anyway.
  const runQueueFrom = async (startIndex, items) => {
    for (let i = startIndex; i < items.length; i += 1) {
      const item = items[i];
      if (item.status !== 'pending') continue; // eslint-disable-line no-continue

      setQueueItem(item.id, { status: 'uploading' });
      try {
        const res = await postFile(item.file, null);
        const data = res.data;
        if (data.needs_approval) {
          setQueueItem(item.id, { status: 'needs_approval', approval: data });
          setIsUploading(false);
          return;
        }
        setQueueItem(item.id, { status: data.success ? 'success' : 'error', result: data });
      } catch (e) {
        setQueueItem(item.id, {
          status: 'error',
          result: e.response?.data || { success: false, msg: 'Upload failed' }
        });
      }
    }
    setIsUploading(false);
    showSnackbar('All files processed', 'info');
  };

  const startQueue = () => {
    if (!queue.length) { showSnackbar('Please add at least one file', 'warning'); return; }
    if (requiresWarehouse && !selectedWarehouse) { showSnackbar('Please select a warehouse', 'warning'); return; }
    if (requiresCompany && !selectedCompany) { showSnackbar('Please select a company', 'warning'); return; }
    setIsUploading(true);
    runQueueFrom(0, queue);
  };

  const approvalItem = queue.find((q) => q.status === 'needs_approval');

  const approveQueueItem = async () => {
    const item = approvalItem;
    if (!item) return;
    setIsUploading(true);
    setQueueItem(item.id, { status: 'uploading', approval: null });
    try {
      const res = await postFile(item.file, { [item.approval.needs_approval]: 'true' });
      const data = res.data;
      setQueueItem(item.id, { status: data.success ? 'success' : 'error', result: data });
    } catch (e) {
      setQueueItem(item.id, {
        status: 'error',
        result: e.response?.data || { success: false, msg: 'Upload failed' }
      });
    }
    const idx = queue.findIndex((q) => q.id === item.id);
    runQueueFrom(idx + 1, queue);
  };

  const rejectQueueItem = () => {
    const item = approvalItem;
    if (!item) return;
    setQueueItem(item.id, { status: 'skipped', approval: null });
    showSnackbar(`${item.file.name} skipped — nothing was saved`, 'info');
    const idx = queue.findIndex((q) => q.id === item.id);
    runQueueFrom(idx + 1, queue);
  };

  const queueAllDone = queue.length > 0 && queue.every((q) => ['success', 'error', 'skipped'].includes(q.status));
  const queueSucceeded = queue.filter((q) => q.status === 'success').length;
  const queueFailed = queue.filter((q) => q.status === 'error' || q.status === 'skipped').length;
  const queueProcessedTotal = queue.reduce((sum, q) => sum + (q.result?.processed_count || 0), 0);

  if (contextLoading) {
    return (
      <div className={classes.loadingContainer}>
        <CircularProgress />
        <Typography variant="body1" style={{ marginLeft: '16px' }}>
          Loading required data…
        </Typography>
      </div>
    );
  }

  if (contextError) {
    return (
      <div style={{ textAlign: 'center', padding: '40px 20px' }}>
        <ErrorOutlineIcon className={classes.errorIcon} />
        <Typography variant="h5" color="error" gutterBottom>Error Loading Data</Typography>
        <Typography variant="body1" gutterBottom>{contextError}</Typography>
        <Button variant="contained" color="primary" style={{ marginTop: '20px' }} onClick={() => window.location.reload()}>
          Retry
        </Button>
      </div>
    );
  }

  const extraStats = uploadResults && computeExtraStats ? computeExtraStats(uploadResults) : [];

  // Unifies the single-file and queued "needs approval" dialogs behind one component.
  const activeApproval = allowMultiple ? approvalItem?.approval : approval;
  const activeApprovalFilename = allowMultiple ? approvalItem?.file?.name : file?.name;
  const onApproveDialog = allowMultiple ? approveQueueItem : () => handleUpload({ [approval.needs_approval]: 'true' });
  const onRejectDialog = allowMultiple
    ? rejectQueueItem
    : () => {
        setApproval(null);
        showSnackbar('Upload cancelled — nothing was saved', 'info');
      };

  const selectorsLocked = allowMultiple
    ? isUploading || (queueAllDone && queue.length > 0)
    : isUploading || uploadStatus === 'success';

  return (
    <>
      <Grid container spacing={3}>
        <Grid item xs={12}>
          <Grid container spacing={3}>
            {/* Left column — drop zone + results */}
            <Grid item lg={8} md={6} sm={12} xs={12}>
              <Card>
                <CardContent>
                  <Grid container spacing={2}>
                    {descriptionNode && (
                      <Grid item xs={12}>
                        {descriptionNode}
                      </Grid>
                    )}

                    {allowMultiple ? (
                      <>
                        <Grid item xs={12}>
                          <div
                            className={`${classes.uploadCard} ${isDragging ? classes.dropzoneActive : ''}`}
                            onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                            onDragLeave={(e) => { e.preventDefault(); setIsDragging(false); }}
                            onDrop={(e) => {
                              e.preventDefault();
                              setIsDragging(false);
                              if (!isUploading) addFiles(e.dataTransfer.files);
                            }}
                            onClick={() => !isUploading && document.getElementById(inputId).click()}
                          >
                            <input
                              type="file"
                              id={inputId}
                              multiple
                              style={{ display: 'none' }}
                              accept={ACCEPT_ATTR}
                              onChange={(e) => {
                                addFiles(e.target.files);
                                e.target.value = null; // allow re-selecting the same file later
                              }}
                            />
                            <CloudUploadIcon className={classes.uploadIcon} />
                            <Typography variant="h6" gutterBottom>
                              Drag &amp; Drop files here
                            </Typography>
                            <Typography variant="body2" color="textSecondary">
                              or click to browse — you can select several files at once
                            </Typography>
                            <Typography variant="caption" color="textSecondary" style={{ marginTop: '8px' }}>
                              Supported formats: {SUPPORTED_LABEL} (Max {maxSizeMB}MB each)
                            </Typography>
                          </div>
                        </Grid>

                        {queue.length > 0 && (
                          <Grid item xs={12}>
                            <List dense className={classes.queueList}>
                              {queue.map((item) => (
                                <ListItem key={item.id}>
                                  <ListItemIcon>{QUEUE_ICON[item.status]}</ListItemIcon>
                                  <ListItemText
                                    primary={item.file.name}
                                    secondary={queueStatusLabel(item)}
                                  />
                                  {item.status === 'pending' && !isUploading && (
                                    <ListItemSecondaryAction>
                                      <IconButton size="small" onClick={() => removeQueueItem(item.id)}>
                                        <CloseIcon fontSize="small" />
                                      </IconButton>
                                    </ListItemSecondaryAction>
                                  )}
                                  {item.status === 'success' && item.result?.error_count > 1 && item.result?.error_report && (
                                    <ListItemSecondaryAction>
                                      <Button
                                        size="small"
                                        onClick={() => downloadErrorExcel(
                                          item.result.error_report,
                                          `${errorFilename}_${item.file.name.replace(/\.[^.]+$/, '')}_${errorDate}.xlsx`
                                        )}
                                      >
                                        Errors
                                      </Button>
                                    </ListItemSecondaryAction>
                                  )}
                                </ListItem>
                              ))}
                            </List>

                            <Box className={classes.queueSummary}>
                              <Typography variant="body2" color="textSecondary">
                                {queueAllDone
                                  ? `Done — ${queueSucceeded} succeeded, ${queueFailed} failed/skipped, ${queueProcessedTotal} record(s) processed in total`
                                  : `${queue.length} file${queue.length === 1 ? '' : 's'} queued`}
                              </Typography>
                              {(queueAllDone || (!isUploading && !approvalItem)) && queue.length > 0 && (
                                <Button size="small" onClick={resetQueue} disabled={isUploading}>
                                  {queueAllDone ? 'Upload More Files' : 'Clear All'}
                                </Button>
                              )}
                            </Box>
                          </Grid>
                        )}
                      </>
                    ) : (
                      <>
                        <Grid item xs={12}>
                          <div
                            className={`${classes.uploadCard} ${isDragging ? classes.dropzoneActive : ''}`}
                            onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                            onDragLeave={(e) => { e.preventDefault(); setIsDragging(false); }}
                            onDrop={(e) => {
                              e.preventDefault();
                              setIsDragging(false);
                              if (e.dataTransfer.files?.[0]) validateAndSetFile(e.dataTransfer.files[0]);
                            }}
                            onClick={() => document.getElementById(inputId).click()}
                          >
                            <input
                              type="file"
                              id={inputId}
                              style={{ display: 'none' }}
                              accept={ACCEPT_ATTR}
                              onChange={(e) => { if (e.target.files?.[0]) validateAndSetFile(e.target.files[0]); }}
                            />
                            {!file ? (
                              <>
                                <CloudUploadIcon className={classes.uploadIcon} />
                                <Typography variant="h6" gutterBottom>
                                  Drag &amp; Drop your file here
                                </Typography>
                                <Typography variant="body2" color="textSecondary">
                                  or click to browse
                                </Typography>
                                <Typography variant="caption" color="textSecondary" style={{ marginTop: '8px' }}>
                                  Supported formats: {SUPPORTED_LABEL} (Max {maxSizeMB}MB)
                                </Typography>
                              </>
                            ) : (
                              <div className={classes.fileInfo}>
                                <DescriptionIcon className={classes.fileIcon} />
                                <div>
                                  <Typography variant="subtitle1" className={classes.fileName}>
                                    {file.name}
                                  </Typography>
                                  <Typography variant="caption" color="textSecondary">
                                    {(file.size / 1024).toFixed(2)} KB
                                  </Typography>
                                </div>
                              </div>
                            )}
                          </div>
                        </Grid>

                        {uploadStatus === 'uploading' && (
                          <Grid item xs={12}>
                            <div className={classes.uploadProgress}>
                              <CircularProgress size={40} />
                              <Typography variant="body1" style={{ marginTop: '16px' }}>
                                {processingMessage}
                              </Typography>
                            </div>
                          </Grid>
                        )}

                        {(uploadStatus === 'success' || uploadStatus === 'error') && uploadResults && (
                          <Grid item xs={12}>
                            <UploadResultCard
                              result={uploadResults}
                              onReset={resetUpload}
                              successLabel={successLabel}
                              errorFilename={`${errorFilename}_${errorDate}.xlsx`}
                              extraStats={extraStats}
                            />
                          </Grid>
                        )}
                      </>
                    )}
                  </Grid>
                </CardContent>
              </Card>
            </Grid>

            {/* Right column — selectors + rules */}
            <Grid item lg={4} md={6} sm={12} xs={12}>
              <Card>
                <CardContent>
                  <Grid container spacing={2}>
                    <Grid item xs={12}>
                      <Typography variant="h4" gutterBottom>Upload Settings</Typography>
                      <Divider sx={{ my: 1.5 }} />
                    </Grid>

                    {requiresWarehouse && (
                      <Grid item xs={12}>
                        <FormControl fullWidth>
                          <InputLabel id={`${inputId}-warehouse-label`}>Warehouse</InputLabel>
                          <Select
                            labelId={`${inputId}-warehouse-label`}
                            value={selectedWarehouse}
                            label="Warehouse"
                            onChange={(e) => setSelectedWarehouse(e.target.value)}
                            disabled={selectorsLocked}
                          >
                            <MenuItem value=""><em>Select a warehouse</em></MenuItem>
                            {warehouses.map((wh) => {
                              const id = wh.warehouse_id ?? wh.id;
                              return <MenuItem key={id} value={id}>{wh.name}</MenuItem>;
                            })}
                          </Select>
                        </FormControl>
                      </Grid>
                    )}

                    {requiresCompany && (
                      <Grid item xs={12}>
                        <FormControl fullWidth>
                          <InputLabel id={`${inputId}-company-label`}>Company</InputLabel>
                          <Select
                            labelId={`${inputId}-company-label`}
                            value={selectedCompany}
                            label="Company"
                            onChange={(e) => setSelectedCompany(e.target.value)}
                            disabled={selectorsLocked}
                          >
                            <MenuItem value=""><em>Select a company</em></MenuItem>
                            {companies.map((company) => (
                              <MenuItem key={company.id} value={company.id}>{company.name}</MenuItem>
                            ))}
                          </Select>
                        </FormControl>
                      </Grid>
                    )}

                    <Grid item xs={12} style={{ marginTop: '16px' }}>
                      <AnimateButton>
                        <Button
                          variant="contained"
                          color="primary"
                          fullWidth
                          startIcon={<CloudUploadIcon />}
                          disabled={
                            allowMultiple
                              ? !queue.length ||
                                (requiresWarehouse && !selectedWarehouse) ||
                                (requiresCompany && !selectedCompany) ||
                                isUploading ||
                                !!approvalItem ||
                                queueAllDone
                              : !file ||
                                (requiresWarehouse && !selectedWarehouse) ||
                                (requiresCompany && !selectedCompany) ||
                                isUploading ||
                                uploadStatus === 'success'
                          }
                          onClick={() => (allowMultiple ? startQueue() : handleUpload())}
                        >
                          {isUploading
                            ? 'Processing…'
                            : allowMultiple
                            ? `Upload ${queue.length} File${queue.length === 1 ? '' : 's'}`
                            : uploadButtonLabel}
                        </Button>
                      </AnimateButton>
                    </Grid>

                    {rulesNode && (
                      <Grid item xs={12} style={{ marginTop: '16px' }}>
                        <Box p={2} bgcolor={theme.palette.primary.light} borderRadius="8px">
                          {rulesNode}
                        </Box>
                      </Grid>
                    )}
                  </Grid>
                </CardContent>
              </Card>
            </Grid>
          </Grid>
        </Grid>
      </Grid>

      {/* The backend asks before writing anything it had to guess at. Approving re-posts
          the same file with the answer; rejecting simply discards it, and because nothing
          was written on the first attempt there is nothing to undo. In multi-file mode the
          rest of the queue resumes automatically once this file is resolved. */}
      <Dialog open={!!activeApproval} onClose={onRejectDialog} maxWidth="sm" fullWidth>
        <DialogTitle>Missing product numbers{activeApprovalFilename ? ` — ${activeApprovalFilename}` : ''}</DialogTitle>
        <DialogContent>
          <DialogContentText>{activeApproval?.msg}</DialogContentText>
          {activeApproval?.sample?.length > 0 && (
            <>
              <Typography variant="subtitle2" sx={{ mt: 2, mb: 1 }}>
                Examples of what would be created
                {activeApproval.missing_count > activeApproval.sample.length
                  ? ` (first ${activeApproval.sample.length} of ${activeApproval.missing_count})`
                  : ''}
              </Typography>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Row</TableCell>
                    <TableCell>Description</TableCell>
                    <TableCell>Product number</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {activeApproval.sample.map((r) => (
                    <TableRow key={r.row}>
                      <TableCell>{r.row}</TableCell>
                      <TableCell>{r.description}</TableCell>
                      <TableCell sx={{ fontFamily: 'monospace' }}>{r.generated}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <Typography variant="caption" color="textSecondary" sx={{ display: 'block', mt: 2 }}>
                These become permanent product codes. Reject if the supplier will issue its
                own — a generated code cannot be reconciled with a real one afterwards.
              </Typography>
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={onRejectDialog}>Reject</Button>
          <Button variant="contained" onClick={onApproveDialog}>
            Approve &amp; upload
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={hideSnackbar}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert onClose={hideSnackbar} severity={snackbar.severity} sx={{ width: '100%' }}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </>
  );
};

export default FileUploadForm;
