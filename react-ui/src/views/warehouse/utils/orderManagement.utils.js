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
    'packed': 'chipPacked',
    'invoiced': 'chipInvoiced',
    'dispatch-ready': 'chipDispatchReady',
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

