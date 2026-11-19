import React from 'react';
import PropTypes from 'prop-types';
import { Link } from '@material-ui/core';

// The DMS (Bizom) reports the uploads come from: the menu path to find each one, a
// direct link to it, and the date range to pick before exporting, where one matters.
// One list, so a moved report is fixed here rather than on every page that names it.
export const DMS_REPORTS = {
  inventory: {
    path: 'DMS → Analytics → Inventory Report',
    url: 'https://reports.bizom.in/reports/view/4549',
  },
  grn: {
    path: 'DMS → Analytics → GRN Approved Status Report Sku-wise',
    url: 'https://reports.bizom.in/reports/view/4073',
    range: 'Last 30 Days',
  },
  beat_plan: {
    path: 'DMS → Analytics → User Beat Details',
    url: 'https://reports.bizom.in/reports/view/20362',
    range: 'Today',
  },
  sku_master: {
    path: 'DMS → Analytics → Category Wise SKU Master',
    url: 'https://reports.bizom.in/reports/view/21905',
  },
};

// "DMS → Analytics → GRN … · https://reports.bizom.in/reports/view/4073 (Last 30 Days)" —
// the path as before, plus the full report address as a link (new tab) and the date
// range to choose.
const DmsReportLink = ({ report }) => (
  <>
    {report.path}
    {' · '}
    <Link href={report.url} target="_blank" rel="noopener noreferrer" underline="always"
      onClick={(e) => e.stopPropagation()} sx={{ wordBreak: 'break-all' }}>
      {report.url}
    </Link>
    {report.range ? ` (${report.range})` : ''}
  </>
);

DmsReportLink.propTypes = {
  report: PropTypes.shape({ path: PropTypes.string, url: PropTypes.string, range: PropTypes.string }).isRequired,
};

export default DmsReportLink;
