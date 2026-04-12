import React, { useState } from 'react';
import {
  Grid,
  Card,
  CardContent,
  Box,
  Button,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Typography
} from '@material-ui/core';
import { IconUpload } from '@tabler/icons';
import { BULK_TARGET_STATUSES } from '../constants/statuses';
import UploadResultCard from '../../../components/UploadResultCard';
import { bulkStatusUpdate } from '../../../services/orderService';

/**
 * Target status dropdown + Excel file upload for bulk order status moves.
 * Shows inline result card after a successful upload.
 *
 * Props:
 *   warehouse         — selected warehouse ID
 *   company           — selected company ID
 *   onUploadComplete  — (result) => void — called after successful bulk move
 */
const BulkActionsBar = ({ warehouse, company, onUploadComplete }) => {
  const [targetStatus, setTargetStatus] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);

  const selectedConfig = BULK_TARGET_STATUSES.find((s) => s.value === targetStatus);

  const handleFileChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    e.target.value = '';

    if (!targetStatus) {
      alert('Please select a target status before uploading.');
      return;
    }

    setUploading(true);
    try {
      const result = await bulkStatusUpdate(file, targetStatus, warehouse, company);
      setUploadResult(result);
      if (result.processed_count > 0) {
        onUploadComplete(result);
      }
    } catch (err) {
      alert('Failed to upload file: ' + (err.response?.data?.msg || err.message));
    } finally {
      setUploading(false);
    }
  };

  const handleReset = () => {
    setUploadResult(null);
    setTargetStatus('');
  };

  if (uploadResult) {
    return (
      <Grid item xs={12}>
        <UploadResultCard
          result={uploadResult}
          onReset={handleReset}
          successLabel="Orders Moved"
          errorFilename={`bulk_status_errors_${new Date().toISOString().slice(0, 10)}.xlsx`}
        />
      </Grid>
    );
  }

  return (
    <Grid item xs={12}>
      <Card>
        <CardContent>
          <Typography variant="subtitle1" style={{ fontWeight: 600, marginBottom: 12 }}>
            Bulk Status Update
          </Typography>
          <Box display="flex" alignItems="center" flexWrap="wrap" style={{ gap: 12 }}>
            <FormControl variant="outlined" style={{ minWidth: 200 }}>
              <InputLabel id="bulk-target-label">Target Status</InputLabel>
              <Select
                labelId="bulk-target-label"
                value={targetStatus}
                onChange={(e) => setTargetStatus(e.target.value)}
                label="Target Status"
              >
                {BULK_TARGET_STATUSES.map((s) => (
                  <MenuItem key={s.value} value={s.value}>{s.label}</MenuItem>
                ))}
              </Select>
            </FormControl>

            <Button
              variant="contained"
              color="primary"
              component="label"
              startIcon={
                uploading ? <CircularProgress size={16} color="inherit" /> : <IconUpload size={16} />
              }
              disabled={uploading || !targetStatus}
            >
              {uploading ? 'Uploading…' : 'Upload Excel'}
              <input type="file" accept=".xlsx,.xls,.csv" hidden onChange={handleFileChange} />
            </Button>
          </Box>

          <Typography variant="caption" color="textSecondary" style={{ marginTop: 8, display: 'block' }}>
            Upload an Excel with an <strong>Order ID</strong> column
            {selectedConfig?.requiresBoxes && (
              <> and a <strong>Number of Boxes</strong> column (required for Packed)</>
            )}
            . Only orders in the correct preceding state will be moved.
          </Typography>
        </CardContent>
      </Card>
    </Grid>
  );
};

export default BulkActionsBar;
