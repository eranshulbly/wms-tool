import React from 'react';
import { useSelector } from 'react-redux';
import { useHistory } from 'react-router-dom';

import {
    Grid,
    Card,
    CardActionArea,
    Box,
    Typography,
    useTheme
} from '@material-ui/core';
import {
    IconTruckDelivery,
    IconFileInvoice,
    IconClipboardList,
    IconChartBar,
    IconSettings,
    IconArrowRight
} from '@tabler/icons';

// -----------------------|| SYSTEM LAUNCHER (tile home) ||-----------------------//

const Launcher = () => {
    const theme = useTheme();
    const history = useHistory();
    const { user } = useSelector((state) => state.account);

    const isAdmin = user?.role === 'admin';
    const isPartConvertor = user?.role === 'part_convertor';
    const perms = user?.permissions || {};

    // The part convertor is scoped to Submitted Orders only.
    const submittedTile = {
        key: 'submitted',
        title: 'Submitted Orders',
        description: 'Review submitted (photo / app) orders and build part-convertor sheets.',
        icon: IconClipboardList,
        color: theme.palette.success.dark,
        tint: theme.palette.success.light,
        path: '/warehouse/submitted-orders',
        show: true
    };

    // Tiles are gated by the same permission flags the route guards use, so a
    // user only sees the systems they can actually open.
    const allTiles = [
        {
            key: 'orders',
            title: 'Order Tracking',
            description: 'Upload orders, then move them through picking, packing, invoicing and dispatch.',
            icon: IconTruckDelivery,
            color: theme.palette.success.dark,
            tint: theme.palette.success.light,
            path: '/dashboard/default',
            show: true
        },
        {
            key: 'eway',
            title: 'E-Way Bill',
            description: 'Configure routes and manifests and generate bulk e-way-bill JSON.',
            icon: IconFileInvoice,
            color: theme.palette.secondary.dark,
            tint: theme.palette.secondary.light,
            path: '/warehouse/eway-bill',
            show: isAdmin || perms.eway_bill_filling === true || perms.eway_bill_admin === true
        },
        {
            key: 'supply',
            title: 'Supply Sheet',
            description: 'Generate dealer/route supply sheets as printable PDFs.',
            icon: IconClipboardList,
            color: theme.palette.primary.dark,
            tint: theme.palette.primary.light,
            path: '/warehouse/supply-sheet',
            show: isAdmin || perms.supply_sheet === true
        },
        {
            key: 'analytics',
            title: 'Analytics',
            description: 'Target Tracker — sales against target by executive, dealer and part.',
            icon: IconChartBar,
            color: theme.palette.error.dark,
            tint: theme.palette.error.light,
            path: '/analytics/target-tracker',
            // Visible to everyone for now; gate with a permission when analytics grow.
            show: true
        },
        {
            key: 'admin',
            title: 'Admin',
            description: 'Manage users, roles, dealers, products and uploaded batches.',
            icon: IconSettings,
            color: theme.palette.warning.dark,
            tint: theme.palette.warning.light,
            path: '/admin-controls',
            show: isAdmin
        }
    ];

    // Part convertor sees only Submitted Orders; everyone else sees their permitted systems.
    const tiles = isPartConvertor ? [submittedTile] : allTiles.filter((t) => t.show);

    return (
        <Box>
            <Typography variant="h2" sx={{ fontWeight: 700, mb: 0.5 }}>
                Welcome back, {user?.username || 'there'}
            </Typography>
            <Typography variant="body1" color="textSecondary" sx={{ mb: 3 }}>
                Signed in as {user?.role || 'user'}. Choose a system to get started.
            </Typography>

            <Grid container spacing={3}>
                {tiles.map((tile) => {
                    const Icon = tile.icon;
                    return (
                        <Grid item xs={12} sm={6} md={4} key={tile.key}>
                            <Card
                                elevation={0}
                                sx={{
                                    height: '100%',
                                    border: `1px solid ${theme.palette.divider}`,
                                    borderTop: `3px solid ${tile.color}`,
                                    borderRadius: 2,
                                    transition: 'box-shadow .2s ease, transform .2s ease',
                                    '&:hover': {
                                        boxShadow: theme.shadows[6],
                                        transform: 'translateY(-2px)'
                                    }
                                }}
                            >
                                <CardActionArea
                                    onClick={() => history.push(tile.path)}
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
                                            backgroundColor: tile.tint,
                                            color: tile.color,
                                            mb: 2
                                        }}
                                    >
                                        <Icon stroke={1.7} size={26} />
                                    </Box>
                                    <Typography variant="h4" sx={{ fontWeight: 600, mb: 1 }}>
                                        {tile.title}
                                    </Typography>
                                    <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
                                        {tile.description}
                                    </Typography>
                                    <Box sx={{ display: 'flex', alignItems: 'center', color: tile.color, fontWeight: 600 }}>
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
        </Box>
    );
};

export default Launcher;
