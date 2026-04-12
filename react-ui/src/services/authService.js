import api from './api';

export const login = (email, password) =>
  api.post('users/login', { email, password });

export const logout = () =>
  api.post('users/logout');

export const register = (data) =>
  api.post('users/register', data);
