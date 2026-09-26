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
 * Parse a backend timestamp as UTC.
 *
 * The API sends `datetime.isoformat()` on a naive UTC value, so the string
 * carries no zone and the browser would read it as LOCAL time — which in
 * IST puts every event 5½ hours in the past and makes the newest state look
 * like it was entered before the one before it. Same convention as
 * getTimeInState, factored out so the two cannot drift apart.
 */
const asUtc = (dateString) => {
  if (!dateString) return null;
  const s =
    dateString.endsWith('Z') || dateString.includes('+') ? dateString : `${dateString}Z`;
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
};

/** "2d 5h 30m" / "3h 12m" / "8m" / "<1m" from a millisecond span. */
export const formatDuration = (ms) => {
  if (ms == null || isNaN(ms)) return 'N/A';
  if (ms < 0) return 'N/A'; // clock skew, or history out of order — say nothing rather than lie
  const mins = Math.floor(ms / 60000);
  if (mins < 1) return '<1m';
  const days = Math.floor(mins / 1440);
  const hours = Math.floor((mins % 1440) / 60);
  const rem = mins % 60;
  if (days > 0) return `${days}d ${hours}h ${rem}m`;
  if (hours > 0) return `${hours}h ${rem}m`;
  return `${rem}m`;
};

/**
 * How long the order sat in each state.
 *
 * A history row records the moment a state was ENTERED, so the time spent in
 * it is the gap to the next row — and for the last row, the gap to now. That
 * last one is still running, which is why it is flagged rather than presented
 * as a settled figure: an order sitting in Packed for three days is the thing
 * worth noticing, and rendering it identically to a finished span hides it.
 *
 * Returns the same rows, each with `durationMs`, `duration` and `isCurrent`.
 *
 * @param {Array} history - state_history from the API, oldest first
 * @param {number} [now]  - injectable for tests
 */
export const withDurations = (history, now = Date.now()) => {
  if (!Array.isArray(history) || history.length === 0) return [];

  // Defensive sort: the API orders by changed_at, but a caller that merged or
  // reversed the list would otherwise produce negative spans that read as 'N/A'
  // for every row rather than for the one that is actually wrong.
  const rows = [...history].sort((a, b) => {
    const ta = asUtc(a.timestamp)?.getTime() ?? 0;
    const tb = asUtc(b.timestamp)?.getTime() ?? 0;
    return ta - tb;
  });

  return rows.map((row, idx) => {
    const entered = asUtc(row.timestamp);
    const isCurrent = idx === rows.length - 1;
    const left = isCurrent ? now : asUtc(rows[idx + 1].timestamp)?.getTime();
    const durationMs =
      entered && left != null ? left - entered.getTime() : null;
    return {
      ...row,
      enteredAt: entered,
      isCurrent,
      durationMs,
      duration: formatDuration(durationMs)
    };
  });
};

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
