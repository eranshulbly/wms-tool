import {
  IconPackage,
  IconTruckDelivery,
  IconBoxSeam,
  IconClipboardList,
  IconUxCircle,
  IconClipboardCheck
} from '@tabler/icons';

// Order status configuration
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
  packing: {
    icon: <IconBoxSeam size={42} color="#9c27b0" />,
    label: 'Packing',
    chipClass: 'chipPacking'
  },
  'dispatch-ready': { // Changed from 'dispatch'
    icon: <IconTruckDelivery size={42} color="#2e7d32" />,
    label: 'Dispatch Ready',
    chipClass: 'chipDispatchReady' // Changed class name
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

// Status filter options
export const STATUS_FILTER_OPTIONS = [
  { value: 'all', label: 'All Orders' },
  { value: 'open', label: 'Open Orders' },
  { value: 'picking', label: 'Picking' },
  { value: 'packing', label: 'Packing' },
  { value: 'dispatch-ready', label: 'Dispatch Ready' }, // Changed from 'dispatch'
  { value: 'completed', label: 'Completed' },
  { value: 'partially-completed', label: 'Partially Completed' }
];

// Table column configuration
export const TABLE_COLUMNS = [
  { id: 'dealer', label: 'Dealer' },
  { id: 'status', label: 'Status' },
  { id: 'orderDate', label: 'Order Date' },
  { id: 'timeInStatus', label: 'Time in Current Status' },
  { id: 'assignedTo', label: 'Assigned To' }
];

// Date formatting options
export const DATE_FORMAT_OPTIONS = {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit'
};