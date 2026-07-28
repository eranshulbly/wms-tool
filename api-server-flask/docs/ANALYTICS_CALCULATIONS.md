# Analytics calculations — Sales % achieved & Part suggestions

Spec for the mobile app to reproduce (or consume) the web analytics. Everything is
**current-month, Hero (company_id = 1)**, computed live (nothing is precomputed/stored).

---

## 1. Data sources & attribution

| Table | Columns used | Meaning |
|-------|--------------|---------|
| `busy_sales_data` | `sale_date`, `particulars`, `item_code`, `quantity`, `amount` | One row per sales line (from Busy). `particulars` = dealer name, `item_code` = part number. |
| `dealer` | `dealer_id`, `name`, `company_id`, `sales_executive_id` | One dealer → one executive. (The rupee target moved to `dealer_money_target`.) |
| `users` | `id`, `username`, `role` | Sales executives have `role = 'sales_executive'`. |
| `part_groups` | `part_number`, `part_group`, `month` | Part → part‑group mapping for the month. **No quantity target here.** |
| `dealer_money_target` | `dealer_id`, `target_period`, `value_target` | The **rupee** target: per **dealer**, per period. |
| `dealer_part_group_target` | `dealer_id`, `part_group`, `target_qty`, `target_period` | The **quantity** target: per **dealer × part group**, per period. |

> **`target_period` is a DATE = the first day of the target's month** (e.g. `2026-07-01`), the
> definitive period key — it will not collide across years. Match it against the current
> month with `target_period = DATE_FORMAT(CURDATE(), '%Y-%m-01')`.

> **Two kinds of target:**
> 1. **Rupee target** — per **dealer** (`dealer_money_target.value_target` for the period); an executive's rupee target = sum over their dealers.
> 2. **Quantity target** — per **dealer × part group** (`dealer_part_group_target.target_qty` for the period). A part group's target for any view = **sum of `target_qty` over the dealers in scope**. Individual parts have **no** target.

**Attribution joins** (this is how a sale is tied to a dealer, an executive, and a part group):

```sql
busy_sales_data b
  JOIN dealer d      ON d.name = b.particulars AND d.company_id = 1        -- sale -> dealer
  JOIN users  u      ON u.id   = d.sales_executive_id                      -- dealer -> executive
  LEFT JOIN part_groups pg ON pg.part_number = b.item_code AND pg.month = 'July'  -- part -> group/target
```

- Sale → dealer is a **string match** on `particulars = dealer.name` (exact). A sale whose `particulars` has no matching Hero dealer is unattributed and dropped.
- `LEFT JOIN part_groups` → parts not in the monthly mapping have `part_group = NULL` (bucket them as `"(Unmapped)"`) and no `target_qty`.

**"This month" filter** (applied to every sales query):

```sql
YEAR(b.sale_date) = YEAR(CURDATE()) AND MONTH(b.sale_date) = MONTH(CURDATE())
```

> ⚠️ Known quirk: sales use the **current calendar month**, but the `part_groups` join is pinned to `month = 'July'`. They align today (July 2026); when you generalize, make the `part_groups.month` match the sales month.

**Helper — percentage:**
```
pct(actual, target) = round(actual / target * 100, 1)   if target > 0
                    = null                                if target is 0 / missing
```

---

## 2. Sales % achieved — EXECUTIVE

**Definition:** an executive's month‑to‑date rupee sales ÷ their rupee target.

- **Actual sales(exec)** = sum of `amount` over all this‑month sales lines whose dealer belongs to that executive.
- **Target(exec)** = sum of `dealer_money_target.value_target` (for the current period) over the dealers assigned to that executive.
- **% achieved(exec)** = `pct(actual_sales, target)`.

```sql
-- Actual (per executive), this month
SELECT u.id AS user_id, u.username, SUM(b.amount) AS sales
FROM busy_sales_data b
JOIN dealer d ON d.name = b.particulars AND d.company_id = 1
JOIN users  u ON u.id   = d.sales_executive_id
WHERE <this-month> AND u.role = 'sales_executive'
GROUP BY u.id, u.username;

-- Target (per executive) — from the dealer master, NOT the sales table
SELECT d.sales_executive_id, SUM(COALESCE(mt.value_target,0)) AS target
FROM dealer d
JOIN dealer_money_target mt ON mt.dealer_id = d.dealer_id
WHERE d.company_id = 1 AND d.sales_executive_id IS NOT NULL
      AND mt.target_period = DATE_FORMAT(CURDATE(), '%Y-%m-01')
GROUP BY d.sales_executive_id;

-- % achieved = sales / target * 100  (per user_id)
```

**Important semantics**
- The **target is a property of the dealer master**, not the sales. It reflects only **executive/dealer** scoping filters — a **part / part‑group filter must NOT reduce the target** (it narrows sales only). So filtering by a part group makes % drop, by design (you're seeing how much of the full monthly target that slice covers).
- Current dummy value: every dealer's period `value_target = 200000`, so an exec's target = `200000 × (their dealer count)`.

---

## 3. Sales % achieved — DEALER

Same idea, one level down.

- **Actual sales(dealer)** = sum of `amount` for that dealer this month.
- **Target(dealer)** = `dealer_money_target.value_target` for the current period.
- **% achieved(dealer)** = `pct(actual_sales, target)`.

```sql
SELECT d.dealer_id, d.name AS dealer, SUM(b.amount) AS sales
FROM busy_sales_data b
JOIN dealer d ON d.name = b.particulars AND d.company_id = 1
WHERE <this-month>
GROUP BY d.dealer_id, d.name;
-- target(dealer) = dealer_money_target.value_target (current period) ; pct = sales / target * 100
```

**UI colour bands** (used on web): green `≥ 100%`, amber `≥ 50%`, red `< 50%`, `—` when target is missing.

---

## 3b. Part‑group quantity % achieved

Quantity targets are **per dealer × part group** (`dealer_part_group_target`). For any view:

- **Sold(group)** = `SUM(quantity)` of this‑month sales in that part group (honours all filters).
- **Target(group)** = `SUM(dealer_part_group_target.target_qty)` over the **dealers in scope**
  (executive/dealer filters), for that group + month. *Not* reduced by a part/part‑group filter.
- **% = Sold / Target × 100.**

```sql
-- Target for each part group over the dealers in view
SELECT dpg.part_group, SUM(dpg.target_qty) AS target
FROM dealer_part_group_target dpg
JOIN dealer d ON d.dealer_id = dpg.dealer_id
WHERE d.company_id = 1 AND dpg.target_period = DATE_FORMAT(CURDATE(), '%Y-%m-01')
      [AND d.sales_executive_id = :EX] [AND d.dealer_id = :D]
GROUP BY dpg.part_group;
```

Individual **parts have no target** (only qty is shown for parts).

---

## 4. Part suggestions for a dealer

Given a `dealer_id`, produce two ranked lists of parts to push on a visit. **No prices** are
used — it's driven by the **dealer's own part‑group quantity targets + sales history**.

### Logic (all this month, company = Hero)
For dealer `D` (executive `EX = dealer.sales_executive_id`):

1. **Load D's part‑group targets** from `dealer_part_group_target` (`dealer_id = D`, `target_period = current month`, `target_qty > 0`).
2. **Per part**, from this month's sales, compute: `dealer_qty` (qty at D), `peer_qty`
   (qty at EX's *other* dealers), `peer_dealers` (count of those peers), and the part's `part_group`.
3. **Per targeted group**, `group_sold = Σ dealer_qty` over that group's parts. A group is
   **behind** when `group_sold < target`; `group_gap = target − group_sold`.
4. Only parts whose group is **behind** are eligible. Each suggestion carries the dealer's
   **group** progress: `group_sold`, `group_target`, `group_gap`, `group_pct = pct(group_sold, group_target)`.

```sql
-- Step 2: per-part dealer/peer quantities this month
SELECT b.item_code, MAX(pg.part_group) AS part_group, MAX(pg.description) AS description,
       SUM(CASE WHEN d.dealer_id = :D THEN b.quantity ELSE 0 END) AS dealer_qty,
       SUM(CASE WHEN d.sales_executive_id = :EX AND d.dealer_id <> :D
                THEN b.quantity ELSE 0 END) AS peer_qty,
       COUNT(DISTINCT CASE WHEN d.sales_executive_id = :EX AND d.dealer_id <> :D
                THEN d.dealer_id END) AS peer_dealers
FROM busy_sales_data b
JOIN dealer d ON d.name = b.particulars AND d.company_id = 1
LEFT JOIN part_groups pg ON pg.part_number = b.item_code AND pg.month = 'July'
WHERE <this-month>
GROUP BY b.item_code;
```

### Split & rank
- **GROW** — parts the dealer already buys (`dealer_qty > 0`) whose group is behind.
  - Each row also carries **`group_last6m`** = the dealer's qty in that part group over the
    **6 months before the current month** (current month excluded) — a prior baseline:
    `sale_date >= DATE_SUB(<1st of this month>, INTERVAL 6 MONTH) AND sale_date < <1st of this month>`.
  - **Sort by `group_gap` desc, then `dealer_qty` desc**; top 25.
- **NEW OPPORTUNITY** — parts the dealer doesn't buy (`dealer_qty = 0`) but peers do
  (`peer_qty > 0`), whose group is behind:
  - **Sort by `group_gap` desc, then `peer_dealers` desc**; top 25.

### Interpretation
- A part surfaces only when **this dealer is behind their own target for that part's group**.
- **Grow** = "you already sell this; you're behind your target for its group → push more" (with 6‑month baseline).
- **New opportunity** = "similar dealers stock this part; you don't, and you're behind on its group."

---

## 5. Consuming the existing APIs (recommended)

Instead of re‑implementing the SQL, the mobile app can call the web endpoints (JWT‑authenticated,
`Authorization: Bearer <token>`). All amounts/quantities are plain numbers; `pct` may be `null`.

### `GET /api/analytics/sales` — exec & dealer % achieved
Optional query filters: `executive_id`, `dealer_id`, `part_group`, `part`.
```jsonc
{
  "success": true,
  "month": "July 2026",
  "summary": { "total_sales": 11832606, "total_qty": 101663, "dealers": 99, ... },
  "by_executive": [ { "user_id": 12, "username": "office",
                      "sales": 7283093, "target": 1000000, "pct": 728.3 }, ... ],
  "by_dealer":     [ { "dealer_id": 118, "dealer": "Verma Auto Agencies | ...",
                      "sales": 5127246, "target": 200000, "pct": 2563.6 }, ... ],
  // by_part_group: qty + target_qty (Σ dealer-group targets in scope) + pct
  "by_part_group": [ { "part_group": "Clutch", "qty": 12570, "target_qty": 8200, "pct": 153.3 }, ... ],
  // by_part: qty only — parts have NO target
  "by_part":       [ { "item_code": "22201AAHA01S", "part_group": "Clutch", "qty": 8648 }, ... ],
  // by_dealer_group: every dealer×part-group target vs qty sold this period (Target Tracker)
  "by_dealer_group": [ { "dealer_id": 74, "dealer": "Janta ...", "part_group": "Clutch",
                         "target_qty": 55, "sold": 42, "pct": 76.4 }, ... ]
}
```

### `GET /api/analytics/dealer-suggestions?dealer_id=<id>` — suggestions
Progress shown is the dealer's **group** progress (`group_*`), not a per‑part/company figure.
```jsonc
{
  "success": true, "month": "July 2026",
  "dealer_id": 74, "dealer": "Janta Auto Parts | AFM | Meerganj",
  "grow": [ { "item_code": "22201AAHA01S", "part_group": "Clutch",
              "dealer_qty": 40, "group_sold": 42, "group_target": 55,
              "group_gap": 13, "group_pct": 76.4, "group_last6m": 0 }, ... ],
  "new_opportunity": [ { "item_code": "22201GF6000S", "part_group": "Clutch",
              "peer_dealers": 2, "peer_qty": 5, "group_sold": 42, "group_target": 55,
              "group_gap": 13, "group_pct": 76.4 }, ... ]
}
```

Mobile equivalents (JWT, scoped to the signed‑in exec): `GET /api/v1/analytics/my-summary`
and `GET /api/v1/analytics/dealer/<dealer_id>` (returns the dealer's sales/target/pct + `grow`/`new_opportunity`).

---

## 6. Edge cases & current data notes
- **Division by zero / missing target** → `pct = null` (render `—`). Suggestions need the dealer to have a `target_qty > 0` for the group.
- **Unmapped parts** (not in `part_groups`) → `part_group = "(Unmapped)"`, no group target, never suggested.
- **Targets are currently dummy**: `dealer_money_target.value_target = 200000` (flat rupee, period 2026-07-01); `dealer_part_group_target.target_qty` is seeded per dealer×group at ~0.7–1.6× the dealer's actual qty (some groups read over/under 100%). Replace with real targets — no formula change.
- **Not stored**: every number is recomputed per request from `busy_sales_data` + `part_groups` + `dealer` + the two target tables. No suggestion history / accept‑reject tracking yet.
- **Attribution is a name string‑match** (`particulars = dealer.name`); keep dealer names in sync between Busy and the `dealer` table.
- **Feeding targets** (per period; `target_period` = first day of the month, e.g. `2026-07-01`):
  - rupee: `dealer_money_target (dealer_id, target_period, value_target)` — one row per dealer.
  - quantity: `dealer_part_group_target (dealer_id, part_group, target_qty, target_period)` — one per dealer×part‑group.
