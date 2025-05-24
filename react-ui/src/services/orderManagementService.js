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
      const response = await fetch(`${API_BASE_URL}/api/orders/${orderId}/details`);
      const data = await response.json();

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
      // Only allow regular status transitions
      const allowedStatuses = ['open', 'picking', 'packing'];

      if (!allowedStatuses.includes(newStatus.toLowerCase())) {
        throw new Error(`Use specific methods for ${newStatus} transitions`);
      }

      const requestBody = {
        new_status: newStatus
      };

      if (additionalData) {
        Object.assign(requestBody, additionalData);
      }

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

  async moveToDispatchReady(orderId, products, boxes) {
    try {
      const requestBody = {
        products: products,
        boxes: boxes
      };

      const response = await fetch(`${API_BASE_URL}/api/orders/${orderId}/move-to-dispatch-ready`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody)
      });

      const data = await response.json();
      return data;
    } catch (error) {
      console.error('Error moving to dispatch ready:', error);
      return { success: false, msg: error.message };
    }
  }

  async completeDispatch(orderId) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/orders/${orderId}/complete-dispatch`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        }
      });

      const data = await response.json();
      return data;
    } catch (error) {
      console.error('Error completing dispatch:', error);
      return { success: false, msg: error.message };
    }
  }

  async handleStatusUpdate(orderId, action, additionalData = null) {
    try {
      switch (action) {
        case 'open':
        case 'picking':
        case 'packing':
          return await this.updateOrderStatus(orderId, action, additionalData);

        case 'packing-to-dispatch':
        case 'dispatch-ready':
          if (!additionalData || !additionalData.products || !additionalData.boxes) {
            throw new Error('Products and boxes data required for dispatch ready');
          }
          return await this.moveToDispatchReady(orderId, additionalData.products, additionalData.boxes);

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
   * Update packing information for an order
   * @param {string} orderId - Order ID (e.g., "PO123")
   * @param {Array} products - Products with packed quantities
   * @param {Array} boxes - Box assignments
   * @returns {Promise<Object>} API response
   */
  async updatePackingInfo(orderId, products, boxes) {
    return this.moveToDispatchReady(orderId, products, boxes);
  }

  /**
   * Finalize order and dispatch
   * @param {string} orderId - Order ID (e.g., "PO123")
   * @param {Array} products - Final products with quantities
   * @param {Array} boxes - Final box assignments
   * @returns {Promise<Object>} API response
   */
   /**
   * Legacy method - kept for backward compatibility
   */
  async finalizeDispatch(orderId, products, boxes) {
    return this.completeDispatch(orderId);
  }

  /**
   * Get order details by ID (legacy method - kept for backward compatibility)
   * @param {string} orderId - Order ID (e.g., "PO123")
   * @returns {Promise<Object>} API response with order details
   */
  async getOrderById(orderId) {
    return this.getOrderDetailsWithProducts(orderId);
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

      const response = await fetch(`${API_BASE_URL}/api/orders/status?${params.toString()}`);
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
  validatePackingData(products, productQuantities, productBoxAssignments, boxProductQuantities) {
    const errors = [];
    const warnings = [];
    let hasRemainingItems = false;

    products.forEach(product => {
      const packedQty = productQuantities[product.product_id] || 0;
      const orderedQty = product.quantity_ordered;
      const availableQty = product.quantity_available;
      const boxAssignment = productBoxAssignments[product.product_id];

      // Check box assignment for packed items
      if (packedQty > 0 && !boxAssignment) {
        errors.push(`${product.name} has packed quantity but no box assignment`);
      }

      // Check quantity limits
      if (packedQty > availableQty) {
        errors.push(`${product.name} packed quantity (${packedQty}) exceeds available (${availableQty})`);
      }

      // Check for remaining items
      if (packedQty < orderedQty) {
        hasRemainingItems = true;
        if (packedQty > 0) {
          warnings.push(`${product.name} partially packed (${packedQty}/${orderedQty})`);
        }
      }

      // Validate box quantities sum up correctly
      if (boxProductQuantities[product.product_id]) {
        const boxTotal = Object.values(boxProductQuantities[product.product_id])
          .reduce((sum, qty) => sum + (parseInt(qty) || 0), 0);

        if (boxTotal !== packedQty) {
          errors.push(`${product.name} box quantities (${boxTotal}) don't match total packed (${packedQty})`);
        }
      }
    });

    // Check that at least one product is packed
    const totalPacked = Object.values(productQuantities).reduce((sum, qty) => sum + (qty || 0), 0);
    if (totalPacked === 0) {
      errors.push('No products have been packed. Please pack at least one product.');
    }

    return {
      isValid: errors.length === 0,
      errors,
      warnings,
      hasRemainingItems,
      totalPacked
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

    const productsSummary = products.map(product => {
      const packedQty = productQuantities[product.product_id] || 0;
      return {
        ...product,
        quantity_packed: packedQty,
        quantity_remaining: product.quantity_ordered - packedQty
      };
    });

    return {
      totalOrdered,
      totalPacked,
      totalRemaining,
      products: productsSummary,
      packingComplete: totalRemaining === 0,
      partialPacking: totalPacked > 0 && totalRemaining > 0,
      hasRemainingItems: totalRemaining > 0
    };
  }

  processBoxAssignments(boxes, products, productBoxAssignments, boxProductQuantities) {
    return boxes.map(box => ({
      box_id: box.box_id,
      box_name: box.box_name,
      products: products
        .filter(product => {
          const assignments = productBoxAssignments[product.product_id] || '';
          return assignments.includes(box.box_id);
        })
        .map(product => ({
          product_id: product.product_id,
          quantity: boxProductQuantities[product.product_id]?.[box.box_id] || 0
        }))
        .filter(p => p.quantity > 0)
    })).filter(box => box.products.length > 0);
  }

  processProductsData(products, productQuantities) {
    return products.map(product => ({
      product_id: product.product_id,
      quantity_packed: productQuantities[product.product_id] || 0,
      quantity_remaining: product.quantity_ordered - (productQuantities[product.product_id] || 0)
    })).filter(p => p.quantity_packed > 0 || p.quantity_remaining > 0);
  }

  debugBoxLogic(products, boxes, productQuantities, productBoxAssignments, boxProductQuantities) {
    console.group('🔍 Debug Box Logic');

    console.log('📦 Products:', products.map(p => ({
      id: p.product_id,
      name: p.name,
      ordered: p.quantity_ordered
    })));

    console.log('📊 Product Quantities:', productQuantities);
    console.log('🏷️ Product Box Assignments:', productBoxAssignments);
    console.log('📋 Box Product Quantities:', boxProductQuantities);

    boxes.forEach(box => {
      const boxTotal = products.reduce((total, product) => {
        const qty = boxProductQuantities[product.product_id]?.[box.box_id] || 0;
        return total + (parseInt(qty) || 0);
      }, 0);

      const productsInBox = products.filter(product => {
        const qty = boxProductQuantities[product.product_id]?.[box.box_id] || 0;
        return parseInt(qty) > 0;
      });

      console.log(`📦 ${box.box_name}:`, {
        total: boxTotal,
        products: productsInBox.length,
        details: productsInBox.map(p => ({
          name: p.name,
          quantity: boxProductQuantities[p.product_id]?.[box.box_id] || 0
        }))
      });
    });

    console.groupEnd();
  }
}



// Export singleton instance
const orderManagementService = new OrderManagementService();
export default orderManagementService;