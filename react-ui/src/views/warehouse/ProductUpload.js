import React from 'react';
import { Typography } from '@material-ui/core';
import MainCard from '../../ui-component/cards/MainCard';
import FileUploadForm from './components/FileUploadForm';

const computeExtraStats = (data) =>
  data.orders_updated != null
    ? [{ label: 'Orders Updated', value: data.orders_updated, color: 'secondary' }]
    : [];

const ProductUpload = () => (
  <MainCard title="Upload Product File">
    <FileUploadForm
      endpoint="products/upload"
      maxSizeMB={10}
      requiresWarehouse={false}
      requiresCompany
      successLabel="Product Lines Processed"
      errorFilename="product_upload_errors"
      processingMessage="Processing product file and linking to orders…"
      uploadButtonLabel="Process Product File"
      inputId="product-file-upload"
      computeExtraStats={computeExtraStats}
      descriptionNode={
        <>
          <Typography variant="h4" gutterBottom>Upload Product Excel/CSV File</Typography>
          <Typography variant="body2" color="textSecondary" gutterBottom>
            Upload your spare parts / product file to attach product lines to existing orders.
            Each row links a <strong>Part #</strong> to an <strong>Order #</strong>.
            Existing product lines for matched orders will be replaced.
          </Typography>
        </>
      }
      rulesNode={
        <>
          <Typography variant="subtitle2" gutterBottom>Processing Rules:</Typography>
          <Typography variant="body2" component="div">
            <ul style={{ paddingLeft: '20px', margin: '8px 0' }}>
              <li>
                File must have <strong>Order #</strong>, <strong>Part #</strong>,{' '}
                <strong>Part Description</strong>, and <strong>Reserved Qty</strong> columns
              </li>
              <li><strong>Reserved Qty</strong> is used as the product quantity</li>
              <li>If an order already has products, they are <strong>replaced</strong> by this upload</li>
              <li>New Part # values are automatically created as products</li>
              <li>Order # must match an existing order in the system</li>
              <li>Errors are provided in a downloadable report</li>
            </ul>
          </Typography>
        </>
      }
    />
  </MainCard>
);

export default ProductUpload;
