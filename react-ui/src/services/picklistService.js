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
 * @param {'printed'|'unprinted'|'all'} printed
 */
export const getPicklists = (
  state = 'open',
  warehouseId,
  companyId,
  printed = 'all',
  owner = 'mine'
) => {
  // `owner` is a request for a wider view, not a grant of one — the server
  // ignores it for anyone but an admin and scopes from the token regardless.
  const params = { state, printed, owner };
  if (warehouseId && warehouseId !== 'all') params.warehouse_id = warehouseId;
  if (companyId && companyId !== 'all') params.company_id = companyId;
  return api.get('picklists', { params }).then((res) => res.data);
};

/**
 * Rebuild the selected pick lists as ONE PDF, each with its QR code.
 * Returns a Blob — a single print job for the whole stack.
 *
 * `markPrinted` tells the SERVER this is a print rather than a save. The mark is
 * set there, not reported back after window.print(): a print dialog can be
 * cancelled and a tab closed, and neither returns — so the browser is not a
 * witness worth trusting. Download passes false and marks nothing.
 */
export const downloadPicklists = (picklistIds, companyId, markPrinted = false) =>
  api
    .post(
      'picklists/download',
      { picklist_ids: picklistIds, company_id: companyId, mark_printed: markPrinted },
      { responseType: 'blob' }
    )
    .then((res) => res.data);

/** Set or clear the printed mark by hand — the fix for a jam or a cancelled dialog. */
export const setPicklistsPrinted = (picklistIds, printed, companyId) =>
  api
    .post('picklists/printed', {
      picklist_ids: picklistIds,
      printed,
      company_id: companyId
    })
    .then((res) => res.data);
