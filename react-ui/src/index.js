import React from 'react';
import ReactDOM from 'react-dom';
import axios from 'axios';
import { BrowserRouter } from 'react-router-dom';
import { Provider } from 'react-redux';
import { PersistGate } from 'redux-persist/integration/react';
import { store, persister } from './store';
import * as serviceWorker from './serviceWorker';
import App from './App';
import config from './config';
import { LOGOUT } from './store/actions';
import './assets/scss/style.scss';

// Attach JWT token to every axios request automatically
axios.interceptors.request.use((cfg) => {
    const token = localStorage.getItem('wms_token');
    if (token) {
        cfg.headers['authorization'] = token;
    }
    return cfg;
});

// Auto-logout on 401 (token expired or invalid)
// Dispatch LOGOUT to Redux so both localStorage keys AND redux-persist storage
// are cleared together, preventing stale rehydration on the next page load.
axios.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response && error.response.status === 401) {
            store.dispatch({ type: LOGOUT });
        }
        return Promise.reject(error);
    }
);

//-----------------------|| REACT DOM RENDER  ||-----------------------//

ReactDOM.render(
    <Provider store={store}>
        <PersistGate loading={null} persistor={persister}>
            <BrowserRouter basename={config.basename}>
                <App />
            </BrowserRouter>
        </PersistGate>
    </Provider>,
    document.getElementById('root')
);

// If you want your app to work offline and load faster, you can change
// unregister() to register() below. Note this comes with some pitfalls.
// Learn more about service workers: https://bit.ly/CRA-PWA
serviceWorker.unregister();
