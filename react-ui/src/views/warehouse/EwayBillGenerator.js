import React, { useState, useEffect, useCallback } from 'react';
import {
  Grid, Typography, Tabs, Tab, Box, Paper, Button, TextField,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  Snackbar, Alert, Dialog, DialogTitle, DialogContent, DialogActions,
  DialogContentText, CircularProgress, MenuItem, Select, InputLabel,
  FormControl, Chip, IconButton, Collapse
} from '@material-ui/core';
import { useSelector } from 'react-redux';
import { gridSpacing } from '../../store/constant';
import config from '../../config';
import axios from 'axios';

// ─── Tab wrapper ────────────────────────────────────────────────────────────
function TabPanel({ children, value, index }) {
  return (
    <div role="tabpanel" hidden={value !== index}>
      {value === index && <Box p={3}>{children}</Box>}
    </div>
  );
}

const ALL_TABS = [
  { label: 'Route Administration',    adminOnly: true,  Component: (props) => <RouteAdmin {...props} /> },
  { label: 'Customer Route Mapping',  adminOnly: true,  Component: (props) => <CustomerRouteMapping {...props} /> },
  { label: 'Company Schema Config',   adminOnly: true,  Component: (props) => <CompanySchemaConfig {...props} /> },
  { label: 'Daily Dispatch Manifest', adminOnly: false, Component: (props) => <DailyManifest {...props} /> },
  { label: 'Generate Bulk JSON',      adminOnly: false, Component: (props) => <GenerateBulkJson {...props} /> },
];

// ─── Root component ──────────────────────────────────────────────────────────
const EwayBillGenerator = () => {
  const [tab, setTab] = useState(0);
  const [snack, setSnack] = useState({ open: false, msg: '', sev: 'info' });
  const user = useSelector((state) => state.account.user);

  const isAdmin = user?.permissions?.eway_bill_admin === true;
  const visibleTabs = ALL_TABS.filter(t => isAdmin || !t.adminOnly);

  const showSnack = useCallback((msg, sev = 'success') => setSnack({ open: true, msg, sev }), []);
  const closeSnack = () => setSnack(s => ({ ...s, open: false }));

  const safeTab = tab < visibleTabs.length ? tab : 0;

  return (
    <Grid container spacing={gridSpacing}>
      <Grid item xs={12}>
        <Typography variant="h3" gutterBottom>E-Way Bill Automation</Typography>
        <Typography variant="subtitle1" color="textSecondary">
          Configure routes, map customers to routes, assign vehicles, and generate bulk JSON for the E-Way portal.
        </Typography>
      </Grid>

      <Grid item xs={12}>
        <Paper>
          <Tabs value={safeTab} onChange={(_, v) => setTab(v)} indicatorColor="primary" textColor="primary" variant="scrollable" scrollButtons="auto">
            {visibleTabs.map((t, i) => <Tab key={i} label={t.label} />)}
          </Tabs>
        </Paper>
      </Grid>

      <Grid item xs={12}>
        <Paper>
          {visibleTabs.map((t, i) => (
            <TabPanel key={i} value={safeTab} index={i}>
              <t.Component showSnack={showSnack} />
            </TabPanel>
          ))}
        </Paper>
      </Grid>

      <Snackbar open={snack.open} autoHideDuration={5000} onClose={closeSnack}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}>
        <Alert onClose={closeSnack} severity={snack.sev}>{snack.msg}</Alert>
      </Snackbar>
    </Grid>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// TAB 1 — Route Administration
// ─────────────────────────────────────────────────────────────────────────────
const RouteAdmin = ({ showSnack }) => {
  const [routes, setRoutes] = useState([]);
  const [form, setForm] = useState({ name: '', description: '' });
  const [expandedRoute, setExpandedRoute] = useState(null);
  const [newCustomer, setNewCustomer] = useState({ customer_code: '', distance: '' });
  const [modal, setModal] = useState({ open: false, routeId: null, routeName: '', customers: [], loading: false });

  const fetchRoutes = useCallback(async () => {
    const res = await axios.get(config.API_SERVER + 'eway/routes');
    if (res.data.success) setRoutes(res.data.routes);
  }, []);

  useEffect(() => { fetchRoutes(); }, [fetchRoutes]);

  const addRoute = async () => {
    if (!form.name) return showSnack('Route name is required', 'warning');
    try {
      const res = await axios.post(config.API_SERVER + 'eway/routes', form);
      if (res.data.success) {
        showSnack(`Route "${form.name}" created`);
        setForm({ name: '', description: '' });
        fetchRoutes();
      } else showSnack(res.data.msg, 'error');
    } catch { showSnack('Failed to create route', 'error'); }
  };

  const addCustomer = async (routeId) => {
    if (!newCustomer.customer_code.trim()) return showSnack('Customer Code is required', 'warning');
    if (!newCustomer.distance) return showSnack('Distance is required', 'warning');
    try {
      const res = await axios.post(config.API_SERVER + 'eway/customer-route-mappings', {
        customer_code: newCustomer.customer_code.trim(),
        customer_name: '',
        route_id: routeId,
        distance: parseInt(newCustomer.distance)
      });
      if (res.data.success) {
        showSnack(`Customer "${newCustomer.customer_code}" added`);
        setNewCustomer({ customer_code: '', distance: '' });
        fetchRoutes();
      } else showSnack(res.data.msg, 'error');
    } catch { showSnack('Failed to add customer', 'error'); }
  };

  const openModal = async (routeId, routeName) => {
    setModal({ open: true, routeId, routeName, customers: [], loading: true });
    try {
      const res = await axios.get(config.API_SERVER + 'eway/route-customers/' + routeId);
      if (res.data.success) {
        setModal(prev => ({ ...prev, customers: res.data.customers, loading: false }));
      } else {
        showSnack(res.data.msg, 'error');
        setModal(prev => ({ ...prev, loading: false }));
      }
    } catch {
      showSnack('Failed to load customers', 'error');
      setModal(prev => ({ ...prev, loading: false }));
    }
  };

  const removeCustomer = async (customerCode) => {
    try {
      const res = await axios.post(config.API_SERVER + 'eway/route-customers/remove', { customer_code: customerCode });
      if (res.data.success) {
        setModal(prev => ({ ...prev, customers: prev.customers.filter(c => c.customer_code !== customerCode) }));
        fetchRoutes();
        showSnack('Customer removed');
      } else showSnack(res.data.msg, 'error');
    } catch { showSnack('Failed to remove customer', 'error'); }
  };

  const closeModal = () => setModal({ open: false, routeId: null, routeName: '', customers: [], loading: false });

  return (
    <Grid container spacing={2}>
      <Grid item xs={12}>
        <Typography variant="h5">Manage Routes</Typography>
        <Typography variant="body2" color="textSecondary" style={{ marginTop: 4 }}>
          Create transport routes. Expand a route to quickly add customers by code and distance.
          Click a customer count to view and remove customers. For full management (name, bulk upload), use the <b>Customer Route Mapping</b> tab.
        </Typography>
      </Grid>

      {/* Add Route Form */}
      <Grid item xs={12}>
        <Paper variant="outlined" style={{ padding: 16 }}>
          <Typography variant="subtitle1" gutterBottom><b>Add New Route</b></Typography>
          <Grid container spacing={2} alignItems="center">
            <Grid item xs={12} sm={3}>
              <TextField fullWidth label="Route Name *" variant="outlined" size="small"
                value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
                placeholder="e.g. UP Route A" />
            </Grid>
            <Grid item xs={12} sm={7}>
              <TextField fullWidth label="Description" variant="outlined" size="small"
                value={form.description} onChange={e => setForm({ ...form, description: e.target.value })}
                placeholder="e.g. Covers Pilibhit, Badaun, Bareilly region" />
            </Grid>
            <Grid item xs={12} sm={2}>
              <Button fullWidth variant="contained" color="primary" onClick={addRoute} style={{ height: 40 }}>
                Add Route
              </Button>
            </Grid>
          </Grid>
        </Paper>
      </Grid>

      {/* Routes Table */}
      <Grid item xs={12}>
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow style={{ backgroundColor: '#f5f5f5' }}>
                <TableCell width={40}></TableCell>
                <TableCell><b>Route Name</b></TableCell>
                <TableCell><b>Description</b></TableCell>
                <TableCell><b>Customers</b></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {routes.map(r => (
                <React.Fragment key={r.route_id}>
                  <TableRow hover>
                    <TableCell>
                      <IconButton size="small" onClick={() => setExpandedRoute(expandedRoute === r.route_id ? null : r.route_id)}>
                        {expandedRoute === r.route_id ? '▲' : '▼'}
                      </IconButton>
                    </TableCell>
                    <TableCell><b>{r.name}</b></TableCell>
                    <TableCell>{r.description || '—'}</TableCell>
                    <TableCell>
                      <Chip
                        label={`${r.customer_count || 0} customers`}
                        size="small"
                        color={r.customer_count > 0 ? 'primary' : 'default'}
                        variant="outlined"
                        onClick={() => openModal(r.route_id, r.name)}
                        style={{ cursor: 'pointer' }}
                      />
                    </TableCell>
                  </TableRow>
                  {/* Expanded customer quick-add row */}
                  <TableRow>
                    <TableCell colSpan={4} style={{ paddingTop: 0, paddingBottom: 0, borderBottom: expandedRoute === r.route_id ? undefined : 'none' }}>
                      <Collapse in={expandedRoute === r.route_id} timeout="auto" unmountOnExit>
                        <Box p={2} bgcolor="#fafafa">
                          <Typography variant="caption" color="textSecondary" style={{ display: 'block', marginBottom: 8 }}>
                            Quick-add a customer to this route. To set customer name or bulk upload, use the <b>Customer Route Mapping</b> tab.
                          </Typography>
                          <Grid container spacing={1} alignItems="center">
                            <Grid item xs={12} sm={4}>
                              <TextField fullWidth size="small" variant="outlined" label="Customer Code *"
                                value={newCustomer.customer_code}
                                onChange={e => setNewCustomer({ ...newCustomer, customer_code: e.target.value })}
                                onKeyPress={e => e.key === 'Enter' && addCustomer(r.route_id)}
                                placeholder="e.g. HMC001" />
                            </Grid>
                            <Grid item xs={12} sm={3}>
                              <TextField fullWidth size="small" variant="outlined" label="Distance (km) *" type="number"
                                value={newCustomer.distance}
                                onChange={e => setNewCustomer({ ...newCustomer, distance: e.target.value })}
                                onKeyPress={e => e.key === 'Enter' && addCustomer(r.route_id)}
                                placeholder="e.g. 120" />
                            </Grid>
                            <Grid item xs="auto">
                              <Button variant="contained" color="primary" size="small" onClick={() => addCustomer(r.route_id)}>
                                Add Customer
                              </Button>
                            </Grid>
                          </Grid>
                        </Box>
                      </Collapse>
                    </TableCell>
                  </TableRow>
                </React.Fragment>
              ))}
              {routes.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} align="center" style={{ color: '#888', padding: 24 }}>
                    No routes yet. Add your first route above.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Grid>

      {/* ── Customers Modal ── */}
      <Dialog open={modal.open} onClose={closeModal} maxWidth="md" fullWidth>
        <DialogTitle style={{ backgroundColor: '#f5f5f5', borderBottom: '1px solid #e0e0e0' }}>
          <Box display="flex" justifyContent="space-between" alignItems="center">
            <Typography variant="h6">Customers on Route: <b>{modal.routeName}</b></Typography>
            <Typography variant="caption" color="textSecondary">
              {modal.customers.length} customer{modal.customers.length !== 1 ? 's' : ''} assigned
            </Typography>
          </Box>
        </DialogTitle>
        <DialogContent style={{ padding: 0 }}>
          {modal.loading ? (
            <Box display="flex" justifyContent="center" alignItems="center" p={5}>
              <CircularProgress />
            </Box>
          ) : (
            <TableContainer>
              <Table>
                <TableHead>
                  <TableRow style={{ backgroundColor: '#fafafa' }}>
                    <TableCell><b>Customer Code</b></TableCell>
                    <TableCell><b>Customer Name</b></TableCell>
                    <TableCell><b>Distance (km)</b></TableCell>
                    <TableCell align="right"><b>Action</b></TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {modal.customers.map((c, i) => (
                    <TableRow key={i} hover>
                      <TableCell>
                        <Chip label={c.customer_code} size="small" color="primary" variant="outlined" />
                      </TableCell>
                      <TableCell>{c.customer_name || <Typography variant="caption" color="textSecondary">—</Typography>}</TableCell>
                      <TableCell>{c.distance} km</TableCell>
                      <TableCell align="right">
                        <Button
                          size="small"
                          variant="outlined"
                          color="secondary"
                          onClick={() => removeCustomer(c.customer_code)}
                        >
                          Remove
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                  {modal.customers.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={4} align="center" style={{ padding: 32, color: '#888' }}>
                        No customers assigned to this route yet. Use the quick-add below or the Customer Route Mapping tab.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </DialogContent>
        <DialogActions style={{ padding: '12px 16px', borderTop: '1px solid #e0e0e0' }}>
          <Button onClick={closeModal} variant="contained" color="primary">Close</Button>
        </DialogActions>
      </Dialog>
    </Grid>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// TAB 2 — Customer Route Mapping
// ─────────────────────────────────────────────────────────────────────────────
const CustomerRouteMapping = ({ showSnack }) => {
  const [routes, setRoutes] = useState([]);
  const [mappings, setMappings] = useState([]);
  const [form, setForm] = useState({ customer_code: '', customer_name: '', route_id: '', distance: '' });
  const [bulkFile, setBulkFile] = useState(null);
  const [bulkLoading, setBulkLoading] = useState(false);

  const fetchAll = useCallback(async () => {
    const [rRes, mRes] = await Promise.all([
      axios.get(config.API_SERVER + 'eway/routes'),
      axios.get(config.API_SERVER + 'eway/customer-route-mappings'),
    ]);
    if (rRes.data.success) setRoutes(rRes.data.routes);
    if (mRes.data.success) setMappings(mRes.data.mappings);
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const addMapping = async () => {
    if (!form.customer_code || !form.route_id || !form.distance)
      return showSnack('Customer Code, Route, and Distance are required', 'warning');
    try {
      const res = await axios.post(config.API_SERVER + 'eway/customer-route-mappings', {
        ...form,
        distance: parseInt(form.distance),
        route_id: parseInt(form.route_id)
      });
      if (res.data.success) {
        showSnack('Mapping saved!');
        setForm({ customer_code: '', customer_name: '', route_id: '', distance: '' });
        fetchAll();
      } else showSnack(res.data.msg, 'error');
    } catch { showSnack('Failed to save mapping', 'error'); }
  };

  const downloadTemplate = () => {
    window.location.href = config.API_SERVER + 'eway/customer-route-mappings/template';
  };

  const handleBulkUpload = async () => {
    if (!bulkFile) return showSnack('Select an Excel file first', 'warning');
    setBulkLoading(true);
    const fd = new FormData();
    fd.append('file', bulkFile);
    try {
      const res = await axios.post(config.API_SERVER + 'eway/customer-route-mappings/bulk', fd, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      if (res.data.success) {
        showSnack(res.data.msg);
        setBulkFile(null);
        fetchAll();
      } else showSnack(res.data.msg, 'error');
    } catch { showSnack('Bulk upload failed', 'error'); }
    finally { setBulkLoading(false); }
  };

  return (
    <Grid container spacing={2}>
      <Grid item xs={12}>
        <Typography variant="h5">Customer Route Mapping</Typography>
        <Typography variant="body2" color="textSecondary" style={{ marginTop: 4 }}>
          Map each Customer Code to a route and distance. If a customer already exists they will be moved to the new route (upsert by customer code).
        </Typography>
      </Grid>

      {/* Manual Add Form */}
      <Grid item xs={12}>
        <Paper variant="outlined" style={{ padding: 16 }}>
          <Typography variant="subtitle1" gutterBottom><b>Add / Update Mapping</b></Typography>
          <Grid container spacing={2} alignItems="flex-start">
            <Grid item xs={12} sm={2}>
              <TextField fullWidth label="Customer Code *" variant="outlined" size="small"
                value={form.customer_code} onChange={e => setForm({ ...form, customer_code: e.target.value })}
                helperText="e.g. HMC001" />
            </Grid>
            <Grid item xs={12} sm={3}>
              <TextField fullWidth label="Customer Name" variant="outlined" size="small"
                value={form.customer_name} onChange={e => setForm({ ...form, customer_name: e.target.value })}
                helperText="For reference only" />
            </Grid>
            <Grid item xs={12} sm={3}>
              <FormControl fullWidth variant="outlined" size="small">
                <InputLabel>Route *</InputLabel>
                <Select label="Route *" value={form.route_id} onChange={e => setForm({ ...form, route_id: e.target.value })}>
                  {routes.map(r => <MenuItem key={r.route_id} value={r.route_id}>{r.name}</MenuItem>)}
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12} sm={2}>
              <TextField fullWidth label="Distance (km) *" variant="outlined" size="small" type="number"
                value={form.distance} onChange={e => setForm({ ...form, distance: e.target.value })}
                helperText="km to hub" />
            </Grid>
            <Grid item xs={12} sm={2}>
              <Button fullWidth variant="contained" color="primary" onClick={addMapping} style={{ height: 40 }}>
                Save Mapping
              </Button>
            </Grid>
          </Grid>
        </Paper>
      </Grid>

      {/* Bulk Upload */}
      <Grid item xs={12}>
        <Paper variant="outlined" style={{ padding: 16 }}>
          <Typography variant="subtitle1" gutterBottom><b>Bulk Upload via Excel</b></Typography>
          <Typography variant="body2" color="textSecondary" gutterBottom>
            Upload an Excel file with columns: <b>Customer Code, Customer Name, Route Name, Distance (km)</b>.
            Route Name is matched case-insensitively. Existing entries will be overwritten (upsert).
          </Typography>
          <Box display="flex" alignItems="center" style={{ gap: 12 }}>
            <Button variant="outlined" size="small" onClick={downloadTemplate}>
              Download Template
            </Button>
            <input type="file" accept=".xlsx,.xls" onChange={e => setBulkFile(e.target.files[0] || null)} />
            <Button variant="contained" color="primary" size="small"
              onClick={handleBulkUpload} disabled={bulkLoading || !bulkFile}>
              {bulkLoading ? <CircularProgress size={20} /> : 'Upload Excel'}
            </Button>
          </Box>
        </Paper>
      </Grid>

      {/* Mappings Table */}
      <Grid item xs={12}>
        <Typography variant="subtitle1" gutterBottom><b>Existing Mappings ({mappings.length})</b></Typography>
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow style={{ backgroundColor: '#f5f5f5' }}>
                <TableCell><b>Customer Code</b></TableCell>
                <TableCell><b>Customer Name</b></TableCell>
                <TableCell><b>Route</b></TableCell>
                <TableCell><b>Distance (km)</b></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {mappings.map((m, i) => (
                <TableRow key={i}>
                  <TableCell><Chip label={m.customer_code} size="small" color="primary" variant="outlined" /></TableCell>
                  <TableCell>{m.customer_name || '—'}</TableCell>
                  <TableCell><Chip label={m.route_name || 'Unmapped'} size="small"
                    color={m.route_name ? 'default' : 'secondary'} /></TableCell>
                  <TableCell>{m.distance} km</TableCell>
                </TableRow>
              ))}
              {mappings.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} align="center" style={{ color: '#888', padding: 24 }}>
                    No mappings yet. Add manually or bulk upload via Excel above.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Grid>
    </Grid>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// TAB 3 — Company Schema Config (unchanged)
// ─────────────────────────────────────────────────────────────────────────────
const CompanySchemaConfig = ({ showSnack }) => {
  const [companies, setCompanies] = useState([]);
  const [selected, setSelected] = useState('');
  const [schema, setSchema] = useState({ invoice_no_col: '', customer_code_col: '', customer_name_col: '', irn_col: '', amount_col: '' });
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    axios.get(config.API_SERVER + 'companies').then(r => { if (r.data.success) setCompanies(r.data.companies); }).catch(() => {});
  }, []);

  const handleCompanyChange = async (id) => {
    setSelected(id); setSaved(false);
    if (!id) return;
    try {
      const r = await axios.get(config.API_SERVER + 'eway/schema-mappings?company_id=' + id);
      if (r.data.success && r.data.schema) {
        setSchema({ invoice_no_col: r.data.schema.invoice_no_col || '', customer_code_col: r.data.schema.customer_code_col || '', customer_name_col: r.data.schema.customer_name_col || '', irn_col: r.data.schema.irn_col || '', amount_col: r.data.schema.amount_col || '' });
      } else {
        setSchema({ invoice_no_col: '', customer_code_col: '', customer_name_col: '', irn_col: '', amount_col: '' });
      }
    } catch { setSchema({ invoice_no_col: '', customer_code_col: '', customer_name_col: '', irn_col: '', amount_col: '' }); }
  };

  const handleSave = async () => {
    if (!selected) return showSnack('Select a company first', 'warning');
    if (!schema.invoice_no_col || !schema.customer_code_col || !schema.customer_name_col || !schema.irn_col)
      return showSnack('Invoice No, Customer Code, Customer Name, and IRN are required', 'warning');
    try {
      const r = await axios.post(config.API_SERVER + 'eway/schema-mappings', { company_id: parseInt(selected), ...schema });
      if (r.data.success) { showSnack('Schema saved!'); setSaved(true); } else showSnack(r.data.msg, 'error');
    } catch { showSnack('Save failed', 'error'); }
  };

  const fields = [
    { key: 'invoice_no_col',    label: 'Invoice # Column *',          hint: 'e.g. Invoice #' },
    { key: 'customer_code_col', label: 'Customer Code Column *',       hint: 'e.g. Code' },
    { key: 'customer_name_col', label: 'Customer Name Column *',       hint: 'e.g. Account Name' },
    { key: 'irn_col',           label: 'IRN Column *',                 hint: 'e.g. IRN#' },
    { key: 'amount_col',        label: 'Amount Column (optional)',      hint: 'e.g. Amount' },
  ];

  return (
    <Grid container spacing={2}>
      <Grid item xs={12}>
        <Typography variant="h5">Company CSV Schema Configuration</Typography>
        <Typography variant="body2" color="textSecondary" style={{ marginTop: 4 }}>
          Each company's CSV may use different column names. Configure them here so the system correctly reads invoices during upload.
        </Typography>
      </Grid>
      <Grid item xs={12} sm={4}>
        <FormControl fullWidth variant="outlined">
          <InputLabel>Select Company</InputLabel>
          <Select label="Select Company" value={selected} onChange={e => handleCompanyChange(e.target.value)}>
            {companies.map(c => <MenuItem key={c.id} value={c.id}>{c.name}</MenuItem>)}
          </Select>
        </FormControl>
      </Grid>
      {selected && (
        <Grid item xs={12}>
          <Paper variant="outlined" style={{ padding: 20 }}>
            <Typography variant="subtitle1" gutterBottom><b>Column Header Mapping</b> — Enter exact header as it appears in the CSV.</Typography>
            <Grid container spacing={2}>
              {fields.map(f => (
                <Grid item xs={12} sm={6} md={4} key={f.key}>
                  <TextField fullWidth label={f.label} variant="outlined" size="small" placeholder={f.hint}
                    value={schema[f.key]} onChange={e => setSchema({ ...schema, [f.key]: e.target.value })} />
                </Grid>
              ))}
            </Grid>
            <Box mt={2} display="flex" alignItems="center" style={{ gap: 12 }}>
              <Button variant="contained" color="primary" onClick={handleSave}>Save Schema</Button>
              {saved && <Typography variant="body2" style={{ color: '#388e3c', fontWeight: 600 }}>✓ Saved</Typography>}
            </Box>
          </Paper>
        </Grid>
      )}
    </Grid>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// TAB 4 — Daily Dispatch Manifest
// ─────────────────────────────────────────────────────────────────────────────
const DailyManifest = ({ showSnack }) => {
  const [routes, setRoutes] = useState([]);
  const [manifests, setManifests] = useState({});
  const [date, setDate] = useState(new Date().toISOString().split('T')[0]);
  const [customerPopup, setCustomerPopup] = useState({ open: false, routeId: null, routeName: '', customers: [] });
  const [popupLoading, setPopupLoading] = useState(false);

  const fetchRoutes = useCallback(async () => {
    const r = await axios.get(config.API_SERVER + 'eway/routes');
    if (r.data.success) setRoutes(r.data.routes);
  }, []);

  const fetchManifests = useCallback(async (d) => {
    const r = await axios.get(config.API_SERVER + 'eway/manifest?date=' + d);
    if (r.data.success) {
      const dict = {};
      r.data.manifests.forEach(m => { dict[m.route_id] = m.vehicle_number; });
      setManifests(dict);
    }
  }, []);

  useEffect(() => { fetchRoutes(); fetchManifests(date); }, [fetchRoutes, fetchManifests, date]);

  const save = async () => {
    const assignments = Object.keys(manifests)
      .map(k => ({ route_id: parseInt(k), vehicle_number: manifests[k] }))
      .filter(x => x.vehicle_number);
    try {
      const r = await axios.post(config.API_SERVER + 'eway/manifest', { date, assignments });
      if (r.data.success) showSnack('Manifest saved!'); else showSnack(r.data.msg, 'error');
    } catch { showSnack('Save failed', 'error'); }
  };

  const openCustomerPopup = async (routeId, routeName) => {
    setCustomerPopup({ open: true, routeId, routeName, customers: [] });
    setPopupLoading(true);
    try {
      const r = await axios.get(config.API_SERVER + 'eway/customer-route-mappings?route_id=' + routeId);
      if (r.data.success) setCustomerPopup(prev => ({ ...prev, customers: r.data.mappings }));
    } catch { showSnack('Failed to load customers', 'error'); }
    finally { setPopupLoading(false); }
  };

  const removeCustomer = async (customerCode) => {
    try {
      await axios.post(config.API_SERVER + 'eway/customer-route-mappings/delete', { customer_code: customerCode });
      setCustomerPopup(prev => ({ ...prev, customers: prev.customers.filter(c => c.customer_code !== customerCode) }));
      showSnack('Customer removed from route');
      fetchRoutes();
    } catch { showSnack('Failed to remove customer', 'error'); }
  };

  return (
    <Grid container spacing={2}>
      <Grid item xs={12} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Typography variant="h5">Daily Dispatch Manifest</Typography>
          <Typography variant="body2" color="textSecondary" style={{ marginTop: 4 }}>
            Assign a vehicle number to each route for the selected date. Click a customer count to view and manage route customers.
          </Typography>
        </div>
        <TextField label="Date" type="date" value={date} onChange={e => setDate(e.target.value)}
          InputLabelProps={{ shrink: true }} variant="outlined" size="small" />
      </Grid>

      <Grid item xs={12}>
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow style={{ backgroundColor: '#f5f5f5' }}>
                <TableCell><b>Route</b></TableCell>
                <TableCell><b>Customers</b></TableCell>
                <TableCell><b>Vehicle Number</b></TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {routes.map(r => (
                <TableRow key={r.route_id}>
                  <TableCell><b>{r.name}</b></TableCell>
                  <TableCell>
                    <Chip
                      label={`${r.customer_count || 0} customers`}
                      size="small"
                      color={r.customer_count > 0 ? 'primary' : 'default'}
                      variant="outlined"
                      onClick={() => openCustomerPopup(r.route_id, r.name)}
                      style={{ cursor: 'pointer' }}
                    />
                  </TableCell>
                  <TableCell>
                    <TextField variant="outlined" size="small" placeholder="e.g. UP 41 AT 1234"
                      value={manifests[r.route_id] || ''}
                      onChange={e => setManifests({ ...manifests, [r.route_id]: e.target.value })}
                      style={{ minWidth: 180 }} />
                  </TableCell>
                </TableRow>
              ))}
              {routes.length === 0 && (
                <TableRow>
                  <TableCell colSpan={3} align="center" style={{ color: '#888', padding: 24 }}>
                    No routes defined. Go to Route Administration to add routes.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Grid>

      <Grid item xs={12}>
        <Button variant="contained" color="primary" onClick={save}>Save Manifest for {date}</Button>
      </Grid>

      {/* Customer Details Popup */}
      <Dialog open={customerPopup.open} onClose={() => setCustomerPopup(p => ({ ...p, open: false }))} maxWidth="sm" fullWidth>
        <DialogTitle>Customers on Route: {customerPopup.routeName}</DialogTitle>
        <DialogContent>
          {popupLoading ? (
            <Box display="flex" justifyContent="center" p={3}><CircularProgress /></Box>
          ) : (
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow style={{ backgroundColor: '#f5f5f5' }}>
                    <TableCell><b>Customer Code</b></TableCell>
                    <TableCell><b>Customer Name</b></TableCell>
                    <TableCell><b>Distance (km)</b></TableCell>
                    <TableCell></TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {customerPopup.customers.map((c, i) => (
                    <TableRow key={i}>
                      <TableCell><Chip label={c.customer_code} size="small" color="primary" variant="outlined" /></TableCell>
                      <TableCell>{c.customer_name || '—'}</TableCell>
                      <TableCell>{c.distance} km</TableCell>
                      <TableCell>
                        <Button size="small" color="secondary" variant="outlined"
                          onClick={() => removeCustomer(c.customer_code)}>
                          Remove
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                  {customerPopup.customers.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={4} align="center" style={{ color: '#888', padding: 16 }}>
                        No customers assigned to this route. Use the Customer Route Mapping tab to add customers.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCustomerPopup(p => ({ ...p, open: false }))} color="primary" variant="contained">
            Close
          </Button>
        </DialogActions>
      </Dialog>
    </Grid>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// TAB 5 — Generate Bulk JSON
// ─────────────────────────────────────────────────────────────────────────────
const GenerateBulkJson = ({ showSnack }) => {
  const [companies, setCompanies] = useState([]);
  const [company, setCompany] = useState('');
  const [file, setFile] = useState(null);
  const [rows, setRows] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(false);
  const [instructionsOpen, setInstructionsOpen] = useState(false);

  // ── Layer 1: preview/confirm modal ──────────────────────────────────────
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewInfo, setPreviewInfo] = useState({ name: '', estimatedRows: 0 });

  useEffect(() => {
    axios.get(config.API_SERVER + 'companies').then(r => { if (r.data.success) setCompanies(r.data.companies); }).catch(() => {});
  }, []);

  // ── Count CSV rows client-side ───────────────────────────────────────────
  const countCsvRows = (f) => new Promise(resolve => {
    const reader = new FileReader();
    reader.onload = e => {
      const text = e.target.result || '';
      const lines = text.split('\n').filter(l => l.trim()).length;
      resolve(Math.max(0, lines - 1));
    };
    reader.readAsText(f.slice(0, 102400));
  });

  const handleProcessClick = async () => {
    if (!company) return showSnack('Select a company first', 'warning');
    if (!file)    return showSnack('Select a CSV file first', 'warning');
    const estimated = await countCsvRows(file);
    setPreviewInfo({ name: file.name, estimatedRows: estimated });
    setPreviewOpen(true);
  };

  const upload = async () => {
    setPreviewOpen(false);
    setLoading(true);
    const fd = new FormData();
    fd.append('file', file);
    fd.append('company_id', company);
    try {
      const r = await axios.post(config.API_SERVER + 'eway/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
      if (r.data.success) {
        setRows(r.data.data);
        setMeta(r.data.meta || null);
        showSnack(`Loaded ${r.data.data.length} e-invoice rows`);
      } else showSnack(r.data.msg, 'error');
    } catch (e) { showSnack(e.response?.data?.msg || 'Upload failed', 'error'); }
    finally { setLoading(false); }
  };

  const clearAndRetry = () => {
    setRows([]);
    setMeta(null);
    setFile(null);
    const inp = document.getElementById('eway-csv-input');
    if (inp) inp.value = '';
  };

  const updateRow = (i, field, val) => {
    const next = [...rows];
    next[i] = { ...next[i], [field]: val };
    setRows(next);
  };

  const exportJson = async () => {
    try {
      const r = await axios.post(config.API_SERVER + 'eway/generate-json', rows);
      if (r.data.success) {
        const blob = new Blob([JSON.stringify(r.data.json_payload, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `EWay_Bulk_${Date.now()}.json`;
        document.body.appendChild(a); a.click();
        document.body.removeChild(a); URL.revokeObjectURL(url);
        setInstructionsOpen(true);
      } else showSnack(r.data.msg, 'error');
    } catch (e) { showSnack(e.response?.data?.msg || 'Export failed', 'error'); }
  };

  // ── Layer 4: date warning ────────────────────────────────────────────────
  const fileDate = meta?.file_date;
  const today    = meta?.today;
  const dateWarn = fileDate && today && fileDate !== today;

  const fmtDate = (d) => {
    if (!d) return d;
    try {
      const [y, m, day] = d.split('-');
      const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      return `${day} ${months[parseInt(m,10)-1]} ${y}`;
    } catch { return d; }
  };

  const incomplete = rows.filter(r => r.status === 'Incomplete').length;

  return (
    <Grid container spacing={2}>
      <Grid item xs={12}>
        <Typography variant="h5">Generate Bulk E-Way JSON</Typography>
        <Typography variant="body2" color="textSecondary" style={{ marginTop: 4 }}>
          Select the source company and upload their invoice CSV. The system auto-fills route, vehicle, and distance from configured mappings.
        </Typography>
      </Grid>

      {/* ── Controls (hidden once rows are loaded) ── */}
      {rows.length === 0 && (
        <>
          <Grid item xs={12} sm={4}>
            <FormControl fullWidth variant="outlined">
              <InputLabel>Company *</InputLabel>
              <Select label="Company *" value={company} onChange={e => setCompany(e.target.value)}>
                {companies.map(c => <MenuItem key={c.id} value={c.id}>{c.name}</MenuItem>)}
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={12} sm={8} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <input id="eway-csv-input" type="file" accept=".csv"
              onChange={e => setFile(e.target.files[0] || null)} />
            <Button variant="contained" color="primary"
              onClick={handleProcessClick} disabled={loading || !file || !company}>
              {loading ? <CircularProgress size={24} /> : 'Process CSV'}
            </Button>
          </Grid>
        </>
      )}

      {/* ── Post-upload header ── */}
      {rows.length > 0 && (
        <Grid item xs={12}>
          <Paper variant="outlined" style={{ padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: '#f9f9f9' }}>
            <Box>
              <Typography variant="subtitle2" style={{ fontWeight: 600 }}>
                📄 {meta?.filename || 'Uploaded file'}
              </Typography>
              <Typography variant="caption" color="textSecondary">
                {rows.length} e-invoice rows loaded
                {meta?.file_date ? ` · File date: ${fmtDate(meta.file_date)}` : ''}
                {meta?.today     ? ` · Today: ${fmtDate(meta.today)}`         : ''}
              </Typography>
            </Box>
            <Button variant="outlined" color="secondary" size="small" onClick={clearAndRetry}
              style={{ whiteSpace: 'nowrap', marginLeft: 16 }}>
              ✕ Upload Different File
            </Button>
          </Paper>
        </Grid>
      )}

      {/* ── Layer 4: Date warning banner ── */}
      {dateWarn && (
        <Grid item xs={12}>
          <Alert severity="warning">
            <b>⚠ Possible wrong file!</b> — The filename suggests this invoice is from{' '}
            <b>{fmtDate(fileDate)}</b>, but today is <b>{fmtDate(today)}</b>.
            If you intended to upload today's invoice, click <b>"✕ Upload Different File"</b> above.
          </Alert>
        </Grid>
      )}

      {/* ── Incomplete rows warning ── */}
      {rows.length > 0 && incomplete > 0 && (
        <Grid item xs={12}>
          <Alert severity="info">
            <b>{incomplete} rows</b> are missing route/vehicle mapping and highlighted below. You can fill them in manually before exporting.
          </Alert>
        </Grid>
      )}

      {/* ── Review Data Grid ── */}
      {rows.length > 0 && (
        <>
          <Grid item xs={12}>
            <TableContainer component={Paper} variant="outlined" style={{ maxHeight: 420 }}>
              <Table stickyHeader size="small">
                <TableHead>
                  <TableRow>
                    <TableCell><b>Status</b></TableCell>
                    <TableCell><b>Invoice #</b></TableCell>
                    <TableCell><b>Customer Code</b></TableCell>
                    <TableCell><b>Customer Name</b></TableCell>
                    <TableCell><b>Distance (km)</b></TableCell>
                    <TableCell><b>Vehicle No</b></TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {rows.map((row, i) => (
                    <TableRow key={i} style={{ backgroundColor: row.status === 'Incomplete' ? '#fff8e1' : undefined }}>
                      <TableCell>
                        <Chip label={row.status} size="small"
                          style={{
                            backgroundColor: row.status === 'Complete' ? '#e8f5e9' : '#fff3e0',
                            color:           row.status === 'Complete' ? '#2e7d32' : '#e65100'
                          }} />
                      </TableCell>
                      <TableCell>{row.invoice_no}</TableCell>
                      <TableCell>{row.customer_code}</TableCell>
                      <TableCell>{row.customer_name}</TableCell>
                      <TableCell>
                        <TextField size="small" type="number" variant="outlined"
                          value={row.distance || ''} error={!row.distance}
                          onChange={e => updateRow(i, 'distance', e.target.value)}
                          style={{ width: 80 }} />
                      </TableCell>
                      <TableCell>
                        <TextField size="small" variant="outlined"
                          value={row.vehicle_no || ''} error={!row.vehicle_no}
                          onChange={e => updateRow(i, 'vehicle_no', e.target.value)}
                          style={{ width: 150 }} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Grid>

          <Grid item xs={12} style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button variant="contained" style={{ backgroundColor: '#2e7d32', color: '#fff' }} onClick={exportJson}>
              Export Bulk JSON ({rows.length} records)
            </Button>
          </Grid>
        </>
      )}

      {/* ── Layer 1: File Preview / Confirm Dialog ── */}
      <Dialog open={previewOpen} onClose={() => setPreviewOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle style={{ backgroundColor: '#e3f2fd', color: '#1565c0' }}>
          📋 Confirm File Upload
        </DialogTitle>
        <DialogContent style={{ marginTop: 16 }}>
          <DialogContentText component="div">
            <Box mb={1}>
              <Typography variant="body2" color="textSecondary">File name</Typography>
              <Typography variant="body1" style={{ fontWeight: 600, wordBreak: 'break-all' }}>
                {previewInfo.name}
              </Typography>
            </Box>
            <Box mb={2}>
              <Typography variant="body2" color="textSecondary">Estimated rows (approx.)</Typography>
              <Typography variant="body1" style={{ fontWeight: 600 }}>
                ~{previewInfo.estimatedRows} invoice rows
              </Typography>
            </Box>
            <Typography variant="body2" style={{ color: '#555' }}>
              Please verify this is <b>today's invoice file</b> before proceeding. Wrong files can generate incorrect E-Way bills.
            </Typography>
          </DialogContentText>
        </DialogContent>
        <DialogActions style={{ padding: '12px 16px' }}>
          <Button onClick={() => setPreviewOpen(false)} variant="outlined">
            Cancel — Wrong File
          </Button>
          <Button onClick={upload} color="primary" variant="contained">
            ✓ Looks Correct — Process
          </Button>
        </DialogActions>
      </Dialog>

      {/* ── Filing Instructions Dialog ── */}
      <Dialog open={instructionsOpen} onClose={() => setInstructionsOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle style={{ backgroundColor: '#e8f5e9', color: '#2e7d32' }}>✅ JSON Generated Successfully!</DialogTitle>
        <DialogContent style={{ marginTop: 12 }}>
          <DialogContentText component="div">
            <b style={{ fontSize: '1.05em' }}>Next Steps — File on the E-Way Bill Portal:</b>
            <ol style={{ lineHeight: 2 }}>
              <li>Open <a href="https://ewaybillgst.gov.in" target="_blank" rel="noreferrer">https://ewaybillgst.gov.in</a> and log in.</li>
              <li>Navigate to <b>E-Waybill → Bulk Generation</b>.</li>
              <li>Click <b>Choose File</b> and select the JSON file you just downloaded.</li>
              <li>Click <b>Upload &amp; Generate</b>.</li>
              <li>Review the generated E-Way bills and download the acknowledgement.</li>
            </ol>
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setInstructionsOpen(false)} color="primary" variant="contained">Got it!</Button>
        </DialogActions>
      </Dialog>
    </Grid>
  );
};

export default EwayBillGenerator;
