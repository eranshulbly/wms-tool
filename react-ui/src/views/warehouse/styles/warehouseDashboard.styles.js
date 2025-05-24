import { makeStyles } from '@material-ui/styles';

export const useWarehouseDashboardStyles = makeStyles((theme) => ({
  statusCard: {
    height: '100%',
    // Removed hover effects and cursor pointer since cards are no longer clickable
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
  dispatchCard: {
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
  formControl: {
    marginBottom: theme.spacing(2),
    minWidth: 200
  },
  orderDetailsDialog: {
    minWidth: 600
  },
  chipOpen: {
    backgroundColor: theme.palette.warning.light,
    color: theme.palette.warning.dark
  },
  chipPicking: {
    backgroundColor: theme.palette.primary.light,
    color: theme.palette.primary.dark
  },
  chipPacking: {
    backgroundColor: theme.palette.secondary.light,
    color: theme.palette.secondary.dark
  },
  chipDispatch: {
    backgroundColor: theme.palette.success.light,
    color: theme.palette.success.dark
  },
  chipCompleted: {
    backgroundColor: '#4caf50',
    color: '#ffffff'
  },
  chipPartiallyCompleted: {
    backgroundColor: '#ff9800',
    color: '#ffffff'
  },
  tableContainer: {
    maxHeight: 440,
    overflowX: 'auto'
  },
  loadingContainer: {
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    height: '100px'
  },
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
  tableRow: {
    cursor: 'pointer',
    '&:hover': {
      backgroundColor: theme.palette.action.hover
    }
  },
  filterTitle: {
    marginLeft: 16,
    color: '#666'
  }
}));