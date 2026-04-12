import React from 'react';
import { Grid, Box, Paper, Typography, CircularProgress } from '@material-ui/core';
import { ORDER_STATUS_DATA } from '../constants/statuses';

/**
 * Horizontal strip of per-status count pills for the dashboard overview.
 *
 * Props:
 *   statusCounts   — { [slug]: { count } }
 *   loading        — bool
 *   classes        — makeStyles classes from WarehouseDashboard
 *   allowedStatuses — string[] | null (null = show all)
 */
const CompactStatusSummary = ({ statusCounts, loading, classes, allowedStatuses }) => {
  const visibleStatuses = allowedStatuses
    ? Object.keys(ORDER_STATUS_DATA).filter((s) => allowedStatuses.includes(s))
    : Object.keys(ORDER_STATUS_DATA);

  return (
    <Grid item xs={12}>
      <Paper className={classes?.statusSummaryContainer} elevation={1}>
        <Typography variant="h6" className={classes?.statusSummaryTitle}>
          Order Status Overview
        </Typography>
        <Box className={classes?.statusSummaryContent}>
          {visibleStatuses.map((status) => {
            const statusData = ORDER_STATUS_DATA[status];
            const count = statusCounts[status]?.count || 0;

            return (
              <Box key={status} className={classes?.compactStatusItem}>
                <Box className={classes?.statusIconSmall}>
                  {React.cloneElement(statusData.icon, { size: 20 })}
                </Box>
                <Box className={classes?.statusInfo}>
                  <Typography variant="body2" className={classes?.statusLabelCompact}>
                    {statusData.label}
                  </Typography>
                  <Typography variant="h6" className={classes?.statusCountCompact}>
                    {loading ? <CircularProgress size={16} /> : count}
                  </Typography>
                </Box>
              </Box>
            );
          })}
        </Box>
      </Paper>
    </Grid>
  );
};

export default CompactStatusSummary;
