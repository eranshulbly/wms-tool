import { useState } from 'react';

/**
 * Manages snackbar open/message/severity state.
 *
 * Usage:
 *   const { snackbar, showSnackbar, hideSnackbar } = useSnackbar();
 *   showSnackbar('Saved!', 'success');
 *
 *   <Snackbar open={snackbar.open} ...>
 *     <Alert severity={snackbar.severity}>{snackbar.message}</Alert>
 *   </Snackbar>
 */
export function useSnackbar() {
  const [snackbar, setSnackbar] = useState({
    open: false,
    message: '',
    severity: 'info'
  });

  const showSnackbar = (message, severity = 'success') => {
    setSnackbar({ open: true, message, severity });
  };

  const hideSnackbar = (event, reason) => {
    if (reason === 'clickaway') return;
    setSnackbar((s) => ({ ...s, open: false }));
  };

  return { snackbar, showSnackbar, hideSnackbar };
}
