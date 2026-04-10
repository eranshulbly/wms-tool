import axios from 'axios';
import config from '../config';

// config.API_SERVER already contains the /api prefix (e.g. "http://localhost:5000/api/")
const API = config.API_SERVER.replace(/\/$/, '');

/**
 * Admin Controls API service.
 *
 * All endpoints require an admin-role JWT (sent automatically via the
 * global axios interceptor configured in the auth layer).
 */
const adminService = {
    /**
     * Fetch upload batches with optional filters.
     *
     * @param {Object} filters
     * @param {string} [filters.upload_type]   - 'orders' | 'invoices'
     * @param {number} [filters.warehouse_id]
     * @param {number} [filters.company_id]
     * @param {string} [filters.date_from]     - 'YYYY-MM-DD'
     * @param {string} [filters.date_to]       - 'YYYY-MM-DD'
     */
    getUploadBatches: async (filters = {}) => {
        const params = {};
        if (filters.upload_type)  params.upload_type  = filters.upload_type;
        if (filters.warehouse_id) params.warehouse_id = filters.warehouse_id;
        if (filters.company_id)   params.company_id   = filters.company_id;
        if (filters.date_from)    params.date_from    = filters.date_from;
        if (filters.date_to)      params.date_to      = filters.date_to;

        const res = await axios.get(`${API}/admin/upload-batches`, { params });
        return res.data;
    },

    /**
     * Fetch the full record list for a single batch.
     *
     * @param {number} batchId
     */
    getBatchDetails: async (batchId) => {
        const res = await axios.get(`${API}/admin/upload-batches/${batchId}/details`);
        return res.data;
    },

    /**
     * Hard-delete a batch and all its associated data.
     * Returns 409 with an error message if the batch cannot be reverted
     * (e.g. orders already past the Invoiced state).
     *
     * @param {number} batchId
     */
    deleteUploadBatch: async (batchId) => {
        const res = await axios.delete(`${API}/admin/upload-batches/${batchId}`);
        return res.data;
    },
};

export default adminService;
