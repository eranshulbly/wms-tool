// FIXED Order Management Constants - Addressing all status mapping issues

// Status filter options
export const STATUS_FILTER_OPTIONS = [
  { value: 'all', label: 'All Orders' },
  { value: 'open', label: 'Open Orders' },
  { value: 'picking', label: 'Picking' },
  { value: 'packed', label: 'Packed' },
  { value: 'invoiced', label: 'Invoiced' },
  { value: 'dispatch-ready', label: 'Dispatch Ready' },
  { value: 'completed', label: 'Completed' },
  { value: 'partially-completed', label: 'Partially Completed' }
];

// Status progression mapping (manual UI transitions only)
export const STATUS_PROGRESSION = {
  'open': 'picking',
  'picking': 'packed',
  'packed': null,            // Packed → Invoiced only via invoice file upload
  'invoiced': null,          // Invoiced → Dispatch Ready (auto, via invoice upload)
  'dispatch-ready': null,
  'completed': null,
  'partially-completed': null
};

// Bulk target statuses (all except Invoiced)
export const BULK_TARGET_STATUSES = [
  { value: 'picking',          label: 'Picking',           requiresBoxes: false },
  { value: 'packed',           label: 'Packed',            requiresBoxes: true  },
  { value: 'completed',        label: 'Completed',         requiresBoxes: false },
];

// Status display names
export const STATUS_LABELS = {
  'open': 'Open',
  'picking': 'Picking',
  'packed': 'Packed',
  'invoiced': 'Invoiced',
  'dispatch-ready': 'Dispatch Ready',
  'completed': 'Completed',
  'partially-completed': 'Partially Completed'
};

// Frontend to Backend Status Mapping
export const FRONTEND_TO_BACKEND_STATUS = {
  'open': 'Open',
  'picking': 'Picking',
  'packed': 'Packed',
  'invoiced': 'Invoiced',
  'dispatch-ready': 'Dispatch Ready',
  'completed': 'Completed',
  'partially-completed': 'Partially Completed'
};

// Backend to Frontend Status Mapping
export const BACKEND_TO_FRONTEND_STATUS = {
  'Open': 'open',
  'Picking': 'picking',
  'Packed': 'packed',
  'Invoiced': 'invoiced',
  'Dispatch Ready': 'dispatch-ready',
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

