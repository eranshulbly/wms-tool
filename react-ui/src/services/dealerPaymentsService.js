import api from './api';

// Dealer Payment Tracker API (/api/dealer-payments/*) — the server always acts on the
// tracker's company (one per instance), so no call carries a company. Admin only on Ebco.

const data = (p) => p.then((res) => res.data);
const MULTIPART = { headers: { 'Content-Type': 'multipart/form-data' } };

// readCheques: read wareops afresh — only when the tile is opened.
export const getScreen = (includeReviewed = false, readCheques = false) =>
  data(api.get('dealer-payments/screen', {
    params: { ...(includeReviewed ? { reviewed: 1 } : {}), ...(readCheques ? { cheques: 1 } : {}) },
  }));

export const getDealers = () => data(api.get('dealer-payments/dealers'));

// feed: 'outstanding' (Export 1) | 'receipts' (Export 2, Receipt Register)
export const uploadTallyExport = (feed, file) => {
  const fd = new FormData();
  fd.append('feed', feed);
  fd.append('file', file);
  return data(api.post('dealer-payments/upload', fd, MULTIPART));
};

export const getPayments = (status) => data(api.get('dealer-payments/payments', { params: status ? { status } : {} }));

export const logPayment = (fields, proof) => {
  const fd = new FormData();
  Object.entries(fields).forEach(([k, v]) => fd.append(k, v ?? ''));
  if (proof) fd.append('proof', proof);
  return data(api.post('dealer-payments/payments', fd, MULTIPART));
};

export const cancelPayment = (id) => data(api.post(`dealer-payments/payments/${id}/cancel`));

export const getProof = (id) =>
  api.get(`dealer-payments/payments/${id}/proof`, { responseType: 'blob' }).then((res) => res.data);

export const setReviewed = (id, reviewed, note) => data(api.put(`dealer-payments/manual-checks/${id}`, { reviewed, note }));

export const reprocess = () => data(api.post('dealer-payments/process'));

export const errMsg = (e, fallback) => e?.response?.data?.msg || e?.message || fallback;

// One dealer in detail: summary, pending bills (with Tally voucher lines), payments, cheques.
export const getDealerDetail = (dealerId) => data(api.get(`dealer-payments/dealers/${encodeURIComponent(dealerId)}`));

// Saves a download from the API in the browser, under the name the server gives it.
const saveFrom = async (path, params, fallback) => {
  let res;
  try {
    res = await api.get(path, { params, responseType: 'blob' });
  } catch (e) {
    // An error comes back as a blob too: read its JSON message.
    const blob = e?.response?.data;
    if (blob instanceof Blob) {
      try {
        e.response.data = JSON.parse(await blob.text());
      } catch (_) { /* not JSON */ }
    }
    throw e;
  }
  const cd = res.headers['content-disposition'] || '';
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  const name = m ? decodeURIComponent(m[1]) : fallback;
  const url = URL.createObjectURL(res.data);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

// The Tally-style Outstanding workbook.
export const downloadOutstanding = () => saveFrom('dealer-payments/export/outstanding', {}, 'Dealer Outstanding.xlsx');

// Beat-wise: each sales executive's dealers (Beat Outstanding's Executive Beats).
export const getBeats = () => data(api.get('dealer-payments/beats'));
// One executive's file (se = name, or 'Unassigned'); without se, all of them as a .zip.
export const downloadBeatFile = (se) =>
  saveFrom('dealer-payments/export/beats', se ? { se } : {}, se ? `${se} Outstanding.xlsx` : 'Beat-wise Outstanding.zip');

// Executive Beats (Dealer Payments' own executive -> beat table, the User Beats list).
export const getExecBeats = () => data(api.get('dealer-payments/exec-beats'));
// Replaces the whole table.
export const saveExecBeats = (rows) => data(api.put('dealer-payments/exec-beats', { rows }));
// Reads a User / Beat file into rows for the table — nothing is saved until saveExecBeats.
export const parseExecBeatsFile = (file) => {
  const fd = new FormData();
  fd.append('file', file);
  return data(api.post('dealer-payments/exec-beats/parse', fd, { headers: { 'Content-Type': 'multipart/form-data' } }));
};

// The last upload of each Tally file (Outstanding page).
export const getUploads = () => data(api.get('dealer-payments/uploads'));
