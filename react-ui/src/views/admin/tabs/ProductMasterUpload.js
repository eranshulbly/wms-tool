import React, { useState } from 'react';
import {
  Box,
  Button,
  Typography,
  CircularProgress,
  Grid,
  MenuItem,
  TextField,
  Paper,
  Alert,
  AlertTitle,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Snackbar,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconUpload, IconFileSpreadsheet } from '@tabler/icons';
import api from '../../../services/api';
import { useWarehouse } from '../../../context/WarehouseContext';
import UploadFormatHelp from '../UploadFormatHelp';

// The nine columns, in the order the downloadable template writes them. Each note
// names the supplier's own heading too, because the upload accepts Cadila's rate list
// unedited — the aliases in master_upload.COLUMNS are what make that true, so the two
// lists have to say the same thing.
const FORMAT_SPEC = {
  id: 'product_master',
  label: 'Product Master',
  table: 'product + product_uom + categories',
  blurb:
    'The product catalogue and how each product is packed. Matched on Part Number: an ' +
    'existing product is updated, a new one is created, and nothing is ever deleted — so ' +
    're-uploading a corrected or extended file is always safe. Prices are not part of this ' +
    'file; a product is priced by the first goods receipt that brings it in.',
  columns: [
    { name: 'Part Number', required: true, note: "The key rows are matched on. Cadila's list calls this PD. CODE" },
    { name: 'Name', required: true, note: 'Product name. Cadila: NAME OF PRODUCTS' },
    { name: 'Strips per Box', required: true, note: 'Cadila: STRIP. For a liquid or a cream this is bottles or tubes per box — 1 when the box holds a single one' },
    { name: 'Boxes per Case', required: true, note: 'Boxes in one case or shipper. Cadila: CASE' },
    { name: 'Tabs per Strip', required: false, note: 'Cadila: TAB. Counted but never ordered or priced. Defaults to 1' },
    { name: 'Pack', required: false, note: 'Label for one strip, e.g. 10 T or 200 ML. Also decides the unit: ML reads as a bottle, GM as a tube, an injection as a vial' },
    { name: 'Box Pack', required: false, note: 'Label for one box, e.g. 30X10T' },
    { name: 'Description', required: false, note: 'Composition or longer description. Cadila: COMPOSITION' },
    { name: 'Division', required: false, note: "Division code, e.g. CG or CR — saved as the product's category. Cadila: DIVN CODE. A code with no category yet creates one; a blank cell leaves the category unchanged" },
  ],
  sample: [
    ['TBA38AU', 'ALERTRIZ 5MG TAB', '30', '66', '10', '10 T', '30X10T', 'Levocetirizine Dihydrochloride 5mg', 'CG'],
    ['TBA15BP', 'ALBENDAZOLE TAB', '100', '60', '1', '1 T', '100X1 T', 'Albendazole IP 400mg', 'CG'],
    ['LQA45AM', 'ADD APP SYRUP', '1', '60', '1', '200 ML', '200 ML', 'Cyproheptadine Hcl IP', 'CG'],
  ],
  info: (
    <>
      Cadila&apos;s <strong>ITEM RATE LIST</strong> can be uploaded as it arrives — the header
      does not have to be on the first row, the supplier&apos;s own column names are
      recognised, and division banner rows are skipped rather than reported as errors.
      The older, longer headings still work too, so a template you downloaded earlier
      does not need redoing.
    </>
  ),
};

const useStyles = makeStyles((theme) => ({
  section: { marginBottom: theme.spacing(3) },
  drop: {
    border: '2px dashed #c4cdd5',
    borderRadius: 8,
    padding: theme.spacing(4),
    textAlign: 'center',
    background: '#fafbfc',
  },
  filename: { marginTop: theme.spacing(1), fontFamily: 'monospace' },
  muted: { color: '#7a869a' },
}));

const ProductMasterUpload = () => {
  const classes = useStyles();
  const { companies, selectedCompany, setSelectedCompany } = useWarehouse();

  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [toast, setToast] = useState(null);

  const upload = async () => {
    if (!file || !selectedCompany) return;
    setBusy(true);
    setResult(null);
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('company_id', selectedCompany);
      const { data } = await api.post('admin/catalog/product-master', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      if (data.success) {
        setResult(data);
        setToast({ severity: 'success', msg: 'Product master uploaded' });
      } else {
        setToast({ severity: 'error', msg: data.msg || 'Upload failed' });
      }
    } catch (e) {
      setToast({
        severity: 'error',
        msg: e?.response?.data?.msg || 'Upload failed',
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Product Master
      </Typography>

      <UploadFormatHelp spec={FORMAT_SPEC} />

      <Paper variant="outlined" className={classes.section} style={{ padding: 16 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} sm={4}>
            <TextField
              select
              fullWidth
              size="small"
              label="Company"
              value={selectedCompany || ''}
              onChange={(e) => setSelectedCompany(e.target.value)}
              helperText="The catalogue these products belong to"
            >
              {companies.map((c) => (
                <MenuItem key={c.id} value={c.id}>
                  {c.name}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid item xs={12} sm={8}>
            <label htmlFor="product-master-file">
              <input
                id="product-master-file"
                type="file"
                accept=".csv,.xls,.xlsx"
                style={{ display: 'none' }}
                onChange={(e) => {
                  setFile(e.target.files[0] || null);
                  setResult(null);
                }}
              />
              <Box className={classes.drop}>
                <IconFileSpreadsheet size={28} />
                <Typography variant="body2" className={classes.muted}>
                  Click to choose a CSV or Excel file
                </Typography>
                {file && (
                  <Typography variant="body2" className={classes.filename}>
                    {file.name}
                  </Typography>
                )}
                <Button component="span" size="small" style={{ marginTop: 8 }}>
                  Browse
                </Button>
              </Box>
            </label>
          </Grid>
        </Grid>

        <Box mt={2} display="flex" alignItems="center">
          <Button
            variant="contained"
            startIcon={busy ? <CircularProgress size={16} /> : <IconUpload size={16} />}
            disabled={!file || !selectedCompany || busy}
            onClick={upload}
          >
            {busy ? 'Uploading…' : 'Upload Product Master'}
          </Button>
          {!selectedCompany && (
            <Typography variant="body2" className={classes.muted} style={{ marginLeft: 12 }}>
              Select a company first.
            </Typography>
          )}
        </Box>
      </Paper>

      {result && (
        <Paper variant="outlined" className={classes.section} style={{ padding: 16 }}>
          <Alert severity={result.error_count ? 'warning' : 'success'}>
            <AlertTitle>
              {result.inserted} created · {result.updated} updated
            </AlertTitle>
            {result.ladders} packaging ladder{result.ladders === 1 ? '' : 's'} written
            {result.divisions > 0 && ` · ${result.divisions} product${
              result.divisions === 1 ? '' : 's'} categorised by division`}
            {result.categories_created?.length > 0 && (
              <div>
                New categories created: <strong>{result.categories_created.join(', ')}</strong>
              </div>
            )}
            {result.skipped > 0 && ` · ${result.skipped} non-product row${
              result.skipped === 1 ? '' : 's'} skipped`}
            {result.error_count > 0 && ` · ${result.error_count} row${
              result.error_count === 1 ? '' : 's'} rejected`}
          </Alert>

          {result.error_count > 0 && (
            <TableContainer style={{ marginTop: 12, maxHeight: '40vh' }}>
              <Table size="small" stickyHeader>
                <TableHead>
                  <TableRow>
                    <TableCell>Row</TableCell>
                    <TableCell>Part Number</TableCell>
                    <TableCell>Reason</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {result.errors.map((e, i) => (
                    <TableRow key={`${e.row}-${i}`}>
                      <TableCell>{e.row}</TableCell>
                      <TableCell>{e.key || '—'}</TableCell>
                      <TableCell>{e.reason}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </Paper>
      )}

      <Snackbar
        open={!!toast}
        autoHideDuration={5000}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity={toast?.severity || 'info'} onClose={() => setToast(null)}>
          {toast?.msg}
        </Alert>
      </Snackbar>
    </Box>
  );
};

export default ProductMasterUpload;
