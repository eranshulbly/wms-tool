import React from 'react';
import {
  Grid,
  Card,
  CardContent,
  FormControl,
  InputLabel,
  MenuItem,
  Select
} from '@material-ui/core';
import { STATUS_FILTER_OPTIONS } from '../constants/statuses';

/**
 * Warehouse / Company / Status filter row.
 * Used by both WarehouseDashboard and OrderManagement.
 *
 * Props:
 *   warehouses, companies          — reference arrays
 *   warehouse, company             — selected values
 *   statusFilter                   — selected status slug or 'all'
 *   onWarehouseChange, onCompanyChange, onStatusFilterChange — change handlers
 *   allowedStatuses                — array of slugs the current user may see (null = all)
 *   classes                        — makeStyles classes from the parent page
 */
const FilterControls = ({
  warehouses,
  companies,
  warehouse,
  company,
  statusFilter,
  onWarehouseChange,
  onCompanyChange,
  onStatusFilterChange,
  allowedStatuses,
  classes
}) => {
  const visibleStatusOptions = STATUS_FILTER_OPTIONS.filter(
    (opt) => opt.value === 'all' || !allowedStatuses || allowedStatuses.includes(opt.value)
  );

  return (
    <Grid item xs={12}>
      <Card>
        <CardContent>
          <Grid container spacing={2}>
            <Grid item xs={12} md={4} lg={3}>
              <FormControl variant="outlined" className={classes?.formControl} fullWidth>
                <InputLabel id="warehouse-select-label">Warehouse</InputLabel>
                <Select
                  labelId="warehouse-select-label"
                  id="warehouse-select"
                  value={warehouse}
                  onChange={onWarehouseChange}
                  label="Warehouse"
                >
                  {warehouses.map((wh) => {
                    const id = wh.warehouse_id ?? wh.id;
                    return (
                      <MenuItem key={id} value={id}>
                        {wh.name}
                      </MenuItem>
                    );
                  })}
                </Select>
              </FormControl>
            </Grid>

            <Grid item xs={12} md={4} lg={3}>
              <FormControl variant="outlined" className={classes?.formControl} fullWidth>
                <InputLabel id="company-select-label">Company</InputLabel>
                <Select
                  labelId="company-select-label"
                  id="company-select"
                  value={company}
                  onChange={onCompanyChange}
                  label="Company"
                >
                  {companies.map((comp) => (
                    <MenuItem key={comp.id} value={comp.id}>
                      {comp.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>

            <Grid item xs={12} md={4} lg={3}>
              <FormControl variant="outlined" className={classes?.formControl} fullWidth>
                <InputLabel id="status-filter-label">Filter by Status</InputLabel>
                <Select
                  labelId="status-filter-label"
                  id="status-filter"
                  value={statusFilter}
                  onChange={onStatusFilterChange}
                  label="Filter by Status"
                >
                  {visibleStatusOptions.map((option) => (
                    <MenuItem key={option.value} value={option.value}>
                      {option.label}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
          </Grid>
        </CardContent>
      </Card>
    </Grid>
  );
};

export default FilterControls;
