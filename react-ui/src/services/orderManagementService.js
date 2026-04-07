// Order Management Service - Cleaned version with unused functions removed
import axios from 'axios';

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:5000';

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
      const response = await axios.get(`${API_BASE_URL}/api/warehouses`);
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
      const response = await axios.get(`${API_BASE_URL}/api/companies`);
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
  async getOrders(warehouseId, companyId, status = null) {
    try {
      const params = {};
      if (warehouseId) params.warehouse_id = warehouseId;
      if (companyId) params.company_id = companyId;
      if (status && status !== 'all') params.status = status;

      const response = await axios.get(`${API_BASE_URL}/api/orders`, { params });
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
      const response = await axios.get(`${API_BASE_URL}/api/orders/${orderId}/details`);
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
   * Update order status
   * @param {string} orderId - Order ID (e.g., "PO123")
   * @param {string} newStatus - New status
   * @param {Object} additionalData - Additional data (boxes, products, etc.)
   * @returns {Promise<Object>} API response
   */
  async updateOrderStatus(orderId, newStatus, additionalData = null) {
    try {
      const allowedStatuses = ['open', 'picking', 'packing'];
      if (!allowedStatuses.includes(newStatus.toLowerCase())) {
        throw new Error(`Use specific methods for ${newStatus} transitions`);
      }

      const requestBody = { new_status: newStatus };
      if (additionalData) Object.assign(requestBody, additionalData);

      const response = await axios.post(`${API_BASE_URL}/api/orders/${orderId}/status`, requestBody);
      return response.data;
    } catch (error) {
      console.error('Error updating order status:', error);
      return { success: false, msg: error.message };
    }
  }

  /**
   * Move order to invoice ready status
   * @param {string} orderId - Order ID
   * @param {number} numberOfBoxes - Number of boxes used for packing
   * @returns {Promise<Object>} API response
   */
  async moveToInvoiceReady(orderId, numberOfBoxes) {
    try {
      const response = await axios.post(`${API_BASE_URL}/api/orders/${orderId}/move-to-invoice-ready`, {
        number_of_boxes: numberOfBoxes
      });
      return response.data;
    } catch (error) {
      console.error('Error moving to invoice ready:', error);
      return { success: false, msg: error.message };
    }
  }

  /**
   * Download bulk order Excel template filtered by current status/warehouse/company
   * @param {Object} filters - { status, warehouseId, companyId }
   */
  async downloadBulkTemplate(filters = {}) {
    const params = {};
    if (filters.status && filters.status !== 'all') params.status = filters.status;
    if (filters.warehouseId) params.warehouse_id = filters.warehouseId;
    if (filters.companyId) params.company_id = filters.companyId;

    const response = await axios.get(`${API_BASE_URL}/api/orders/bulk-export`, {
      params,
      responseType: 'blob'
    });

    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = url;
    const filename = `orders_bulk_${new Date().toISOString().slice(0, 10)}.xlsx`;
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  }

  /**
   * Upload filled bulk Excel file and process status transitions
   * @param {File} file - The uploaded Excel file
   * @returns {Promise<Object>} API response with summary and details
   */
  async uploadBulkFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    const response = await axios.post(`${API_BASE_URL}/api/orders/bulk-import`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
    return response.data;
  }

  /**
   * Complete order dispatch
   * @param {string} orderId - Order ID
   * @returns {Promise<Object>} API response
   */
  async completeDispatch(orderId) {
    try {
      const response = await axios.post(`${API_BASE_URL}/api/orders/${orderId}/complete-dispatch`);
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
        case 'packing':
          return await this.updateOrderStatus(orderId, action, additionalData);

        case 'packing-to-invoice':
        case 'invoice-ready':
          if (!additionalData || !additionalData.number_of_boxes) {
            throw new Error('number_of_boxes required for invoice ready');
          }
          return await this.moveToInvoiceReady(orderId, additionalData.number_of_boxes);

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

      const response = await axios.get(`${API_BASE_URL}/api/orders/status`, { params });
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