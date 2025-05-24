import { makeStyles } from '@material-ui/styles';

export const useOrderManagementStyles = makeStyles((theme) => ({
  formControl: {
    marginBottom: theme.spacing(2),
    minWidth: 200
  },
  tableContainer: {
    maxHeight: 600,
    marginTop: theme.spacing(2)
  },
  statusChip: {
    margin: theme.spacing(0.5)
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
  loadingContainer: {
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    height: '100px'
  },
  orderFilterContainer: {
    marginBottom: theme.spacing(3)
  },
  statusActionButton: {
    margin: theme.spacing(0, 0.5)
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

  // Enhanced dialog styles
  orderDetailsDialog: {
    '& .MuiDialog-paper': {
      minHeight: '70vh',
      maxHeight: '90vh'
    }
  },

  // Stepper styles
  stepperContainer: {
    marginBottom: theme.spacing(3),
    padding: theme.spacing(2),
    backgroundColor: theme.palette.background.default,
    borderRadius: theme.shape.borderRadius
  },

  // Product packing form styles
  packingFormContainer: {
    padding: theme.spacing(2)
  },
  productRow: {
    '&:nth-of-type(odd)': {
      backgroundColor: theme.palette.action.hover,
    }
  },
  quantityInput: {
    width: '80px',
    '& input': {
      textAlign: 'center'
    }
  },
  boxSelector: {
    minWidth: 120
  },

  // Box management styles
  boxContainer: {
    marginTop: theme.spacing(2),
    padding: theme.spacing(2),
    border: `1px solid ${theme.palette.divider}`,
    borderRadius: theme.shape.borderRadius,
    backgroundColor: theme.palette.background.paper
  },
  boxHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: theme.spacing(2)
  },
  boxItem: {
    marginBottom: theme.spacing(1),
    padding: theme.spacing(1),
    backgroundColor: theme.palette.background.default,
    borderRadius: theme.shape.borderRadius,
    border: `1px solid ${theme.palette.divider}`
  },
  boxTitle: {
    display: 'flex',
    alignItems: 'center',
    '& svg': {
      marginRight: theme.spacing(1)
    }
  },
  emptyBox: {
    color: theme.palette.text.secondary,
    fontStyle: 'italic'
  },

  // Enhanced box quantity management
  boxQuantityContainer: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(1),
    marginTop: theme.spacing(1)
  },
  productInBox: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: theme.spacing(1),
    backgroundColor: theme.palette.grey[50],
    borderRadius: theme.shape.borderRadius,
    marginBottom: theme.spacing(0.5)
  },
  productInBoxName: {
    flex: 1
  },
  productInBoxQuantity: {
    minWidth: '80px'
  },

  // Accordion styles for boxes
  accordionSummary: {
    backgroundColor: theme.palette.background.default,
    '&.Mui-expanded': {
      backgroundColor: theme.palette.primary.light
    }
  },

  // Summary styles
  summaryContainer: {
    padding: theme.spacing(2),
    backgroundColor: theme.palette.info.light,
    borderRadius: theme.shape.borderRadius,
    marginBottom: theme.spacing(2)
  },
  summaryItem: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: theme.spacing(1),
    '&:last-child': {
      marginBottom: 0
    }
  },
  summaryLabel: {
    fontWeight: 500
  },
  summaryValue: {
    fontWeight: 600,
    color: theme.palette.primary.main
  },

  // Dispatch summary styles
  dispatchSummary: {
    padding: theme.spacing(2),
    backgroundColor: theme.palette.success.light,
    borderRadius: theme.shape.borderRadius,
    marginBottom: theme.spacing(2)
  },
  dispatchSummaryTitle: {
    fontWeight: 600,
    marginBottom: theme.spacing(1),
    color: theme.palette.success.dark
  },

  // Validation styles
  errorText: {
    color: theme.palette.error.main,
    fontSize: '0.875rem',
    marginTop: theme.spacing(0.5)
  },
  warningText: {
    color: theme.palette.warning.main,
    fontSize: '0.875rem',
    marginTop: theme.spacing(0.5)
  },

  // Mobile responsive adjustments
  [theme.breakpoints.down('sm')]: {
    orderDetailsDialog: {
      '& .MuiDialog-paper': {
        margin: theme.spacing(1),
        width: `calc(100% - ${theme.spacing(2)}px)`,
        maxWidth: 'none'
      }
    },
    tableContainer: {
      '& .MuiTable-root': {
        minWidth: 'unset'
      }
    },
    quantityInput: {
      width: '60px'
    },
    boxSelector: {
      minWidth: 100
    }
  }
}));