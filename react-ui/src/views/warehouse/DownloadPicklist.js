import React from 'react';
import { Grid } from '@material-ui/core';
import { gridSpacing } from '../../store/constant';
import DownloadPicklistPanel from './components/DownloadPicklist';

// Top-level sidebar page — the panel itself (company/warehouse-scoped order list +
// per-row PDF download) lives in components/DownloadPicklist.js, self-contained the
// same way DownloadDmsInput's card is.
const DownloadPicklist = () => (
  <Grid container spacing={gridSpacing}>
    <Grid item xs={12}>
      <DownloadPicklistPanel />
    </Grid>
  </Grid>
);

export default DownloadPicklist;
