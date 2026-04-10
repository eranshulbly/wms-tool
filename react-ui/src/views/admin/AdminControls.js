import React, { useState } from 'react';
import {
    Grid,
    Typography,
    Tabs,
    Tab,
    Box,
    Paper,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconTrash } from '@tabler/icons';

import DeleteUploads from './tabs/DeleteUploads';

// ---------------------------------------------------------------------------
// Tab registry — add future admin tabs here only.
// ---------------------------------------------------------------------------
const TABS = [
    {
        id:        'delete-uploads',
        label:     'Delete Uploads',
        icon:      <IconTrash size={16} />,
        component: DeleteUploads,
    },
    // Future example:
    // { id: 'user-management', label: 'User Management', icon: <IconUsers size={16} />, component: UserManagement },
];

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------
const useStyles = makeStyles((theme) => ({
    pageTitle: {
        marginBottom: theme.spacing(2),
        fontWeight:   600,
    },
    tabsWrapper: {
        borderBottom: `1px solid ${theme.palette.divider}`,
        marginBottom: theme.spacing(2),
    },
    tab: {
        textTransform: 'none',
        minWidth:      120,
        fontWeight:    500,
    },
    tabPanel: {
        padding: theme.spacing(0),
    },
}));

// ---------------------------------------------------------------------------
// TabPanel
// ---------------------------------------------------------------------------
function TabPanel({ children, activeIndex, index }) {
    return activeIndex === index ? (
        <Box role="tabpanel" id={`admin-tabpanel-${index}`} aria-labelledby={`admin-tab-${index}`}>
            {children}
        </Box>
    ) : null;
}

// ---------------------------------------------------------------------------
// AdminControls
// ---------------------------------------------------------------------------
const AdminControls = () => {
    const classes = useStyles();
    const [activeTab, setActiveTab] = useState(0);

    return (
        <Grid container spacing={2}>
            <Grid item xs={12}>
                <Typography variant="h3" className={classes.pageTitle}>
                    Admin Controls
                </Typography>
            </Grid>

            <Grid item xs={12}>
                <Paper elevation={0} variant="outlined">
                    <Box className={classes.tabsWrapper}>
                        <Tabs
                            value={activeTab}
                            onChange={(_, newVal) => setActiveTab(newVal)}
                            indicatorColor="primary"
                            textColor="primary"
                        >
                            {TABS.map((tab, idx) => (
                                <Tab
                                    key={tab.id}
                                    className={classes.tab}
                                    label={
                                        <Box display="flex" alignItems="center" style={{ gap: 6 }}>
                                            {tab.icon}
                                            {tab.label}
                                        </Box>
                                    }
                                    id={`admin-tab-${idx}`}
                                    aria-controls={`admin-tabpanel-${idx}`}
                                />
                            ))}
                        </Tabs>
                    </Box>

                    <Box className={classes.tabPanel}>
                        {TABS.map((tab, idx) => (
                            <TabPanel key={tab.id} activeIndex={activeTab} index={idx}>
                                <tab.component />
                            </TabPanel>
                        ))}
                    </Box>
                </Paper>
            </Grid>
        </Grid>
    );
};

export default AdminControls;
