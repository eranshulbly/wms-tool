import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { compact, qty, mins, monthsLabel, band, pctText } from './format';
import { Kpi, RankTable, QtyTable, Empty, Pct, ColSearch, NoMatch } from './parts';
import FilterTrail from './FilterTrail';
import DetailModal from './DetailModal';
import OtherCategoriesModal from './OtherCategoriesModal';
import { getCompanies, getMonths, getDashboard, getDetail } from '../../../services/targetTrackerService';
import './targetTracker.css';

// Target Tracker — company › months › executive › dealer, against target.
//
// Every figure comes from /api/target-tracker/*; nothing is computed here except
// formatting. The three screens are one component because they share the filter trail
// and the KPI row, and the level is derived from the filters rather than held twice.

const EMPTY_F = { exec: [], dealer: [], group: [], part: [] };

const TargetTracker = () => {
  const [companies, setCompanies] = useState([]);
  const [months, setMonths] = useState([]);
  const [state, setState] = useState({ companyId: null, months: [], f: { ...EMPTY_F } });
  const [pending, setPending] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [catView, setCatView] = useState('category');
  const [dealerTab, setDealerTab] = useState('cats');
  const [modal, setModal] = useState(null);
  const [modalData, setModalData] = useState(null);
  const [modalLoading, setModalLoading] = useState(false);
  // The multi-month grid is built inline rather than through RankTable, so its
  // first-column search lives here.
  const [gridQ, setGridQ] = useState('');
  const [otherOpen, setOtherOpen] = useState(false);

  useEffect(() => {
    getCompanies().then((d) => d.success && setCompanies(d.companies)).catch(() => setCompanies([]));
  }, []);

  useEffect(() => {
    if (!state.companyId) return;
    getMonths(state.companyId)
      .then((d) => {
        const list = d.success ? d.months : [];
        setMonths(list);
        // The current month is pre-ticked (§4.2) but nothing applies until confirm.
        if (list.length && !state.months.length) setPending('month');
      })
      .catch(() => setMonths([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.companyId]);

  const scope = useMemo(
    () => ({ companyId: state.companyId, months: state.months, ...state.f }),
    [state]
  );
  const ready = Boolean(state.companyId && state.months.length);

  const load = useCallback(() => {
    if (!ready) return;
    setLoading(true);
    setError(null);
    getDashboard(scope)
      .then((d) => (d.success ? setData(d) : setError(d.msg || 'Failed to load')))
      .catch((e) => setError(e?.response?.data?.msg || 'Failed to load'))
      .finally(() => setLoading(false));
  }, [scope, ready]);

  useEffect(() => { load(); }, [load]);
  // §8.4 — the popup is month-specific, so any filter change closes it.
  useEffect(() => { setModal(null); setModalData(null); setOtherOpen(false); }, [scope]);

  useEffect(() => {
    if (!modal) return undefined;
    let live = true;
    setModalLoading(true);
    getDetail(scope, modal.key, modal.mode)
      .then((d) => live && setModalData(d.success ? d.detail : null))
      .catch(() => live && setModalData(null))
      .finally(() => live && setModalLoading(false));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modal]);

  // ---- filter actions ----
  const onCompany = (id) => {
    // Changing company clears every downstream selection (§4.1).
    setState({ companyId: id, months: [], f: { ...EMPTY_F } });
    setData(null);
    setPending(null);
  };
  const onMonths = (ms) => {
    setState((s) => ({
      ...s,
      months: months.filter((m) => ms.includes(m.id)).map((m) => m.id),
      // §10.1 — drill-down is single-month only; picking a second month returns to the
      // overview rather than leaving a stale executive/dealer selection in place.
      f: ms.length > 1 ? { ...s.f, exec: [], dealer: [] } : s.f
    }));
    setPending(null);
  };
  const onDim = (key, vals) => {
    setState((s) => {
      const f = { ...s.f, [key]: vals };
      // §10.6 — removing/changing a parent drops orphaned children.
      if (key === 'group') f.part = [];
      if (key === 'exec') f.dealer = [];
      return { ...s, f };
    });
    setPending(null);
  };
  const onClear = (key) => {
    setState((s) => {
      const f = { ...s.f, [key]: [] };
      if (key === 'group') f.part = [];
      if (key === 'exec') f.dealer = [];
      return { ...s, f };
    });
    setPending(null);
  };
  const onReset = () => {
    setState({ companyId: null, months: [], f: { ...EMPTY_F } });
    setData(null);
    setPending(null);
  };

  const labelFor = (key, val) => {
    if (key === 'exec') return data?.executives?.find((e) => e.id === val)?.name || data?.exec?.name || String(val);
    if (key === 'dealer') return data?.dealers?.find((d) => d.id === val)?.name || data?.dealer?.name || String(val);
    return String(val);
  };

  const co = companies.find((c) => c.id === state.companyId);
  const mLabel = monthsLabel(state.months, months);
  const level = data?.level || 'all';
  const multi = Boolean(data?.multi_month);
  const scopeName =
    level === 'dealer' ? (data?.dealer?.name || '').split('|')[0].trim()
      : level === 'exec' ? data?.exec?.name || ''
        : 'All executives';

  const kp = data?.kpis;
  const catItems = catView === 'category' ? data?.categories : data?.schemes;
  // The leading category. A two-dimensional grid (executive × month) has no room for a
  // per-category axis as well, so it reports this one and names it in the header rather
  // than falling back to a combined figure.
  const primary = (data?.axis || [])[0] || null;
  const gridRows = useMemo(() => {
    const terms = gridQ.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const all = data?.executives || [];
    if (!terms.length) return all;
    return all.filter((e) => terms.every((t) => String(e.name || '').toLowerCase().includes(t)));
  }, [data, gridQ]);

  return (
    <div className="tt-root">
      <div className="wrap">
        <div className="head">
          <div>
            <h1>Target Tracker</h1>
            <div className="sub">
              Pick a company and a month, then narrow down to an executive, dealer or part.
              {multi && ' Several months are selected — pick a single month to drill in.'}
            </div>
          </div>
          <div className="scope">
            {co ? <><b>{co.line}</b> · {mLabel || 'pick a month'}</> : 'Nothing selected yet'}
          </div>
        </div>

        <FilterTrail
          companies={companies}
          months={months}
          state={state}
          pending={pending}
          setPending={setPending}
          onCompany={onCompany}
          onMonths={onMonths}
          onClear={onClear}
          onReset={onReset}
          labelFor={labelFor}
        />

        {!ready ? null : error ? (
          <section className="panel"><Empty title="Could not load" help={error} /></section>
        ) : loading || !data ? (
          <section className="panel"><div className="empty">Loading…</div></section>
        ) : (
          <>
            {/* level bar / breadcrumb */}
            <div className="levelbar">
              {level !== 'all' && (
                <div className="drillpath">
                  <button type="button" className="link" onClick={() => onClear('exec')}>All executives</button>
                  {level === 'dealer' && (
                    <>
                      <span className="arrow">›</span>
                      <button type="button" className="link" onClick={() => onClear('dealer')}>
                        {data.dealer?.exec_name || 'Dealers'}
                      </button>
                    </>
                  )}
                </div>
              )}
              <div className="lvl">
                <h2>{scopeName}</h2>
                <span>
                  {level === 'all'
                    ? `${mLabel} · ${multi ? 'month-wise comparison — drill-down needs a single month' : 'tap any row to drill in'}`
                    : level === 'exec'
                      ? `${data.dealers?.length || 0} dealers · ${mLabel}`
                      : `${data.dealer?.exec_name || 'unassigned'} · ${mLabel}`}
                </span>
              </div>
            </div>

            {/* §5.1 — one card per category, then the two scope-wide cards. Categories
                are never added together: each is shown against its own target, or
                against none at all if it has none. */}
            <div className="kpis">
              {kp.parts && (
                <Kpi
                  label={`Total sales ${kp.parts.category}`}
                  value={kp.parts.target_kind === 'qty' ? qty(kp.parts.qty_sold) : compact(kp.parts.sales)}
                  foot={kp.parts.target_kind === 'value'
                    ? `${pctText(kp.parts.pct)} of ${compact(kp.parts.target)} target to date`
                    : kp.parts.target_kind === 'qty'
                      ? `${pctText(kp.parts.pct)} of ${qty(kp.parts.target)} qty target to date`
                      : null}
                />
              )}
              {/* Every non-Parts category in one tile. It shows no target: its categories
                  sit on different scales, so a summed target would mean nothing. The
                  bifurcation lives in the popup. */}
              <Kpi
                label="Total sales Other"
                value={compact(kp.other?.sales)}
                onClick={kp.other?.category_count ? () => setOtherOpen(true) : undefined}
                foot={kp.other?.category_count
                  ? `${kp.other.category_count} categories — tap for the breakdown`
                  : 'No sales outside Parts'}
              />
              <Kpi
                label="Dealers billed"
                value={`${kp.dealers_billed} / ${kp.dealers_total}`}
                foot={`${kp.dealers_total - kp.dealers_billed} at zero — ${
                  level === 'dealer' ? 'this dealer' : level === 'exec' ? `${scopeName}'s book` : 'all executives'}`}
              />
              <Kpi
                label="Avg time at dealer"
                value={mins(kp.avg_minutes)}
                foot={`${kp.visits} visits ${multi ? `across ${state.months.length} months` : 'this month'}`}
              />
            </div>

            {/* §5.2 — month strip, only when more than one month is selected */}
            {multi && (
              <section className="panel">
                <div className="panel-h">
                  <h3>Month by month</h3>
                  <span className="note">Billed value against target to date</span>
                </div>
                <div className="mstrip">
                  {data.months.map((m) => (
                    <div className="mcard" key={m.id}>
                      <div className="ml">{m.label}{m.current ? ' · to date' : ''}</div>
                      {(m.categories || []).map((c) => (
                        <div className="mcat" key={c.category}>
                          <div className="mcatname">{c.category}</div>
                          <div className="mv">{c.target_kind === 'qty' ? qty(c.qty_sold) : compact(c.sales)}</div>
                          {c.target_kind ? (
                            <>
                              <Pct pct={c.pct} />
                              <div className="mf">
                                target {c.target_kind === 'qty' ? qty(c.target) : compact(c.target)}
                              </div>
                            </>
                          ) : (
                            <div className="mf"><span className="dash">no target</span></div>
                          )}
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* ---- Screen 1: all executives ---- */}
            {level === 'all' && (
              <section className="panel">
                <div className="panel-h">
                  <h3>Sales by executive</h3>
                  <span className="note">
                    {multi
                      ? 'Month-wise achievement · select a single month to drill into an executive'
                      : 'Weakest first · tap an executive to drill in'}
                  </span>
                </div>
                <div className="scroll">
                  {multi ? (
                    !data.executives.length ? (
                      <Empty title="Nothing to show" help="Loosen a filter or pick another month." />
                    ) : (
                      <table>
                        <thead>
                          <tr>
                            <th>
                              Executive
                              <ColSearch value={gridQ} onChange={setGridQ} placeholder="Search executive…" />
                            </th>
                            {data.month_ids.map((m) => (
                              <th className="num" key={m}>
                                {months.find((x) => x.id === m)?.label.replace(' 20', " '") || m}
                                {primary && <span className="dim"> · {primary.category}</span>}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {/* Not clickable when several months are selected (§5.3 case B). */}
                          {!gridRows.length && (
                            <tr>
                              <td colSpan={1 + data.month_ids.length}>
                                <NoMatch q={gridQ} what="executive" />
                              </td>
                            </tr>
                          )}
                          {gridRows.map((e) => (
                            <tr key={e.id}>
                              <td>
                                <span className="name">{e.name}</span>
                                <br />
                                <span className="dim" style={{ fontSize: 12 }}>
                                  {e.dealers} dealers · {e.billed} billed
                                </span>
                              </td>
                              {data.month_ids.map((m) => {
                                // The grid is exec × month, so it can only show ONE
                                // category — the leading targeted one, named in the header.
                                const cell = primary ? data.exec_grid?.[e.id]?.[m]?.[primary.category] : null;
                                return (
                                  <td className="num" key={m}>
                                    <span className={`pct ${band(cell?.pct)}`}>{pctText(cell?.pct ?? null)}</span>
                                    <span className="mcell">
                                      {primary?.target_kind === 'qty' ? qty(cell?.qty_sold || 0) : compact(cell?.sales || 0)}
                                    </span>
                                  </td>
                                );
                              })}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )
                  ) : (
                    <RankTable
                      head="Executive"
                      axis={data.axis}
                      clickable
                      onPick={(o) => onDim('exec', [o.id])}
                      items={data.executives.map((e) => ({ ...e, sub: `${e.dealers} dealers · ${e.billed} billed` }))}
                    />
                  )}
                </div>
              </section>
            )}

            {/* ---- Screen 2: one executive ---- */}
            {level === 'exec' && (
              <div className="duo">
                <section className="panel">
                  <div className="panel-h">
                    <h3>Dealers under {scopeName}</h3>
                    <span className="note">Weakest first · tap to drill in</span>
                  </div>
                  <div className="scroll">
                    <RankTable
                      head="Dealer"
                      axis={data.axis}
                      clickable
                      onPick={(o) => onDim('dealer', [o.id])}
                      items={data.dealers.map((d) => ({ ...d, sub: d.exec_name }))}
                    />
                  </div>
                </section>
                <section className="panel">
                  <div className="panel-h">
                    <h3>{catView === 'category' ? 'Sales by category' : 'Sales by scheme'}</h3>
                    <span className="note">Tap a row for product detail</span>
                  </div>
                  <div style={{ padding: '0 22px 12px' }}>
                    <div className="seg">
                      <button type="button" aria-pressed={catView === 'category'} onClick={() => setCatView('category')}>By category</button>
                      <button type="button" aria-pressed={catView === 'scheme'} onClick={() => setCatView('scheme')}>By scheme</button>
                    </div>
                  </div>
                  <div className="scroll">
                    <QtyTable mode={catView} items={catItems || []} onOpen={(o) => setModal({ key: o.key, mode: catView })} />
                  </div>
                </section>
              </div>
            )}

            {/* ---- Screen 3: one dealer ---- */}
            {level === 'dealer' && (
              <section className="panel">
                <div className="panel-h">
                  <h3>{scopeName}</h3>
                  <div className="seg">
                    <button type="button" aria-pressed={dealerTab === 'cats'} onClick={() => setDealerTab('cats')}>Categories</button>
                    <button type="button" aria-pressed={dealerTab === 'opp'} onClick={() => setDealerTab('opp')}>Opportunity</button>
                  </div>
                </div>
                {dealerTab === 'cats' ? (
                  <>
                    <div style={{ padding: '0 22px 12px' }}>
                      <div className="seg">
                        <button type="button" aria-pressed={catView === 'category'} onClick={() => setCatView('category')}>By category</button>
                        <button type="button" aria-pressed={catView === 'scheme'} onClick={() => setCatView('scheme')}>By scheme</button>
                      </div>
                    </div>
                    <div className="scroll">
                      <QtyTable mode={catView} items={catItems || []} onOpen={(o) => setModal({ key: o.key, mode: catView })} />
                    </div>
                  </>
                ) : (
                  <>
                    {/* §7 Tab 2 — the rule is not agreed; the banner must say so. */}
                    <div className="callout">
                      Placeholder rule — currently comparing this dealer against the average of the
                      executive&apos;s other dealers for the selected months. This is provisional and not an
                      agreed metric.
                    </div>
                    {!data.opportunity?.length ? (
                      <Empty
                        title="No gap against peers"
                        help="This dealer is at or above peer average in every part group for the selected months."
                      />
                    ) : (
                      <div className="scroll">
                        <table>
                          <thead>
                            <tr>
                              <th>Part group</th>
                              <th className="num">Sold here</th>
                              <th className="num">Peer avg</th>
                              <th className="num">Gap qty</th>
                              <th className="num">Est. value</th>
                            </tr>
                          </thead>
                          <tbody>
                            {data.opportunity.map((o) => (
                              <tr key={o.part_group}>
                                <td><span className="name">{o.part_group}</span></td>
                                <td className="num">{qty(o.sold_here)}</td>
                                <td className="num">{qty(o.peer_avg)}</td>
                                <td className="num">{qty(o.gap)}</td>
                                <td className="num">{compact(o.value)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                )}
              </section>
            )}
          </>
        )}
      </div>

      {otherOpen && (
        <OtherCategoriesModal
          categories={kp?.other?.categories}
          total={kp?.other?.sales}
          scopeLabel={scopeName}
          monthsLabel={mLabel}
          onClose={() => setOtherOpen(false)}
        />
      )}

      {modal && (
        <DetailModal
          detail={modalData}
          loading={modalLoading}
          scopeLabel={scopeName}
          monthsLabel={mLabel}
          onClose={() => { setModal(null); setModalData(null); }}
        />
      )}
    </div>
  );
};

export default TargetTracker;
