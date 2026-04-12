// action - state management
import { ACCOUNT_INITIALIZE, LOGIN, LOGOUT } from './actions';

// Bug 26 fix: check JWT expiry on rehydration so an expired token in localStorage
// doesn't restore an authenticated session on page load.
const _isTokenValid = (token) => {
    if (!token) return false;
    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        return payload.exp && payload.exp * 1000 > Date.now();
    } catch {
        return false;
    }
};

// Rehydrate from localStorage on page load
const savedToken = localStorage.getItem('wms_token');
const savedUser = (() => { try { return JSON.parse(localStorage.getItem('wms_user')); } catch { return null; } })();
const _tokenValid = _isTokenValid(savedToken);

// Clear stale auth data if the token has expired
if (savedToken && !_tokenValid) {
    localStorage.removeItem('wms_token');
    localStorage.removeItem('wms_user');
}

export const initialState = {
    token: _tokenValid ? savedToken : '',
    isLoggedIn: !!(savedToken && savedUser && _tokenValid),
    isInitialized: true,
    user: _tokenValid ? savedUser : null
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
