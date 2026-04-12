import React from 'react';
import { Grid, Card, CardContent, Box, Typography, CircularProgress } from '@material-ui/core';
import { ORDER_STATUS_DATA } from '../constants/statuses';

/**
 * Legacy per-status card widget. Kept for backward compatibility.
 *
 * Props:
 *   status   — frontend slug key
 *   count    — number
 *   loading  — bool
 *   classes  — makeStyles classes from WarehouseDashboard
 */
const StatusCard = ({ status, count, loading, classes }) => {
  const statusData = ORDER_STATUS_DATA[status];
  const cardClass = `${classes?.statusCard || ''} ${classes?.[`${status}Card`] || ''}`;

  return (
    <Grid item xs={12} sm={6} md={6} lg={3}>
      <Card className={cardClass}>
        <CardContent>
          <Box display="flex" alignItems="center">
            <Box className={classes?.iconContainer}>
              {statusData?.icon}
            </Box>
            <Box>
              <Typography variant="h3" className={classes?.orderCount}>
                {loading ? <CircularProgress size={30} /> : (count || 0)}
              </Typography>
              <Typography variant="subtitle1" className={classes?.statusLabel}>
                {statusData?.label}
              </Typography>
            </Box>
          </Box>
        </CardContent>
      </Card>
    </Grid>
  );
};

export default StatusCard;
