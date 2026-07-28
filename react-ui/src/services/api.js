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
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      store.dispatch({ type: LOGOUT });
    }
    return Promise.reject(error);
  }
);

export default api;
