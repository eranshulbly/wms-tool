import { makeStyles } from '@material-ui/styles';

export const useWarehouseDashboardStyles = makeStyles((theme) => ({
  // Original status card styles (kept for backwards compatibility)
  statusCard: {
    height: '100%',
  },
  openCard: {
    borderTop: `5px solid ${theme.palette.warning.main}`
  },
  pickingCard: {
    borderTop: `5px solid ${theme.palette.primary.main}`
  },
  packingCard: {
    borderTop: `5px solid ${theme.palette.secondary.main}`
  },
  dispatchReadyCard: {
    borderTop: `5px solid ${theme.palette.success.main}`
  },
  completedCard: {
    borderTop: `5px solid #4caf50`
  },
  partiallyCompletedCard: {
    borderTop: `5px solid #ff9800`
  },
  iconContainer: {
    backgroundColor: theme.palette.background.default,
    padding: theme.spacing(2),
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: theme.spacing(2)
  },
  orderCount: {
    fontSize: '2rem',
    fontWeight: 600,
    marginBottom: theme.spacing(1)
  },
  statusLabel: {
    fontSize: '1.25rem',
    fontWeight: 500
  },

  // NEW COMPACT STATUS SUMMARY STYLES
  statusSummaryContainer: {
    padding: theme.spacing(2),
    backgroundColor: theme.palette.background.paper,
    border: `1px solid ${theme.palette.divider}`,
    borderRadius: theme.shape.borderRadius,
  },
  statusSummaryTitle: {
    marginBottom: theme.spacing(2),
    fontWeight: 600,
    color: theme.palette.text.primary,
  },
  statusSummaryContent: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: theme.spacing(2),
    alignItems: 'center',
  },
  compactStatusItem: {
    display: 'flex',
    alignItems: 'center',
    padding: theme.spacing(1),
    backgroundColor: theme.palette.background.default,
    borderRadius: theme.shape.borderRadius,
    minWidth: 140,
    border: `1px solid ${theme.palette.divider}`,
  },
  statusIconSmall: {
    marginRight: theme.spacing(1),
    display: 'flex',
    alignItems: 'center',
  },
  statusInfo: {
    display: 'flex',
    flexDirection: 'column',
  },
  statusLabelCompact: {
    fontSize: '0.75rem',
    color: theme.palette.text.secondary,
    lineHeight: 1.2,
  },
  statusCountCompact: {
    fontSize: '1.25rem',
    fontWeight: 700,
    color: theme.palette.text.primary,
    lineHeight: 1,
  },

  // HORIZONTAL STATUS BAR STYLES
  horizontalStatusCard: {
    boxShadow: 'none',
    border: `1px solid ${theme.palette.divider}`,
  },
  horizontalStatusContent: {
    padding: `${theme.spacing(1.5)}px !important`,
  },
  statusBarTitle: {
    fontWeight: 600,
    marginBottom: theme.spacing(1),
    color: theme.palette.text.primary,
  },
  horizontalStatusContainer: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: theme.spacing(1),
    alignItems: 'center',
  },
  horizontalStatusItem: {
    // Each chip item styling handled by Material-UI Chip component
  },

  // Form controls
  formControl: {
    marginBottom: theme.spacing(2),
    minWidth: 200
  },

  // Dialog styles
  orderDetailsDialog: {
    minWidth: 600
  },

  // Status chip styles
  chipOpen: {
    backgroundColor: theme.palette.warning.light,
    color: theme.palette.warning.dark,
    '& .MuiChip-icon': {
      color: theme.palette.warning.dark,
    }
  },
  chipPicking: {
    backgroundColor: theme.palette.primary.light,
    color: theme.palette.primary.dark,
    '& .MuiChip-icon': {
      color: theme.palette.primary.dark,
    }
  },
  chipPacking: {
    backgroundColor: theme.palette.secondary.light,
    color: theme.palette.secondary.dark,
    '& .MuiChip-icon': {
      color: theme.palette.secondary.dark,
    }
  },
  chipDispatchReady: {
    backgroundColor: theme.palette.success.light,
    color: theme.palette.success.dark,
    '& .MuiChip-icon': {
      color: theme.palette.success.dark,
    }
  },
  chipCompleted: {
    backgroundColor: '#4caf50',
    color: '#ffffff',
    '& .MuiChip-icon': {
      color: '#ffffff',
    }
  },
  chipPartiallyCompleted: {
    backgroundColor: '#ff9800',
    color: '#ffffff',
    '& .MuiChip-icon': {
      color: '#ffffff',
    }
  },

  // Table styles
  tableContainer: {
    maxHeight: 600, // Increased height since status cards are now compact
    overflowX: 'auto'
  },
  loadingContainer: {
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    height: '100px'
  },
  tableRow: {
    cursor: 'pointer',
    '&:hover': {
      backgroundColor: theme.palette.action.hover
    }
  },
  filterTitle: {
    marginLeft: 16,
    color: '#666'
  },

  // Dialog content styles
  statsSummary: {
    marginBottom: theme.spacing(3),
    padding: theme.spacing(2),
    backgroundColor: theme.palette.background.default,
    borderRadius: theme.shape.borderRadius
  },
  summaryItem: {
    display: 'flex',
    alignItems: 'center',
    marginRight: theme.spacing(3)
  },
  detailsHeader: {
    display: 'flex',
    alignItems: 'center',
    marginBottom: theme.spacing(2)
  },
  orderIcon: {
    marginRight: theme.spacing(1)
  },
  infoSection: {
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(2)
  },
  infoGrid: {
    marginBottom: theme.spacing(1)
  },
  infoLabel: {
    fontWeight: 500,
    color: theme.palette.grey[700]
  },
  infoValue: {
    fontWeight: 400
  },
  timelineItem: {
    padding: theme.spacing(2),
    borderLeft: `2px solid ${theme.palette.primary.main}`,
    marginLeft: theme.spacing(2),
    position: 'relative',
    '&:before': {
      content: '""',
      position: 'absolute',
      left: -8,
      top: 24,
      width: 14,
      height: 14,
      borderRadius: '50%',
      backgroundColor: theme.palette.primary.main
    }
  },

  // Responsive design
  [theme.breakpoints.down('md')]: {
    compactStatusItem: {
      minWidth: 120,
    },
    statusSummaryContent: {
      justifyContent: 'center',
    },
    horizontalStatusContainer: {
      justifyContent: 'center',
    }
  },

  [theme.breakpoints.down('sm')]: {
    compactStatusItem: {
      minWidth: '100%',
      justifyContent: 'space-between',
    },
    statusSummaryContent: {
      flexDirection: 'column',
      gap: theme.spacing(1),
    }
  }
}));