import React, { useState } from 'react';
import {
  Box,
  Button,
  Typography,
  Paper,
  Chip,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconInfoCircle, IconDownload } from '@tabler/icons';

// ---------------------------------------------------------------------------
// Shared "required format + sample template" helper for admin uploads.
// Same shape as the Monthly Data Upload tab: a blurb, a column-spec dialog
// with example rows, and a downloadable CSV template built from `columns`
// and `sample`.
//
//   spec = {
//     id, label, table?, blurb,
//     columns: [{ name, required, note }],
//     sample:  [[...], ...],
//     info?:   node rendered in the dialog's info alert,
//   }
// ---------------------------------------------------------------------------

const csvEscape = (v) => (/[",\n]/.test(v) ? `"${String(v).replace(/"/g, '""')}"` : v);
const toCsv = (spec) =>
  [spec.columns.map((c) => c.name), ...spec.sample]
    .map((r) => r.map(csvEscape).join(','))
    .join('\n');

const useStyles = makeStyles((theme) => ({
  instructions: {
    backgroundColor: theme.palette.grey[50],
    border: `1px solid ${theme.palette.divider}`,
    borderRadius: theme.shape.borderRadius,
    padding: theme.spacing(2),
    marginBottom: theme.spacing(2),
  },
  actions: {
    display: 'flex',
    gap: theme.spacing(1),
    marginTop: theme.spacing(1.5),
    flexWrap: 'wrap',
  },
  codeCell: { fontFamily: 'monospace', fontSize: '0.8rem' },
}));

export const downloadTemplate = (spec) => {
  const blob = new Blob([toCsv(spec)], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${spec.id}_template.csv`;
  a.click();
  URL.revokeObjectURL(url);
};

const UploadFormatHelp = ({ spec }) => {
  const classes = useStyles();
  const [showFormat, setShowFormat] = useState(false);

  return (
    <Box className={classes.instructions}>
      <Typography variant="body2" color="textSecondary">
        {spec.blurb}
      </Typography>

      <Box className={classes.actions}>
        <Button
          size="small"
          variant="outlined"
          startIcon={<IconInfoCircle size={15} />}
          onClick={() => setShowFormat(true)}
          style={{ textTransform: 'none' }}
        >
          Required format
        </Button>
        <Button
          size="small"
          variant="outlined"
          startIcon={<IconDownload size={15} />}
          onClick={() => downloadTemplate(spec)}
          style={{ textTransform: 'none' }}
        >
          Download sample template
        </Button>
      </Box>

      {/* Format dialog */}
      <Dialog open={showFormat} onClose={() => setShowFormat(false)} maxWidth="md" fullWidth>
        <DialogTitle>
          {spec.label} — required file format
          {spec.table && (
            <Typography variant="body2" color="textSecondary">
              Loads into <code>{spec.table}</code>.
            </Typography>
          )}
        </DialogTitle>
        <DialogContent dividers>
          <TableContainer component={Paper} variant="outlined">
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell><strong>Column</strong></TableCell>
                  <TableCell><strong>Required</strong></TableCell>
                  <TableCell><strong>Notes</strong></TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {spec.columns.map((c) => (
                  <TableRow key={c.name}>
                    <TableCell className={classes.codeCell}>{c.name}</TableCell>
                    <TableCell>
                      {c.required
                        ? <Chip size="small" label="required" style={{ backgroundColor: '#ffebee', color: '#c62828' }} />
                        : <Chip size="small" variant="outlined" label="optional" />}
                    </TableCell>
                    <TableCell><Typography variant="body2" color="textSecondary">{c.note}</Typography></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          <Typography variant="subtitle2" style={{ marginTop: 16, marginBottom: 4 }}>Example</Typography>
          <TableContainer component={Paper} variant="outlined" style={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  {spec.columns.map((c) => (
                    <TableCell key={c.name} className={classes.codeCell}><strong>{c.name}</strong></TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {spec.sample.map((row, i) => (
                  <TableRow key={i}>
                    {row.map((v, j) => <TableCell key={j} className={classes.codeCell}>{v}</TableCell>)}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          {spec.info && (
            <Alert severity="info" style={{ marginTop: 16 }}>{spec.info}</Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button startIcon={<IconDownload size={16} />} onClick={() => downloadTemplate(spec)}>
            Download template CSV
          </Button>
          <Button onClick={() => setShowFormat(false)} variant="contained">Close</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default UploadFormatHelp;
