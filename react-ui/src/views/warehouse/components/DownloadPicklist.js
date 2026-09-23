import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  CircularProgress,
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
import { getPicklistOrders, downloadPicklistZip } from '../../../services/orderService';

const useStyles = makeStyles((theme) => ({
  head: { fontWeight: 600, whiteSpace: 'nowrap' },
  num: { whiteSpace: 'nowrap' },
  empty: { padding: theme.spacing(4), textAlign: 'center' },
  checkboxCell: { width: 42 }
}));

const dt = (v) => {
  if (!v) return '—';
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
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
 * Every order that's open and ready to pick, one row each — appears here the moment an
 * "Upload Orders" file creates it (see api/modules/fulfillment/order/picklist.py) and
 * drops off once it moves past Picking, so this never grows into a list of orders
 * already picked. Select any number of rows and "Download Picklist" fetches one zip
 * with one PDF per order (bin location, part, HSN, stock on hand, order qty and a Cases
 * figure, laid out for a picker to work off and sign).
 */
const DownloadPicklist = () => {
  const classes = useStyles();
  const { selectedWarehouse, selectedCompany } = useWarehouse();
  const { snackbar, showSnackbar, hideSnackbar } = useSnackbar();

  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState([]); // order_ids
  const [downloading, setDownloading] = useState(false);

  const load = useCallback(async () => {
    if (!selectedCompany) {
      setOrders([]);
      return;
    }
    setLoading(true);
    try {
      const data = await getPicklistOrders(selectedCompany, selectedWarehouse);
      if (data.success) {
        const ids = new Set((data.orders || []).map((o) => o.order_id));
        setOrders(data.orders || []);
        // Drop selections for rows that no longer qualify (e.g. picked since the last load).
        setSelected((sel) => sel.filter((id) => ids.has(id)));
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

  const allSelected = orders.length > 0 && selected.length === orders.length;
  const someSelected = selected.length > 0 && !allSelected;

  const toggleAll = () => setSelected(allSelected ? [] : orders.map((o) => o.order_id));
  const toggleOne = (orderId) =>
    setSelected((sel) => (sel.includes(orderId) ? sel.filter((id) => id !== orderId) : [...sel, orderId]));

  const handleDownload = async () => {
    if (!selected.length) return;
    setDownloading(true);
    try {
      const blob = await downloadPicklistZip(selected, selectedCompany);
      saveBlob(blob, `picklists_${new Date().toISOString().slice(0, 10)}.zip`);
    } catch (e) {
      showSnackbar(e?.response?.data?.msg || 'Could not download these picklists', 'error');
    } finally {
      setDownloading(false);
    }
  };

  const rows = useMemo(() => orders, [orders]);

  return (
    <Card>
      <CardContent>
        <Typography variant="h4" gutterBottom>Download Picklist</Typography>
        <Typography variant="body2" color="textSecondary" gutterBottom>
          Pick lists for orders that are open and ready to pick. Quantities print in stock
          units, with the number of full cases beside them. Select several orders to
          download a zip containing one PDF each.
        </Typography>

        <Box display="flex" alignItems="center" mt={2} mb={1}>
          <Box flexGrow={1} />
          <Button size="small" startIcon={<IconRefresh size={16} />} onClick={load} disabled={loading} style={{ marginRight: 8 }}>
            Refresh
          </Button>
          <Button
            variant="contained"
            color="primary"
            size="small"
            startIcon={downloading ? <CircularProgress size={16} color="inherit" /> : <IconFileDownload size={16} />}
            onClick={handleDownload}
            disabled={!selected.length || downloading}
          >
            {downloading ? 'Preparing…' : 'Download Picklist'}
          </Button>
        </Box>

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
              No orders open and ready to pick right now.
            </Typography>
          </Box>
        ) : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell className={classes.checkboxCell} padding="checkbox">
                    <Checkbox
                      indeterminate={someSelected}
                      checked={allSelected}
                      onChange={toggleAll}
                      size="small"
                    />
                  </TableCell>
                  <TableCell className={classes.head}>Order No</TableCell>
                  <TableCell className={classes.head}>Dealer</TableCell>
                  <TableCell className={classes.head}>City</TableCell>
                  <TableCell className={classes.head}>Order Date</TableCell>
                  <TableCell className={classes.head} align="right">Lines</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((o) => (
                  <TableRow key={o.order_id} hover onClick={() => toggleOne(o.order_id)} style={{ cursor: 'pointer' }}>
                    <TableCell padding="checkbox" onClick={(e) => e.stopPropagation()}>
                      <Checkbox
                        checked={selected.includes(o.order_id)}
                        onChange={() => toggleOne(o.order_id)}
                        size="small"
                      />
                    </TableCell>
                    <TableCell>{o.order_number}</TableCell>
                    <TableCell>{o.dealer_name}</TableCell>
                    <TableCell>{o.dealer_town || '—'}</TableCell>
                    <TableCell>{dt(o.order_date)}</TableCell>
                    <TableCell align="right" className={classes.num}>{o.item_count}</TableCell>
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
