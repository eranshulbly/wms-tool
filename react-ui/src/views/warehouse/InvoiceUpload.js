import React from 'react';
import { Typography } from '@material-ui/core';
import MainCard from '../../ui-component/cards/MainCard';
import FileUploadForm from './components/FileUploadForm';

const computeExtraStats = (data) => [
  ...(data.orders_invoiced != null
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
      processingMessage="Processing invoice file and updating orders…"
      uploadButtonLabel="Process Invoice File"
      inputId="invoice-file-upload"
      computeExtraStats={computeExtraStats}
      descriptionNode={
        <>
          <Typography variant="h4" gutterBottom>Upload Invoice Excel/CSV File</Typography>
          <Typography variant="body2" color="textSecondary" gutterBottom>
            Upload your invoice file to move matched orders to <strong>Invoiced</strong> status.
            Orders in <em>Packed</em> state (or bypass order types like ZGOI) are invoiced immediately.
            Orders still in Open/Picking receive an <em>Invoice Submitted</em> flag and are
            auto-invoiced when moved to Packed.
          </Typography>
        </>
      }
      rulesNode={
        <>
          <Typography variant="subtitle2" gutterBottom>Processing Rules:</Typography>
          <Typography variant="body2" component="div">
            <ul style={{ paddingLeft: '20px', margin: '8px 0' }}>
              <li>File must have <strong>Invoice #</strong> and <strong>Order #</strong> columns</li>
              <li><strong>Bypass types (e.g. ZGOI):</strong> moved to Invoiced regardless of current state</li>
              <li><strong>Packed orders:</strong> moved to Invoiced immediately</li>
              <li>
                <strong>Open / Picking orders:</strong> flagged as "Invoice Submitted" — auto-transition
                to Invoiced when moved to Packed
              </li>
              <li>Already Invoiced / Dispatch Ready orders are reported as duplicates</li>
              <li>Errors are provided in a downloadable report</li>
            </ul>
          </Typography>
        </>
      }
    />
  </MainCard>
);

export default InvoiceUpload;
