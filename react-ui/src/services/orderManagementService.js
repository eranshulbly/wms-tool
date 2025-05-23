// Order Management Service - API calls for order management

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
      const response = await fetch(`${API_BASE_URL}/api/warehouses`);
      const data = await response.json();
      return data;
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
      const response = await fetch(`${API_BASE_URL}/api/companies`);
      const data = await response.json();
      return data;
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
      const params = new URLSearchParams();

      if (warehouseId) params.append('warehouse_id', warehouseId);
      if (companyId) params.append('company_id', companyId);
      if (status && status !== 'all') params.append('status', status);

      const response = await fetch(`${API_BASE_URL}/api/orders?${params.toString()}`);
      const data = await response.json();

      // Transform the data to ensure current_state_time is available
      if (data.success && data.orders) {
        data.orders = data.orders.map(order => ({
          ...order,
          // Use current_state_time if available, otherwise use updated_at or current time
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
   * Update order status
   * @param {string} orderId - Order ID (e.g., "PO123")
   * @param {string} newStatus - New status
   * @param {Array} boxes - Box data for packing to dispatch transition (optional)
   * @returns {Promise<Object>} API response
   */
  async updateOrderStatus(orderId, newStatus, boxes = null) {
    try {
      const requestBody = {
        new_status: newStatus
      };

      if (boxes) {
        requestBody.boxes = boxes;
      }

      // Use the correct endpoint - either the existing one or the new status-specific one
      const response = await fetch(`${API_BASE_URL}/api/orders/${orderId}/status`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody)
      });

      const data = await response.json();
      return data;
    } catch (error) {
      console.error('Error updating order status:', error);
      return { success: false, msg: error.message };
    }
  }

  /**
   * Get order details by ID
   * @param {string} orderId - Order ID (e.g., "PO123")
   * @returns {Promise<Object>} API response with order details
   */
  async getOrderById(orderId) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/orders/${orderId}`);
      const data = await response.json();

      // Transform the data to ensure current_state_time is available
      if (data.success && data.orders && data.orders.length > 0) {
        data.orders = data.orders.map(order => ({
          ...order,
          current_state_time: order.current_state_time || order.updated_at || new Date().toISOString()
        }));
      }

      return data;
    } catch (error) {
      console.error('Error fetching order details:', error);
      return { success: false, msg: error.message };
    }
  }
}

// Export singleton instance
const orderManagementService = new OrderManagementService();
export default orderManagementService;