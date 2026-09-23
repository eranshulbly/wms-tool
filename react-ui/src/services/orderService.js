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

// A submitted order's photo, fetched as an authenticated blob (an <img> tag can't
// send the bearer token). Caller creates an object URL from the returned Blob.
export const fetchSubmittedOrderPhoto = (orderId, attachmentId) =>
  api
    .get(`orders/submitted/${orderId}/photo/${attachmentId}`, { responseType: 'blob' })
    .then((res) => res.data);

// A submitted order's line items — product, SKU, quantity and the unit it's actually
// counted in. Used to build the plain product/quantity export on this screen; also what
// SubmittedOrderItems fetches for the detail view.
export const getSubmittedOrderItems = (orderId) =>
  api.get(`orders/submitted/${orderId}/items`).then((res) => res.data);

// Reject a submitted order with a note — sends it back to Submitted Orders as
// 're_submitted' and clears its parts.
export const rejectSubmittedOrder = (orderId, note) =>
  api.post(`orders/submitted/${orderId}/reject`, { note }).then((res) => res.data);

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

// Products for the cart picker on "Add Order", each with the packaging units
// (STRIP/BOX/CASE, whatever it actually has) it can be ordered in. `search` narrows by
// name/SKU as the operator types, so the list stays short on a catalogue of thousands.
export const getOrderProducts = (companyId, search = '') => {
  const params = { company_id: companyId };
  if (search) params.search = search;
  return api.get('orders/products', { params }).then((res) => res.data);
};

// Raise an order by hand with its lines picked from the catalogue — a product, a unit
// and a quantity per line — instead of an uploaded sheet. `items` is
// [{ productId, uom, quantity }]. Otherwise the same order details and the same result
// shape as createManualOrder, since both land in the same Submitted Orders list.
export const createCartOrder = ({ items, dealerId, companyId, warehouseId, notes, expectedDate }) => {
  const body = {
    dealer_id: dealerId,
    company_id: companyId,
    items: items.map((i) => ({ product_id: i.productId, uom: i.uom, quantity: i.quantity }))
  };
  if (warehouseId && warehouseId !== 'all') body.warehouse_id = warehouseId;
  if (notes) body.notes = notes;
  if (expectedDate) body.expected_delivery_date = expectedDate;
  return api.post('orders/submitted/manual-cart', body).then((res) => res.data);
};

export const getRecentActivity = (warehouseId, companyId, limit = 100) => {
  const params = { limit };
  if (warehouseId && warehouseId !== 'all') params.warehouse_id = warehouseId;
  if (companyId && companyId !== 'all') params.company_id = companyId;
  return api.get('orders/recent', { params }).then((res) => res.data);
};
