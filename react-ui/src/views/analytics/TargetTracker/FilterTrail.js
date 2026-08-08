import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import { monthsLabel } from './format';

// The filter flow (§4). Company and month are asked here, one question at a time, and
// each answer becomes a chip on a trail — clicking either chip re-opens that step.
//
// Executive / dealer / part group / part are NOT asked here. They are set by clicking a
// row in the tables below, so the only thing this component does with them is show the
// resulting chip and let it be cleared.

export const DIMS = [
  { key: 'exec', label: 'Sales executive', plural: 'executives' },
  { key: 'dealer', label: 'Dealer', plural: 'dealers' },
  { key: 'group', label: 'Part group', plural: 'part groups' },
  { key: 'part', label: 'Part', plural: 'parts' }
];

// `onEdit` is optional: company and month re-open their step when clicked, but a
// drill-down chip has no step to go back to — it is set from a table row, so it is
// display-and-remove only.
const Crumb = ({ k, label, value, removable, onEdit, onClear }) => (
  <span
    className="crumb"
    {...(onEdit ? {
      role: 'button',
      tabIndex: 0,
      onClick: onEdit,
      onKeyDown: (e) => e.key === 'Enter' && onEdit()
    } : {})}
  >
    <span>
      <span className="k">{label}</span>
      <br />
      <span className="v">{value}</span>
    </span>
    {removable && (
      <button
        type="button"
        className="x"
        aria-label={`Remove ${label} filter`}
        onClick={(e) => {
          e.stopPropagation();
          onClear(k);
        }}
      >
        ×
      </button>
    )}
  </span>
);
Crumb.propTypes = {
  k: PropTypes.string,
  label: PropTypes.string,
  value: PropTypes.string,
  removable: PropTypes.bool,
  onEdit: PropTypes.func,
  onClear: PropTypes.func
};

const StepShell = ({ n, q, hint, children }) => (
  <div className="step">
    <div className="step-q">
      <span className="step-n">Step {n}</span>
      <h2>{q}</h2>
      <span className="hint">{hint}</span>
    </div>
    {children}
  </div>
);
StepShell.propTypes = { n: PropTypes.number, q: PropTypes.string, hint: PropTypes.string, children: PropTypes.node };


const FilterTrail = ({
  companies, months, state, pending, setPending, onCompany, onMonths, onClear, onReset, labelFor
}) => {
  const [draftMonths, setDraftMonths] = useState(state.months);
  useEffect(() => setDraftMonths(state.months), [state.months, pending]);

  const trail = [];
  if (state.companyId) {
    const co = companies.find((c) => c.id === state.companyId);
    trail.push(
      <Crumb key="company" k="company" label="Company" value={co ? co.name : ''} onEdit={() => setPending('company')} />
    );
  }
  if (state.months.length) {
    trail.push(
      <Crumb
        key="month"
        k="month"
        label={state.months.length > 1 ? 'Months' : 'Month'}
        value={monthsLabel(state.months, months)}
        onEdit={() => setPending('month')}
      />
    );
  }
  DIMS.forEach((d) => {
    const v = state.f[d.key];
    if (!v.length) return;
    trail.push(
      <Crumb
        key={d.key}
        k={d.key}
        label={d.label}
        value={v.length === 1 ? labelFor(d.key, v[0]) : `${v.length} ${d.plural}`}
        removable
        onClear={onClear}
      />
    );
  });

  return (
    <section className="path" aria-label="Filters">
      <div className="path-top">
        <span className="path-title">Your selection</span>
        <button type="button" className="reset" disabled={!state.companyId} onClick={onReset}>Start over</button>
      </div>

      <div className="trail">
        {trail.length ? (
          trail.map((c, i) => (
            <React.Fragment key={c.key}>
              {i > 0 && <span className="arrow">›</span>}
              {c}
            </React.Fragment>
          ))
        ) : (
          <span style={{ fontSize: 14, color: 'var(--muted)' }}>Start by choosing a company below.</span>
        )}
      </div>

      {/* Step 1 — company. Nothing else renders until this is answered (§4.1). */}
      {(!state.companyId || pending === 'company') && (
        <StepShell n={1} q="Which company are you reviewing?" hint="Each company has its own dealers, executives and part groups.">
          <div className="opts">
            {companies.map((c) => (
              <button type="button" className="opt wide" key={c.id} onClick={() => onCompany(c.id)}>
                <span className="t">{c.name}</span>
              </button>
            ))}
          </div>
        </StepShell>
      )}

      {/* Step 2 — months. Multi-select, applied only on confirm (§4.2). */}
      {state.companyId && pending !== 'company' && (!state.months.length || pending === 'month') && (
        <StepShell n={2} q="Which months?" hint="Every month counts its full target — the current one included, so its % climbs as the month is worked through.">
          <div className="presets">
            <button type="button" className="preset" onClick={() => setDraftMonths(months.slice(0, 1).map((m) => m.id))}>This month</button>
            <button type="button" className="preset" onClick={() => setDraftMonths(months.slice(0, 3).map((m) => m.id))}>Last 3 months</button>
            <button type="button" className="preset" onClick={() => setDraftMonths(months.map((m) => m.id))}>All {months.length} months</button>
            <button type="button" className="preset" onClick={() => setDraftMonths([])}>Clear</button>
          </div>
          <div className="opts">
            {months.map((m) => (
              <button
                type="button"
                key={m.id}
                className={`opt check${draftMonths.includes(m.id) ? ' on' : ''}${m.current ? ' now' : ''}`}
                aria-pressed={draftMonths.includes(m.id)}
                onClick={() =>
                  setDraftMonths((d) => (d.includes(m.id) ? d.filter((x) => x !== m.id) : [...d, m.id]))}
              >
                <span className="box">{draftMonths.includes(m.id) ? '✓' : ''}</span>
                {m.label}
              </button>
            ))}
          </div>
          <div className="apply">
            <button type="button" className="btn" disabled={!draftMonths.length} onClick={() => onMonths(draftMonths)}>
              {draftMonths.length > 1 ? `Show ${draftMonths.length} months` : 'Show month'}
            </button>
            <span className="hint">
              {draftMonths.length > 1
                ? 'Several months give a month-wise comparison — drilling into an executive needs a single month.'
                : 'One month lets you drill executive › dealer › product.'}
            </span>
            {state.months.length > 0 && (
              <button type="button" className="btn ghost" onClick={() => setPending(null)}>Cancel</button>
            )}
          </div>
        </StepShell>
      )}
    </section>
  );
};

FilterTrail.propTypes = {
  companies: PropTypes.array,
  months: PropTypes.array,
  state: PropTypes.object,
  pending: PropTypes.string,
  setPending: PropTypes.func,
  onCompany: PropTypes.func,
  onMonths: PropTypes.func,
  onClear: PropTypes.func,
  onReset: PropTypes.func,
  labelFor: PropTypes.func
};

export default FilterTrail;
