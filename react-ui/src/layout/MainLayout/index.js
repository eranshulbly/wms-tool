import PropTypes from 'prop-types';
import React from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useLocation } from 'react-router-dom';

// material-ui
import { makeStyles, useTheme } from '@material-ui/styles';
import { AppBar, CssBaseline, Toolbar, useMediaQuery } from '@material-ui/core';

// third-party
import clsx from 'clsx';

// project imports
import Breadcrumbs from './../../ui-component/extended/Breadcrumbs';
import Header from './Header';
import Sidebar from './Sidebar';
import navigation from './../../menu-items';
import { drawerWidth } from '../../store/constant';
import { SET_MENU } from './../../store/actions';
import { WarehouseProvider } from '../../context/WarehouseContext';

// assets
import { IconChevronRight } from '@tabler/icons';

// style constant
const useStyles = makeStyles((theme) => ({
    root: {
        display: 'flex'
    },
    appBar: {
        backgroundColor: theme.palette.background.default
    },
    appBarWidth: {
        transition: theme.transitions.create('width'),
        backgroundColor: theme.palette.background.default
    },
    content: {
        ...theme.typography.mainContent,
        borderBottomLeftRadius: 0,
        borderBottomRightRadius: 0,
        transition: theme.transitions.create('margin', {
            easing: theme.transitions.easing.sharp,
            duration: theme.transitions.duration.leavingScreen
        }),
        [theme.breakpoints.up('md')]: {
            marginLeft: -(drawerWidth - 20),
            width: `calc(100% - ${drawerWidth}px)`
        },
        [theme.breakpoints.down('md')]: {
            marginLeft: '20px',
            width: `calc(100% - ${drawerWidth}px)`,
            padding: '16px'
        },
        [theme.breakpoints.down('sm')]: {
            marginLeft: '10px',
            width: `calc(100% - ${drawerWidth}px)`,
            padding: '16px',
            marginRight: '10px'
        }
    },
    contentShift: {
        transition: theme.transitions.create('margin', {
            easing: theme.transitions.easing.easeOut,
            duration: theme.transitions.duration.enteringScreen
        }),
        marginLeft: 0,
        borderBottomLeftRadius: 0,
        borderBottomRightRadius: 0,
        [theme.breakpoints.down('md')]: {
            marginLeft: '20px'
        },
        [theme.breakpoints.down('sm')]: {
            marginLeft: '10px'
        }
    },
    // Launcher (/home): no sidebar, full-width content.
    contentHome: {
        ...theme.typography.mainContent,
        borderBottomLeftRadius: 0,
        borderBottomRightRadius: 0,
        width: '100%',
        marginLeft: 0,
        [theme.breakpoints.up('md')]: {
            marginLeft: 0,
            width: '100%'
        },
        [theme.breakpoints.down('md')]: {
            marginLeft: 0,
            width: '100%',
            padding: '16px'
        },
        [theme.breakpoints.down('sm')]: {
            marginLeft: 0,
            width: '100%',
            padding: '16px'
        }
    }
}));

//-----------------------|| MAIN LAYOUT ||-----------------------//

const MainLayout = ({ children }) => {
    const classes = useStyles();
    const theme = useTheme();
    const matchDownMd = useMediaQuery(theme.breakpoints.down('md'));
    const { pathname } = useLocation();

    // The launcher is a chooser screen — no sidebar, full-width tiles.
    const isHome = pathname === '/home';

    // Handle left drawer
    const leftDrawerOpened = useSelector((state) => state.customization.opened);
    const dispatch = useDispatch();
    const handleLeftDrawerToggle = () => {
        dispatch({ type: SET_MENU, opened: !leftDrawerOpened });
    };

    React.useEffect(() => {
        dispatch({ type: SET_MENU, opened: !matchDownMd });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [matchDownMd]);

    return (
        <WarehouseProvider>
            <div className={classes.root}>
                <CssBaseline />
                {/* header */}
                <AppBar
                    enableColorOnDark
                    position="fixed"
                    color="inherit"
                    elevation={0}
                    className={isHome || leftDrawerOpened ? classes.appBar : classes.appBarWidth}
                >
                    <Toolbar>
                        <Header handleLeftDrawerToggle={handleLeftDrawerToggle} hideMenuButton={isHome} />
                    </Toolbar>
                </AppBar>

                {/* drawer — hidden on the launcher */}
                {!isHome && <Sidebar drawerOpen={leftDrawerOpened} drawerToggle={handleLeftDrawerToggle} />}

                {/* main content */}
                <main
                    className={
                        isHome
                            ? classes.contentHome
                            : clsx([
                                  classes.content,
                                  {
                                      [classes.contentShift]: leftDrawerOpened
                                  }
                              ])
                    }
                >
                    {/* breadcrumb */}
                    <Breadcrumbs separator={IconChevronRight} navigation={navigation} icon title rightAlign />
                    <div>{children}</div>
                </main>
            </div>
        </WarehouseProvider>
    );
};

MainLayout.propTypes = {
    children: PropTypes.node
};

export default MainLayout;
