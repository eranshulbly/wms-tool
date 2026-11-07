import React, { useCallback, useEffect, useState } from 'react';
import { Box, Button, Typography, CircularProgress, Grid, Paper, Alert } from '@material-ui/core';
import { makeStyles } from '@material-ui/styles';
import { IconUpload } from '@tabler/icons';
import { getFeedStatus, uploadFeed } from '../../services/tatCheckService';
import { getBeatFeedStatus, uploadBeatFeed } from '../../services/beatOutstandingService';

// The DMS / Tally uploads. Each upload replaces the previous one of the same kind.
//   FEEDS       read by TAT Check (views/tat-check/TatCheck.js) — Admin pages, one per file
//   BEAT_FEEDS  read by Beat Outstanding (views/beat-outstanding/BeatOutstanding.js) — the
//               Outlet Master has an Admin page; the daily Beat Plan and Outstanding Report
//               are uploaded on the Beat Outstanding page itself (UploadRow below)

const TAT_API = { getStatus: getFeedStatus, upload: uploadFeed, usedBy: 'TAT Check' };
const BEAT_API = { getStatus: getBeatFeedStatus, upload: uploadBeatFeed, usedBy: 'Beat Outstanding' };

export const FEEDS = [
  {
    feed: 'inventory',
    label: 'DMS Inventory',
    title: 'DMS Inventory Upload',
    hint: 'DMS inventory export (.csv) — only current stock (Units) is used',
    accept: '.csv,.xlsx',
    ...TAT_API,
  },
  {
    feed: 'dispatch_pending',
    label: 'Dispatch and Pending',
    title: 'Dispatch and Pending Upload',
    hint: 'Ebco workbook with a DISPATCH sheet, a PENDING sheet, or both (.xlsx or .csv) — only the sheets in the file are replaced',
    accept: '.xlsx',
    ...TAT_API,
  },
  {
    feed: 'grn',
    label: 'GRN',
    title: 'GRN Upload',
    hint: 'DMS GRN report, SKU-wise (.csv) — approved GRNs mark dispatches as received',
    accept: '.csv,.xlsx',
    ...TAT_API,
  },
];

export const BEAT_FEEDS = [
  {
    feed: 'outlets',
    label: 'Outlet Master',
    title: 'Outlet Master Upload',
    hint: 'DMS Outlet Master export (.csv) — which beat and city each outlet is on',
    accept: '.csv,.xlsx',
    ...BEAT_API,
  },
  {
    feed: 'beat_plan',
    label: 'Beat Plan',
    title: 'Beat Plan Upload',
    hint: 'DMS User Beat Details export (.csv) — which beats each executive covers on a day',
    accept: '.csv,.xlsx',
    ...BEAT_API,
  },
  {
    feed: 'outstanding',
    label: 'Outstanding Report',
    title: 'Outstanding Upload',
    hint: "Distributor's Tally Bills Receivable export (.xlsx) — replaces only that distributor's previous report",
    accept: '.xlsx',
    ...BEAT_API,
  },
];

const ALL_FEEDS = [...FEEDS, ...BEAT_FEEDS];

const useStyles = makeStyles(() => ({
  muted: { color: '#7a869a' },
  mono: { fontFamily: 'monospace', fontSize: '0.85rem' },
}));

const nf = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 });
const fmtDateTime = (iso) => {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
};
const errMsg = (e, fallback) => e?.response?.data?.msg || fallback;

const lastText = (s) => {
  const last = s?.last_upload;
  if (!last) return 'Not uploaded yet';
  const who = s.distributor ? `${s.distributor}${s.report_to ? ` (up to ${s.report_to})` : ''}: ` : '';
  return `${who}${last.filename} · ${fmtDateTime(last.uploaded_on)} · ${last.uploaded_by}`;
};

export const UploadRow = ({ def, statuses, onUploaded }) => {
  const classes = useStyles();
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const inputId = `feed-upload-${def.feed}`;

  const upload = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const res = await def.upload(def.feed, file);
      const counts = Object.entries(res.result.counts)
        .map(([k, n]) => `${nf.format(n)} ${k} rows`)
        .join(', ');
      const warn = res.result.warning_count ? ` · ${res.result.warning_count} warning(s)` : '';
      const whose = res.result.distributor ? ` for ${res.result.distributor}` : '';
      setMsg({
        type: 'success',
        text: `Loaded ${counts}${whose}${warn}. Previous upload replaced.`,
        warnings: res.result.warnings || [],
      });
      setFile(null);
      onUploaded();
    } catch (e) {
      setMsg({ type: 'error', text: errMsg(e, 'Upload failed — nothing was changed.') });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box py={1.5} style={{ borderBottom: '1px solid #eef0f3' }}>
      <Grid container spacing={1} alignItems="center">
        <Grid item xs={12} sm={5}>
          <Typography variant="subtitle2">{def.label}</Typography>
          <Typography variant="caption" className={classes.muted} component="div">
            {def.hint}
          </Typography>
          {(statuses.length ? statuses : [null]).map((st, i) => (
            <Typography key={i} variant="caption" component="div" style={{ color: '#b91c1c', fontWeight: 600 }}>
              Last: {lastText(st)}
            </Typography>
          ))}
        </Grid>
        <Grid item xs={12} sm={7}>
          <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
            <label htmlFor={inputId}>
              <input
                id={inputId}
                type="file"
                accept={def.accept}
                style={{ display: 'none' }}
                onChange={(e) => {
                  setFile(e.target.files?.[0] || null);
                  setMsg(null);
                  e.target.value = '';
                }}
              />
              <Button component="span" size="small" variant="outlined">
                Choose file
              </Button>
            </label>
            {file && (
              <Typography variant="body2" className={classes.mono}>
                {file.name}
              </Typography>
            )}
            <Button
              size="small"
              variant="contained"
              disabled={!file || busy}
              onClick={upload}
              startIcon={busy ? <CircularProgress size={14} /> : <IconUpload size={14} />}
            >
              {busy ? 'Uploading…' : 'Upload'}
            </Button>
          </Box>
        </Grid>
      </Grid>
      {msg && (
        <Alert severity={msg.type} style={{ marginTop: 8 }}>
          {msg.text}
          {msg.warnings?.slice(0, 10).map((w) => (
            <div key={w} className={classes.mono}>
              {w}
            </div>
          ))}
        </Alert>
      )}
    </Box>
  );
};

const DmsFeedUpload = ({ feed }) => {
  const classes = useStyles();
  const def = ALL_FEEDS.find((f) => f.feed === feed);
  const [feeds, setFeeds] = useState([]);

  const loadStatus = useCallback(() => {
    def
      .getStatus()
      .then((res) => setFeeds(res.feeds || []))
      .catch(() => setFeeds([]));
  }, [def]);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        {def.title}
      </Typography>
      <Typography variant="body2" className={classes.muted} style={{ marginBottom: 16 }}>
        Used by {def.usedBy}. Each upload replaces the previous one.
      </Typography>
      <Paper variant="outlined" style={{ padding: 16 }}>
        <UploadRow def={def} statuses={feeds.filter((f) => f.feed === def.feed)} onUploaded={loadStatus} />
      </Paper>
    </Box>
  );
};

export default DmsFeedUpload;
