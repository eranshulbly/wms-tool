import React, { useState, useEffect } from 'react';
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
    useMediaQuery,
} from '@material-ui/core';
import { makeStyles, useTheme } from '@material-ui/styles';
import CloudUploadIcon from '@material-ui/icons/CloudUpload';
import DescriptionIcon from '@material-ui/icons/Description';
import ErrorOutlineIcon from '@material-ui/icons/ErrorOutline';
import { Snackbar, Alert } from '@material-ui/core';
import MainCard from '../../ui-component/cards/MainCard';
import AnimateButton from '../../ui-component/extended/AnimateButton';
import UploadResultCard from '../../components/UploadResultCard';
import axios from 'axios';
import config from '../../config';

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
        '&:hover': {
            borderColor: theme.palette.primary.main
        }
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
    fileName: {
        wordBreak: 'break-all'
    },
    uploadProgress: {
        marginTop: '24px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'column'
    },
    successIcon: {
        fontSize: '3rem',
        color: theme.palette.success.main,
        marginBottom: '8px'
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

}));

const InvoiceUpload = () => {
    const classes = useStyles();
    const theme = useTheme();
    const matchDownSM = useMediaQuery(theme.breakpoints.down('sm'));

    // State variables
    const [file, setFile] = useState(null);
    const [isDragging, setIsDragging] = useState(false);
    const [isUploading, setIsUploading] = useState(false);
    const [uploadStatus, setUploadStatus] = useState(null);
    const [warehouses, setWarehouses] = useState([]);
    const [companies, setCompanies] = useState([]);
    const [selectedWarehouse, setSelectedWarehouse] = useState('');
    const [selectedCompany, setSelectedCompany] = useState('');
    const [snackbarOpen, setSnackbarOpen] = useState(false);
    const [snackbarMessage, setSnackbarMessage] = useState('');
    const [snackbarSeverity, setSnackbarSeverity] = useState('success');
    const [uploadResults, setUploadResults] = useState(null);
    const [isLoading, setIsLoading] = useState(true);
    const [dataError, setDataError] = useState(null);

    // Fetch warehouses and companies from the API
    useEffect(() => {
        const fetchData = async () => {
            setIsLoading(true);
            setDataError(null);

            try {
                // Fetch warehouses
                const warehousesResponse = await axios.get(`${config.API_SERVER}warehouses`);

                if (warehousesResponse.data.success) {
                    setWarehouses(warehousesResponse.data.warehouses);
                } else {
                    throw new Error(warehousesResponse.data.msg || 'Failed to fetch warehouses');
                }

                // Fetch companies
                const companiesResponse = await axios.get(`${config.API_SERVER}companies`);

                if (companiesResponse.data.success) {
                    setCompanies(companiesResponse.data.companies);
                } else {
                    throw new Error(companiesResponse.data.msg || 'Failed to fetch companies');
                }
            } catch (error) {
                console.error('Error fetching data:', error);
                setDataError(error.message || 'Failed to load required data');
                showSnackbar('Failed to load warehouses and companies', 'error');
            } finally {
                setIsLoading(false);
            }
        };

        fetchData();
    }, []);

    const showSnackbar = (message, severity) => {
        setSnackbarMessage(message);
        setSnackbarSeverity(severity);
        setSnackbarOpen(true);
    };

    const handleSnackbarClose = (event, reason) => {
        if (reason === 'clickaway') {
            return;
        }
        setSnackbarOpen(false);
    };

    const handleDragOver = (e) => {
        e.preventDefault();
        setIsDragging(true);
    };

    const handleDragLeave = (e) => {
        e.preventDefault();
        setIsDragging(false);
    };

    const handleDrop = (e) => {
        e.preventDefault();
        setIsDragging(false);

        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            const droppedFile = e.dataTransfer.files[0];
            validateAndSetFile(droppedFile);
        }
    };

    const handleFileSelect = (e) => {
        if (e.target.files && e.target.files.length > 0) {
            const selectedFile = e.target.files[0];
            validateAndSetFile(selectedFile);
        }
    };

    const validateAndSetFile = (file) => {
        // Validate file type (Excel or CSV)
        const validTypes = [
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'text/csv',
            'application/csv'
        ];

        if (!validTypes.includes(file.type)) {
            showSnackbar('Please upload a valid Excel or CSV file', 'error');
            return;
        }

        // Validate file size (max 10MB for invoices)
        if (file.size > 10 * 1024 * 1024) {
            showSnackbar('File size exceeds 10MB limit', 'error');
            return;
        }

        setFile(file);
        setUploadStatus(null);
        setUploadResults(null);
    };

    const handleUpload = () => {
        if (!file) {
            showSnackbar('Please select a file to upload', 'warning');
            return;
        }

        if (!selectedWarehouse) {
            showSnackbar('Please select a warehouse', 'warning');
            return;
        }

        if (!selectedCompany) {
            showSnackbar('Please select a company', 'warning');
            return;
        }

        setIsUploading(true);
        setUploadStatus('uploading');

        // Create form data
        const formData = new FormData();
        formData.append('file', file);
        formData.append('warehouse_id', selectedWarehouse);
        formData.append('company_id', selectedCompany);

        // Send to API
        axios.post(`${config.API_SERVER}invoices/upload`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
        })
        .then(response => {
            const data = response.data;
            setUploadResults(data);
            if (data.success) {
                setUploadStatus('success');
                showSnackbar(
                    `Processed ${data.processed_count} invoice(s)` +
                    (data.error_count > 0 ? ` — ${data.error_count} row(s) failed` : ''),
                    data.error_count > 0 ? 'warning' : 'success'
                );
            } else {
                setUploadStatus('error');
                showSnackbar(data.msg || 'Processing failed', 'error');
            }
        })
        .catch(error => {
            setUploadStatus('error');
            setUploadResults(error.response?.data || null);
            showSnackbar(error.response?.data?.msg || 'Error processing invoice file', 'error');
            console.error('Upload error:', error);
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

    // Show loading state while fetching warehouses and companies
    if (isLoading) {
        return (
            <MainCard title="Upload Invoice File">
                <div className={classes.loadingContainer}>
                    <CircularProgress />
                    <Typography variant="body1" style={{ marginLeft: '16px' }}>
                        Loading required data...
                    </Typography>
                </div>
            </MainCard>
        );
    }

    // Show error state if data fetching failed
    if (dataError) {
        return (
            <MainCard title="Upload Invoice File">
                <div style={{ textAlign: 'center', padding: '40px 20px' }}>
                    <ErrorOutlineIcon className={classes.errorIcon} />
                    <Typography variant="h5" color="error" gutterBottom>
                        Error Loading Data
                    </Typography>
                    <Typography variant="body1" gutterBottom>
                        {dataError}
                    </Typography>
                    <Button
                        variant="contained"
                        color="primary"
                        style={{ marginTop: '20px' }}
                        onClick={() => window.location.reload()}
                    >
                        Retry
                    </Button>
                </div>
            </MainCard>
        );
    }

    return (
        <MainCard title="Upload Invoice File">
            <Grid container spacing={3}>
                <Grid item xs={12}>
                    <Grid container spacing={3}>
                        <Grid item lg={8} md={6} sm={12} xs={12}>
                            <Card>
                                <CardContent>
                                    <Grid container spacing={2}>
                                        <Grid item xs={12}>
                                            <Typography variant="h4" gutterBottom>
                                                Upload Invoice Excel/CSV File
                                            </Typography>
                                            <Typography variant="body2" color="textSecondary" gutterBottom>
                                                Upload your invoice file to move matched orders to <strong>Invoiced</strong> status.
                                                Orders in <em>Packed</em> state (or bypass order types like ZGOI) are invoiced immediately.
                                                Orders still in Open/Picking receive an <em>Invoice Submitted</em> flag and are auto-invoiced when moved to Packed.
                                            </Typography>
                                        </Grid>

                                        <Grid item xs={12}>
                                            <div
                                                className={`${classes.uploadCard} ${isDragging ? classes.dropzoneActive : ''}`}
                                                onDragOver={handleDragOver}
                                                onDragLeave={handleDragLeave}
                                                onDrop={handleDrop}
                                                onClick={() => document.getElementById('invoice-file-upload').click()}
                                            >
                                                <input
                                                    type="file"
                                                    id="invoice-file-upload"
                                                    style={{ display: 'none' }}
                                                    accept=".xlsx,.xls,.csv"
                                                    onChange={handleFileSelect}
                                                />
                                                {!file ? (
                                                    <>
                                                        <CloudUploadIcon className={classes.uploadIcon} />
                                                        <Typography variant="h6" gutterBottom>
                                                            Drag & Drop your invoice file here
                                                        </Typography>
                                                        <Typography variant="body2" color="textSecondary">
                                                            or click to browse
                                                        </Typography>
                                                        <Typography variant="caption" color="textSecondary" style={{ marginTop: '8px' }}>
                                                            Supported formats: .xlsx, .xls, .csv (Max 10MB)
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
                                                        Processing invoice file and updating orders...
                                                    </Typography>
                                                </div>
                                            </Grid>
                                        )}

                                        {(uploadStatus === 'success' || uploadStatus === 'error') && uploadResults && (
                                            <Grid item xs={12}>
                                                <UploadResultCard
                                                    result={uploadResults}
                                                    onReset={resetUpload}
                                                    successLabel="Invoices Processed"
                                                    errorFilename={`invoice_upload_errors_${new Date().toISOString().split('T')[0]}.xlsx`}
                                                    extraStats={[
                                                        ...(uploadResults.orders_invoiced != null
                                                            ? [{ label: 'Orders Invoiced', value: uploadResults.orders_invoiced, color: 'secondary' }]
                                                            : []),
                                                        ...(uploadResults.orders_flagged != null && uploadResults.orders_flagged > 0
                                                            ? [{ label: 'Invoice Submitted (pending pack)', value: uploadResults.orders_flagged, color: 'default' }]
                                                            : []),
                                                    ]}
                                                />
                                            </Grid>
                                        )}
                                    </Grid>
                                </CardContent>
                            </Card>
                        </Grid>

                        <Grid item lg={4} md={6} sm={12} xs={12}>
                            <Card>
                                <CardContent>
                                    <Grid container spacing={2}>
                                        <Grid item xs={12}>
                                            <Typography variant="h4" gutterBottom>
                                                Invoice Processing Settings
                                            </Typography>
                                            <Divider sx={{ my: 1.5 }} />
                                        </Grid>

                                        <Grid item xs={12}>
                                            <FormControl fullWidth>
                                                <InputLabel id="warehouse-select-label">Warehouse</InputLabel>
                                                <Select
                                                    labelId="warehouse-select-label"
                                                    id="warehouse-select"
                                                    value={selectedWarehouse}
                                                    label="Warehouse"
                                                    onChange={(e) => setSelectedWarehouse(e.target.value)}
                                                    disabled={isUploading || uploadStatus === 'success'}
                                                >
                                                    <MenuItem value="">
                                                        <em>Select a warehouse</em>
                                                    </MenuItem>
                                                    {warehouses.map((warehouse) => (
                                                        <MenuItem key={warehouse.id} value={warehouse.id}>
                                                            {warehouse.name}
                                                        </MenuItem>
                                                    ))}
                                                </Select>
                                            </FormControl>
                                        </Grid>

                                        <Grid item xs={12}>
                                            <FormControl fullWidth>
                                                <InputLabel id="company-select-label">Company</InputLabel>
                                                <Select
                                                    labelId="company-select-label"
                                                    id="company-select"
                                                    value={selectedCompany}
                                                    label="Company"
                                                    onChange={(e) => setSelectedCompany(e.target.value)}
                                                    disabled={isUploading || uploadStatus === 'success'}
                                                >
                                                    <MenuItem value="">
                                                        <em>Select a company</em>
                                                    </MenuItem>
                                                    {companies.map((company) => (
                                                        <MenuItem key={company.id} value={company.id}>
                                                            {company.name}
                                                        </MenuItem>
                                                    ))}
                                                </Select>
                                            </FormControl>
                                        </Grid>

                                        <Grid item xs={12} style={{ marginTop: '16px' }}>
                                            <AnimateButton>
                                                <Button
                                                    variant="contained"
                                                    color="primary"
                                                    fullWidth
                                                    startIcon={<CloudUploadIcon />}
                                                    disabled={!file || !selectedWarehouse || !selectedCompany || isUploading || uploadStatus === 'success'}
                                                    onClick={handleUpload}
                                                >
                                                    {isUploading ? 'Processing...' : 'Process Invoice File'}
                                                </Button>
                                            </AnimateButton>
                                        </Grid>

                                        <Grid item xs={12} style={{ marginTop: '16px' }}>
                                            <Box p={2} bgcolor={theme.palette.primary.light} borderRadius="8px">
                                                <Typography variant="subtitle2" gutterBottom>
                                                    Processing Rules:
                                                </Typography>
                                                <Typography variant="body2" component="div">
                                                    <ul style={{ paddingLeft: '20px', margin: '8px 0' }}>
                                                        <li>File must have <strong>Invoice #</strong> and <strong>Order #</strong> columns</li>
                                                        <li><strong>Bypass types (e.g. ZGOI):</strong> moved to Invoiced regardless of current state</li>
                                                        <li><strong>Packed orders:</strong> moved to Invoiced immediately</li>
                                                        <li><strong>Open / Picking orders:</strong> flagged as "Invoice Submitted" — auto-transition to Invoiced when moved to Packed</li>
                                                        <li>Already Invoiced / Dispatch Ready orders are reported as duplicates</li>
                                                        <li>Errors are provided in a downloadable report</li>
                                                    </ul>
                                                </Typography>
                                            </Box>
                                        </Grid>
                                    </Grid>
                                </CardContent>
                            </Card>
                        </Grid>
                    </Grid>
                </Grid>
            </Grid>

            {/* Snackbar for notifications */}
            <Snackbar
                open={snackbarOpen}
                autoHideDuration={6000}
                onClose={handleSnackbarClose}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
            >
                <Alert onClose={handleSnackbarClose} severity={snackbarSeverity} sx={{ width: '100%' }}>
                    {snackbarMessage}
                </Alert>
            </Snackbar>
        </MainCard>
    );
};

export default InvoiceUpload;