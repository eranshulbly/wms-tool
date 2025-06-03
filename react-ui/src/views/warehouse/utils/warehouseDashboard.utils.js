import { DATE_FORMAT_OPTIONS, STATUS_PROGRESSION } from '../constants/orderManagement.constants';

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
export const getTimeInState = (dateString) => {
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
    console.error('Error calculating time in state:', error);
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
 * FIXED: Get status chip class name based on status including new states
 * @param {string} status - Order status
 * @returns {string} CSS class name for the status chip
 */
export const getStatusChipClass = (status) => {
  const normalizedStatus = String(status).toLowerCase().replace(' ', '-');
  const statusClassMap = {
    'open': 'chipOpen',
    'picking': 'chipPicking',
    'packing': 'chipPacking',
    'dispatch-ready': 'chipDispatch',
    'completed': 'chipCompleted',
    'partially-completed': 'chipPartiallyCompleted'
  };

  return statusClassMap[normalizedStatus] || '';
};

/**
 * Filter orders based on status
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
    const orderStatus = String(order.status || '').toLowerCase().replace(' ', '-');
    const filterStatus = statusFilter.toLowerCase().replace(' ', '-');
    return orderStatus === filterStatus;
  });
};