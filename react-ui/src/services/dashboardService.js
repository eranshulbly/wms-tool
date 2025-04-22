import axios from 'axios';
import config from '../config';

// This service handles all API calls related to the warehouse dashboard

const dashboardService = {
  /**
   * Fetch available warehouses
   * @returns {Promise} Promise object that resolves to warehouse data
   */
  getWarehouses: async () => {
    try {
      const response = await axios.get(`${config.API_SERVER}warehouses`);
      return response.data;
    } catch (error) {
      console.error('Error fetching warehouses:', error);
      throw error;
    }
  },

  /**
   * Fetch available companies
   * @returns {Promise} Promise object that resolves to company data
   */
  getCompanies: async () => {
    try {
      const response = await axios.get(`${config.API_SERVER}companies`);
      return response.data;
    } catch (error) {
      console.error('Error fetching companies:', error);
      throw error;
    }
  },

  /**
   * Fetch order status counts for dashboard
   * @param {number} warehouseId - ID of the selected warehouse
   * @param {number} companyId - ID of the selected company
   * @returns {Promise} Promise object that resolves to order status data
   */
  getOrderStatusCounts: async (warehouseId, companyId) => {
    try {
      const response = await axios.get(`${config.API_SERVER}orders/status`, {
        params: {
          warehouse_id: warehouseId,
          company_id: companyId
        }
      });
      return response.data;
    } catch (error) {
      console.error('Error fetching order status counts:', error);
      throw error;
    }
  },

  /**
   * Fetch orders by status
   * @param {string} status - Status of orders to fetch (open, picking, packing, dispatch)
   * @param {number} warehouseId - ID of the selected warehouse
   * @param {number} companyId - ID of the selected company
   * @returns {Promise} Promise object that resolves to orders list
   */
  getOrdersByStatus: async (status, warehouseId, companyId) => {
    try {
      const response = await axios.get(`${config.API_SERVER}orders`, {
        params: {
          status,
          warehouse_id: warehouseId,
          company_id: companyId
        }
      });
      return response.data;
    } catch (error) {
      console.error(`Error fetching ${status} orders:`, error);
      throw error;
    }
  },

  /**
   * Fetch order details
   * @param {string} orderId - ID of the order to fetch details for
   * @returns {Promise} Promise object that resolves to order details
   */
  getOrderDetails: async (orderId) => {
    try {
      const response = await axios.get(`${config.API_SERVER}orders/${orderId}`);
      return response.data;
    } catch (error) {
      console.error('Error fetching order details:', error);
      throw error;
    }
  },

  /**
   * Fetch recent activity for dashboard
   * @param {number} warehouseId - ID of the selected warehouse
   * @param {number} companyId - ID of the selected company
   * @param {number} limit - Maximum number of records to return
   * @returns {Promise} Promise object that resolves to recent activity data
   */
  getRecentActivity: async (warehouseId, companyId, limit = 10) => {
    try {
      const response = await axios.get(`${config.API_SERVER}orders/recent`, {
        params: {
          warehouse_id: warehouseId,
          company_id: companyId,
          limit
        }
      });
      return response.data;
    } catch (error) {
      console.error('Error fetching recent activity:', error);
      throw error;
    }
  }
};

export default dashboardService;