import {
  IconPackage,
  IconTruckDelivery,
  IconBoxSeam,
  IconClipboardList,
  IconUxCircle,
  IconClipboardCheck
} from '@tabler/icons';

// Order status data: icons, labels, chip class names
export const ORDER_STATUS_DATA = {
  open: {
    icon: <IconClipboardList size={42} color="#ed6c02" />,
    label: 'Open Orders',
    chipClass: 'chipOpen'
  },
  picking: {
    icon: <IconPackage size={42} color="#1976d2" />,
    label: 'Picking',
    chipClass: 'chipPicking'
  },
  packed: {
    icon: <IconBoxSeam size={42} color="#9c27b0" />,
    label: 'Packed',
    chipClass: 'chipPacked'
  },
  invoiced: {
    icon: <IconClipboardCheck size={42} color="#0288d1" />,
    label: 'Invoiced',
    chipClass: 'chipInvoiced'
  },
  'dispatch-ready': {
    icon: <IconTruckDelivery size={42} color="#2e7d32" />,
    label: 'Dispatch Ready',
    chipClass: 'chipDispatchReady'
  },
  completed: {
    icon: <IconUxCircle size={42} color="#4caf50" />,
    label: 'Completed',
    chipClass: 'chipCompleted'
  },
  'partially-completed': {
    icon: <IconClipboardCheck size={42} color="#ff9800" />,
    label: 'Partially Completed',
    chipClass: 'chipPartiallyCompleted'
  }
};

// Human-readable labels for frontend slug keys
export const STATUS_LABELS = {
  'open': 'Open',
  'picking': 'Picking',
  'packed': 'Packed',
  'invoiced': 'Invoiced',
  'dispatch-ready': 'Dispatch Ready',
  'completed': 'Completed',
  'partially-completed': 'Partially Completed'
};

// Dropdown filter options used by FilterControls on both Dashboard and OrderManagement
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

// Manual UI status progression (Packed → Invoiced is only via invoice upload)
export const STATUS_PROGRESSION = {
  'open': 'picking',
  'picking': 'packed',
  'packed': null,
  'invoiced': null,
  'dispatch-ready': null,
  'completed': null,
  'partially-completed': null
};

// Bulk upload target statuses
export const BULK_TARGET_STATUSES = [
  { value: 'picking',   label: 'Picking',   requiresBoxes: false },
  { value: 'packed',    label: 'Packed',     requiresBoxes: true  },
  { value: 'completed', label: 'Completed',  requiresBoxes: false }
];

// Mapping helpers
export const FRONTEND_TO_BACKEND_STATUS = {
  'open': 'Open',
  'picking': 'Picking',
  'packed': 'Packed',
  'invoiced': 'Invoiced',
  'dispatch-ready': 'Dispatch Ready',
  'completed': 'Completed',
  'partially-completed': 'Partially Completed'
};

export const BACKEND_TO_FRONTEND_STATUS = {
  'Open': 'open',
  'Picking': 'picking',
  'Packed': 'packed',
  'Invoiced': 'invoiced',
  'Dispatch Ready': 'dispatch-ready',
  'Completed': 'completed',
  'Partially Completed': 'partially-completed'
};

// Table columns — base (5) and with Actions (6)
export const TABLE_COLUMNS_BASE = [
  { id: 'dealer',        label: 'Dealer' },
  { id: 'status',        label: 'Status' },
  { id: 'orderDate',     label: 'Order Date' },
  { id: 'timeInStatus',  label: 'Time in Current Status' },
  { id: 'assignedTo',    label: 'Assigned To' }
];

export const TABLE_COLUMNS_WITH_ACTIONS = [
  ...TABLE_COLUMNS_BASE,
  { id: 'actions', label: 'Actions' }
];

// Date formatting options (shared)
export const DATE_FORMAT_OPTIONS = {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit'
};
