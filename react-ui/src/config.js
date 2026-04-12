const BACKEND_SERVER = process.env.REACT_APP_BACKEND_SERVER || 'http://localhost:5000/api/';

const config = {
    basename: '',
    defaultPath: '/dashboard/default',
    fontFamily: `'Roboto', sans-serif`,
    borderRadius: 12,
    API_SERVER: BACKEND_SERVER,

    // Deployment metadata — injected at build time via env vars
    APP_VERSION: process.env.REACT_APP_VERSION || '1.0.0',
    APP_ENV: process.env.REACT_APP_ENV || 'development',
};

export default config;
