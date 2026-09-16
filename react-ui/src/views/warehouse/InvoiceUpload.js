import React from 'react';
import { Typography } from '@material-ui/core';
import MainCard from '../../ui-component/cards/MainCard';
import FileUploadForm from './components/FileUploadForm';

const computeExtraStats = (data) => [
  ...(data.orders_completed != null && data.orders_completed > 0
    ? [{ label: 'Orders Completed', value: data.orders_completed, color: 'primary' }]
    : []),
  ...(data.orders_invoiced != null && data.orders_invoiced > 0
    ? [{ label: 'Orders Invoiced', value: data.orders_invoiced, color: 'secondary' }]
    : []),
  ...(data.orders_flagged != null && data.orders_flagged > 0
    ? [{ label: 'Invoice Submitted (pending pack)', value: data.orders_flagged, color: 'default' }]
    : [])
];

const InvoiceUpload = () => (
  <MainCard title="Upload Invoice File">
    <FileUploadForm
      endpoint="invoices/upload"
      maxSizeMB={10}
      requiresWarehouse
      requiresCompany
      successLabel="Invoices Processed"
      errorFilename="invoice_upload_errors"
      processingMessage="Processing invoice file and closing orders…"
      uploadButtonLabel="Process Invoice File"
      inputId="invoice-file-upload"
      computeExtraStats={computeExtraStats}
      descriptionNode={
        <>
          <Typography variant="h4" gutterBottom>Upload Invoice File</Typography>
          <Typography variant="body2" color="textSecondary" gutterBottom>
            Upload the same GST invoice PDF that opened the order. The invoice closes it:
            the stock leaves the batches printed on the invoice and the order moves
            to <strong>Completed</strong>.
          </Typography>
        </>
      }
      rulesNode={
        <>
          <Typography variant="subtitle2" gutterBottom>Processing Rules:</Typography>
          <Typography variant="body2" component="div">
            <ul style={{ paddingLeft: '20px', margin: '8px 0' }}>
              <li>The order must already exist — upload the invoice to <strong>Upload Orders</strong> first</li>
              <li>
                <strong>Stock:</strong> taken out of the exact batch on each line. If any batch
                is short, that order is not closed and nothing about it changes
              </li>
              <li>The invoice amount and date are recorded against the order&apos;s dealer</li>
              <li>A closed order cannot be invoiced again — a repeat upload is reported as a duplicate</li>
              <li>Only sales invoices are accepted; goods receipts and credit notes belong in Inventory Ingestion</li>
              <li>Errors are provided in a downloadable report</li>
            </ul>
          </Typography>
        </>
      }
    />
  </MainCard>
);

export default InvoiceUpload;
