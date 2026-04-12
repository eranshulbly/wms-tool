import api from './api';

export const getWarehouses = () =>
  api.get('warehouses').then((res) => res.data);

export const getCompanies = () =>
  api.get('companies').then((res) => res.data);
