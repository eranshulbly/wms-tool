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

const ProductUpload = () => {
    const classes = useStyles();
    const theme = useTheme();

    const [file, setFile] = useState(null);
    const [isDragging, setIsDragging] = useState(false);
    const [isUploading, setIsUploading] = useState(false);
    const [uploadStatus, setUploadStatus] = useState(null);
    const [companies, setCompanies] = useState([]);
    const [selectedCompany, setSelectedCompany] = useState('');
    const [snackbarOpen, setSnackbarOpen] = useState(false);
    const [snackbarMessage, setSnackbarMessage] = useState('');
    const [snackbarSeverity, setSnackbarSeverity] = useState('success');
    const [uploadResults, setUploadResults] = useState(null);
    const [isLoading, setIsLoading] = useState(true);
    const [dataError, setDataError] = useState(null);

    useEffect(() => {
        const fetchData = async () => {
            setIsLoading(true);
            setDataError(null);
            try {
                const companiesResponse = await axios.get(`${config.API_SERVER}companies`);
                if (companiesResponse.data.success) {
                    setCompanies(companiesResponse.data.companies);
                } else {
                    throw new Error(companiesResponse.data.msg || 'Failed to fetch companies');
                }
            } catch (error) {
                console.error('Error fetching companies:', error);
                setDataError(error.message || 'Failed to load required data');
                showSnackbar('Failed to load companies', 'error');
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
        if (reason === 'clickaway') return;
        setSnackbarOpen(false);
    };

    const handleDragOver = (e) => { e.preventDefault(); setIsDragging(true); };
    const handleDragLeave = (e) => { e.preventDefault(); setIsDragging(false); };

    const handleDrop = (e) => {
        e.preventDefault();
        setIsDragging(false);
        if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
            validateAndSetFile(e.dataTransfer.files[0]);
        }
    };

    const handleFileSelect = (e) => {
        if (e.target.files && e.target.files.length > 0) {
            validateAndSetFile(e.target.files[0]);
        }
    };

    const validateAndSetFile = (selectedFile) => {
        const validTypes = [
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'text/csv',
            'application/csv'
        ];
        if (!validTypes.includes(selectedFile.type)) {
            showSnackbar('Please upload a valid Excel or CSV file', 'error');
            return;
        }
        if (selectedFile.size > 10 * 1024 * 1024) {
            showSnackbar('File size exceeds 10MB limit', 'error');
            return;
        }
        setFile(selectedFile);
        setUploadStatus(null);
        setUploadResults(null);
    };

    const handleUpload = () => {
        if (!file) {
            showSnackbar('Please select a file to upload', 'warning');
            return;
        }
        if (!selectedCompany) {
            showSnackbar('Please select a company', 'warning');
            return;
        }

        setIsUploading(true);
        setUploadStatus('uploading');

        const formData = new FormData();
        formData.append('file', file);
        formData.append('company_id', selectedCompany);

        axios.post(`${config.API_SERVER}products/upload`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
        })
        .then(response => {
            const data = response.data;
            setUploadResults(data);
            if (data.success) {
                setUploadStatus('success');
                showSnackbar(
                    `Processed ${data.processed_count} product line(s)` +
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
            showSnackbar(error.response?.data?.msg || 'Error processing product file', 'error');
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

    if (isLoading) {
        return (
            <MainCard title="Upload Product File">
                <div className={classes.loadingContainer}>
                    <CircularProgress />
                    <Typography variant="body1" style={{ marginLeft: '16px' }}>
                        Loading required data...
                    </Typography>
                </div>
            </MainCard>
        );
    }

    if (dataError) {
        return (
            <MainCard title="Upload Product File">
                <div style={{ textAlign: 'center', padding: '40px 20px' }}>
                    <ErrorOutlineIcon className={classes.errorIcon} />
                    <Typography variant="h5" color="error" gutterBottom>
                        Error Loading Data
                    </Typography>
                    <Typography variant="body1" gutterBottom>{dataError}</Typography>
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
        <MainCard title="Upload Product File">
            <Grid container spacing={3}>
                <Grid item xs={12}>
                    <Grid container spacing={3}>
                        <Grid item lg={8} md={6} sm={12} xs={12}>
                            <Card>
                                <CardContent>
                                    <Grid container spacing={2}>
                                        <Grid item xs={12}>
                                            <Typography variant="h4" gutterBottom>
                                                Upload Product Excel/CSV File
                                            </Typography>
                                            <Typography variant="body2" color="textSecondary" gutterBottom>
                                                Upload your spare parts / product file to attach product lines to existing orders.
                                                Each row links a <strong>Part #</strong> to an <strong>Order #</strong>.
                                                Existing product lines for matched orders will be replaced.
                                            </Typography>
                                        </Grid>

                                        <Grid item xs={12}>
                                            <div
                                                className={`${classes.uploadCard} ${isDragging ? classes.dropzoneActive : ''}`}
                                                onDragOver={handleDragOver}
                                                onDragLeave={handleDragLeave}
                                                onDrop={handleDrop}
                                                onClick={() => document.getElementById('product-file-upload').click()}
                                            >
                                                <input
                                                    type="file"
                                                    id="product-file-upload"
                                                    style={{ display: 'none' }}
                                                    accept=".xlsx,.xls,.csv"
                                                    onChange={handleFileSelect}
                                                />
                                                {!file ? (
                                                    <>
                                                        <CloudUploadIcon className={classes.uploadIcon} />
                                                        <Typography variant="h6" gutterBottom>
                                                            Drag & Drop your product file here
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
                                                        Processing product file and linking to orders...
                                                    </Typography>
                                                </div>
                                            </Grid>
                                        )}

                                        {(uploadStatus === 'success' || uploadStatus === 'error') && uploadResults && (
                                            <Grid item xs={12}>
                                                <UploadResultCard
                                                    result={uploadResults}
                                                    onReset={resetUpload}
                                                    successLabel="Product Lines Processed"
                                                    errorFilename={`product_upload_errors_${new Date().toISOString().split('T')[0]}.xlsx`}
                                                    extraStats={[
                                                        ...(uploadResults.orders_updated != null
                                                            ? [{ label: 'Orders Updated', value: uploadResults.orders_updated, color: 'secondary' }]
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
                                                Upload Settings
                                            </Typography>
                                            <Divider sx={{ my: 1.5 }} />
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
                                                    disabled={!file || !selectedCompany || isUploading || uploadStatus === 'success'}
                                                    onClick={handleUpload}
                                                >
                                                    {isUploading ? 'Processing...' : 'Process Product File'}
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
                                                        <li>File must have <strong>Order #</strong>, <strong>Part #</strong>, <strong>Part Description</strong>, and <strong>Reserved Qty</strong> columns</li>
                                                        <li><strong>Reserved Qty</strong> is used as the product quantity</li>
                                                        <li>If an order already has products, they are <strong>replaced</strong> by this upload</li>
                                                        <li>New Part # values are automatically created as products</li>
                                                        <li>Order # must match an existing order in the system</li>
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

export default ProductUpload;
