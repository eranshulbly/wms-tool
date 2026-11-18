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
// downloaded). warehouseId / companyId are optional filters. state: 'pending' (default:
// not yet accepted) | 'accepted' | 'all'.
export const getSubmittedOrders = (warehouseId = null, companyId = null, stage = 'submitted', state = 'pending') => {
  const params = { stage, state };
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

// Hard-delete a submitted order — it and its products/attachments/history are gone,
// not just hidden. Safe unconditionally: submitted_orders is its own store (nothing
// elsewhere references the row — see SubmittedOrderDelete's own docstring), and nothing
// here ever takes live stock before its own invoice closes an order separately.
export const deleteSubmittedOrder = (orderId) =>
  api.delete(`orders/submitted/${orderId}`).then((res) => res.data);

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

// Products for the cart picker on "Add Order", each with the packaging units
// (STRIP/BOX/CASE, whatever it actually has) it can be ordered in. `search` narrows by
// name/SKU as the operator types, so the list stays short on a catalogue of thousands.
export const getOrderProducts = (companyId, search = '') => {
  const params = { company_id: companyId };
  if (search) params.search = search;
  return api.get('orders/products', { params }).then((res) => res.data);
};

// Raise an order by hand with its lines picked from the catalogue — a product, a unit
// and a quantity per line. `items` is [{ productId, uom, quantity }].
//
// dealerId (an existing dealer) and newDealerName (a dealer not in the picker yet) are
// mutually exclusive. newDealerName never creates a dealer record — the backend keeps
// it as pending_dealer_name/pending_dealer_town on the order itself; only a later
// order/invoice upload that names this exact dealer ever creates a real one.
export const createCartOrder = ({
  items, dealerId, newDealerName, newDealerTown, companyId, warehouseId, notes, expectedDate
}) => {
  const body = {
    company_id: companyId,
    items: items.map((i) => ({ product_id: i.productId, uom: i.uom, quantity: i.quantity }))
  };
  if (dealerId) {
    body.dealer_id = dealerId;
  } else if (newDealerName) {
    body.new_dealer_name = newDealerName;
    if (newDealerTown) body.new_dealer_town = newDealerTown;
  }
  if (warehouseId && warehouseId !== 'all') body.warehouse_id = warehouseId;
  if (notes) body.notes = notes;
  if (expectedDate) body.expected_delivery_date = expectedDate;
  return api.post('orders/submitted/manual-cart', body).then((res) => res.data);
};

// Orders eligible for a picklist download — every order an "Upload Orders" file
// created (Download Picklist tab). warehouseId is optional; companyId is required by
// the backend's company-scoping (resolve_company_scope resolves it from the user's own
// access when omitted, so it's fine to leave out too).
export const getPicklistOrders = (companyId, warehouseId = null) => {
  const params = {};
  if (companyId && companyId !== 'all') params.company_id = companyId;
  if (warehouseId && warehouseId !== 'all') params.warehouse_id = warehouseId;
  return api.get('orders/picklist', { params }).then((res) => res.data);
};

// One or more orders' picklists, bundled as a zip (one PDF per order) — fetched as an
// authenticated blob (a plain <a href> can't send the bearer token), then handed to the
// browser as a download. orderIds is an array; the backend skips any that no longer
// qualify (e.g. picked since the list was last loaded) rather than failing the batch.
export const downloadPicklistZip = (orderIds, companyId) => {
  const params = { order_ids: orderIds.join(',') };
  if (companyId && companyId !== 'all') params.company_id = companyId;
  return api.get('orders/picklist/zip', { params, responseType: 'blob' }).then((res) => res.data);
};

export const getRecentActivity = (warehouseId, companyId, limit = 100) => {
  const params = { limit };
  if (warehouseId && warehouseId !== 'all') params.warehouse_id = warehouseId;
  if (companyId && companyId !== 'all') params.company_id = companyId;
  return api.get('orders/recent', { params }).then((res) => res.data);
};

// ── App orders on Submitted Orders: Accept and Edit ─────────────────────────
// Close an app order: it leaves the pending list and the app can no longer change it.
export const acceptSubmittedOrder = (orderId) =>
  api.post(`orders/submitted/${orderId}/accept`).then((res) => res.data);

// An order's lines, as the expandable row shows them.
export const getSubmittedOrderLines = (orderId) =>
  api.get(`orders/submitted/${orderId}/items`).then((res) => res.data);

// Exactly these products, with their unit ladders (to load an order's lines into the cart).
export const getOrderProductsByIds = (companyId, ids) =>
  api.get('orders/products', { params: { company_id: companyId, ids: ids.join(',') } }).then((res) => res.data);

// Replace an app order's lines. `items` is [{ productId, uom, quantity }], as Add Order sends.
export const updateSubmittedOrderItems = (orderId, items) =>
  api
    .put(`orders/submitted/${orderId}/items`, {
      items: items.map((i) => ({ product_id: i.productId, uom: i.uom, quantity: i.quantity }))
    })
    .then((res) => res.data);
