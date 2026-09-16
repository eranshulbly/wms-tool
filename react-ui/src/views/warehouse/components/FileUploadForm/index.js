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
  TableRow
} from '@material-ui/core';
import { makeStyles, useTheme } from '@material-ui/styles';
import CloudUploadIcon from '@material-ui/icons/CloudUpload';
import DescriptionIcon from '@material-ui/icons/Description';
import ErrorOutlineIcon from '@material-ui/icons/ErrorOutline';
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

/**
 * Generic drag-and-drop file upload form driven by props.
 *
 * Props:
 *   endpoint          — API path (relative to config.API_SERVER), e.g. 'orders/upload'
 *   maxSizeMB         — max file size in MB (default 10)
 *   requiresWarehouse — show warehouse selector (default true)
 *   requiresCompany   — show company selector (default true)
 *   successLabel      — label for processed count chip in UploadResultCard
 *   errorFilename     — base filename for downloadable error report (no date or .xlsx)
 *   processingMessage — text shown while the upload is in-flight
 *   descriptionNode   — ReactNode shown below the form title
 *   rulesNode         — ReactNode shown in the right-side rules box
 *   computeExtraStats — (responseData) => [{label, value, color}] for UploadResultCard
 *   uploadButtonLabel — default 'Process File'
 *   inputId           — unique id for the hidden file input (avoids collisions on same page)
 */
const FileUploadForm = ({
  endpoint,
  maxSizeMB = 10,
  requiresWarehouse = true,
  requiresCompany = true,
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

  // Several files can be chosen at once. Each is still uploaded as its OWN request, one
  // after another, so every file goes through the same server pipeline a single upload
  // does — duplicate checks, error reports, the approval prompt — and one bad file fails
  // only itself rather than taking the rest of the batch down with it.
  const [files, setFiles] = useState([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState(null); // null | 'uploading' | 'success' | 'error'
  const [uploadResults, setUploadResults] = useState(null); // single-file result (unchanged UX)
  const [batchResults, setBatchResults] = useState([]);     // one entry per file when >1
  const [progress, setProgress] = useState(null);           // { done, total, name }
  const [approval, setApproval] = useState(null); // backend asked a question before writing
  // Resolves the pending approval when the dialog is answered, so the queue can wait on it.
  const approvalResolver = useRef(null);

  const addFiles = (fileList) => {
    const accepted = [];
    const rejected = [];
    Array.from(fileList || []).forEach((f) => {
      if (f.size === 0) {
        // A zero-byte file is a download that never finished. Sent to the server it fails
        // with "No /Root object!", which says nothing useful; caught here it says what to do.
        rejected.push(`${f.name}: the file is empty (0 bytes) — download it again`);
      } else if (!VALID_TYPES.includes(f.type) && !/\.(xlsx|xls|csv|pdf)$/i.test(f.name)) {
        rejected.push(`${f.name}: not an Excel, CSV or PDF file`);
      } else if (f.size > maxSizeMB * 1024 * 1024) {
        rejected.push(`${f.name}: larger than ${maxSizeMB}MB`);
      } else {
        accepted.push(f);
      }
    });
    if (rejected.length) showSnackbar(rejected.join(' · '), 'error');
    if (!accepted.length) return;
    setFiles((prev) => {
      // Picking the same file twice should not upload it twice.
      const seen = new Set(prev.map((f) => `${f.name}|${f.size}|${f.lastModified}`));
      return [...prev, ...accepted.filter((f) => !seen.has(`${f.name}|${f.size}|${f.lastModified}`))];
    });
    setUploadStatus(null);
    setUploadResults(null);
    setBatchResults([]);
  };

  const removeFile = (index) => setFiles((prev) => prev.filter((_, i) => i !== index));

  const handleDragOver = (e) => { e.preventDefault(); setIsDragging(true); };
  const handleDragLeave = (e) => { e.preventDefault(); setIsDragging(false); };
  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    addFiles(e.dataTransfer.files);
  };
  const handleFileSelect = (e) => {
    addFiles(e.target.files);
    // Cleared so choosing the same file again still fires onChange.
    e.target.value = '';
  };

  // `approvals` carries the operator's answers to anything the backend asked about — see
  // the needs_approval branch below. The same file is simply re-posted with the answer, so
  // no partially-processed upload is left waiting on the server for a decision.
  const postOne = async (f, approvals = null) => {
    const formData = new FormData();
    formData.append('file', f);
    if (requiresWarehouse) formData.append('warehouse_id', selectedWarehouse);
    if (requiresCompany) formData.append('company_id', selectedCompany);
    if (approvals) Object.entries(approvals).forEach(([k, v]) => formData.append(k, v));
    try {
      const response = await api.post(endpoint, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      return response.data;
    } catch (error) {
      // A 4xx still carries a useful body (msg, error_report); keep it.
      return error.response?.data || { success: false, msg: error.message || 'Error processing file' };
    }
  };

  // Waits for the operator to answer the approval dialog. Resolves true to approve.
  const askApproval = (data) =>
    new Promise((resolve) => {
      approvalResolver.current = resolve;
      setApproval(data);
    });

  const answerApproval = (approved) => {
    const resolve = approvalResolver.current;
    approvalResolver.current = null;
    setApproval(null);
    if (resolve) resolve(approved);
  };

  const handleUpload = async () => {
    if (!files.length) { showSnackbar('Please select a file to upload', 'warning'); return; }
    if (requiresWarehouse && !selectedWarehouse) { showSnackbar('Please select a warehouse', 'warning'); return; }
    if (requiresCompany && !selectedCompany) { showSnackbar('Please select a company', 'warning'); return; }

    setIsUploading(true);
    setUploadStatus('uploading');
    setUploadResults(null);
    setBatchResults([]);

    const results = [];
    for (let i = 0; i < files.length; i += 1) {
      const f = files[i];
      setProgress({ done: i, total: files.length, name: f.name });

      let data = await postOne(f);
      // The backend stopped to ask something rather than guessing. Nothing was written, so
      // the batch waits for an answer: approving re-posts this file, rejecting skips it.
      if (data?.needs_approval) {
        const approved = await askApproval(data);
        if (approved) {
          data = await postOne(f, { [data.needs_approval]: 'true' });
        } else {
          data = { success: false, skipped: true, msg: 'Skipped — not approved, nothing was saved' };
        }
      }
      results.push({ name: f.name, data });
    }
    setProgress(null);
    setIsUploading(false);

    const ok = results.filter((r) => r.data?.success).length;
    const failed = results.length - ok;

    if (results.length === 1) {
      // A single file keeps exactly the result card it always had.
      const data = results[0].data;
      setUploadResults(data);
      setUploadStatus(data?.success ? 'success' : 'error');
      showSnackbar(
        data?.success
          ? `Processed ${data.processed_count} record(s)` +
              (data.error_count > 0 ? ` — ${data.error_count} row(s) failed` : '')
          : data?.msg || 'Processing failed',
        data?.success ? (data.error_count > 0 ? 'warning' : 'success') : 'error'
      );
      return;
    }

    setBatchResults(results);
    setUploadStatus(ok ? 'success' : 'error');
    showSnackbar(
      `${results.length} files: ${ok} uploaded` + (failed ? `, ${failed} failed` : ''),
      failed ? (ok ? 'warning' : 'error') : 'success'
    );
  };

  const resetUpload = () => {
    setFiles([]);
    setUploadStatus(null);
    setUploadResults(null);
    setBatchResults([]);
  };

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

  const errorDate = new Date().toISOString().split('T')[0];
  const extraStats = uploadResults && computeExtraStats ? computeExtraStats(uploadResults) : [];

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

                    <Grid item xs={12}>
                      <div
                        className={`${classes.uploadCard} ${isDragging ? classes.dropzoneActive : ''}`}
                        onDragOver={handleDragOver}
                        onDragLeave={handleDragLeave}
                        onDrop={handleDrop}
                        onClick={() => document.getElementById(inputId).click()}
                      >
                        <input
                          type="file"
                          id={inputId}
                          style={{ display: 'none' }}
                          accept={ACCEPT_ATTR}
                          multiple
                          onChange={handleFileSelect}
                        />
                        <CloudUploadIcon className={classes.uploadIcon} />
                        <Typography variant="h6" gutterBottom>
                          {files.length ? 'Add more files' : 'Drag & Drop your files here'}
                        </Typography>
                        <Typography variant="body2" color="textSecondary">
                          or click to browse — you can select several at once
                        </Typography>
                        <Typography variant="caption" color="textSecondary" style={{ marginTop: '8px' }}>
                          Supported formats: {SUPPORTED_LABEL} (Max {maxSizeMB}MB each)
                        </Typography>
                      </div>
                    </Grid>

                    {files.length > 0 && (
                      <Grid item xs={12}>
                        <Typography variant="subtitle2" gutterBottom>
                          {files.length} file{files.length === 1 ? '' : 's'} selected
                        </Typography>
                        {files.map((f, i) => (
                          <div key={`${f.name}-${f.lastModified}-${i}`} className={classes.fileInfo}>
                            <DescriptionIcon className={classes.fileIcon} />
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <Typography variant="subtitle1" className={classes.fileName} noWrap>
                                {f.name}
                              </Typography>
                              <Typography variant="caption" color="textSecondary">
                                {(f.size / 1024).toFixed(2)} KB
                              </Typography>
                            </div>
                            {!isUploading && uploadStatus !== 'success' && (
                              <Button size="small" onClick={() => removeFile(i)}>
                                Remove
                              </Button>
                            )}
                          </div>
                        ))}
                      </Grid>
                    )}

                    {uploadStatus === 'uploading' && (
                      <Grid item xs={12}>
                        <div className={classes.uploadProgress}>
                          <CircularProgress size={40} />
                          <Typography variant="body1" style={{ marginTop: '16px' }}>
                            {progress && progress.total > 1
                              ? `Uploading ${progress.done + 1} of ${progress.total}: ${progress.name}`
                              : processingMessage}
                          </Typography>
                        </div>
                      </Grid>
                    )}

                    {batchResults.length > 0 && (
                      <Grid item xs={12}>
                        <Typography variant="h6" gutterBottom>
                          Results
                        </Typography>
                        <Table size="small">
                          <TableHead>
                            <TableRow>
                              <TableCell>File</TableCell>
                              <TableCell>Result</TableCell>
                              <TableCell align="right">{successLabel}</TableCell>
                              <TableCell align="right">Errors</TableCell>
                              <TableCell />
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {batchResults.map((r, i) => {
                              const d = r.data || {};
                              return (
                                <TableRow key={`${r.name}-${i}`}>
                                  <TableCell style={{ maxWidth: 220, wordBreak: 'break-word' }}>{r.name}</TableCell>
                                  <TableCell>
                                    <Typography
                                      variant="body2"
                                      color={d.success ? 'textPrimary' : 'error'}
                                    >
                                      {d.success ? (d.error_count ? 'Uploaded, with errors' : 'Uploaded') : d.msg || 'Failed'}
                                    </Typography>
                                  </TableCell>
                                  <TableCell align="right">{d.processed_count ?? '—'}</TableCell>
                                  <TableCell align="right">{d.error_count ?? '—'}</TableCell>
                                  <TableCell align="right">
                                    {d.error_report && d.error_count > 0 && (
                                      <Button
                                        size="small"
                                        onClick={() =>
                                          downloadErrorExcel(
                                            d.error_report,
                                            `${errorFilename}_${r.name.replace(/\.[^.]+$/, '')}_${errorDate}.xlsx`
                                          )
                                        }
                                      >
                                        Error report
                                      </Button>
                                    )}
                                  </TableCell>
                                </TableRow>
                              );
                            })}
                          </TableBody>
                        </Table>
                        <Box mt={2}>
                          <Button variant="outlined" onClick={resetUpload}>
                            Upload more files
                          </Button>
                        </Box>
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
                            disabled={isUploading || uploadStatus === 'success'}
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
                            disabled={isUploading || uploadStatus === 'success'}
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
                            !files.length ||
                            (requiresWarehouse && !selectedWarehouse) ||
                            (requiresCompany && !selectedCompany) ||
                            isUploading ||
                            uploadStatus === 'success'
                          }
                          onClick={() => handleUpload()}
                        >
                          {isUploading
                            ? 'Processing…'
                            : files.length > 1
                              ? `${uploadButtonLabel} (${files.length} files)`
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
          was written on the first attempt there is nothing to undo. */}
      {/* Dismissing counts as Reject. Merely clearing the dialog would leave the upload
          queue waiting on an answer that never comes, stuck on "Processing…". */}
      <Dialog open={!!approval} onClose={() => answerApproval(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Missing product numbers</DialogTitle>
        <DialogContent>
          <DialogContentText>{approval?.msg}</DialogContentText>
          {approval?.sample?.length > 0 && (
            <>
              <Typography variant="subtitle2" sx={{ mt: 2, mb: 1 }}>
                Examples of what would be created
                {approval.missing_count > approval.sample.length
                  ? ` (first ${approval.sample.length} of ${approval.missing_count})`
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
                  {approval.sample.map((r) => (
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
          {/* Answering resumes the batch: approve re-posts this file, reject skips it and
              moves on to the next — nothing was written for it either way. */}
          <Button onClick={() => answerApproval(false)}>
            Reject
          </Button>
          <Button variant="contained" onClick={() => answerApproval(true)}>
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
