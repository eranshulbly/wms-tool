import axios from 'axios';
import config from '../config';

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

export default api;
