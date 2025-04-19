import axios from 'axios';
import config from '../config';

// This service handles all API calls related to order management

const orderService = {
  /**
   * Fetch orders with optional filters
   * @param {number} warehouseId - ID of the selected warehouse
   * @param {number} companyId - ID of the selected company
   * @param {string} status - Optional status filter
   * @returns {Promise} Promise object that resolves to orders data
   */
  getOrders: async (warehouseId, companyId, status = null) => {
    try {
      const params = {
        warehouse_id: warehouseId,
        company_id: companyId
      };

      if (status && status !== 'all') {
        params.status = status;
      }

      const response = await axios.get(`${config.API_SERVER}orders`, { params });
      return response.data;
    } catch (error) {
      console.error('Error fetching orders:', error);
      throw error;
    }
  },

  /**
   * Fetch a single order by ID
   * @param {string} orderId - ID of the order to fetch
   * @returns {Promise} Promise object that resolves to order data
   */
  getOrderById: async (orderId) => {
    try {
      const response = await axios.get(`${config.API_SERVER}orders/${orderId}`);
      return response.data;
    } catch (error) {
      console.error('Error fetching order details:', error);
      throw error;
    }
  },

  /**
   * Update order status
   * @param {string} orderId - ID of the order to update
   * @param {string} newStatus - New status to set
   * @param {Array} boxes - Optional boxes data (required when moving to dispatch status)
   * @returns {Promise} Promise object that resolves to updated order data
   */
  updateOrderStatus: async (orderId, newStatus, boxes = null) => {
    try {
      const requestData = {
        new_status: newStatus
      };

      // Include boxes data if provided (for packing to dispatch transition)
      if (boxes) {
        requestData.boxes = boxes;
      }

      const response = await axios.post(`${config.API_SERVER}orders/${orderId}/status`, requestData);
      return response.data;
    } catch (error) {
      console.error('Error updating order status:', error);
      throw error;
    }
  },

  /**
   * Assign products to boxes
   * @param {string} orderId - ID of the order
   * @param {Array} boxAssignments - Array of box assignments with product mappings
   * @returns {Promise} Promise object that resolves to updated order data
   */
  assignProductsToBoxes: async (orderId, boxAssignments) => {
    try {
      const response = await axios.post(`${config.API_SERVER}orders/${orderId}/box-assignments`, {
        box_assignments: boxAssignments
      });
      return response.data;
    } catch (error) {
      console.error('Error assigning products to boxes:', error);
      throw error;
    }
  },

  /**
   * Get all possible transitions for an order based on its current status
   * @param {string} orderId - ID of the order
   * @returns {Promise} Promise object that resolves to possible transitions
   */
  getPossibleTransitions: async (orderId) => {
    try {
      const response = await axios.get(`${config.API_SERVER}orders/${orderId}/transitions`);
      return response.data;
    } catch (error) {
      console.error('Error fetching possible transitions:', error);
      throw error;
    }
  }
};

export default orderService;