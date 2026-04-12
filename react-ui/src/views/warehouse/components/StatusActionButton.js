import React, { useState } from 'react';
import {
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Typography
} from '@material-ui/core';
import { IconArrowRight } from '@tabler/icons';

// Manual UI progression (Packed → Invoiced is only via invoice upload)
const STATUS_PROGRESSION = {
  'open':          { next: 'picking',   label: 'Start Picking' },
  'picking':       { next: 'packed',    label: 'Move to Packed' },
  'packed':        null,
  'invoiced':      null,
  'dispatch-ready': { next: 'completed', label: 'Complete Dispatch' },
  'completed':     null,
  'partially-completed': null
};

/**
 * Per-row action button that advances the order to its next status.
 * Picking → Packed prompts for number of boxes first.
 *
 * Props:
 *   order          — order object
 *   onStatusUpdate — (order, action, additionalData?) => void
 *   classes        — makeStyles classes from the parent page
 */
const StatusActionButton = ({ order, onStatusUpdate, classes }) => {
  const [boxDialogOpen, setBoxDialogOpen] = useState(false);
  const [boxCount, setBoxCount] = useState(1);

  const currentStatus = order.status?.toLowerCase().replace(/\s+/g, '-');
  const nextAction = STATUS_PROGRESSION[currentStatus];

  if (!nextAction) return null;

  const handleClick = (e) => {
    e.stopPropagation();
    if (currentStatus === 'picking') {
      setBoxCount(1);
      setBoxDialogOpen(true);
    } else if (currentStatus === 'dispatch-ready') {
      onStatusUpdate(order, 'complete-dispatch');
    } else {
      onStatusUpdate(order, nextAction.next);
    }
  };

  const handleBoxConfirm = (e) => {
    e.stopPropagation();
    const boxes = parseInt(boxCount, 10);
    if (!boxes || boxes < 1) {
      alert('Please enter a valid number of boxes (minimum 1).');
      return;
    }
    setBoxDialogOpen(false);
    onStatusUpdate(order, 'packed', { number_of_boxes: boxes });
  };

  return (
    <>
      <Button
        variant="outlined"
        color="primary"
        size="small"
        className={classes?.statusActionButton}
        onClick={handleClick}
        startIcon={<IconArrowRight size={16} />}
      >
        {nextAction.label}
      </Button>

      <Dialog
        open={boxDialogOpen}
        onClose={(e) => { e.stopPropagation(); setBoxDialogOpen(false); }}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>Number of Boxes</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="textSecondary" style={{ marginBottom: 12 }}>
            Enter the number of boxes for packing order{' '}
            <strong>{order.order_request_id}</strong>.
          </Typography>
          <TextField
            label="Number of Boxes"
            type="number"
            variant="outlined"
            fullWidth
            value={boxCount}
            onChange={(e) => setBoxCount(e.target.value)}
            inputProps={{ min: 1, step: 1 }}
            autoFocus
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={(e) => { e.stopPropagation(); setBoxDialogOpen(false); }}>
            Cancel
          </Button>
          <Button onClick={handleBoxConfirm} color="primary" variant="contained">
            Move to Packed
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
};

export default StatusActionButton;
