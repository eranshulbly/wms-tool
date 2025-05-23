import { DATE_FORMAT_OPTIONS } from '../constants/warehouseDashboard.constants';

/**
 * Format date for display
 * @param {string} dateString - ISO date string
 * @returns {string} Formatted date string
 */
export const formatDate = (dateString) => {
  return new Date(dateString).toLocaleString(undefined, DATE_FORMAT_OPTIONS);
};

/**
 * Calculate time in state - Fixed to handle undefined/null values
 * @param {string} dateString - ISO date string when state was entered
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
 * Filter orders based on status
 * @param {Array} orders - Array of order objects
 * @param {string} statusFilter - Status to filter by ('all' for no filter)
 * @returns {Array} Filtered array of orders
 */
export const filterOrdersByStatus = (orders, statusFilter) => {
  if (statusFilter === 'all') {
    return orders;
  }
  return orders.filter(order => order.status === statusFilter);
};

/**
 * Get status chip class name based on status
 * @param {string} status - Order status
 * @returns {string} CSS class name for the status chip
 */
export const getStatusChipClass = (status) => {
  const statusClassMap = {
    open: 'chipOpen',
    picking: 'chipPicking',
    packing: 'chipPacking',
    dispatch: 'chipDispatch'
  };

  return statusClassMap[status] || '';
};