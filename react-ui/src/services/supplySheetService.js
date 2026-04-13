import api from './api';

/**
 * Dealers who have at least one Invoiced order for a warehouse/company.
 * Used to populate the dealer multi-select on the supply sheet page.
 */
export const getSupplySheetDealers = (warehouseId, companyId) =>
  api
    .get('supply-sheet/dealers', { params: { warehouse_id: warehouseId, company_id: companyId } })
    .then((res) => res.data);

/**
 * All transport routes — for the optional route selector.
 */
export const getSupplySheetRoutes = () =>
  api.get('supply-sheet/routes').then((res) => res.data);

/**
 * Dealers belonging to a specific route who also have Invoiced orders.
 */
export const getRouteDealers = (routeId, warehouseId, companyId) =>
  api
    .get(`supply-sheet/routes/${routeId}/dealers`, {
      params: { warehouse_id: warehouseId, company_id: companyId },
    })
    .then((res) => res.data);

/**
 * Generate the supply sheet PDF.
 * Returns a Blob that can be used to create an object URL for preview/download.
 *
 * @param {object} payload  { warehouse_id, company_id, dealer_ids: [] }
 * @returns {Promise<Blob>}
 */
export const generateSupplySheet = (payload) =>
  api
    .post('supply-sheet/generate', payload, { responseType: 'blob' })
    .then((res) => res.data);
