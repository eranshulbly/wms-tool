import api from './api';

export const getOrders = (warehouseId, companyId, status = null) => {
  const params = {};
  // 'all' (or empty) => omit the filter so the backend aggregates across everything.
  if (warehouseId && warehouseId !== 'all') params.warehouse_id = warehouseId;
  if (companyId && companyId !== 'all') params.company_id = companyId;
  if (status && status !== 'all') params.status = status;

  return api.get('orders', { params }).then((res) => {
    const data = res.data;
    if (data.success && data.orders) {
      data.orders = data.orders.map((order) => ({
        ...order,
        current_state_time: order.current_state_time || order.updated_at || new Date().toISOString()
      }));
    }
    return data;
  });
};

export const getOrderStatusCounts = (warehouseId, companyId) => {
  const params = {};
  if (warehouseId && warehouseId !== 'all') params.warehouse_id = warehouseId;
  if (companyId && companyId !== 'all') params.company_id = companyId;
  return api.get('orders/status', { params }).then((res) => res.data);
};

export const getOrderDetails = (orderId) =>
  api.get(`orders/${orderId}/details`).then((res) => {
    const data = res.data;
    if (data.success && data.order) {
      data.order = {
        ...data.order,
        current_state_time: data.order.current_state_time || data.order.updated_at || new Date().toISOString()
      };
    }
    return data;
  });

export const updateOrderStatus = (orderId, newStatus, additionalData = null) => {
  const body = { new_status: newStatus };
  if (additionalData) Object.assign(body, additionalData);
  return api.post(`orders/${orderId}/status`, body).then((res) => res.data);
};

export const completeDispatch = (orderId) =>
  api.post(`orders/${orderId}/complete-dispatch`).then((res) => res.data);

export const bulkStatusUpdate = (file, targetStatus, warehouseId, companyId) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('target_status', targetStatus);
  formData.append('warehouse_id', warehouseId);
  formData.append('company_id', companyId);
  return api
    .post('orders/bulk-status-update', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    .then((res) => res.data);
};

// App-submitted orders (from the submitted_orders store, separate from potential_order).
// stage: 'submitted' (awaiting part-convertor upload) | 'download' (ready / already
// downloaded). warehouseId / companyId are optional filters.
export const getSubmittedOrders = (warehouseId = null, companyId = null, stage = 'submitted') => {
  const params = { stage };
  if (warehouseId && warehouseId !== 'all') params.warehouse_id = warehouseId;
  if (companyId && companyId !== 'all') params.company_id = companyId;
  return api.get('orders/submitted', { params }).then((res) => res.data);
};

// Reject a DMS-input order (from the Download DMS tab) with a note — sends it back to
// Submitted Orders as 're_submitted' and clears its parts.
export const rejectSubmittedOrder = (orderId, note) =>
  api.post(`orders/submitted/${orderId}/reject`, { note }).then((res) => res.data);

// A submitted order's photo, fetched as an authenticated blob (an <img> tag can't
// send the bearer token). Caller creates an object URL from the returned Blob.
export const fetchSubmittedOrderPhoto = (orderId, attachmentId) =>
  api
    .get(`orders/submitted/${orderId}/photo/${attachmentId}`, { responseType: 'blob' })
    .then((res) => res.data);

// Upload the part-convertor sheet for a photo order — the system turns it into the
// order's line items so a DMS file can then be generated.
export const uploadPartConvertor = (orderId, file) => {
  const formData = new FormData();
  formData.append('file', file);
  return api
    .post(`orders/submitted/${orderId}/part-convertor`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    .then((res) => res.data);
};

// Download the company's DMS file for a submitted order. Returned as a blob so the
// browser saves it; a 409 (no parts yet) surfaces as a rejected promise whose blob
// body we read for the message.
export const downloadDmsFile = (orderId) =>
  api.get(`orders/submitted/${orderId}/dms-file`, { responseType: 'blob' }).then((res) => {
    const disposition = res.headers['content-disposition'] || '';
    const match = /filename[^;=\n]*=(?:"?)([^";\n]*)/.exec(disposition);
    const filename = match ? match[1].trim() : `DMS_${orderId}.csv`;
    // A file trimmed to available stock is indistinguishable from a complete one, so the
    // server reports what it cut in headers (the body is the CSV itself).
    return {
      blob: res.data,
      filename,
      shortfallCount: parseInt(res.headers['x-dms-shortfall-count'] || '0', 10),
      shortfallSummary: res.headers['x-dms-shortfall-summary'] || ''
    };
  });

// Stock on hand for the DMS step. The freshness summary drives the banner; a DMS download
// is refused when the last upload is older than the server's window.
export const getDmsInventory = () => api.get('orders/inventory').then((res) => res.data);

// Apply a stock sheet (PART# | QTY). A full snapshot: parts the sheet omits are set to 0.
export const uploadDmsInventory = (file) => {
  const formData = new FormData();
  formData.append('file', file);
  return api
    .post('orders/inventory', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
    .then((res) => res.data);
};

// Active dealers for the manual-order picker. Narrowed by company, because an order's
// dealer has to belong to the company it is raised against.
export const getOrderDealers = (companyId) => {
  const params = {};
  if (companyId && companyId !== 'all') params.company_id = companyId;
  return api.get('orders/dealers', { params }).then((res) => res.data);
};

// Raise an order by hand with its parts taken from an uploaded sheet — for parts that
// arrived outside the app (phone/WhatsApp). The result is an ordinary submitted order
// that appears in this list like any other, so its DMS file is then downloaded through
// the normal per-order route.
export const createManualOrder = ({ file, dealerId, companyId, warehouseId, notes, expectedDate }) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('dealer_id', dealerId);
  formData.append('company_id', companyId);
  if (warehouseId && warehouseId !== 'all') formData.append('warehouse_id', warehouseId);
  if (notes) formData.append('notes', notes);
  if (expectedDate) formData.append('expected_delivery_date', expectedDate);
  return api
    .post('orders/submitted/manual', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    .then((res) => res.data);
};

// Best-effort extraction of a JSON error message from an axios error whose response
// body is a Blob (because we requested responseType: 'blob').
export const readBlobError = async (error) => {
  const data = error?.response?.data;
  if (data instanceof Blob) {
    try {
      return JSON.parse(await data.text())?.msg || null;
    } catch (e) {
      return null;
    }
  }
  return data?.msg || null;
};

export const getRecentActivity = (warehouseId, companyId, limit = 100) => {
  const params = { limit };
  if (warehouseId && warehouseId !== 'all') params.warehouse_id = warehouseId;
  if (companyId && companyId !== 'all') params.company_id = companyId;
  return api.get('orders/recent', { params }).then((res) => res.data);
};
