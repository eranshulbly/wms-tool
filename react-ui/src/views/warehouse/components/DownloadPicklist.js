import React, { useCallback, useEffect, useState } from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  CircularProgress,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
  Snackbar,
  Alert
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconRefresh, IconFileDownload } from '@tabler/icons';
import { useWarehouse } from '../../../context/WarehouseContext';
import { useSnackbar } from '../../../hooks/useSnackbar';
import { getPicklistOrders, downloadPicklist } from '../../../services/orderService';
import { dealerLabel } from '../../../utils/dealerLabel';

const useStyles = makeStyles((theme) => ({
  head: { fontWeight: 600, whiteSpace: 'nowrap' },
  num: { whiteSpace: 'nowrap' },
  empty: { padding: theme.spacing(4), textAlign: 'center' }
}));

const dt = (v) => {
  if (!v) return '—';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
};

const dtTime = (v) => {
  if (!v) return '—';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
};

const saveBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
};

/**
 * Every order an "Upload Orders" file created, one row each — appears here the moment
 * that upload finishes (see api/modules/fulfillment/order/picklist.py: eligibility is
 * just "has an upload_batch_id"). Each row downloads its own picklist PDF: bin
 * location, part, HSN, stock on hand, order qty and a Cases figure, laid out for a
 * picker to work off and sign.
 */
const DownloadPicklist = () => {
  const classes = useStyles();
  const { selectedWarehouse, selectedCompany } = useWarehouse();
  const { snackbar, showSnackbar, hideSnackbar } = useSnackbar();

  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [downloadingId, setDownloadingId] = useState(null);

  const load = useCallback(async () => {
    if (!selectedCompany) {
      setOrders([]);
      return;
    }
    setLoading(true);
    try {
      const data = await getPicklistOrders(selectedCompany, selectedWarehouse);
      if (data.success) {
        setOrders(data.orders || []);
      } else {
        showSnackbar(data.msg || 'Could not load picklist orders', 'error');
        setOrders([]);
      }
    } catch (e) {
      showSnackbar(e?.response?.data?.msg || 'Could not load picklist orders', 'error');
      setOrders([]);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCompany, selectedWarehouse]);

  useEffect(() => {
    load();
  }, [load]);

  const handleDownload = async (order) => {
    setDownloadingId(order.order_id);
    try {
      const blob = await downloadPicklist(order.order_id, order.company_id);
      saveBlob(blob, `picklist_${order.order_number}.pdf`);
    } catch (e) {
      showSnackbar(e?.response?.data?.msg || 'Could not download this picklist', 'error');
    } finally {
      setDownloadingId(null);
    }
  };

  return (
    <Card>
      <CardContent>
        <Box display="flex" alignItems="center" mb={2}>
          <Typography variant="h4">Download Picklist</Typography>
          <Box flexGrow={1} />
          <Button size="small" startIcon={<IconRefresh size={16} />} onClick={load} disabled={loading}>
            Refresh
          </Button>
        </Box>
        <Typography variant="body2" color="textSecondary" gutterBottom>
          Every order the file you upload creates shows up here — download its picklist to hand to a picker.
        </Typography>

        {!selectedCompany ? (
          <Box className={classes.empty}>
            <Typography variant="body2" color="textSecondary">Select a company to see its orders.</Typography>
          </Box>
        ) : loading && !orders.length ? (
          <Box display="flex" justifyContent="center" p={4}>
            <CircularProgress />
          </Box>
        ) : !orders.length ? (
          <Box className={classes.empty}>
            <Typography variant="body2" color="textSecondary">
              No orders yet — they appear here as soon as an order file is uploaded.
            </Typography>
          </Box>
        ) : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell className={classes.head}>Order No</TableCell>
                  <TableCell className={classes.head}>Dealer</TableCell>
                  <TableCell className={classes.head}>Order Date</TableCell>
                  <TableCell className={classes.head} align="right">Items</TableCell>
                  <TableCell className={classes.head}>Status</TableCell>
                  <TableCell className={classes.head}>Uploaded</TableCell>
                  <TableCell className={classes.head} align="center">Download</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {orders.map((o) => (
                  <TableRow key={o.order_id} hover>
                    <TableCell>{o.order_number}</TableCell>
                    <TableCell>{dealerLabel(o.dealer_name, o.dealer_town)}</TableCell>
                    <TableCell>{dt(o.order_date)}</TableCell>
                    <TableCell align="right" className={classes.num}>{o.item_count}</TableCell>
                    <TableCell>{o.status}</TableCell>
                    <TableCell>
                      <Typography variant="body2">{dtTime(o.uploaded_at)}</Typography>
                      {o.upload_filename && (
                        <Typography variant="caption" color="textSecondary">{o.upload_filename}</Typography>
                      )}
                    </TableCell>
                    <TableCell align="center">
                      <IconButton
                        size="small"
                        onClick={() => handleDownload(o)}
                        disabled={downloadingId === o.order_id}
                      >
                        {downloadingId === o.order_id ? <CircularProgress size={18} /> : <IconFileDownload size={18} />}
                      </IconButton>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </CardContent>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={hideSnackbar}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert onClose={hideSnackbar} severity={snackbar.severity}>{snackbar.message}</Alert>
      </Snackbar>
    </Card>
  );
};

export default DownloadPicklist;
