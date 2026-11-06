import api from './api';

// TAT Check API (/api/tat-check/*) — Ebco only: the server always acts on the Ebco
// company, so no call carries a company. Lookup and status are open to any logged-in
// user; upload is admin only.

const data = (p) => p.then((res) => res.data);

export const lookupSku = (q) => data(api.get('tat-check/lookup', { params: { q } }));

export const suggestSkus = (q) => data(api.get('tat-check/suggest', { params: { q } }));

export const getFeedStatus = () => data(api.get('tat-check/status'));

export const uploadFeed = (feed, file) => {
  const fd = new FormData();
  fd.append('feed', feed);
  fd.append('file', file);
  return data(api.post('tat-check/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } }));
};
