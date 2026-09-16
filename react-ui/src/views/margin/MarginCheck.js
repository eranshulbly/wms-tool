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
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Snackbar,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconUpload, IconReceipt2 } from '@tabler/icons';
import api from '../../services/api';
import { useWarehouse } from '../../context/WarehouseContext';

// Margin Check — upload Marg order invoices and see what each product earns, then the
// invoice overall. Nothing is saved: the backend reads the PDFs in memory and returns
// figures only, so an invoice can be checked as often as needed without side effects.

const useStyles = makeStyles((theme) => ({
  section: { marginBottom: theme.spacing(3) },
  drop: {
    border: '2px dashed #c4cdd5',
    borderRadius: 8,
    padding: theme.spacing(3),
    textAlign: 'center',
    background: '#fafbfc',
  },
  muted: { color: '#7a869a' },
  mono: { fontFamily: 'monospace', fontSize: '0.8rem' },
  num: { whiteSpace: 'nowrap' },
  positive: { color: '#12805c' },
  negative: { color: '#c62828' },
  tileValue: { fontWeight: 600, lineHeight: 1.2 },
}));

const money = (v) =>
  v === null || v === undefined
    ? '—'
    : `₹${Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const unit = (v) =>
  v === null || v === undefined
    ? '—'
    : Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 3 });
const pct = (v) => (v === null || v === undefined ? '—' : `${Number(v).toFixed(1)}%`);
const qty = (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString('en-IN'));

// Why a line has no margin, said in words: a dash alone reads as a bug.
const STATUS_NOTE = {
  no_cost: 'No landed cost for this batch — it has not been received through ingestion',
  ambiguous: 'This batch has more than one cost on record, so no single cost is used',
};

const Totals = ({ totals, classes }) => {
  const tone = totals.margin > 0 ? classes.positive : totals.margin < 0 ? classes.negative : '';
  return (
    <>
      <Grid container spacing={3} style={{ marginTop: 4 }}>
        <Grid item xs={12} sm={4}>
          <Typography variant="body2" className={classes.muted}>Sales value (ex-GST)</Typography>
          <Typography variant="h4" className={classes.tileValue}>{money(totals.order_total)}</Typography>
        </Grid>
        <Grid item xs={12} sm={4}>
          <Typography variant="body2" className={classes.muted}>Landed cost (ex-GST)</Typography>
          <Typography variant="h4" className={classes.tileValue}>{money(totals.landing_cost)}</Typography>
        </Grid>
        <Grid item xs={12} sm={4}>
          <Typography variant="body2" className={classes.muted}>Margin (ex-GST)</Typography>
          <Typography variant="h4" className={`${classes.tileValue} ${tone}`}>
            {money(totals.margin)}
            {totals.margin_pct != null && (
              <Typography component="span" variant="body1" style={{ marginLeft: 6 }}>
                ({pct(totals.margin_pct)})
              </Typography>
            )}
          </Typography>
        </Grid>
      </Grid>
      {/* Lines without a cost are left out of the margin, not counted at zero — so say
          how much of the invoice the figure actually covers. */}
      {totals.costed_lines < totals.lines && (
        <Alert severity="warning" style={{ marginTop: 12 }}>
          Margin covers {totals.costed_lines} of {totals.lines} lines. The rest have no landed
          cost on record and are left out rather than counted at zero, which would overstate
          the margin. Sales value above includes every priced line.
        </Alert>
      )}
    </>
  );
};

const InvoiceResult = ({ inv, classes }) => (
  <Paper variant="outlined" className={classes.section} style={{ padding: 16 }}>
    <Typography variant="h5">
      Invoice {inv.doc_number}
      {inv.party_name ? ` — ${inv.party_name}` : ''}
    </Typography>
    <Typography variant="body2" className={classes.muted}>
      {inv.filename}
      {inv.doc_date ? ` · ${inv.doc_date}` : ''} · {inv.lines.length} line
      {inv.lines.length === 1 ? '' : 's'}
    </Typography>

    <Totals totals={inv.totals} classes={classes} />

    <TableContainer style={{ marginTop: 16, maxHeight: '60vh' }}>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            <TableCell>Product</TableCell>
            <TableCell>Batch</TableCell>
            <TableCell align="right">Qty</TableCell>
            <TableCell align="right">Sold at / unit (ex-GST)</TableCell>
            <TableCell align="right">Cost / unit (ex-GST)</TableCell>
            <TableCell align="right">Margin / unit (ex-GST)</TableCell>
            <TableCell align="right">Margin %</TableCell>
            <TableCell align="right">Line margin</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {inv.lines.map((l) => {
            const tone =
              l.margin_value > 0 ? classes.positive : l.margin_value < 0 ? classes.negative : '';
            return (
              <TableRow key={l.line_no} hover>
                <TableCell>
                  <Typography variant="body2" style={{ fontWeight: 600 }}>{l.product_name}</Typography>
                  <Typography variant="caption" className={classes.muted}>
                    {[l.sku_code, l.pack].filter(Boolean).join(' · ')}
                  </Typography>
                  {STATUS_NOTE[l.status] && (
                    <Typography variant="caption" display="block" className={classes.negative}>
                      {STATUS_NOTE[l.status]}
                    </Typography>
                  )}
                </TableCell>
                <TableCell className={classes.mono}>{l.batch || '—'}</TableCell>
                <TableCell align="right" className={classes.num}>{qty(l.quantity)}</TableCell>
                <TableCell align="right" className={classes.num}>{unit(l.sale_rate)}</TableCell>
                <TableCell align="right" className={classes.num}>{unit(l.cost_rate)}</TableCell>
                <TableCell align="right" className={`${classes.num} ${tone}`}>{unit(l.margin_rate)}</TableCell>
                <TableCell align="right" className={`${classes.num} ${tone}`}>{pct(l.margin_pct)}</TableCell>
                <TableCell align="right" className={`${classes.num} ${tone}`}>{money(l.margin_value)}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </TableContainer>

    {inv.warnings?.length > 0 && (
      <Alert severity="info" style={{ marginTop: 12 }}>
        {inv.warnings.map((w, i) => (
          <div key={i} className={classes.mono}>{w}</div>
        ))}
      </Alert>
    )}
  </Paper>
);

const MarginCheck = () => {
  const classes = useStyles();
  const { companies, selectedCompany, setSelectedCompany } = useWarehouse();

  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [toast, setToast] = useState(null);

  const check = async () => {
    if (!files.length || !selectedCompany) return;
    setBusy(true);
    setResult(null);
    try {
      const form = new FormData();
      files.forEach((f) => form.append('files', f));
      form.append('company_id', selectedCompany);
      const { data } = await api.post('admin/margin-check', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      if (data.success) setResult(data);
      else setToast({ severity: 'error', msg: data.msg || 'Margin check failed' });
    } catch (e) {
      setToast({ severity: 'error', msg: e?.response?.data?.msg || 'Margin check failed' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Margin Check
      </Typography>
      <Typography variant="body2" className={classes.muted} style={{ marginBottom: 16 }}>
        Upload Marg order invoices to see the margin on each product and overall. Margin is the
        rate sold at (after discount, ex-GST) less that batch&apos;s landed cost (after credit
        notes, ex-GST). Both sides exclude GST: it is charged on the sale and reclaimed on the
        purchase, so counting it would flatter the margin rather than measure it. Nothing from
        this check is saved.
      </Typography>

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
              helperText="Whose landed costs to compare against"
            >
              {companies.map((c) => (
                <MenuItem key={c.id} value={c.id}>
                  {c.name}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid item xs={12} sm={8}>
            <label htmlFor="margin-check-files">
              <input
                id="margin-check-files"
                type="file"
                accept=".pdf"
                multiple
                style={{ display: 'none' }}
                onChange={(e) => {
                  setFiles(Array.from(e.target.files || []));
                  setResult(null);
                }}
              />
              <Box className={classes.drop}>
                <IconReceipt2 size={28} />
                <Typography variant="body2" className={classes.muted}>
                  Choose one or more Marg order invoice PDFs
                </Typography>
                {files.length > 0 && (
                  <Typography variant="body2" className={classes.mono} style={{ marginTop: 6 }}>
                    {files.map((f) => f.name).join(', ')}
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
            disabled={!files.length || !selectedCompany || busy}
            onClick={check}
          >
            {busy ? 'Checking…' : 'Check margin'}
          </Button>
          {!selectedCompany && (
            <Typography variant="body2" className={classes.muted} style={{ marginLeft: 12 }}>
              Select a company first.
            </Typography>
          )}
        </Box>
      </Paper>

      {result?.failed?.map((f) => (
        <Alert key={f.filename} severity="error" className={classes.section}>
          <strong>{f.filename}</strong> — {f.error}
        </Alert>
      ))}

      {result?.combined && (
        <Paper variant="outlined" className={classes.section} style={{ padding: 16 }}>
          <Typography variant="h5">All {result.invoices.length} invoices</Typography>
          <Typography variant="body2" className={classes.muted}>
            Worked out across every line, so a large invoice counts for more than a small one.
          </Typography>
          <Totals totals={result.combined} classes={classes} />
        </Paper>
      )}

      {result?.invoices?.map((inv) => (
        <InvoiceResult key={`${inv.filename}:${inv.doc_number}`} inv={inv} classes={classes} />
      ))}

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

export default MarginCheck;
