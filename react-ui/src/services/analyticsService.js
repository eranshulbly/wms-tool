import api from './api';

// Sales-executive analytics, computed from the Busy sales data (current month).
export const getSalesExecutives = () =>
  api.get('analytics/sales-executives').then((res) => res.data);

export const getSalesExecutiveDetail = (userId) =>
  api.get(`analytics/sales-executives/${userId}`).then((res) => res.data);

// Filter options for the sales explorer (executives, dealers, part groups, parts).
export const getAnalyticsFilters = () => api.get('analytics/filters').then((res) => res.data);

// Part suggestions for a dealer visit (company part-qty targets + dealer/peer history).
export const getDealerSuggestions = (dealerId) =>
  api.get('analytics/dealer-suggestions', { params: { dealer_id: dealerId } }).then((res) => res.data);

// Filtered sales analytics — summary + breakdowns by executive / dealer / part group / part.
export const getSalesAnalytics = (filters = {}) => {
  const params = {};
  if (filters.executive_id) params.executive_id = filters.executive_id;
  if (filters.dealer_id) params.dealer_id = filters.dealer_id;
  if (filters.part_group) params.part_group = filters.part_group;
  if (filters.part) params.part = filters.part;
  if (filters.period) params.period = filters.period;
  return api.get('analytics/sales', { params }).then((res) => res.data);
};
