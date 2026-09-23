// A dealer's name with its town appended — "M.S DISTRIBUTORS - Rajkot" — used wherever a
// dealer name is shown: table columns, filters, dropdowns, dialog labels. Two dealers can
// share a name in different towns, and the town is what tells them apart at a glance,
// without needing every screen to open the dealer to find out where it is.
//
// Falls back to the bare name when no town is on file, rather than a trailing "- " that
// would read as a typo.
export const dealerLabel = (name, town) => {
  const n = (name || '').trim();
  const t = (town || '').trim();
  if (!n) return t || '';
  return t ? `${n} - ${t}` : n;
};
