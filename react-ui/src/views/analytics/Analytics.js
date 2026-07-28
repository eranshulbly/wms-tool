import React from 'react';
import { useHistory } from 'react-router-dom';
import { Grid, Box, Card, CardActionArea, Typography, useTheme } from '@material-ui/core';
import { IconUsers, IconArrowRight } from '@tabler/icons';

import { gridSpacing } from '../../store/constant';

// Analytics — landing page. Lists the available analytics; more get added over time.

const REPORTS = [
    {
        key: 'target-tracker',
        title: 'Target Tracker Analytics',
        description: "Sales vs targets by executive, dealer and dealer×part-group, plus part suggestions.",
        icon: IconUsers,
        path: '/analytics/sales-executives'
    }
];

const Analytics = () => {
    const theme = useTheme();
    const history = useHistory();

    return (
        <Grid container spacing={gridSpacing}>
            <Grid item xs={12}>
                <Typography variant="h2" sx={{ fontWeight: 700, mb: 0.5 }}>
                    Analytics
                </Typography>
                <Typography variant="body1" color="textSecondary">
                    Dashboards and reports across orders, sales and dealers.
                </Typography>
            </Grid>

            {REPORTS.map((r) => {
                const Icon = r.icon;
                return (
                    <Grid item xs={12} sm={6} md={4} key={r.key}>
                        <Card
                            elevation={0}
                            sx={{
                                height: '100%',
                                border: `1px solid ${theme.palette.divider}`,
                                borderTop: `3px solid ${theme.palette.error.dark}`,
                                borderRadius: 2,
                                transition: 'box-shadow .2s ease, transform .2s ease',
                                '&:hover': { boxShadow: theme.shadows[6], transform: 'translateY(-2px)' }
                            }}
                        >
                            <CardActionArea
                                onClick={() => history.push(r.path)}
                                sx={{ height: '100%', p: 3, alignItems: 'flex-start' }}
                            >
                                <Box
                                    sx={{
                                        width: 48,
                                        height: 48,
                                        borderRadius: 2,
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        backgroundColor: theme.palette.error.light,
                                        color: theme.palette.error.dark,
                                        mb: 2
                                    }}
                                >
                                    <Icon stroke={1.7} size={26} />
                                </Box>
                                <Typography variant="h4" sx={{ fontWeight: 600, mb: 1 }}>
                                    {r.title}
                                </Typography>
                                <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
                                    {r.description}
                                </Typography>
                                <Box sx={{ display: 'flex', alignItems: 'center', color: theme.palette.error.dark, fontWeight: 600 }}>
                                    <Typography variant="body2" sx={{ fontWeight: 600, mr: 0.5 }}>
                                        Open
                                    </Typography>
                                    <IconArrowRight size={16} stroke={2} />
                                </Box>
                            </CardActionArea>
                        </Card>
                    </Grid>
                );
            })}
        </Grid>
    );
};

export default Analytics;
