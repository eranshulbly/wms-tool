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

// Auto-logout when a call comes back unauthenticated.
// Dispatch LOGOUT to Redux so both localStorage keys AND redux-persist storage
// are cleared together, preventing stale rehydration on the next page load.
//
// An expired token returns 401; a MISSING one returns 400 ("Valid JWT token is missing").
// Both mean the session is over, so both log out — otherwise the app keeps rendering as
// if signed in while every request fails.
axios.interceptors.response.use(
    (response) => response,
    (error) => {
        const res = error && error.response;
        const unauthenticated =
            res && (res.status === 401 ||
                    (res.status === 400 && /token is missing/i.test(res.data?.msg || '')));
        if (unauthenticated) {
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
