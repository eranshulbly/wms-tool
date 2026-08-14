import axios from 'axios';
import config from '../config';
import { store } from '../store';
import { LOGOUT } from '../store/actions';

/**
 * Single shared axios instance with auth interceptor.
 * All domain services import this instead of creating their own axios instances.
 */
const api = axios.create({ baseURL: config.API_SERVER });

api.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('wms_token');
  if (token) {
    cfg.headers = cfg.headers || {};
    cfg.headers.Authorization = `Bearer ${token}`;
  }
  return cfg;
});

// Auto-logout on 401 (expired or invalid token). Mirrors the global axios
// interceptor in index.js — without this, a service call like getWarehouses()
// would 401 silently and the caller would just render empty (e.g. blank filter
// dropdowns) instead of the user being sent to log in again.
// An expired token gets a 401, but a MISSING one gets a 400 ("Valid JWT token is
// missing") — and a session whose token has gone is exactly as unauthenticated as one
// whose token has expired. Treating only 401 as logout leaves the app looking signed in
// while every call fails.
const isUnauthenticated = (error) => {
    const res = error && error.response;
    if (!res) return false;
    if (res.status === 401) return true;
    return res.status === 400 && /token is missing/i.test(res.data?.msg || '');
};

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (isUnauthenticated(error)) {
      store.dispatch({ type: LOGOUT });
    }
    return Promise.reject(error);
  }
);

export default api;
