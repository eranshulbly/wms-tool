import React, { useState, useEffect, useMemo, useRef } from 'react';
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
  Snackbar,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconUpload, IconFileSpreadsheet } from '@tabler/icons';
import api from '../../../services/api';
import UploadFormatHelp from '../UploadFormatHelp';

// ---------------------------------------------------------------------------
// Templates
//
// The master arrives in a different shape per company, because each supplier
// identifies its products differently. Hero's dump is keyed on a part number;
// Cadila's is a name and a description with no code at all.
//
// The backend accepts BOTH without being told which: it keys on the part-number
// column when the file has one, and on the product name within the company when
// it does not. These specs exist so the operator sees the right guidance and
// downloads the right sample — they do not drive parsing.
// ---------------------------------------------------------------------------
const HERO_TEMPLATE = {
  id: 'product_master_partno',
  label: 'Product Master (part-numbered)',
  table: 'product',
  blurb:
    'The product master. Matched on Part Number: existing products are updated, new ones ' +
    'are created, nothing is ever deleted. Every column except Part Number is optional, so ' +
    'a file covering just a few of them updates only those.',
  columns: [
    { name: 'Part Number', required: true, note: 'The key rows are matched on. Also accepted: Part No, Product String' },
    { name: 'Name', required: false, note: 'Product name; on a new product defaults to the description' },
    { name: 'Description', required: false, note: 'Longer description. Also accepted: Part Description' },
    { name: 'Product Category', required: false, note: 'Sub-category, e.g. HHML Parts / HDX Parts / VIDA Parts' },
    { name: 'Category', required: false, note: 'Parts / Oil / Battery / Tyre / Accessories / Publications / Pro Parts' },
    { name: 'UOM', required: false, note: 'Selling unit, e.g. Pcs. (max 20 chars)' },
    { name: 'Size', required: false, note: 'Packed size, e.g. 390 x 240 x 330 MM (max 100 chars)' },
    { name: 'Weight', required: false, note: 'Number, stored as-is with no unit conversion. Also accepted: Net Weight' },
    { name: 'Price', required: false, note: 'Number, up to 2 decimal places' },
    { name: 'Barcode', required: false, note: 'Must be unique across products (max 100 chars)' },
    { name: 'HSN Code', required: false, note: 'Max 20 chars. Also accepted: HSN' },
    { name: 'is_active', required: false, note: 'Y or N — defaults to active on a new product' },
  ],
  sample: [
    ['HDH96600060220FS', 'SOCKET BOLT 6X22', 'SOCKET BOLT 6X22', 'HDX Parts', 'Parts', 'Pcs.', '90 x 40 x 40 MM', '12', '', '', '', 'Y'],
    ['22121198900S', 'CENTER CLUTCH', 'CENTER CLUTCH', 'HHML Parts', 'Parts', 'Pcs.', '390 x 240 x 330 MM', '223', '', '', '', 'Y'],
  ],
};

const NAME_TEMPLATE = {
  id: 'product_master_named',
  label: 'Product Master (by name)',
  table: 'product',
  blurb:
    'The product master for a supplier that issues no product codes. Matched on the ' +
    'product Name within this company: an existing product is updated, a new one is ' +
    'created with a product code generated from its name. Nothing is ever deleted.',
  columns: [
    { name: 'Name', required: true, note: 'The key rows are matched on, within the selected company' },
    { name: 'Description', required: false, note: 'Composition or longer description' },
  ],
  sample: [
    ['ACENEXT MR TAB', 'Aceclofenac 100 mg + Paracetamol 325 mg + Chlorzoxazone 250 mg'],
    ['ACENEXT P TAB', 'Aceclofenac BP 100mg + Paracetamol 325 mg'],
  ],
};

// Cadila's master is packed and priced in a hierarchy: tablets in a strip, strips
// in a box, boxes in a case — ordered by the box or case, but priced per strip.
// Those columns do not live on the product row; the backend writes them to the
// packaging ladder (product_uom) and the dated price table (product_price).
//
// The three marked required are the ones a NEW product cannot be created without,
// because without them an order in boxes cannot be converted to strips and priced.
// An existing product can still be updated one column at a time — correcting a
// single price does not mean restating the whole pack.
const CADILA_TEMPLATE = {
  id: 'product_master_packaged',
  label: 'Product Master (packaged & priced)',
  table: 'product',
  blurb:
    'The product master for a supplier that sells in packs. Matched on Part Number: existing ' +
    'products are updated, new ones are created, nothing is ever deleted. Orders are placed in ' +
    'boxes or cases and converted to selling units (strips) for pricing, so a new product must ' +
    'carry its pack sizes and a billing price. Prices are dated on upload — orders already ' +
    'placed keep the rate they were priced at.',
  columns: [
    { name: 'Part Number', required: true, note: 'The key rows are matched on (Cadila: PD. CODE). Also accepted: Part No, Product String' },
    { name: 'Name', required: true, note: 'Product name, e.g. ALERTRIZ 5MG TAB' },
    { name: 'Selling Units per Box', required: true, note: 'Strips in one box (Cadila: STRIP). This is what converts a box order into priced units' },
    { name: 'Boxes per Case', required: true, note: 'Boxes in one case/shipper (Cadila: CASE)' },
    { name: 'Billing Price', required: true, note: 'Price of ONE selling unit (per strip), not per box. Up to 4 decimals' },
    { name: 'Base Units per Selling Unit', required: false, note: 'Tablets in one strip (Cadila: TAB). Informational — never ordered or priced. Defaults to 1' },
    { name: 'Selling Unit', required: false, note: 'STRIP / BOTTLE / VIAL / TUBE / SACHET. Defaults to STRIP; use BOTTLE for liquids so the unit reads correctly' },
    { name: 'Landing Price', required: false, note: 'Per selling unit, net of scheme. Used for order value when present, else Billing Price' },
    { name: 'Net Rate', required: false, note: 'Per selling unit, after further scheme discount' },
    { name: 'MRP', required: false, note: 'Per selling unit' },
    { name: 'Pack', required: false, note: 'Label for one selling unit, e.g. 10 T or 200 ML' },
    { name: 'Box Pack', required: false, note: 'Label for one box, e.g. 30X10T' },
    { name: 'Composition', required: false, note: 'Stored as a product attribute, not a product column' },
    { name: 'Division', required: false, note: 'e.g. CG / CR — stored as a product attribute' },
    { name: 'HSN Code', required: false, note: 'Max 20 chars. Also accepted: HSN' },
    { name: 'Description', required: false, note: 'Longer description. Also accepted: Part Description' },
    { name: 'is_active', required: false, note: 'Y or N — defaults to active on a new product' },
  ],
  sample: [
    // Real shapes from the June'26 list: a 30x10 tablet box, a 100x1 box, and a
    // single-bottle liquid where the strip level collapses to 1.
    ['TBA38AU', 'ALERTRIZ 5MG TAB', '30', '66', '4.14', '10', 'STRIP', '', '', '52.73', '10 T', '30X10T', 'Levocetirizine Dihydrochloride 5mg', 'CG', '30049099', '', 'Y'],
    ['TBA15BP', 'ALBENDAZOLE TAB', '100', '60', '2.75', '1', 'STRIP', '', '', '7.57', '1 T', '100X1 T', 'Albendazole IP 400mg', 'CG', '30049099', '', 'Y'],
    ['LQA45AM', 'ADD APP SYRUP', '1', '60', '26.25', '1', 'BOTTLE', '25.48', '', '138.66', '200 ML', '200 ML', 'Cyproheptadine Hcl IP', 'CG', '30049093', '', 'Y'],
  ],
};

// Which template a company's master follows. A company not listed gets the
// name-keyed one, since that is the shape that needs no supplier-issued codes.
// Matched on the leading word so a trading name ('Cadila Pharmaceuticals Ltd')
// resolves the same as the bare brand — the backend profile lookup does likewise.
const TEMPLATE_BY_COMPANY = { hero: HERO_TEMPLATE, cadila: CADILA_TEMPLATE };
const templateFor = (name) => {
  const norm = (name || '').trim().toLowerCase();
  const hit = Object.keys(TEMPLATE_BY_COMPANY).find(
    (key) => norm === key || norm.startsWith(`${key} `)
  );
  return hit ? TEMPLATE_BY_COMPANY[hit] : NAME_TEMPLATE;
};

const useStyles = makeStyles((theme) => ({
  section: { marginBottom: theme.spacing(3) },
  dropzone: {
    border: '2px dashed #c3c9d5',
    borderRadius: 8,
    padding: theme.spacing(4),
    textAlign: 'center',
    cursor: 'pointer',
    '&:hover': { borderColor: theme.palette.primary.main, background: '#fafbfc' },
  },
  hidden: { display: 'none' },
  muted: { color: '#7a869a' },
}));

const ProductMasterUpload = () => {
  const classes = useStyles();
  const fileRef = useRef(null);

  const [companies, setCompanies] = useState([]);
  const [companyId, setCompanyId] = useState('');
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    api
      .get('companies')
      .then((res) => setCompanies(res.data?.companies || []))
      .catch(() => setToast({ severity: 'error', msg: 'Could not load companies' }));
  }, []);

  const company = companies.find((c) => c.id === companyId);
  const spec = useMemo(() => templateFor(company?.name), [company]);

  const upload = async () => {
    if (!file || !companyId) return;
    const form = new FormData();
    form.append('file', file);
    form.append('company_id', companyId);

    setUploading(true);
    setResult(null);
    try {
      const { data } = await api.post('admin/monthly/products', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setResult(data);
      setToast({
        severity: data.success ? 'success' : 'error',
        msg: data.msg || (data.success ? 'Upload complete' : 'Upload failed'),
      });
    } catch (e) {
      setToast({ severity: 'error', msg: e?.response?.data?.msg || 'Upload failed' });
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Product Master
      </Typography>

      <Paper variant="outlined" className={classes.section} style={{ padding: 16 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} sm={5}>
            <TextField
              select
              fullWidth
              size="small"
              label="Company"
              value={companyId}
              onChange={(e) => {
                setCompanyId(e.target.value);
                setResult(null);
              }}
              helperText="The master loads into this company — the file carries no company column"
            >
              {companies.map((c) => (
                <MenuItem key={c.id} value={c.id}>
                  {c.name}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid item xs={12} sm={7}>
            {companyId ? (
              <Box display="flex" alignItems="center" style={{ gap: 8 }}>
                <IconFileSpreadsheet size={18} />
                <Typography variant="body2">
                  Expected format: <strong>{spec.label}</strong>
                </Typography>
                <UploadFormatHelp spec={spec} />
              </Box>
            ) : (
              <Typography variant="body2" className={classes.muted}>
                Select a company to see the format its master should follow.
              </Typography>
            )}
          </Grid>
        </Grid>

        <Box
          mt={2}
          className={classes.dropzone}
          onClick={() => companyId && fileRef.current && fileRef.current.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            if (companyId && e.dataTransfer.files?.[0]) setFile(e.dataTransfer.files[0]);
          }}
        >
          {uploading ? (
            <CircularProgress size={26} />
          ) : (
            <>
              <IconUpload size={26} />
              <Typography variant="subtitle1">
                {file ? file.name : 'Drop the product master here, or click to choose'}
              </Typography>
              <Typography variant="caption" className={classes.muted}>
                .xlsx, .xls or .csv — existing products are updated, new ones created,
                nothing is deleted.
              </Typography>
            </>
          )}
        </Box>
        <input
          ref={fileRef}
          type="file"
          accept=".xlsx,.xls,.csv"
          className={classes.hidden}
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />

        <Box mt={2} display="flex" alignItems="center">
          {!companyId && (
            <Typography variant="caption" style={{ color: '#ed6c02' }}>
              Select a company before uploading.
            </Typography>
          )}
          <Box flexGrow={1} />
          <Button
            variant="contained"
            disabled={!file || !companyId || uploading}
            onClick={upload}
          >
            Upload product master
          </Button>
        </Box>
      </Paper>

      {result && (
        <Alert severity={result.success ? 'success' : 'error'} className={classes.section}>
          {result.msg}
          {result.warnings?.map((w, i) => (
            <div key={i} style={{ fontSize: '0.82rem', marginTop: 4 }}>
              {w}
            </div>
          ))}
        </Alert>
      )}

      <Snackbar
        open={!!toast}
        autoHideDuration={6000}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        {toast && <Alert severity={toast.severity}>{toast.msg}</Alert>}
      </Snackbar>
    </Box>
  );
};

export default ProductMasterUpload;
