# -*- encoding: utf-8 -*-
"""Match the SKU codes in a customer list / quotation to the SKU master. Pure — no DB.

Lists from the field rarely carry the exact supplier code: the finish suffix is missing
("CDSS250-SP" for CDSS250-SP-ZW), sits in a separate Finish column, is given as a choice
("GSP1-4-50-3M-AS/AB"), or the code is simply mistyped ("RH3S" for RH35, "S02" for SO2).
The matcher works through four steps and reports which one produced the answer:

  1. exact          the code as written (spaces / dash variants ignored)
     finish_added   code + the finish from the Finish column (or the code's own "AS/AB")
  2. base_single    the code is a base code with exactly one finish in the master
     needs_choice   the code is a base code with several finishes — the user picks
  3. fuzzy          look-alike characters (0/O, 1/I, 5/S) or a close spelling — suggestions
                    only, never applied without the user confirming
  4. unmatched      nothing close — stays in the "fix these" list

exact / finish_added / base_single resolve on their own; the rest need a choice.
"""

import bisect
import difflib
import re

AUTO_STATUSES = ('exact', 'finish_added', 'base_single')

# Your list (ZW NP GR AT SL BL BR CR WH AL GM) plus the finishes that are common at the
# end of Ebco's active codes. Fixed: change it here, not per company.
DEFAULT_FINISH_SUFFIXES = (
    'ZW,NP,GR,AT,SL,BL,BR,CR,WH,AL,GM,'
    'AB,AS,BA,BG,BM,BS,BT,CG,CH,CL,CP,EB,FB,FW,GD,GF,IV,NB,OP,SF,SG,SS,TD,TN,TP,'
    'WM,WT,WW,ZB,ZY,AG,AN,AC,AQ'
)

_DASHES = re.compile(r'[‐-―−]')
_CONFUSABLE = str.maketrans({'0': 'O', '1': 'I', '5': 'S'})


def loose(code):
    """Comparison key: upper-case, dash variants unified, all whitespace removed."""
    s = _DASHES.sub('-', str(code or '')).upper()
    return re.sub(r'\s+', '', s).strip('.')


def _canon(code):
    return loose(code).translate(_CONFUSABLE)


def parse_suffixes(text):
    """'ZW, NP;gr' -> ['ZW', 'NP', 'GR'] (de-duplicated, longest first)."""
    out = []
    for tok in re.split(r'[\s,;/|]+', str(text or '').upper()):
        if tok and tok not in out:
            out.append(tok)
    return sorted(out, key=lambda t: (-len(t), t))


def derive_finish(code, suffixes):
    """The finish a full SKU code ends in: 'CDSS250-SP-ZW' -> 'ZW', '...-04BR' -> 'BR'."""
    c = loose(code)
    for suf in suffixes:
        if c.endswith('-' + suf):
            return suf
    for suf in suffixes:
        if c.endswith(suf) and len(c) > len(suf) and c[-len(suf) - 1].isdigit():
            return suf
    return ''


class Matcher:
    """Index over the active SKUs of one SKU master."""

    def __init__(self, active_codes, suffixes, inactive_codes=()):
        self.suffixes = list(suffixes)
        self._suffix_set = set(self.suffixes)
        self.by_loose = {loose(c): c for c in active_codes}
        self._keys = sorted(self.by_loose)
        self.by_canon = {}
        for k, c in self.by_loose.items():
            self.by_canon.setdefault(_canon(k), []).append(c)
        self._canon_keys = sorted(self.by_canon)
        self.inactive = {loose(c) for c in inactive_codes} - set(self.by_loose)

    # -- helpers --------------------------------------------------------------

    def _finishes(self, text):
        """Finish codes named in a free-text finish cell: 'WH/AT' -> [WH, AT],
        'AT (WITH WOOD)' -> [AT]. Unknown 2-letter tokens are kept too, so a finish
        missing from the suffix list still narrows the choice."""
        toks = re.findall(r'[A-Z0-9]+', str(text or '').upper())
        known = [t for t in toks if t in self._suffix_set]
        if known:
            return known
        return [t for t in toks if re.fullmatch(r'[A-Z]{2}', t)][:1]

    @staticmethod
    def _prefixed(keys, prefix):
        i = bisect.bisect_left(keys, prefix)
        out = []
        while i < len(keys) and keys[i].startswith(prefix):
            out.append(keys[i])
            i += 1
        return out

    def _variants(self, base):
        """Active codes that are `base` plus a finish / further qualifier."""
        out = []
        for k in self._prefixed(self._keys, base):
            rest = k[len(base):]
            if rest and (rest.startswith('-') or rest in self._suffix_set):
                out.append(self.by_loose[k])
        return out

    def _strip_suffix(self, q):
        for suf in self.suffixes:
            if q.endswith('-' + suf):
                return q[:-len(suf) - 1]
            if q.endswith(suf) and len(q) > len(suf) and q[-len(suf) - 1].isdigit():
                return q[:-len(suf)]
        return None

    @staticmethod
    def _rank(codes, fins):
        """De-duplicate, codes ending in a wanted finish first, then shortest."""
        seen, out = set(), []
        for c in codes:
            if c not in seen:
                seen.add(c)
                out.append(c)
        if fins:
            out.sort(key=lambda c: (not any(loose(c).endswith(f) for f in fins), len(c)))
        return out

    # -- the cascade ----------------------------------------------------------

    def match(self, raw_code, raw_finish=''):
        """{status, sku_code (when resolved), candidates, note}."""
        q = loose(raw_code)
        if not q:
            return _result('unmatched', note='No code')

        fins = self._finishes(raw_finish)
        slash = re.fullmatch(r'(.+?)-?([A-Z]{2}(?:/[A-Z]{2})+)', q)
        if slash:
            q = slash.group(1)
            fins = fins or slash.group(2).split('/')

        # 1. exact, code + finish
        if q in self.by_loose and not slash:
            return _result('exact', self.by_loose[q])
        with_finish = []
        for f in fins:
            for cand in (q + '-' + f, q + f):
                if cand in self.by_loose and self.by_loose[cand] not in with_finish:
                    with_finish.append(self.by_loose[cand])
        if len(with_finish) == 1:
            return _result('finish_added', with_finish[0],
                           note=f'Finish {loose(with_finish[0])[len(q):].lstrip("-")} added')
        if len(with_finish) > 1:
            return _result('needs_choice', candidates=with_finish,
                           note='Several finishes given')

        note = 'Inactive in SKU master' if q in self.inactive else ''

        # 2. base code -> its finishes
        bases = [q]
        stripped = self._strip_suffix(q)
        if stripped:
            bases.append(stripped)
        cands = []
        for b in bases:
            cands += [c for c in self._variants(b) if c not in cands]
        if fins:
            wanted = [c for c in cands if any(loose(c).endswith(f) for f in fins)]
            if wanted:
                cands = wanted
        if len(cands) == 1:
            return _result('base_single', cands[0],
                           note=note or 'Only finish in the master')
        if len(cands) > 1:
            return _result('needs_choice', candidates=self._rank(cands, fins)[:12],
                           note=note or f'{len(cands)} finishes')

        # 3. fuzzy — look-alike characters first, then spelling distance
        sugg = []
        cq = _canon(q)
        for key in [cq] + ([_canon(stripped)] if stripped else []):
            sugg += self.by_canon.get(key, [])
            for k in self._prefixed(self._canon_keys, key + '-'):
                sugg += self.by_canon[k]
        close = difflib.get_close_matches(q, self._keys, n=6, cutoff=0.75)
        sugg += [self.by_loose[k] for k in close]
        sugg = self._rank(sugg, fins)[:8]
        if sugg:
            return _result('fuzzy', candidates=sugg, note=note or 'Did you mean…')

        return _result('unmatched', note=note or 'Not in SKU master')


def _result(status, sku_code=None, candidates=None, note=''):
    return {'status': status, 'sku_code': sku_code,
            'candidates': candidates or ([sku_code] if sku_code else []), 'note': note}
