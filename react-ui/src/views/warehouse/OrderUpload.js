import React from 'react';
import { Typography } from '@material-ui/core';
import MainCard from '../../ui-component/cards/MainCard';
import FileUploadForm from './components/FileUploadForm';

const OrderUpload = () => (
  <MainCard title="Upload Order File">
    <FileUploadForm
      endpoint="orders/upload"
      maxSizeMB={5}
      requiresWarehouse
      requiresCompany
      successLabel="Orders Processed"
      errorFilename="order_upload_errors"
      processingMessage="Uploading and processing file…"
      uploadButtonLabel="Upload File"
      inputId="order-file-upload"
      descriptionNode={
        <>
          <Typography variant="h4" gutterBottom>Upload Excel/CSV File</Typography>
          <Typography variant="body2" color="textSecondary" gutterBottom>
            Upload your order file in Excel or CSV format. The system will process the data and
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
  </MainCard>
);

export default OrderUpload;
