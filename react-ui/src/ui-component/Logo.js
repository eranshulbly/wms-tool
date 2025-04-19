import React from 'react';

// material-ui
import { useTheme } from '@material-ui/styles';

/**
 * if you want to use image instead of <svg> uncomment following.
 *
 * import logoDark from './../../assets/images/logo-dark.svg';
 * import logo from './../../assets/images/logo.svg';
 *
 */

//-----------------------|| LOGO SVG ||-----------------------//

const Logo = () => {
    const theme = useTheme();
    return (
    <div style={{ fontSize: '24px', fontWeight: 'bold', color: theme.palette.primary.main }}>
        Warehub
    </div>
);

};

export default Logo;
