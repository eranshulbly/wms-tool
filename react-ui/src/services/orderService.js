import axios from 'axios';
import config from '../config';

// Base API URL
const API_BASE_URL = 'http://localhost:5000';

// This service handles all API calls related to order management
const orderService = {
  /**
   * Fetch status counts for orders dashboard
   * @param {number} warehouseId - ID of the selected warehouse
   * @param {number} companyId - ID of the selected company
   * @returns {Promise} Promise object that resolves to status counts data
   */
  getStatusCounts: async (warehouseId, companyId) => {
    try {
      const params = {
        warehouse_id: warehouseId,
        company_id: companyId
      };

      const response = await axios.get(`${API_BASE_URL}/api/orders/status-counts`, { params });
      return response.data;
    } catch (error) {
      console.error('Error fetching status counts:', error);
      throw error;
    }
  },

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

      const response = await axios.get(`${API_BASE_URL}/api/orders`, { params });
      return response.data;
    } catch (error) {
      console.error('Error fetching orders:', error);
      throw error;
    }
  },

  /**
   * Fetch warehouses
   * @returns {Promise} Promise object that resolves to warehouses data
   */
  getWarehouses: async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/warehouses`);
      return response.data;
    } catch (error) {
      console.error('Error fetching warehouses:', error);
      throw error;
    }
  },

  /**
   * Fetch companies
   * @returns {Promise} Promise object that resolves to companies data
   */
  getCompanies: async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/companies`);
      return response.data;
    } catch (error) {
      console.error('Error fetching companies:', error);
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
      const response = await axios.get(`${API_BASE_URL}/api/orders/${orderId}`);
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

      const response = await axios.post(`${API_BASE_URL}/api/orders/${orderId}`, requestData);
      return response.data;
    } catch (error) {
      console.error('Error updating order status:', error);
      throw error;
    }
  }
};

export default orderService;