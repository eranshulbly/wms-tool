import {
  DATE_FORMAT_OPTIONS,
  STATUS_PROGRESSION,
  BACKEND_TO_FRONTEND_STATUS,
  FRONTEND_TO_BACKEND_STATUS
} from '../constants/statuses';

/**
 * Format a date string for display.
 * @param {string} dateString - ISO date string
 * @returns {string} Formatted date or 'N/A'
 */
export const formatDate = (dateString) => {
  if (!dateString) return 'N/A';
  try {
    return new Date(dateString).toLocaleString(undefined, DATE_FORMAT_OPTIONS);
  } catch {
    return 'Invalid Date';
  }
};

/**
 * Calculate how long an order has been in its current status.
 * Backend returns UTC timestamps without 'Z'; we append it so the browser
 * parses them as UTC rather than local time.
 * @param {string} dateString - ISO date string when status was entered
 * @returns {string} e.g. "2d 5h 30m" or "3h 12m"
 */
export const getTimeInState = (dateString) => {
  if (!dateString) return 'N/A';
  try {
    const utcString =
      dateString.endsWith('Z') || dateString.includes('+') ? dateString : dateString + 'Z';
    const date = new Date(utcString);
    if (isNaN(date.getTime())) return 'N/A';

    const diffMs = Date.now() - date.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    const diffHours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
    const diffMins = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));

    if (diffDays > 0) return `${diffDays}d ${diffHours}h ${diffMins}m`;
    if (diffHours > 0) return `${diffHours}h ${diffMins}m`;
    return `${diffMins}m`;
  } catch {
    return 'N/A';
  }
};

// Alias used by orderManagement components
export const getTimeInCurrentStatus = getTimeInState;

/**
 * Get the next manual status for an order, or null if no manual step exists.
 * @param {string} currentStatus - Frontend slug ('open', 'picking', etc.)
 */
export const getNextStatus = (currentStatus) =>
  STATUS_PROGRESSION[currentStatus?.toLowerCase()] || null;

/**
 * Map a status slug to its CSS chip class name.
 * @param {string} status - Frontend slug or raw status string
 * @returns {string} e.g. 'chipOpen'
 */
export const getStatusChipClass = (status) => {
  const normalized = String(status).toLowerCase().replace(/\s+/g, '-');
  const map = {
    'open': 'chipOpen',
    'picking': 'chipPicking',
    'packed': 'chipPacked',
    'invoiced': 'chipInvoiced',
    'dispatch-ready': 'chipDispatchReady',
    'completed': 'chipCompleted',
    'partially-completed': 'chipPartiallyCompleted'
  };
  return map[normalized] || 'chipOpen';
};

/**
 * Filter an orders array by a frontend status slug.
 * @param {Array} orders
 * @param {string} statusFilter - 'all' or a slug like 'picking'
 */
export const filterOrdersByStatus = (orders, statusFilter) => {
  if (!Array.isArray(orders)) return [];
  if (statusFilter === 'all') return orders;
  return orders.filter((order) => {
    const orderStatus = String(order.status || '').toLowerCase().replace(/\s+/g, '-');
    return orderStatus === statusFilter.toLowerCase().replace(/\s+/g, '-');
  });
};

/** Convert a frontend status slug to the backend PascalCase string. */
export const frontendToBackendStatus = (frontendStatus) =>
  FRONTEND_TO_BACKEND_STATUS[frontendStatus?.toLowerCase()] || frontendStatus;

/** Convert a backend PascalCase status string to a frontend slug. */
export const backendToFrontendStatus = (backendStatus) =>
  BACKEND_TO_FRONTEND_STATUS[backendStatus] || backendStatus?.toLowerCase();
