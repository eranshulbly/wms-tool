import api from './api';

// Target Tracker API. Every number on that screen comes from these four calls; nothing
// is computed client-side except formatting and each table's first-column search.

const listParams = (params, key, values) => {
  if (values && values.length) params[key] = values.join(',');
};

const scopeParams = ({ companyId, months, exec, dealer, group, part }) => {
  const p = { company_id: companyId };
  listParams(p, 'months', months);
  listParams(p, 'exec', exec);
  listParams(p, 'dealer', dealer);
  listParams(p, 'group', group);
  listParams(p, 'part', part);
  return p;
};

export const getCompanies = () => api.get('target-tracker/companies').then((r) => r.data);

export const getMonths = (companyId) =>
  api.get('target-tracker/months', { params: { company_id: companyId } }).then((r) => r.data);

export const getDashboard = (scope) =>
  api.get('target-tracker/dashboard', { params: scopeParams(scope) }).then((r) => r.data);

export const getDetail = (scope, key, mode) =>
  api.get('target-tracker/detail', { params: { ...scopeParams(scope), key, mode } }).then((r) => r.data);
