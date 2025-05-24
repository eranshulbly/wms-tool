// FIXED Order Management Utils - All issues addressed

import { 
  DATE_FORMAT_OPTIONS, 
  STATUS_PROGRESSION,
  BACKEND_TO_FRONTEND_STATUS,
  FRONTEND_TO_BACKEND_STATUS 
} from '../constants/orderManagement.constants';

/**
 * Format date for display
 * @param {string} dateString - ISO date string
 * @returns {string} Formatted date string
 */
export const formatDate = (dateString) => {
  if (!dateString) return 'N/A';
  try {
    return new Date(dateString).toLocaleString(undefined, DATE_FORMAT_OPTIONS);
  } catch (error) {
    console.error('Error formatting date:', error);
    return 'Invalid Date';
  }
};

/**
 * Calculate time in current status
 * @param {string} dateString - ISO date string when status was entered
 * @returns {string} Human readable time duration (e.g., "2d 5h" or "3h")
 */
export const getTimeInCurrentStatus = (dateString) => {
  if (!dateString) return 'N/A';

  try {
    const date = new Date(dateString);
    if (isNaN(date.getTime())) return 'N/A';

    const now = new Date();
    const diffMs = now - date;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    const diffHours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));

    if (diffDays > 0) {
      return `${diffDays}d ${diffHours}h`;
    }
    return `${diffHours}h`;
  } catch (error) {
    console.error('Error calculating time in status:', error);
    return 'N/A';
  }
};

/**
 * Get the next possible status for an order
 * @param {string} currentStatus - Current order status
 * @returns {string|null} Next status or null if no next status
 */
export const getNextStatus = (currentStatus) => {
  return STATUS_PROGRESSION[currentStatus?.toLowerCase()] || null;
};

/**
 * FIXED: Get status chip class name based on status including all states
 * @param {string} status - Order status
 * @returns {string} CSS class name for the status chip
 */
export const getStatusChipClass = (status) => {
  const normalizedStatus = String(status).toLowerCase().replace(/\s+/g, '-');
  const statusClassMap = {
    'open': 'chipOpen',
    'picking': 'chipPicking',
    'packing': 'chipPacking',
    'dispatch': 'chipDispatch',
    'dispatch-ready': 'chipDispatch', // Handle both formats
    'completed': 'chipCompleted',
    'partially-completed': 'chipPartiallyCompleted'
  };

  return statusClassMap[normalizedStatus] || 'chipOpen';
};

/**
 * FIXED: Filter orders based on status with proper status mapping
 * @param {Array} orders - Array of order objects
 * @param {string} statusFilter - Status to filter by ('all' for no filter)
 * @returns {Array} Filtered array of orders
 */
export const filterOrdersByStatus = (orders, statusFilter) => {
  if (!orders || !Array.isArray(orders)) return [];

  if (statusFilter === 'all') {
    return orders;
  }

  return orders.filter(order => {
    const orderStatus = String(order.status || '').toLowerCase().replace(/\s+/g, '-');
    const filterStatus = statusFilter.toLowerCase().replace(/\s+/g, '-');
    
    // Handle special case for dispatch/dispatch-ready mapping
    if (filterStatus === 'dispatch' && (orderStatus === 'dispatch' || orderStatus === 'dispatch-ready')) {
      return true;
    }
    
    return orderStatus === filterStatus;
  });
};

/**
 * FIXED: Convert frontend status to backend status
 * @param {string} frontendStatus - Frontend status
 * @returns {string} Backend status
 */
export const frontendToBackendStatus = (frontendStatus) => {
  return FRONTEND_TO_BACKEND_STATUS[frontendStatus?.toLowerCase()] || frontendStatus;
};

/**
 * FIXED: Convert backend status to frontend status
 * @param {string} backendStatus - Backend status
 * @returns {string} Frontend status
 */
export const backendToFrontendStatus = (backendStatus) => {
  return BACKEND_TO_FRONTEND_STATUS[backendStatus] || backendStatus?.toLowerCase();
};

/**
 * FIXED: Validate product quantities in boxes - addresses issue #1
 * @param {Array} products - Products array
 * @param {Object} boxProductQuantities - Nested object: {productId: {boxId: quantity}}
 * @returns {Object} Validation result with details
 */
export const validateBoxQuantities = (products, boxProductQuantities) => {
  const validation = {
    isValid: true,
    errors: [],
    warnings: [],
    totalsByProduct: {},
    totalsByBox: {}
  };

  // Calculate totals by product
  products.forEach(product => {
    const productId = product.product_id;
    let total = 0;
    
    if (boxProductQuantities[productId]) {
      Object.values(boxProductQuantities[productId]).forEach(qty => {
        const quantity = parseInt(qty) || 0;
        total += quantity;
      });
    }
    
    validation.totalsByProduct[productId] = total;
    
    // Validate against available quantity
    if (total > product.quantity_available) {
      validation.errors.push(`${product.name}: Total packed (${total}) exceeds available (${product.quantity_available})`);
      validation.isValid = false;
    }
    
    // Warning for partial packing
    if (total > 0 && total < product.quantity_ordered) {
      validation.warnings.push(`${product.name}: Partially packed (${total}/${product.quantity_ordered})`);
    }
  });

  return validation;
};

/**
 * FIXED: Calculate box contents properly - addresses issue #1
 * @param {Array} boxes - Boxes array
 * @param {Array} products - Products array
 * @param {Object} boxProductQuantities - Nested object: {productId: {boxId: quantity}}
 * @returns {Object} Box contents with totals
 */
export const calculateBoxContents = (boxes, products, boxProductQuantities) => {
  const boxContents = {};
  
  boxes.forEach(box => {
    const boxId = box.box_id;
    let totalItems = 0;
    const productsInBox = [];
    
    products.forEach(product => {
      const quantity = boxProductQuantities[product.product_id]?.[boxId] || 0;
      const parsedQuantity = parseInt(quantity) || 0;
      
      if (parsedQuantity > 0) {
        totalItems += parsedQuantity;
        productsInBox.push({
          ...product,
          quantity: parsedQuantity
        });
      }
    });
    
    boxContents[boxId] = {
      box,
      totalItems,
      productsInBox,
      isEmpty: totalItems === 0
    };
  });
  
  return boxContents;
};

/**
 * FIXED: Parse quantity input safely - addresses issue #2
 * @param {string|number} input - Input value from text field
 * @returns {number} Parsed quantity (0 if invalid)
 */
export const parseQuantityInput = (input) => {
  if (input === '' || input === null || input === undefined) {
    return 0;
  }
  
  const parsed = parseInt(input, 10);
  return isNaN(parsed) || parsed < 0 ? 0 : parsed;
};

/**
 * FIXED: Format quantity for input field - addresses issue #2
 * @param {number} quantity - Quantity to format
 * @returns {string} Formatted quantity for input
 */
export const formatQuantityForInput = (quantity) => {
  const parsed = parseInt(quantity) || 0;
  return parsed.toString();
};

/**
 * FIXED: Validate packing data before submission
 * @param {Array} products - Products array
 * @param {Object} productQuantities - Product quantities
 * @param {Object} productBoxAssignments - Product box assignments
 * @param {Object} boxProductQuantities - Box product quantities
 * @returns {Object} Comprehensive validation result
 */
export const validatePackingData = (products, productQuantities, productBoxAssignments, boxProductQuantities) => {
  const errors = [];
  const warnings = [];
  
  // Validate each product
  products.forEach(product => {
    const productId = product.product_id;
    const totalPacked = productQuantities[productId] || 0;
    const hasAssignment = productBoxAssignments[productId];
    
    // Check if packed quantity has box assignment
    if (totalPacked > 0 && !hasAssignment) {
      errors.push(`${product.name} has packed quantity (${totalPacked}) but no box assignment`);
    }
    
    // Check if quantity exceeds available
    if (totalPacked > product.quantity_available) {
      errors.push(`${product.name} packed quantity (${totalPacked}) exceeds available quantity (${product.quantity_available})`);
    }
    
    // Warning for partial packing
    if (totalPacked > 0 && totalPacked < product.quantity_ordered) {
      warnings.push(`${product.name} is partially packed (${totalPacked}/${product.quantity_ordered})`);
    }
    
    // Validate box quantities add up correctly
    if (boxProductQuantities[productId]) {
      const boxTotal = Object.values(boxProductQuantities[productId])
        .reduce((sum, qty) => sum + (parseInt(qty) || 0), 0);
      
      if (boxTotal !== totalPacked) {
        errors.push(`${product.name} box quantities (${boxTotal}) don't match total packed (${totalPacked})`);
      }
    }
  });
  
  // Check that at least one product is packed
  const totalAllProducts = Object.values(productQuantities).reduce((sum, qty) => sum + (qty || 0), 0);
  if (totalAllProducts === 0) {
    errors.push('No products have been packed. Please pack at least one product.');
  }
  
  return {
    isValid: errors.length === 0,
    errors,
    warnings,
    totalPacked: totalAllProducts
  };
};

/**
 * FIXED: Create box assignment string for multiple boxes
 * @param {Object} boxProductQuantities - Box product quantities
 * @param {string} productId - Product ID
 * @returns {string} Comma-separated box IDs where product has quantity
 */
export const createBoxAssignmentString = (boxProductQuantities, productId) => {
  if (!boxProductQuantities[productId]) return '';
  
  const boxesWithProduct = Object.keys(boxProductQuantities[productId])
    .filter(boxId => (parseInt(boxProductQuantities[productId][boxId]) || 0) > 0);
  
  return boxesWithProduct.join(',');
};

/**
 * FIXED: Get product distribution across boxes
 * @param {string} productId - Product ID
 * @param {Object} boxProductQuantities - Box product quantities
 * @returns {Array} Array of {boxId, quantity} objects
 */
export const getProductBoxDistribution = (productId, boxProductQuantities) => {
  if (!boxProductQuantities[productId]) return [];
  
  return Object.entries(boxProductQuantities[productId])
    .map(([boxId, quantity]) => ({
      boxId,
      quantity: parseInt(quantity) || 0
    }))
    .filter(item => item.quantity > 0);
};

/**
 * FIXED: Check if box has any products
 * @param {string} boxId - Box ID
 * @param {Array} products - Products array
 * @param {Object} boxProductQuantities - Box product quantities
 * @returns {boolean} True if box has products
 */
export const boxHasProducts = (boxId, products, boxProductQuantities) => {
  return products.some(product => {
    const quantity = boxProductQuantities[product.product_id]?.[boxId] || 0;
    return (parseInt(quantity) || 0) > 0;
  });
};

/**
 * FIXED: Generate unique box ID
 * @param {Array} existingBoxes - Existing boxes array
 * @returns {string} Unique box ID
 */
export const generateUniqueBoxId = (existingBoxes = []) => {
  const timestamp = Date.now();
  const random = Math.floor(Math.random() * 1000);
  return `B${timestamp}${random}`;
};

/**
 * FIXED: Generate box name
 * @param {number} boxIndex - Box index (0-based)
 * @returns {string} Box name
 */
export const generateBoxName = (boxIndex) => {
  return `Box-${boxIndex + 1}`;
};

/**
 * Export utility functions for debugging
 */
export const debugUtils = {
  logBoxQuantities: (boxProductQuantities) => {
    console.log('Box Product Quantities:', JSON.stringify(boxProductQuantities, null, 2));
  },
  
  logProductTotals: (products, boxProductQuantities) => {
    products.forEach(product => {
      const total = Object.values(boxProductQuantities[product.product_id] || {})
        .reduce((sum, qty) => sum + (parseInt(qty) || 0), 0);
      console.log(`${product.name}: ${total} total across all boxes`);
    });
  },
  
  logBoxContents: (boxes, products, boxProductQuantities) => {
    boxes.forEach(box => {
      const contents = products
        .map(product => ({
          name: product.name,
          quantity: boxProductQuantities[product.product_id]?.[box.box_id] || 0
        }))
        .filter(item => item.quantity > 0);
      
      console.log(`${box.box_name}:`, contents);
    });
  }
};