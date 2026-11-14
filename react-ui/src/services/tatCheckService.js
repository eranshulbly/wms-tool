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

// Analytics → Inventory Report → By Category as .xlsx: the rows on screen (filtered and
// sorted) are posted, so the file is the view. The server names the file for the
// inventory upload's date; `fallbackName` is used when the browser cannot read that name
// (a cross-origin API, as in local development).
export const exportInventoryByCategory = (rows, fallbackName) =>
  api
    .post('tat-check/inventory-by-category/export', { rows }, { responseType: 'blob' })
    .then((res) => {
      const disposition = res.headers['content-disposition'] || '';
      const match = /filename[^;=\n]*=(?:"?)([^";\n]*)/.exec(disposition);
      const href = window.URL.createObjectURL(res.data);
      const a = document.createElement('a');
      a.href = href;
      a.download = match ? match[1].trim() : fallbackName || 'In_Stock_SKUs_by_Category.xlsx';
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(href);
    });
