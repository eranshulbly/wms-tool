// Order Management Constants

// Status filter options
export const STATUS_FILTER_OPTIONS = [
  { value: 'all', label: 'All Orders' },
  { value: 'open', label: 'Open Orders' },
  { value: 'picking', label: 'Picking' },
  { value: 'packing', label: 'Packing' },
  { value: 'dispatch', label: 'Dispatch Ready' },
  { value: 'completed', label: 'Completed' },
  { value: 'partially-completed', label: 'Partially Completed' }
];

// Status progression mapping
export const STATUS_PROGRESSION = {
  'open': 'picking',
  'picking': 'packing',
  'packing': 'dispatch',
  'dispatch': null, // Final status - will be handled in dispatch process
  'completed': null, // Final status
  'partially-completed': null // Final status
};

// Status display names
export const STATUS_LABELS = {
  'open': 'Open',
  'picking': 'Picking',
  'packing': 'Packing',
  'dispatch': 'Dispatch Ready',
  'completed': 'Completed',
  'partially-completed': 'Partially Completed'
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