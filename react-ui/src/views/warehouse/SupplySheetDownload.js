// Create this as: react-ui/src/views/warehouse/SupplySheetDownload.js

import React, { useState, useEffect } from 'react';
import {
  Grid,
  Card,
  CardContent,
  Typography,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  TextField,
  Box,
  CircularProgress,
  Snackbar,
  Alert
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import {
    IconDownload,
    IconPhoto,
    IconFilter, IconTable
} from '@tabler/icons';
import { gridSpacing } from '../../store/constant';
import dashboardService from '../../services/dashboardService';
import config from '../../config';

const useStyles = makeStyles((theme) => ({
  pageHeader: {
    marginBottom: theme.spacing(3),
    padding: theme.spacing(3),
    background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
    color: 'white',
    borderRadius: theme.shape.borderRadius,
    textAlign: 'center'
  },
  filterCard: {
    marginBottom: theme.spacing(3),
  },
  formControl: {
    minWidth: 200,
    marginBottom: theme.spacing(2)
  },
  dateField: {
    marginBottom: theme.spacing(2)
  },
  downloadSection: {
    textAlign: 'center',
    padding: theme.spacing(4)
  },
  downloadButton: {
    margin: theme.spacing(1),
    minWidth: 200,
    height: 60,
    fontSize: '1.1rem'
  },
  excelButton: {
    backgroundColor: '#1d4ed8',
    color: 'white',
    '&:hover': {
      backgroundColor: '#1e40af'
    }
  },
  pngButton: {
    backgroundColor: '#059669',
    color: 'white',
    '&:hover': {
      backgroundColor: '#047857'
    }
  },
  buttonIcon: {
    marginRight: theme.spacing(1)
  },
  filterSection: {
    display: 'flex',
    gap: theme.spacing(2),
    flexWrap: 'wrap',
    alignItems: 'center'
  }
}));

const SupplySheetDownload = () => {
  const classes = useStyles();

  // State
  const [warehouse, setWarehouse] = useState('');
  const [company, setCompany] = useState('');
  const [warehouses, setWarehouses] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [batchId, setBatchId] = useState('');
  const [loading, setLoading] = useState(false);
  const [notification, setNotification] = useState({
    open: false,
    message: '',
    severity: 'success'
  });

  // Load warehouses and companies
  useEffect(() => {
    const fetchInitialData = async () => {
      try {
        const [warehouseResponse, companyResponse] = await Promise.all([
          dashboardService.getWarehouses(),
          dashboardService.getCompanies()
        ]);

        if (warehouseResponse.success) {
          setWarehouses(warehouseResponse.warehouses);
          if (warehouseResponse.warehouses.length > 0) {
            setWarehouse(warehouseResponse.warehouses[0].id);
          }
        }

        if (companyResponse.success) {
          setCompanies(companyResponse.companies);
          if (companyResponse.companies.length > 0) {
            setCompany(companyResponse.companies[0].id);
          }
        }
      } catch (error) {
        console.error('Error fetching initial data:', error);
        showNotification('Error loading initial data', 'error');
      }
    };

    fetchInitialData();
  }, []);

  const showNotification = (message, severity = 'success') => {
    setNotification({
      open: true,
      message,
      severity
    });
  };

  const handleCloseNotification = () => {
    setNotification(prev => ({ ...prev, open: false }));
  };

  const buildDownloadUrl = (format) => {
    const params = new URLSearchParams();
    params.append('format', format);

    if (warehouse) params.append('warehouse_id', warehouse);
    if (company) params.append('company_id', company);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    if (batchId) params.append('batch_id', batchId);

    return `${config.API_SERVER}invoices/supply-sheet/download?${params.toString()}`;
  };

  const handleDownload = async (format) => {
    if (!warehouse || !company) {
      showNotification('Please select both warehouse and company', 'error');
      return;
    }

    setLoading(true);
    try {
      const downloadUrl = buildDownloadUrl(format);

      // Create a temporary link and trigger download
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = `supply_sheet_${format}_${new Date().toISOString().split('T')[0]}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      showNotification(`Supply sheet downloaded as ${format.toUpperCase()}`, 'success');
    } catch (error) {
      console.error('Download error:', error);
      showNotification('Error downloading file', 'error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Grid container spacing={gridSpacing}>
      {/* Page Header */}
      <Grid item xs={12}>
        <Box className={classes.pageHeader}>
          <Typography variant="h3" gutterBottom>
            Marketing Supply Sheet Generator
          </Typography>
          <Typography variant="subtitle1">
            Generate and download supply sheets from invoice data
          </Typography>
        </Box>
      </Grid>

      {/* Filter Controls */}
      <Grid item xs={12}>
        <Card className={classes.filterCard}>
          <CardContent>
            <Typography variant="h4" gutterBottom>
              <IconFilter className={classes.buttonIcon} />
              Filter Options
            </Typography>

            <Grid container spacing={3}>
              <Grid item xs={12} md={6} lg={3}>
                <FormControl variant="outlined" className={classes.formControl} fullWidth>
                  <InputLabel>Warehouse *</InputLabel>
                  <Select
                    value={warehouse}
                    onChange={(e) => setWarehouse(e.target.value)}
                    label="Warehouse *"
                  >
                    {warehouses.map((wh) => (
                      <MenuItem key={wh.id} value={wh.id}>
                        {wh.name}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>

              <Grid item xs={12} md={6} lg={3}>
                <FormControl variant="outlined" className={classes.formControl} fullWidth>
                  <InputLabel>Company *</InputLabel>
                  <Select
                    value={company}
                    onChange={(e) => setCompany(e.target.value)}
                    label="Company *"
                  >
                    {companies.map((comp) => (
                      <MenuItem key={comp.id} value={comp.id}>
                        {comp.name}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>

              <Grid item xs={12} md={6} lg={3}>
                <TextField
                  fullWidth
                  label="Start Date"
                  type="date"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  InputLabelProps={{ shrink: true }}
                  className={classes.dateField}
                />
              </Grid>

              <Grid item xs={12} md={6} lg={3}>
                <TextField
                  fullWidth
                  label="End Date"
                  type="date"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  InputLabelProps={{ shrink: true }}
                  className={classes.dateField}
                />
              </Grid>

              <Grid item xs={12} md={6} lg={3}>
                <TextField
                  fullWidth
                  label="Batch ID (Optional)"
                  value={batchId}
                  onChange={(e) => setBatchId(e.target.value)}
                  placeholder="Enter upload batch ID"
                />
              </Grid>
            </Grid>
          </CardContent>
        </Card>
      </Grid>

      {/* Download Section */}
      <Grid item xs={12}>
        <Card>
          <CardContent className={classes.downloadSection}>
            <Typography variant="h4" gutterBottom>
              <IconDownload className={classes.buttonIcon} />
              Download Supply Sheet
            </Typography>
            <Typography variant="body1" color="textSecondary" gutterBottom>
              Choose your preferred format to download the marketing supply sheet
            </Typography>

            <Box mt={4}>
              <Button
                variant="contained"
                className={`${classes.downloadButton} ${classes.excelButton}`}
                onClick={() => handleDownload('excel')}
                disabled={loading || !warehouse || !company}
                startIcon={loading ? <CircularProgress size={20} /> : <IconTable />}
              >
                {loading ? 'Generating...' : 'Download Excel'}
              </Button>

              <Button
                variant="contained"
                className={`${classes.downloadButton} ${classes.pngButton}`}
                onClick={() => handleDownload('png')}
                disabled={loading || !warehouse || !company}
                startIcon={loading ? <CircularProgress size={20} /> : <IconPhoto />}
              >
                {loading ? 'Generating...' : 'Download PNG'}
              </Button>
            </Box>

            {(!warehouse || !company) && (
              <Typography variant="body2" color="error" style={{ marginTop: 16 }}>
                Please select both warehouse and company to enable downloads
              </Typography>
            )}
          </CardContent>
        </Card>
      </Grid>

      {/* Notification Snackbar */}
      <Snackbar
        open={notification.open}
        autoHideDuration={6000}
        onClose={handleCloseNotification}
        anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <Alert
          onClose={handleCloseNotification}
          severity={notification.severity}
          variant="filled"
        >
          {notification.message}
        </Alert>
      </Snackbar>
    </Grid>
  );
};

export default SupplySheetDownload;