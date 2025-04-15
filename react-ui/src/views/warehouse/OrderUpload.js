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
    useMediaQuery
} from '@material-ui/core';
import { makeStyles, useTheme } from '@material-ui/styles';
import CloudUploadIcon from '@material-ui/icons/CloudUpload';
import DescriptionIcon from '@material-ui/icons/Description';
import CheckCircleOutlineIcon from '@material-ui/icons/CheckCircleOutline';
import ErrorOutlineIcon from '@material-ui/icons/ErrorOutline';
import { gridSpacing } from '../../store/constant';
import { Snackbar, Alert } from '@material-ui/core';
import MainCard from '../../ui-component/cards/MainCard';
import AnimateButton from '../../ui-component/extended/AnimateButton';
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
    }
}));

const OrderUpload = () => {
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

        // Validate file size (max 5MB)
        if (file.size > 5 * 1024 * 1024) {
            showSnackbar('File size exceeds 5MB limit', 'error');
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
        axios.post(`${config.API_SERVER}orders/upload`, formData, {
            headers: {
                'Content-Type': 'multipart/form-data'
            }
        })
        .then(response => {
            if (response.data.success) {
                setUploadStatus('success');
                setUploadResults(response.data);
                showSnackbar('File uploaded successfully', 'success');
            } else {
                setUploadStatus('error');
                showSnackbar(response.data.msg || 'Upload failed', 'error');
            }
        })
        .catch(error => {
            setUploadStatus('error');
            const errorMessage = error.response?.data?.msg || 'Error uploading file';
            showSnackbar(errorMessage, 'error');
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
            <MainCard title="Upload Order File">
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
            <MainCard title="Upload Order File">
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
        <MainCard title="Upload Order File">
            <Grid container spacing={gridSpacing}>
                <Grid item xs={12}>
                    <Grid container spacing={gridSpacing}>
                        <Grid item lg={8} md={6} sm={12} xs={12}>
                            <Card>
                                <CardContent>
                                    <Grid container spacing={2}>
                                        <Grid item xs={12}>
                                            <Typography variant="h4" gutterBottom>
                                                Upload Excel/CSV File
                                            </Typography>
                                            <Typography variant="body2" color="textSecondary" gutterBottom>
                                                Upload your order file in Excel or CSV format. The system will process the data and create orders accordingly.
                                            </Typography>
                                        </Grid>

                                        <Grid item xs={12}>
                                            <div
                                                className={`${classes.uploadCard} ${isDragging ? classes.dropzoneActive : ''}`}
                                                onDragOver={handleDragOver}
                                                onDragLeave={handleDragLeave}
                                                onDrop={handleDrop}
                                                onClick={() => document.getElementById('file-upload').click()}
                                            >
                                                <input
                                                    type="file"
                                                    id="file-upload"
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
                                                            Supported formats: .xlsx, .xls, .csv (Max 5MB)
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
                                                        Uploading and processing file...
                                                    </Typography>
                                                </div>
                                            </Grid>
                                        )}

                                        {uploadStatus === 'success' && (
                                            <Grid item xs={12}>
                                                <div className={classes.uploadProgress}>
                                                    <CheckCircleOutlineIcon className={classes.successIcon} />
                                                    <Typography variant="h6" gutterBottom>
                                                        Upload Successful!
                                                    </Typography>
                                                    <Typography variant="body2">
                                                        {uploadResults?.orders_processed || 0} orders and {uploadResults?.products_processed || 0} products were processed.
                                                    </Typography>
                                                    <Button
                                                        variant="outlined"
                                                        color="primary"
                                                        style={{ marginTop: '16px' }}
                                                        onClick={resetUpload}
                                                    >
                                                        Upload Another File
                                                    </Button>
                                                </div>
                                            </Grid>
                                        )}

                                        {uploadStatus === 'error' && (
                                            <Grid item xs={12}>
                                                <div className={classes.uploadProgress}>
                                                    <ErrorOutlineIcon className={classes.errorIcon} />
                                                    <Typography variant="h6" gutterBottom>
                                                        Upload Failed
                                                    </Typography>
                                                    <Typography variant="body2" color="error">
                                                        There was an error processing your file. Please try again.
                                                    </Typography>
                                                    <Button
                                                        variant="outlined"
                                                        color="primary"
                                                        style={{ marginTop: '16px' }}
                                                        onClick={resetUpload}
                                                    >
                                                        Try Again
                                                    </Button>
                                                </div>
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
                                                Order Details
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
                                                    {isUploading ? 'Uploading...' : 'Upload File'}
                                                </Button>
                                            </AnimateButton>
                                        </Grid>

                                        <Grid item xs={12} style={{ marginTop: '8px' }}>
                                            <Typography variant="caption" color="textSecondary">
                                                Note: The system will automatically process the file and create orders based on the data.
                                                Make sure your file follows the required format.
                                            </Typography>
                                        </Grid>

                                        <Grid item xs={12} style={{ marginTop: '16px' }}>
                                            <Box p={2} bgcolor={theme.palette.primary.light} borderRadius="8px">
                                                <Typography variant="subtitle2" gutterBottom>
                                                    File Format Requirements:
                                                </Typography>
                                                <Typography variant="body2" component="div">
                                                    <ul style={{ paddingLeft: '20px', margin: '8px 0' }}>
                                                        <li>Order # = Order ID</li>
                                                        <li>Date = Order creation date</li>
                                                        <li>Part # = Product ID</li>
                                                        <li>Part Description = Product description</li>
                                                        <li>Account Name = Dealer name</li>
                                                        <li>Order Quantity = Actual ordered quantity</li>
                                                        <li>Reserved Qty = Reserved quantity</li>
                                                    </ul>
                                                </Typography>
                                                <Button
                                                    size="small"
                                                    color="primary"
                                                    style={{ marginTop: '8px' }}
                                                    onClick={() => {
                                                        // Add functionality to download a template
                                                        showSnackbar('Template download functionality will be implemented', 'info');
                                                    }}
                                                >
                                                    Download Template
                                                </Button>
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

export default OrderUpload;