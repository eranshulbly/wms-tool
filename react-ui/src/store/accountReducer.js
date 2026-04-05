// action - state management
import { ACCOUNT_INITIALIZE, LOGIN, LOGOUT } from './actions';

// Rehydrate from localStorage on page load
const savedToken = localStorage.getItem('wms_token');
const savedUser = (() => { try { return JSON.parse(localStorage.getItem('wms_user')); } catch { return null; } })();

export const initialState = {
    token: savedToken || '',
    isLoggedIn: !!(savedToken && savedUser),
    isInitialized: true,
    user: savedUser || null
};

//-----------------------|| ACCOUNT REDUCER ||-----------------------//

const accountReducer = (state = initialState, action) => {
    switch (action.type) {
        case ACCOUNT_INITIALIZE: {
            const { isLoggedIn, user, token } = action.payload;
            if (isLoggedIn && token) {
                localStorage.setItem('wms_token', token);
                localStorage.setItem('wms_user', JSON.stringify(user));
            }
            return { ...state, isLoggedIn, isInitialized: true, token, user };
        }
        case LOGIN: {
            const { user, token } = action.payload;
            if (token) {
                localStorage.setItem('wms_token', token);
                localStorage.setItem('wms_user', JSON.stringify(user));
            }
            return { ...state, isLoggedIn: true, token: token || state.token, user };
        }
        case LOGOUT: {
            localStorage.removeItem('wms_token');
            localStorage.removeItem('wms_user');
            return { ...state, isLoggedIn: false, token: '', user: null };
        }
        default: {
            return { ...state };
        }
    }
};

export default accountReducer;
