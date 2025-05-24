// FIXED Order Management Constants - Addressing all status mapping issues

// Status filter options - FIXED to include all states
export const STATUS_FILTER_OPTIONS = [
  { value: 'all', label: 'All Orders' },
  { value: 'open', label: 'Open Orders' },
  { value: 'picking', label: 'Picking' },
  { value: 'packing', label: 'Packing' },
  { value: 'dispatch-ready', label: 'Dispatch Ready' }, // Changed from 'dispatch'
  { value: 'completed', label: 'Completed' },
  { value: 'partially-completed', label: 'Partially Completed' }
];

// FIXED Status progression mapping
export const STATUS_PROGRESSION = {
  'open': 'picking',
  'picking': 'packing',
  'packing': 'dispatch-ready', // Changed from 'dispatch'
  'dispatch-ready': null,
  'completed': null,
  'partially-completed': null
};

// FIXED Status display names - consistent naming
export const STATUS_LABELS = {
  'open': 'Open',
  'picking': 'Picking',
  'packing': 'Packing',
  'dispatch-ready': 'Dispatch Ready', // Changed from 'dispatch'
  'completed': 'Completed',
  'partially-completed': 'Partially Completed'
};

// FIXED Frontend to Backend Status Mapping
export const FRONTEND_TO_BACKEND_STATUS = {
  'open': 'Open',
  'picking': 'Picking',
  'packing': 'Packing',
  'dispatch-ready': 'Dispatch Ready', // Changed from 'dispatch'
  'completed': 'Completed',
  'partially-completed': 'Partially Completed'
};

// FIXED Backend to Frontend Status Mapping
export const BACKEND_TO_FRONTEND_STATUS = {
  'Open': 'open',
  'Picking': 'picking',
  'Packing': 'packing',
  'Dispatch Ready': 'dispatch-ready', // This is the key mapping
  'Completed': 'completed',
  'Partially Completed': 'partially-completed'
};

// Table column configuration
export const TABLE_COLUMNS = [
  { id: 'dealer', label: 'Dealer' },
  { id: 'status', label: 'Status' },
  { id: 'orderDate', label: 'Order Date' },
  { id: 'timeInStatus', label: 'Time in Current Status' },
  { id: 'assignedTo', label: 'Assigned To' },
  { id: 'actions', label: 'Actions' }
];

// Date formatting options
export const DATE_FORMAT_OPTIONS = {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit'
};

// FIXED: Box management constants for validation
export const BOX_VALIDATION_RULES = {
  MIN_QUANTITY: 0,
  MAX_BOXES_PER_ORDER: 50,
  MIN_BOX_NAME_LENGTH: 1,
  MAX_BOX_NAME_LENGTH: 100
};

// FIXED: Product packing validation constants
export const PACKING_VALIDATION_RULES = {
  REQUIRE_BOX_ASSIGNMENT_FOR_PACKED_ITEMS: true,
  ALLOW_PARTIAL_PACKING: true,
  ALLOW_OVER_PACKING: false,
  MIN_PACKED_QUANTITY: 0
};