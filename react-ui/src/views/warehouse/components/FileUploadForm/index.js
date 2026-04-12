import React, { useState } from 'react';
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
  Typography
} from '@material-ui/core';
import { makeStyles, useTheme } from '@material-ui/styles';
import CloudUploadIcon from '@material-ui/icons/CloudUpload';
import DescriptionIcon from '@material-ui/icons/Description';
import ErrorOutlineIcon from '@material-ui/icons/ErrorOutline';
import { Snackbar, Alert } from '@material-ui/core';
import AnimateButton from '../../../../ui-component/extended/AnimateButton';
import UploadResultCard from '../../../../components/UploadResultCard';
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

const VALID_TYPES = [
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'text/csv',
  'application/csv'
];

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

  const [file, setFile] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadStatus, setUploadStatus] = useState(null); // null | 'uploading' | 'success' | 'error'
  const [uploadResults, setUploadResults] = useState(null);

  const validateAndSetFile = (selectedFile) => {
    if (!VALID_TYPES.includes(selectedFile.type)) {
      showSnackbar('Please upload a valid Excel or CSV file', 'error');
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

  const handleDragOver = (e) => { e.preventDefault(); setIsDragging(true); };
  const handleDragLeave = (e) => { e.preventDefault(); setIsDragging(false); };
  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files?.[0]) validateAndSetFile(e.dataTransfer.files[0]);
  };
  const handleFileSelect = (e) => {
    if (e.target.files?.[0]) validateAndSetFile(e.target.files[0]);
  };

  const handleUpload = () => {
    if (!file) { showSnackbar('Please select a file to upload', 'warning'); return; }
    if (requiresWarehouse && !selectedWarehouse) { showSnackbar('Please select a warehouse', 'warning'); return; }
    if (requiresCompany && !selectedCompany) { showSnackbar('Please select a company', 'warning'); return; }

    setIsUploading(true);
    setUploadStatus('uploading');

    const formData = new FormData();
    formData.append('file', file);
    if (requiresWarehouse) formData.append('warehouse_id', selectedWarehouse);
    if (requiresCompany) formData.append('company_id', selectedCompany);

    api
      .post(endpoint, formData, { headers: { 'Content-Type': 'multipart/form-data' } })
      .then((response) => {
        const data = response.data;
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
                          accept=".xlsx,.xls,.csv"
                          onChange={handleFileSelect}
                        />
                        {!file ? (
                          <>
                            <CloudUploadIcon className={classes.uploadIcon} />
                            <Typography variant="h6" gutterBottom>
                              Drag & Drop your file here
                            </Typography>
                            <Typography variant="body2" color="textSecondary">
                              or click to browse
                            </Typography>
                            <Typography variant="caption" color="textSecondary" style={{ marginTop: '8px' }}>
                              Supported formats: .xlsx, .xls, .csv (Max {maxSizeMB}MB)
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
                            !file ||
                            (requiresWarehouse && !selectedWarehouse) ||
                            (requiresCompany && !selectedCompany) ||
                            isUploading ||
                            uploadStatus === 'success'
                          }
                          onClick={handleUpload}
                        >
                          {isUploading ? 'Processing…' : uploadButtonLabel}
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
