# Dealer visit — Overview tab specification

A complete description of the mobile app's **Overview** tab, for rebuilding the
same view in the admin web app. Everything here is what the Flutter app does
today; source references point at the mobile implementation so behaviour can be
checked rather than guessed.

Mobile source: `lib/screens/dealer_session_screen.dart` (`_overview`),
`lib/screens/category_detail_screen.dart`, `lib/widgets/paper.dart`.

---

## 1. What the screen is

One dealer, one month. It answers three questions in order:

1. **Can I trust these numbers?** — how stale the sales feed is.
2. **How is this dealer doing overall?** — sales against the dealer's money target.
3. **Where is the gap?** — the same question per category, drillable.

Then it shows the last note anyone left at this dealer.

In the rep app the dealer is fixed by the rep's active check-in. **In the admin
web app the dealer is chosen** — see §7.

---

## 2. Layout

```
┌──────────────────────────────────────────────┐
│ ⚠ Sales data through 23 Jul 2026 · 10 days   │  full-bleed lag banner
│   behind. Anything billed since then isn't   │  (amber when ≥2 days stale)
│   counted yet.                               │
├──────────────────────────────────────────────┤
│ AUGUST 2026 · PARTS & PRO PARTS         12%  │  month summary card
│ ▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │
│ Sales                        Dealer target   │
│ ₹24,500                          ₹2,00,000   │
├──────────────────────────────────────────────┤
│ BY CATEGORY                     August 2026  │  section head
│ ┌──────────────────────────────────────────┐ │
│ │ Parts                     ₹84,200      › │ │  one row per category
│ │ Target ₹2,75,111           31% achieved  │ │
│ │ ▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │ │
│ ├──────────────────────────────────────────┤ │
│ │ Pro Parts                      ₹0      › │ │
│ │ Target ₹44,111              0% achieved  │ │
│ │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  │ │
│ ├──────────────────────────────────────────┤ │
│ │ Oil                            ₹0      › │ │
│ │ Target ₹50,000              0% achieved  │ │
│ └──────────────────────────────────────────┘ │
├──────────────────────────────────────────────┤
│ LAST VISIT                        24 Jul 2026│  omitted entirely when the
│ ┌──────────────────────────────────────────┐ │  dealer has no earlier note
│ │ Asked for 15 days credit on pro parts.   │ │
│ └──────────────────────────────────────────┘ │
└──────────────────────────────────────────────┘
```

Above the tab strip (shared by Overview / Orders / Notes, not part of Overview
itself): dealer name, `dealer_code · town`, and the check-in status strip.

---

## 3. Data sources

### 3.1 `GET /api/v1/analytics/dealer/{dealer_id}`

JWT auth (`Authorization: Bearer …`), no extra permission required. Returns 404
if the dealer doesn't exist or is outside the caller's company scope.

Powers everything except the Last-visit block. Real response (lists truncated):

```jsonc
{
  "success": true,
  "month": "August 2026",              // display label for the period
  "dealer_id": 4,
  "dealer": "Aakash Auto Service | AFM | Chaupla",
  "target": 200000,                    // the DEALER'S OWN money target
  "data_through": "2026-07-23",        // last sale date loaded (see §5.1)

  "categories": [                      // Parts and Pro Parts ONLY
    {
      "category": "Parts",
      "category_id": 6,
      "sales": 0,                      // this month, rupees
      "target": 275111,                // this category's own money target
      "pct": 0.0,                      // sales/target*100, null when no target
      "grow": [ /* target sheet — see the category detail spec */ ],
      "new_opportunity": [ /* top-10 peer-spend products */ ]
    },
    { "category": "Pro Parts", "category_id": 5, "sales": 0, "target": 44111, "pct": 0.0, … }
  ],

  "category_sales": [                  // EVERY category, sales + its own target
    { "category_id": 6, "category": "Parts",     "this_month": 0, "last6m": 97180.99, "target": 275111, "pct": 0.0 },
    { "category_id": 5, "category": "Pro Parts", "this_month": 0, "last6m": 4576.20,  "target": 44111,  "pct": 0.0 },
    { "category_id": 1, "category": "Oil",       "this_month": 0, "last6m": 0,        "target": 50000,  "pct": 0.0 }
  ]
}
```

Notes on this payload:

- `categories[]` carries the drill-down detail (`grow`, `new_opportunity`) and
  exists **only for Parts and Pro Parts**. Every other category appears in
  `category_sales[]` with sales and target but no detail.
- `category_sales[]` lists categories the dealer has bought in **plus** any
  category it is targeted on with zero sales (e.g. Oil above). Ordered by
  `this_month + last6m` descending, with the zero-sales targeted ones appended.
- `target` (top level) is the dealer's own money target. It is **not** the sum of
  the category targets — see §6.1.
- `pct` is `null`, not `0`, when a category has no target. Render "no target set",
  not 0%.

### 3.2 `GET /api/v1/visits/dealer/{dealer_id}/notes`

JWT auth, company-scoped. Powers the Last-visit block. Newest visit first.

```jsonc
[
  {
    "visit_id": 3,
    "dealer_id": 4,
    "check_in_at": "2026-07-24T11:20:14",
    "check_out_at": "2026-07-24T11:52:31",
    "status": "checked_out",
    "notes": "Asked for 15 days credit on pro parts.",
    "updated_at": "2026-07-24T11:51:02",
    "author": "Mohit",                 // username who wrote it
    "is_mine": false                   // true when the caller wrote it
  }
]
```

Only visits with a non-empty note are returned. Optional `?limit=` (default 50,
max 200).

---

## 4. Block-by-block mapping

### 4.1 Data-lag banner

| Field | Source |
|---|---|
| Date shown | `data_through` |
| Days behind | whole calendar days between `data_through` and today |

- Rendered only when `data_through` is present.
- **< 2 days behind:** neutral tint, text `Sales data through 23 Jul 2026.`
- **≥ 2 days behind:** amber tint + warning icon, text
  `Sales data through 23 Jul 2026 · 10 days behind. Anything billed since then isn't counted yet.`
- Full-bleed (edge to edge), above all figures, because it qualifies all of them.

### 4.2 Month summary card

| Element | Value |
|---|---|
| Eyebrow | `"{month} · Parts & Pro Parts"`, uppercased |
| Big % | `sales / target * 100`, where `sales` = **sum of `categories[].sales`** and `target` = top-level `target` |
| Bar | same percentage, clamped 0–100 |
| Left figure | `Sales` = that combined sales figure |
| Right figure | `Dealer target` = top-level `target`, or `"No target set"` when 0 |

Percentage display: no decimal when whole (`12%`), one decimal otherwise
(`76.5%`). Null (no target) renders `—` and an empty bar.

### 4.3 Category rows

One row per category. **Order:**

1. every entry in `categories[]`, in API order (Parts, then Pro Parts);
2. then every `category_sales[]` entry whose `category` name is not already
   listed, in API order.

| Element | Value |
|---|---|
| Name | `category` |
| Right figure | `sales` (from `categories[]`) or `this_month` (from `category_sales[]`) |
| Sub-left | `"Target ₹2,75,111"`, or `"Target ₹0"` when none |
| Sub-right | `"{pct}% achieved"` — omitted entirely when `pct` is null |
| Bar | 3px, same percentage, achievement-coloured |
| Affordance | chevron; tapping opens the category detail |

### 4.4 Last visit

- Take the **newest** note from §3.2 that is not the visit currently in progress
  (in the admin app, simply the newest — there is no active visit).
- Caption: that visit's `check_in_at`, formatted `24 Jul 2026`.
- Body: `notes` text.
- **When there are no notes, the whole block — heading included — is omitted.**
  Do not render an empty card.

---

## 5. Rules

### 5.1 Data lag

Sales arrive by batch import from Busy, so `data_through` normally trails today.
This is why a month can legitimately show ₹0 everywhere: at the time of writing,
the period is August 2026 and the feed runs to 23 July 2026, so no August sale
has landed yet. The banner is what stops that being read as "this dealer bought
nothing".

### 5.2 Achievement colour

One scale, used by every percentage, bar and figure on the screen:

| Percentage | Meaning | Mobile colour |
|---|---|---|
| `null` (no target) | neutral | `#9A9C92` grey |
| `< 60` | behind | `#A32B1F` red |
| `60 – 89` | needs watching | `#8A5A00` amber |
| `≥ 90` | fine | `#2F6B3D` green |

Source: `AppTheme.pctColor`, `lib/core/theme.dart`.

### 5.3 Formatting

| Kind | Rule | Example |
|---|---|---|
| Money | Indian grouping, `₹`, **no decimals** | `₹2,75,111` |
| Quantity | Indian grouping | `2,491` |
| Percentage | 0 dp if whole, else 1 dp, `%` suffix | `76.5%` |
| Date | `d MMM yyyy` | `24 Jul 2026` |
| Time | `h:mm a` | `4:12 PM` |

Locale is `en_IN` throughout (lakh/crore grouping, not thousands).

### 5.4 Palette and type (to match the mobile app)

Paper `#EFEDE7` page, white `#FFFFFF` cards, 1px `#DCD9D0` borders, no shadows.
Ink `#191B1A` headings, `#4A4D48` body, `#76796F` labels. Row dividers
`#EBE8E1`. Accent teal `#0B5D66`. Type is IBM Plex Sans, with **IBM Plex Mono for
every number** — money, quantities, percentages, times — so columns of figures
align. Section headings are 11px uppercase with ~0.13em tracking.

---

## 6. Things the web team should know before building

### 6.1 The dealer target is not the sum of category targets

For dealer 4: dealer target ₹2,00,000, but Parts ₹2,75,111 + Pro Parts ₹44,111 +
Oil ₹50,000 = ₹3,69,222. They come from different rows of `dealer_money_target`
(`category_id IS NULL` vs rows naming a category) and are set independently. The
summary card's percentage therefore is **not** the weighted average of the
category rows, and shouldn't be presented as if it were.

### 6.2 Only Parts and Pro Parts have detail

`grow` (the target sheet) and `new_opportunity` (peer-spend products) are
computed for those two categories only. Other categories are sales + target; a
drill-down for them will legitimately be empty.

### 6.3 Quantity targets can be absent even with a money target

Quantity targets come from schemes/part groups, which currently cover only the
Parts category. Pro Parts has a ₹44,111 money target and **zero** quantity
targets — no scheme this period contains a Pro Parts product. Show "No targets"
rather than treating it as an error.

### 6.4 `dealer` in the payload is a compound string

`"Aakash Auto Service | AFM | Chaupla"` — the dealer master's `name` column
contains pipe-separated name/code/town. The mobile app doesn't use this field for
the header; it reads name, `dealer_code` and `town` from the dealers endpoint
instead. Do the same, or split on `|`.

---

## 7. Admin web app differences

The mobile screen is scoped to the rep's active check-in. For an admin view of
sales-executive activity:

- **Dealer selection** replaces the active visit. Everything above is per-dealer
  and needs only `dealer_id`.
- **No check-in strip** and no "New order" action bar — those are rep actions.
- **Notes are read-only.** The write endpoint (`PUT /api/v1/visits/{visit_id}/notes`)
  is owner-only and returns 403 for anyone else, so an admin can display notes
  with their `author` but must not offer editing.
- **Visit history is the admin's real subject** — see §8. The endpoints above
  describe a dealer, not a rep's day.
- Company scoping is applied server-side from the caller's token; an admin with
  `company:all` sees every dealer.

---

## 8. Sales-executive activity view (needs a new endpoint)

Everything in §1–§7 is per **dealer**. An admin watching *executives* needs the
other axis: who went where, when, for how long, and what came of it. The data all
exists in `dealer_visits`; **no endpoint exposes it by executive today**, so this
section specifies both the view and the API to build for it.

### 8.1 What the view shows

```
┌────────────────────────────────────────────────────────────┐
│ Executive: Mohit ▾        2 Aug 2026 – 2 Aug 2026 ▾        │
├────────────────────────────────────────────────────────────┤
│ 5 visits · 4 dealers · 3h 12m in shops · 6 orders          │  day summary
├────────────────────────────────────────────────────────────┤
│ 11:59  Aakash Auto Service              48 m from shop  ›  │  one row per visit
│        checked out 12:47 · 48 min · 2 orders · note ✎      │
│ ────────────────────────────────────────────────────────── │
│ 10:12  Sharma Motors                    ⚠ 2.4 km away   ›  │  distance flag
│        checked out 10:31 · 19 min · no order               │
│ ────────────────────────────────────────────────────────── │
│ 09:40  Verma Auto                       location unknown › │  dealer has no
│        still checked in · 2h 31m                           │  coordinates
└────────────────────────────────────────────────────────────┘
```

Each row expands (or links) to the dealer's Overview from §2, so an admin can go
from "he visited this dealer" to "and here's how that dealer stands".

### 8.2 Endpoint to build

```
GET /api/v1/visits?executive_id={user_id}&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD
```

- **Auth:** JWT. Gate on `order:read_all` (`P.ORDER_READ_ALL`) — that is the
  existing "sees other people's work" permission; a field rep holds `order:read`
  only and must not reach this. Listing executives to choose from needs
  `user:read` (`P.USER_READ`).
- **Scope:** filter by the caller's company grants exactly as the other endpoints
  do (`company_filter(current_user, 'v.company_id')`). `company:all` sees all.
- **Params:** `executive_id` optional (omit = every executive in scope),
  `date_from` / `date_to` on `check_in_at` (default: today), `limit` (default 200).
- **Order:** `check_in_at DESC`.

Suggested response:

```jsonc
{
  "executive_id": 4,
  "executive": "Mohit",
  "date_from": "2026-08-02",
  "date_to": "2026-08-02",
  "summary": {
    "visits": 5,
    "dealers": 4,                      // distinct dealer_id
    "minutes_in_shops": 192,           // summed over checked-out visits
    "orders": 6,
    "visits_flagged": 1                // distance beyond the threshold, §8.4
  },
  "visits": [
    {
      "visit_id": 5,
      "dealer_id": 4,
      "dealer": "Aakash Auto Service",
      "check_in_at": "2026-08-02T11:59:47",
      "check_out_at": "2026-08-02T12:47:03",
      "status": "checked_out",         // 'active' while still in the shop
      "duration_minutes": 47,          // null while active — compute live client-side
      "check_in_latitude": 28.6153201,
      "check_in_longitude": 77.2091502,
      "check_in_accuracy_m": 8.4,
      "check_out_latitude": 28.6153388,
      "check_out_longitude": 77.2091901,
      "distance_from_dealer_m": 48.2,  // null when either side lacks coordinates
      "orders": 2,                     // orders raised at this dealer during the visit
      "notes": "Asked for 15 days credit on pro parts."
    }
  ]
}
```

### 8.3 Where each field comes from

| Field | Source |
|---|---|
| visit rows | `dealer_visits` — `visit_id, user_id, dealer_id, company_id, status, check_in_at, check_in_latitude/longitude/accuracy_m, check_out_at, check_out_latitude/longitude/accuracy_m, notes` |
| `executive` | `users.username` via `users.id = dealer_visits.user_id` |
| `dealer` | `dealer.name` (pipe-separated — see §6.4) |
| `distance_from_dealer_m` | Haversine between `check_in_latitude/longitude` and `dealer.latitude/longitude`. Reuse `_distance_m()` in `api/modules/fulfillment/order/router_v1.py:29` rather than writing a second one. Null when the dealer has no stored coordinates. |
| `duration_minutes` | `TIMESTAMPDIFF(MINUTE, check_in_at, check_out_at)`; null while `status = 'active'` |
| `orders` | count from `submitted_orders` where `dealer_id` matches, `created_by = user_id`, and `created_at` falls between check-in and check-out (or now, if active) |

`dealer_visits` is indexed on `user_id`, `dealer_id` and `(user_id, status)`.
There is **no index on `check_in_at`**, so a wide date range across all
executives will scan; add one if this view is used over long ranges.

### 8.4 Rules for the view

- **Distance flag.** A check-in far from the dealer's stored shop is the single
  most useful signal here. Suggested bands: under 200 m fine, 200 m – 1 km amber,
  over 1 km red. Show `location unknown` (neutral, not a warning) when the dealer
  has no coordinates — that is a missing-data problem, not a rep problem, and it
  is exactly what the location-capture flow exists to fix.
- **Never show a bare distance without its accuracy.** A 300 m gap on a fix
  accurate to ±250 m means nothing. Suppress or grey the flag when
  `check_in_accuracy_m` is of the same order as the distance.
- **Active visits.** `check_out_at` null means the rep is still in the shop;
  render "still checked in" and count elapsed time live. A visit still open from a
  previous day usually means someone forgot to check out — worth surfacing.
- **Zero-order visits are not automatically bad.** Collection, complaint handling
  and stock checks are real visits. Present the count, not a judgement.
- Reuse the colour scale and formatting rules from §5.2 and §5.3.

### 8.5 Related endpoints that already exist

| Purpose | Endpoint | Notes |
|---|---|---|
| A dealer's note history | `GET /api/v1/visits/dealer/{dealer_id}/notes` | Read-only for anyone but the author |
| The caller's own active visit | `GET /api/v1/visits/active` | Rep-scoped; not useful to an admin |
| Dealer month analytics | `GET /api/v1/analytics/dealer/{dealer_id}` | §3.1 — the drill-down target |
| An executive's own month | `GET /api/v1/analytics/my-summary` | Caller-scoped only; an admin view of *another* exec's target would need the same treatment as §8.2 |
