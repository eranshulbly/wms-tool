// Order Management Service - Cleaned version with unused functions removed
import axios from 'axios';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:5000';

// Bug 27 fix: attach auth token to every request from this service
const axiosWithAuth = axios.create();
axiosWithAuth.interceptors.request.use((config) => {
  const token = localStorage.getItem('wms_token');
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/**
 * API service for order management operations
 */
class OrderManagementService {

  /**
   * Get all warehouses
   * @returns {Promise<Object>} API response with warehouses
   */
  async getWarehouses() {
    try {
      const response = await axiosWithAuth.get(`${API_BASE_URL}/api/warehouses`);
      return response.data;
    } catch (error) {
      console.error('Error fetching warehouses:', error);
      return { success: false, msg: error.message };
    }
  }

  /**
   * Get all companies
   * @returns {Promise<Object>} API response with companies
   */
  async getCompanies() {
    try {
      const response = await axiosWithAuth.get(`${API_BASE_URL}/api/companies`);
      return response.data;
    } catch (error) {
      console.error('Error fetching companies:', error);
      return { success: false, msg: error.message };
    }
  }

  /**
   * Get orders with optional filtering
   * @param {number} warehouseId - Warehouse ID
   * @param {number} companyId - Company ID
   * @param {string} status - Order status filter (optional)
   * @returns {Promise<Object>} API response with orders
   */
  async getOrders(warehouseId, companyId, status = null, page = 1, limit = 100) {
    try {
      const params = { page, limit };
      if (warehouseId) params.warehouse_id = warehouseId;
      if (companyId) params.company_id = companyId;
      if (status && status !== 'all') params.status = status;

      const response = await axiosWithAuth.get(`${API_BASE_URL}/api/orders`, { params });
      const data = response.data;

      if (data.success && data.orders) {
        data.orders = data.orders.map(order => ({
          ...order,
          current_state_time: order.current_state_time || order.updated_at || new Date().toISOString()
        }));
      }

      return data;
    } catch (error) {
      console.error('Error fetching orders:', error);
      return { success: false, msg: error.message };
    }
  }

  /**
   * Get order details with products by ID
   * @param {string} orderId - Order ID (e.g., "PO123")
   * @returns {Promise<Object>} API response with detailed order information
   */
  async getOrderDetailsWithProducts(orderId) {
    try {
      const response = await axiosWithAuth.get(`${API_BASE_URL}/api/orders/${orderId}/details`);
      const data = response.data;

      if (data.success && data.order) {
        data.order = {
          ...data.order,
          current_state_time: data.order.current_state_time || data.order.updated_at || new Date().toISOString()
        };
      }

      return data;
    } catch (error) {
      console.error('Error fetching order details:', error);
      return { success: false, msg: error.message };
    }
  }

  /**
   * Update order status (Open→Picking, Picking→Packed, Dispatch Ready→Completed)
   * @param {string} orderId - Order ID (e.g., "PO123")
   * @param {string} newStatus - New status
   * @param {Object} additionalData - For 'packed': { number_of_boxes }
   * @returns {Promise<Object>} API response
   */
  async updateOrderStatus(orderId, newStatus, additionalData = null) {
    try {
      const requestBody = { new_status: newStatus };
      if (additionalData) Object.assign(requestBody, additionalData);

      const response = await axiosWithAuth.post(`${API_BASE_URL}/api/orders/${orderId}/status`, requestBody);
      return response.data;
    } catch (error) {
      console.error('Error updating order status:', error);
      return { success: false, msg: error.message };
    }
  }

  /**
   * Bulk status update from an Excel file.
   * Excel must have 'Order ID' column; 'Number of Boxes' required when targetStatus='packed'.
   * @param {File} file
   * @param {string} targetStatus - e.g. 'picking', 'packed', 'completed'
   * @param {number} warehouseId
   * @param {number} companyId
   * @returns {Promise<Object>} { success, processed_count, error_count, error_report? }
   */
  async bulkStatusUpdate(file, targetStatus, warehouseId, companyId) {
    // Bug 34 fix: wrap in try/catch like all other service methods
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('target_status', targetStatus);
      formData.append('warehouse_id', warehouseId);
      formData.append('company_id', companyId);

      const response = await axiosWithAuth.post(`${API_BASE_URL}/api/orders/bulk-status-update`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      return response.data;
    } catch (error) {
      console.error('Error bulk updating order statuses:', error);
      return { success: false, msg: error.response?.data?.msg || error.message };
    }
  }

  /**
   * Complete order dispatch
   * @param {string} orderId - Order ID
   * @returns {Promise<Object>} API response
   */
  async completeDispatch(orderId) {
    try {
      const response = await axiosWithAuth.post(`${API_BASE_URL}/api/orders/${orderId}/complete-dispatch`);
      return response.data;
    } catch (error) {
      console.error('Error completing dispatch:', error);
      return { success: false, msg: error.message };
    }
  }

  /**
   * Handle status update based on action type
   * @param {string} orderId - Order ID
   * @param {string} action - Action type
   * @param {Object} additionalData - Additional data for the action
   * @returns {Promise<Object>} API response
   */
  async handleStatusUpdate(orderId, action, additionalData = null) {
    try {
      switch (action) {
        case 'open':
        case 'picking':
        case 'packed':
          return await this.updateOrderStatus(orderId, action, additionalData);

        case 'complete-dispatch':
        case 'completed':
          return await this.completeDispatch(orderId);

        default:
          throw new Error(`Unknown action: ${action}`);
      }
    } catch (error) {
      console.error('Error handling status update:', error);
      return { success: false, msg: error.message };
    }
  }

  /**
   * Get order status counts
   * @param {number} warehouseId - Warehouse ID
   * @param {number} companyId - Company ID
   * @returns {Promise<Object>} API response with status counts
   */
  async getOrderStatusCounts(warehouseId, companyId) {
    try {
      const params = {};
      if (warehouseId) params.warehouse_id = warehouseId;
      if (companyId) params.company_id = companyId;

      const response = await axiosWithAuth.get(`${API_BASE_URL}/api/orders/status`, { params });
      return response.data;
    } catch (error) {
      console.error('Error fetching order status counts:', error);
      return { success: false, msg: error.message };
    }
  }

}

// Export singleton instance
const orderManagementService = new OrderManagementService();
export default orderManagementService;