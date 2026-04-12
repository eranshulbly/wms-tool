import React from 'react';
import { Chip } from '@material-ui/core';
import { STATUS_LABELS } from '../constants/statuses';
import { getStatusChipClass } from '../utils';

/**
 * Color-coded status badge.
 *
 * Props:
 *   status  — backend PascalCase or frontend slug string (e.g. 'Picking' or 'picking')
 *   classes — makeStyles classes from the parent page (must include chipXxx entries)
 */
const StatusChip = ({ status, classes }) => {
  const normalized = String(status).toLowerCase().replace(/\s+/g, '-');
  const className = classes ? classes[getStatusChipClass(normalized)] : undefined;
  const label = STATUS_LABELS[normalized] || status;

  return (
    <Chip
      label={label}
      className={className ? `${classes?.statusChip || ''} ${className}` : undefined}
      size="small"
    />
  );
};

export default StatusChip;
