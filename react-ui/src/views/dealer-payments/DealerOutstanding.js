import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Box, Paper, Typography } from '@material-ui/core';
import { errMsg, getUploads } from '../../services/dealerPaymentsService';
import { getBeatFeedStatus } from '../../services/beatOutstandingService';
import { BEAT_FEEDS, UploadRow } from '../dms-uploads/DmsFeedUpload';
import { FILES, FileRow } from './DealerPayments';
import BeatDownloads from './BeatDownloads';

// Dealer Payments → Outstanding: each sales executive's dealers, on all the beats they own
// (Executive Beats), with the dealer screen's amounts and a file each to hand them. The
// Outlet Master and Beat Plan uploads are Beat Outstanding's own (one copy, shared by both
// pages; the Outlet Master is incremental). The two Tally files are uploaded only here; the
// dealer screen reads them (FILES and FileRow live in DealerPayments.js).

const OutstandingPage = () => {
  const [beatFeeds, setBeatFeeds] = useState([]);
  const [uploads, setUploads] = useState({});
  const [error, setError] = useState('');
  const [reloadKey, setReloadKey] = useState(0);

  const load = useCallback(() => {
    setError('');
    Promise.all([getBeatFeedStatus(), getUploads()])
      .then(([b, u]) => {
        setBeatFeeds(b.feeds || []);
        setUploads(u.uploads || {});
      })
      .catch((e) => setError(errMsg(e, 'Could not load the files.')));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const uploaded = () => {
    load();
    setReloadKey((k) => k + 1);
  };

  return (
    <Box>
      <Typography variant="h3" gutterBottom>Outstanding</Typography>
      <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
        Each executive in Executive Beats gets the outstanding of the dealers on all their beats. Dealers no executive
        covers are under Unassigned.
      </Typography>
      {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}

      <Paper variant="outlined" sx={{ p: 2, mb: 2, borderRadius: 2 }}>
        <Typography variant="subtitle2">Files</Typography>
        {BEAT_FEEDS.map((def) => (
          <UploadRow key={def.feed} def={def} statuses={beatFeeds.filter((f) => f.feed === def.feed)} onUploaded={uploaded} />
        ))}
        {FILES.map((def) => (
          <FileRow key={def.key} def={def} last={uploads[def.key]} onDone={uploaded} />
        ))}
      </Paper>

      <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
        <BeatDownloads reloadKey={reloadKey} />
      </Paper>
    </Box>
  );
};

export default OutstandingPage;
