import React, { useState } from 'react';
import { Typography, Tabs, Tab, Box } from '@material-ui/core';
import MainCard from '../../ui-component/cards/MainCard';
import FileUploadForm from './components/FileUploadForm';
import DownloadPicklist from './components/DownloadPicklist';

// Two tabs on one screen: upload the file, then — right next to it, not a separate
// menu item — download the picklist each order in that file just became eligible for.
const OrderUpload = () => {
  const [tab, setTab] = useState('upload');

  return (
    <MainCard title="Upload Order File">
      <Tabs value={tab} onChange={(e, v) => setTab(v)} style={{ marginBottom: 16 }}>
        <Tab label="Upload Orders" value="upload" />
        <Tab label="Download Picklist" value="picklist" />
      </Tabs>

      {tab === 'upload' ? (
        <FileUploadForm
          endpoint="orders/upload"
          maxSizeMB={5}
          requiresWarehouse
          requiresCompany
          allowMultiple
          successLabel="Orders Processed"
          errorFilename="order_upload_errors"
          processingMessage="Uploading and processing file…"
          uploadButtonLabel="Upload File"
          inputId="order-file-upload"
          descriptionNode={
            <>
              <Typography variant="h4" gutterBottom>Upload Order File</Typography>
              <Typography variant="body2" color="textSecondary" gutterBottom>
                Upload your order file as Excel, CSV or PDF. The system will process the data and
                create orders accordingly.
              </Typography>
            </>
          }
          rulesNode={
            <>
              <Typography variant="subtitle2" gutterBottom>File Format Requirements:</Typography>
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
            </>
          }
        />
      ) : (
        <Box>
          <DownloadPicklist />
        </Box>
      )}
    </MainCard>
  );
};

export default OrderUpload;
