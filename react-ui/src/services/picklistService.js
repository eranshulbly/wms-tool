import api from './api';

/**
 * Import one pick-list PDF.
 *
 * One file per request on purpose: nginx caps request bodies at 12M and the API runs
 * a single gunicorn process, so posting a whole batch at once would either 413 or
 * hold the only worker for the duration. The upload page calls this in sequence and
 * reports each file's outcome as it lands.
 *
 * Resolves with the response body whether the import succeeded or failed, so the
 * caller can show a per-file reason rather than a generic error.
 */
export const uploadPicklist = (file, warehouseId, companyId) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('warehouse_id', warehouseId);
  formData.append('company_id', companyId);

  return api
    .post('picklists/upload', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
    .then((res) => res.data)
    .catch((err) => err?.response?.data || { success: false, msg: 'Upload failed' });
};

/**
 * Pick lists with their order's live status.
 * @param {'open'|'closed'|'all'} state
 */
export const getPicklists = (state = 'open', warehouseId, companyId) => {
  const params = { state };
  if (warehouseId && warehouseId !== 'all') params.warehouse_id = warehouseId;
  if (companyId && companyId !== 'all') params.company_id = companyId;
  return api.get('picklists', { params }).then((res) => res.data);
};

/**
 * Rebuild the selected pick lists as ONE PDF, each with its QR code.
 * Returns a Blob — a single print job for the whole stack.
 */
export const downloadPicklists = (picklistIds, companyId) =>
  api
    .post(
      'picklists/download',
      { picklist_ids: picklistIds, company_id: companyId },
      { responseType: 'blob' }
    )
    .then((res) => res.data);
