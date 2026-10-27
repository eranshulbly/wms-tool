import api from './api';

// PO Builder API (/api/po-builder/*) — admin only, Ebco only: the server always acts on
// the Ebco company, so no call carries a company.

const form = (fields) => {
  const fd = new FormData();
  Object.entries(fields).forEach(([k, v]) => {
    if (v !== undefined && v !== null) fd.append(k, v);
  });
  return fd;
};
const multipart = { headers: { 'Content-Type': 'multipart/form-data' } };
const data = (p) => p.then((res) => res.data);

// Download a file response and hand it to the browser, using the server's filename.
const download = (url, params, fallback) =>
  api.get(url, { params, responseType: 'blob' }).then((res) => {
    const disposition = res.headers['content-disposition'] || '';
    const match = /filename[^;=\n]*=(?:"?)([^";\n]*)/.exec(disposition);
    const href = window.URL.createObjectURL(res.data);
    const a = document.createElement('a');
    a.href = href;
    a.download = match ? match[1].trim() : fallback;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(href);
  });

// A blob error body is JSON the caller cannot read directly; turn it back into a message.
export const blobErrorMessage = async (e, fallback) => {
  try {
    const text = await e?.response?.data?.text?.();
    return JSON.parse(text).msg || fallback;
  } catch (_) {
    return e?.response?.data?.msg || fallback;
  }
};

export const errorMessage = (e, fallback) => e?.response?.data?.msg || fallback;

const poBuilderService = {
  // settings
  getSettings: () => data(api.get('po-builder/settings')),
  saveSettings: (body) => data(api.put('po-builder/settings', body)),

  // SKU master
  listMasters: () => data(api.get('po-builder/sku-masters')),
  uploadMaster: (file, name, commit) =>
    data(api.post('po-builder/sku-masters', form({ file, name, commit: commit ? '1' : '0' }), multipart)),

  // schemes
  listSchemes: () => data(api.get('po-builder/schemes')),
  uploadScheme: (file, fields, commit) =>
    data(api.post('po-builder/schemes', form({ file, ...fields, commit: commit ? '1' : '0' }), multipart)),
  getScheme: (id) => data(api.get(`po-builder/schemes/${id}`)),
  updateScheme: (id, body) => data(api.put(`po-builder/schemes/${id}`, body)),
  getMapping: (id, view, q) => data(api.get(`po-builder/schemes/${id}/mapping`, { params: { view, q } })),

  // POs
  current: () => data(api.post('po-builder/current')),
  createPo: (body) => data(api.post('po-builder/pos', body)),
  getPo: (id) => data(api.get(`po-builder/pos/${id}`)),
  updatePo: (id, body) => data(api.put(`po-builder/pos/${id}`, body)),
  deletePo: (id) => data(api.delete(`po-builder/pos/${id}`)),
  search: (id, q, group, limit) => data(api.get(`po-builder/pos/${id}/search`, { params: { q, group: group || undefined, limit } })),
  groupOptions: (id) => data(api.get(`po-builder/pos/${id}/groups`)),
  addLine: (id, skuCode, qty) => data(api.post(`po-builder/pos/${id}/lines`, { sku_code: skuCode, qty })),
  setQty: (id, lineId, qty) => data(api.put(`po-builder/pos/${id}/lines/${lineId}`, { qty })),
  deleteLine: (id, lineId) => data(api.delete(`po-builder/pos/${id}/lines/${lineId}`)),
  finalise: (id) => data(api.post(`po-builder/pos/${id}/finalise`)),
  reopen: (id) => data(api.post(`po-builder/pos/${id}/reopen`)),
  exportOrderBook: (id) => download(`po-builder/pos/${id}/export`, {}, 'Order_Book.xlsx'),

  // bulk import
  createImport: (id, { file, text, sourceTag, sheet }) =>
    data(api.post(`po-builder/pos/${id}/imports`, form({ file, text, source_tag: sourceTag, sheet }), multipart)),
  getImport: (id, importId) => data(api.get(`po-builder/pos/${id}/imports/${importId}`)),
  resolveRow: (id, importId, rowId, body) =>
    data(api.put(`po-builder/pos/${id}/imports/${importId}/rows/${rowId}`, body)),
  addImportRow: (id, importId, rowId, skuCode, qty) =>
    data(api.post(`po-builder/pos/${id}/imports/${importId}/rows/${rowId}/add`, { sku_code: skuCode, qty })),
  applyImport: (id, importId) => data(api.post(`po-builder/pos/${id}/imports/${importId}/apply`)),
  discardImport: (id, importId) => data(api.post(`po-builder/pos/${id}/imports/${importId}/discard`)),
};

export default poBuilderService;
