import api from './api';

export const getOrders = (warehouseId, companyId, status = null) => {
  const params = {};
  if (warehouseId) params.warehouse_id = warehouseId;
  if (companyId) params.company_id = companyId;
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
  if (warehouseId) params.warehouse_id = warehouseId;
  if (companyId) params.company_id = companyId;
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

export const getRecentActivity = (warehouseId, companyId, limit = 100) =>
  api
    .get('orders/recent', {
      params: { warehouse_id: warehouseId, company_id: companyId, limit }
    })
    .then((res) => res.data);
