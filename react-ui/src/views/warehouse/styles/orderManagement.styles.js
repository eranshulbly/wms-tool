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
  }
}));