import React, { createContext, useContext, useState, useEffect } from 'react';
import { getWarehouses, getCompanies } from '../services/warehouseService';

const WarehouseContext = createContext(null);

/**
 * Provides warehouse and company reference data + the user's current selection
 * to all descendant components. Wrap the MainLayout (or App) with this provider
 * so every warehouse page shares the same selection without independent fetches.
 */
export function WarehouseProvider({ children }) {
  const [warehouses, setWarehouses] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [selectedWarehouse, setSelectedWarehouse] = useState('');
  const [selectedCompany, setSelectedCompany] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let mounted = true;

    const fetchReferenceData = async () => {
      setLoading(true);
      setError(null);
      try {
        const [warehouseData, companyData] = await Promise.all([
          getWarehouses(),
          getCompanies()
        ]);

        if (!mounted) return;

        if (warehouseData.success && warehouseData.warehouses?.length) {
          setWarehouses(warehouseData.warehouses);
          // Normalise id field — API may return warehouse_id or id
          const first = warehouseData.warehouses[0];
          setSelectedWarehouse(first.warehouse_id ?? first.id);
        }

        if (companyData.success && companyData.companies?.length) {
          setCompanies(companyData.companies);
          setSelectedCompany(companyData.companies[0].id);
        }
      } catch (err) {
        if (mounted) setError(err.message || 'Failed to load warehouse data');
      } finally {
        if (mounted) setLoading(false);
      }
    };

    fetchReferenceData();
    return () => { mounted = false; };
  }, []);

  return (
    <WarehouseContext.Provider
      value={{
        warehouses,
        companies,
        selectedWarehouse,
        setSelectedWarehouse,
        selectedCompany,
        setSelectedCompany,
        loading,
        error
      }}
    >
      {children}
    </WarehouseContext.Provider>
  );
}

/** Access the warehouse context from any component inside WarehouseProvider. */
export const useWarehouse = () => {
  const ctx = useContext(WarehouseContext);
  if (!ctx) throw new Error('useWarehouse must be used inside WarehouseProvider');
  return ctx;
};
