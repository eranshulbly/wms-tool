// Order Management Service - Updated with product details and packing functionality

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
   * Get order details with products by ID
   * @param {string} orderId - Order ID (e.g., "PO123")
   * @returns {Promise<Object>} API response with detailed order information
   */
  async getOrderDetailsWithProducts(orderId) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/orders/${orderId}/details`);
      const data = await response.json();

      // Transform the data to ensure current_state_time is available
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
      const requestBody = {
        new_status: newStatus
      };

      if (additionalData) {
        Object.assign(requestBody, additionalData);
      }

      // Use the correct endpoint
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
   * Update packing information for an order
   * @param {string} orderId - Order ID (e.g., "PO123")
   * @param {Array} products - Products with packed quantities
   * @param {Array} boxes - Box assignments
   * @returns {Promise<Object>} API response
   */
  async updatePackingInfo(orderId, products, boxes) {
    try {
      const requestBody = {
        products: products,
        boxes: boxes
      };

      const response = await fetch(`${API_BASE_URL}/api/orders/${orderId}/packing`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody)
      });

      const data = await response.json();
      return data;
    } catch (error) {
      console.error('Error updating packing info:', error);
      return { success: false, msg: error.message };
    }
  }

  /**
   * Finalize order and dispatch
   * @param {string} orderId - Order ID (e.g., "PO123")
   * @param {Array} products - Final products with quantities
   * @param {Array} boxes - Final box assignments
   * @returns {Promise<Object>} API response
   */
  async finalizeDispatch(orderId, products, boxes) {
    try {
      const requestBody = {
        products: products,
        boxes: boxes
      };

      const response = await fetch(`${API_BASE_URL}/api/orders/${orderId}/dispatch`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody)
      });

      const data = await response.json();
      return data;
    } catch (error) {
      console.error('Error finalizing dispatch:', error);
      return { success: false, msg: error.message };
    }
  }

  /**
   * Get order details by ID (legacy method - kept for backward compatibility)
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

  /**
   * Get order status counts
   * @param {number} warehouseId - Warehouse ID
   * @param {number} companyId - Company ID
   * @returns {Promise<Object>} API response with status counts
   */
  async getOrderStatusCounts(warehouseId, companyId) {
    try {
      const params = new URLSearchParams();

      if (warehouseId) params.append('warehouse_id', warehouseId);
      if (companyId) params.append('company_id', companyId);

      const response = await fetch(`${API_BASE_URL}/api/orders/status-counts?${params.toString()}`);
      const data = await response.json();
      return data;
    } catch (error) {
      console.error('Error fetching order status counts:', error);
      return { success: false, msg: error.message };
    }
  }

  /**
   * Validate packing data before submission
   * @param {Array} products - Products with quantities
   * @param {Array} boxes - Box assignments
   * @param {Object} productBoxAssignments - Product to box mappings
   * @returns {Object} Validation result
   */
  validatePackingData(products, boxes, productBoxAssignments) {
    const errors = [];
    const warnings = [];

    // Check that all products with quantities have box assignments
    products.forEach(product => {
      const packedQty = product.quantity_packed || 0;
      const boxAssignment = productBoxAssignments[product.product_id];

      if (packedQty > 0 && !boxAssignment) {
        errors.push(`${product.name} has packed quantity but no box assignment`);
      }

      if (packedQty > product.quantity_available) {
        errors.push(`${product.name} packed quantity (${packedQty}) exceeds available quantity (${product.quantity_available})`);
      }

      if (packedQty < product.quantity_ordered) {
        warnings.push(`${product.name} packed quantity (${packedQty}) is less than ordered quantity (${product.quantity_ordered})`);
      }
    });

    // Check that all boxes have at least one product
    boxes.forEach(box => {
      const productsInBox = products.filter(product =>
        productBoxAssignments[product.product_id] === box.box_id &&
        (product.quantity_packed || 0) > 0
      );

      if (productsInBox.length === 0) {
        warnings.push(`${box.box_name} has no products assigned`);
      }
    });

    return {
      isValid: errors.length === 0,
      errors,
      warnings
    };
  }

  /**
   * Calculate packing summary
   * @param {Array} products - Products with quantities
   * @param {Object} productQuantities - Product quantities
   * @returns {Object} Packing summary
   */
  calculatePackingSummary(products, productQuantities) {
    const totalOrdered = products.reduce((sum, product) => sum + product.quantity_ordered, 0);
    const totalPacked = Object.values(productQuantities).reduce((sum, qty) => sum + (qty || 0), 0);
    const totalRemaining = totalOrdered - totalPacked;

    const productsSummary = products.map(product => ({
      ...product,
      quantity_packed: productQuantities[product.product_id] || 0,
      quantity_remaining: product.quantity_ordered - (productQuantities[product.product_id] || 0)
    }));

    return {
      totalOrdered,
      totalPacked,
      totalRemaining,
      products: productsSummary,
      packingComplete: totalRemaining === 0,
      partialPacking: totalPacked > 0 && totalRemaining > 0
    };
  }
}

// Export singleton instance
const orderManagementService = new OrderManagementService();
export default orderManagementService;