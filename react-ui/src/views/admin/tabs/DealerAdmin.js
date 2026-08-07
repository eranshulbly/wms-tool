import React, { useState, useCallback } from 'react';
import { Box, Tabs, Tab } from '@material-ui/core';
import DealerLocationApprovals from './DealerLocationApprovals';
import DealerApprovals from './DealerApprovals';
import DealerCreate from './DealerCreate';
import DealerBook from './DealerBook';

/**
 * The Dealer Locations admin tab — everything an admin does to a dealer record.
 *
 * Three jobs that share the same subject, so they share one tab rather than three:
 *   Dealer book — every dealer, its executive and this month's targets, all editable;
 *   Locations   — approve the GPS fix + shopfront photo a rep captured;
 *   Dealers     — approve (or reject) a dealer a rep proposed from the field;
 *   Add dealer  — create one directly, active immediately.
 *
 * The first two overlap: a rep-proposed dealer appears in BOTH lists, because it arrives
 * with a photo attached. Deciding it in either place resolves the other, so `reloadKey`
 * remounts the sibling panel to stop one list showing work that no longer exists.
 */

const SECTIONS = [
  { key: 'book', label: 'Dealer book' },
  { key: 'locations', label: 'Location approvals' },
  { key: 'dealers', label: 'Dealer approvals' },
  { key: 'create', label: 'Add dealer' },
];

export default function DealerAdmin() {
  const [tab, setTab] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);
  const refreshSiblings = useCallback(() => setReloadKey((k) => k + 1), []);

  return (
    <Box>
      <Tabs
        value={tab}
        onChange={(e, v) => setTab(v)}
        indicatorColor="primary"
        textColor="primary"
        variant="scrollable"
        scrollButtons="auto"
        sx={{ mb: 2 }}
      >
        {SECTIONS.map((s) => (
          <Tab key={s.key} label={s.label} />
        ))}
      </Tabs>

      <Box mt={2}>
        {tab === 0 && <DealerBook key={`book-${reloadKey}`} />}
        {tab === 1 && <DealerLocationApprovals key={`loc-${reloadKey}`} onChanged={refreshSiblings} />}
        {tab === 2 && <DealerApprovals key={`dlr-${reloadKey}`} onChanged={refreshSiblings} />}
        {tab === 3 && <DealerCreate onCreated={refreshSiblings} />}
      </Box>
    </Box>
  );
}
