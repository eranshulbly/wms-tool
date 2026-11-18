import React, { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  CircularProgress,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@material-ui/core';
import { IconPhoto } from '@tabler/icons';
import { errMsg, getDealers, logPayment } from '../../services/dealerPaymentsService';

// Log a dealer payment the moment you hear of it (spec 2.4). Built to fill in under ten
// seconds on a phone: the dealer search has focus, choosing a dealer moves to the amount,
// the mode remembers the last one used and the date is today. Reference, note and proof
// are optional and sit below the Save button.

const MODE_KEY = 'dpt.lastMode';

const todayIso = () => {
  const d = new Date(Date.now() + 5.5 * 3600 * 1000); // IST
  return d.toISOString().slice(0, 10);
};

const readMode = () => {
  try {
    return localStorage.getItem(MODE_KEY) || 'BT';
  } catch (_) {
    return 'BT';
  }
};

const dealerLabel = (d) => (d ? `${d.dealer_name}${d.town ? ` (${d.town})` : ''}` : '');

const PaymentForm = ({ onSaved, compact = false }) => {
  const [dealers, setDealers] = useState([]);
  const [loadError, setLoadError] = useState('');
  const [dealer, setDealer] = useState(null);
  const [mode, setMode] = useState(readMode);
  const [amount, setAmount] = useState('');
  const [paymentDate, setPaymentDate] = useState(todayIso);
  const [reference, setReference] = useState('');
  const [note, setNote] = useState('');
  const [proof, setProof] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(null);
  const amountRef = useRef(null);
  const dealerRef = useRef(null);

  useEffect(() => {
    getDealers()
      .then((res) => setDealers((res.dealers || []).filter((d) => d.active)))
      .catch((e) => setLoadError(errMsg(e, 'Could not load the dealer list.')));
  }, []);

  const reset = () => {
    setDealer(null);
    setAmount('');
    setReference('');
    setNote('');
    setProof(null);
    setPaymentDate(todayIso());
    setTimeout(() => dealerRef.current && dealerRef.current.focus(), 0);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!dealer) {
      setError('Choose the dealer.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const res = await logPayment(
        { dealer_id: dealer.dealer_id, mode, amount, payment_date: paymentDate, reference, note },
        proof
      );
      try {
        localStorage.setItem(MODE_KEY, mode);
      } catch (_) {
        /* a remembered mode is a convenience only */
      }
      setSaved(res.payment);
      reset();
      if (onSaved) onSaved(res.payment);
    } catch (err) {
      setError(errMsg(err, 'Could not save the payment.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box component="form" onSubmit={submit} sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
      {loadError && <Alert severity="error">{loadError}</Alert>}
      {saved && (
        <Alert severity={saved.status === 'POSTED' ? 'success' : 'info'} onClose={() => setSaved(null)}>
          Saved: {saved.dealer_name} · ₹{Number(saved.amount).toLocaleString('en-IN')} · {saved.mode}.{' '}
          {saved.status === 'POSTED'
            ? `Already in Tally (receipt ${saved.matched_vch_no}) — POSTED.`
            : saved.status === 'BOUNCED'
            ? `Tally shows it reversed (${saved.bounced_by_ref}) — BOUNCED.`
            : 'OPEN until Tally posts it.'}
        </Alert>
      )}
      <Autocomplete
        options={dealers}
        value={dealer}
        onChange={(_, v) => {
          setDealer(v);
          if (v) setTimeout(() => amountRef.current && amountRef.current.focus(), 0);
        }}
        getOptionLabel={dealerLabel}
        isOptionEqualToValue={(o, v) => o.dealer_id === v.dealer_id}
        filterOptions={(opts, { inputValue }) => {
          const q = inputValue.trim().toLowerCase();
          if (!q) return opts;
          return opts.filter((o) => `${o.dealer_name} ${o.town} ${o.dealer_id}`.toLowerCase().includes(q));
        }}
        renderInput={(params) => (
          <TextField {...params} inputRef={dealerRef} label="Dealer" autoFocus required size={compact ? 'small' : 'medium'} />
        )}
      />
      <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap' }}>
        <ToggleButtonGroup
          exclusive
          color="primary"
          value={mode}
          onChange={(_, v) => v && setMode(v)}
          size={compact ? 'small' : 'medium'}
        >
          <ToggleButton value="BT">BT (NEFT/RTGS/UPI)</ToggleButton>
          <ToggleButton value="CASH">Cash</ToggleButton>
        </ToggleButtonGroup>
        <TextField
          inputRef={amountRef}
          label="Amount (₹)"
          value={amount}
          onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ''))}
          inputProps={{ inputMode: 'decimal' }}
          required
          size={compact ? 'small' : 'medium'}
          sx={{ flex: '1 1 140px' }}
        />
        <TextField
          label="Payment date"
          type="date"
          value={paymentDate}
          onChange={(e) => setPaymentDate(e.target.value)}
          InputLabelProps={{ shrink: true }}
          required
          size={compact ? 'small' : 'medium'}
          sx={{ flex: '1 1 150px' }}
        />
      </Box>
      {error && <Alert severity="error">{error}</Alert>}
      <Button
        type="submit"
        variant="contained"
        size="large"
        disableElevation
        disabled={saving || !dealer || !amount}
        startIcon={saving ? <CircularProgress size={16} color="inherit" /> : null}
      >
        {saving ? 'Saving…' : 'Save payment'}
      </Button>
      <Typography variant="caption" color="textSecondary">
        Optional
      </Typography>
      <TextField
        label="Reference (UTR)"
        value={reference}
        onChange={(e) => setReference(e.target.value)}
        size="small"
        inputProps={{ maxLength: 64 }}
      />
      <TextField label="Note" value={note} onChange={(e) => setNote(e.target.value)} size="small" inputProps={{ maxLength: 500 }} />
      <Button component="label" variant="outlined" size="small" startIcon={<IconPhoto size={16} />} sx={{ alignSelf: 'flex-start' }}>
        {proof ? `Proof: ${proof.name}` : 'Add proof photo'}
        <input hidden type="file" accept="image/*" capture="environment" onChange={(e) => setProof(e.target.files?.[0] || null)} />
      </Button>
    </Box>
  );
};

export default PaymentForm;
