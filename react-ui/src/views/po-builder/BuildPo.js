import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Alert, Box, CircularProgress } from '@material-ui/core';

import poBuilderService, { errorMessage } from '../../services/poBuilderService';
import PoEditor from './PoEditor';

// PO Builder opens straight onto the PO being built — the latest one, or a fresh draft
// when there is none. There is deliberately no list of past POs.

const BuildPo = () => {
  const [poId, setPoId] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    poBuilderService
      .current()
      .then((r) => setPoId(r.id))
      .catch((e) => setError(errorMessage(e, 'Could not open the PO')));
  }, []);

  if (error) {
    return (
      <Alert severity="info">
        {error} Upload it under Admin → <Link to="/sku-master-upload">SKU Master Upload</Link> (and the scheme under <Link to="/scheme-upload">Scheme Upload</Link>), then come back here.
      </Alert>
    );
  }
  if (!poId) {
    return (
      <Box p={6} textAlign="center">
        <CircularProgress />
      </Box>
    );
  }
  return <PoEditor key={poId} poId={poId} onNewPo={setPoId} />;
};

export default BuildPo;
