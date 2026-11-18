# Build spec: Dealer Payment Tracker (Cadila) — for Claude Code

## 1. Context and goal

I run a pharma distribution business (Anmol Associates, principal: Cadila). Dealer payments are posted into Tally manually by an accountant, days after the money arrives. So Tally's outstanding report is always behind reality.

Build a module in my existing app that:
1. Lets me log a dealer payment the moment I hear about it (bank transfer / cash), and shows it until Tally catches up.
2. Pulls post-dated cheques (PDCs) from my cheque reconciliation system and shows them against each dealer.
3. Takes two daily Tally exports (Outstanding with bill-wise voucher detail, and the Receipt Register), auto-closes my logged payments when Tally posts them, and shows bounced cheques from Tally's reversal (Boo) bills.
4. Flags suspected duplicate receipts in a "Manual check" list. Never auto-correct them.
5. Shows one daily dealer screen: who to chase, who to wait for (PDC), who is clear.

Fit this into my app's existing stack and conventions. Inspect the repo first. Ask me before adding a new framework or database.

Scope is only what's below. Do NOT build bank-statement matching, other principals, notifications, or anything marked optional.

---

## 2. Inputs

### 2.1 Dealer master (seed, provided)
File: `Cadila_Dealer_Master.csv` (35 rows). Columns:
`Dealer ID, Tally Ledger Name, Dealer Name, Principal, Town, Cheque System Name, Phone, Salesman, Exclude From Chase, Active, First Txn Date, Source`

- `Tally Ledger Name` is the join key to every Tally export. Match it EXACTLY: no trimming of inner spaces, no case changes. Example: `Shri Ram Pharma  | Cadila | Chandausi` has two spaces.
- `Dealer ID` (CAD-001…) is the app's stable ID.
- `Cheque System Name` maps cheque-system parties to dealers. If it's blank, fall back to `Tally Ledger Name`.
- `Exclude From Chase = Y` (Cadila Pharmaceuticals Limited) means never show the dealer on the chase list.
- Any party name in a Tally upload that isn't in the master gets added automatically with the next ID, and is flagged "New dealer" for me to review.

### 2.2 Tally Export 1: Outstanding (pending bills), group "Cadila Dist"
- Period: always `1-Apr-<FY start>` to export date. It's an "as of" snapshot.
- Sample file: `CADILA_1_1.xlsx`, sheet `Cadila Dist`. Layout:
  - Row 0: `Group : | Cadila Dist | | 1-Apr-26 to 14-Nov-26` (parse the as-of date from the end of this range)
  - Rows 3–4: two-line header: `Date, Ref. No., Party's Name, Opening Amount, Pending Amount, Post-Dated Amount, Final Balance, Due on, Overdue by days`
  - Party header row: only column C (Party's Name) is filled
  - Bill rows: Date + Ref. No. filled, under the most recent party header
  - Party subtotal row: no Date, no Ref, amounts filled. Skip it.
  - Grand total row(s) at the end. Skip them.
  - Note: the sample also contains a stray bill row (A000077) after a subtotal with no party header. Attach it to the last party seen, and log a warning.
- Preferred sample: `GrpBills.xlsx` (as of 17-Nov-26), exported WITH bill-wise voucher detail. Under each pending bill row, it lists the vouchers that created or adjusted that bill: `Date | (blank) | Vch Type | Vch No. | Amount` in columns A, C, D, E. Parse these as `bill_adjustments(as_of_date, dealer_id, ref_no, vch_type, vch_no, date, amount)`. Columns in this export: `Date, Ref. No., Party's Name/Vch Type, Vch No., Amount, -, Opening Amount, Pending Amount, Due on, Overdue by days`.
- **Bill refs:**
  - `^A\d{6}$` = Cadila sales invoice (debit).
  - `Boo <n>` = a bill created by a **Payment** voucher. In this business that's a **cheque-bounce / receipt reversal**, and it is a **DEBIT**: the dealer owes it again. Examples: M S Distributors `Boo 338558` = Payment 488, 22-Sep-26, 250,000, reversing Receipt 3842 of the same day. Shraddha `Boo 104059` = Payment 634, 27-Oct-26, 70,039, reversing Receipt 4766 of the same day.
- **Dr/Cr is in the cell NUMBER FORMAT, not the value.** Tally writes each amount as a positive number with the format `""0.00" Dr"` or `""0.00" Cr"`. pandas drops this, so read the amount cells with openpyxl and take the sign from `cell.number_format` (Cr = negative). This applies to bill lines, the voucher-detail lines (Receipt = Cr, Sales/Payment = Dr), subtotals and the grand total. Verified: Rishika Pharma credit notes CN00005 (44,457) and CN00006 (924) are Cr. All `Boo` lines are Dr. Signed bill lines sum exactly to Tally's grand total of 5,195,763 Dr (17-Nov-26). Use Tally's subtotals as a parser check: the signed sum per dealer must equal the subtotal.
- This report shows only bills with a pending balance. Fully cleared bills (and their receipts) are omitted.
- Store as a snapshot per as-of date: `tally_outstanding(as_of_date, dealer_id, ref_no, bill_date, opening_amt, pending_amt_signed, due_on, overdue_days)`.

### 2.3 Tally Export 2: Receipt Register
- Period: first load `1-Apr-<FY start>` to today; then daily the **last 60 days** to today.
- **Window reload:** on each upload, DELETE all stored receipts dated inside the file's date range, then insert the file's receipts. This catches backdated entries, edits and deletions in Tally. Never just append.
- Sample: `cadilaDayBook16Nov.xlsx`. Company header rows 0–8, the period on row 8, headers on rows 9–10 (`Date, Particulars, Vch Type, Vch No., Debit, Credit`), data from row 11, and a `Total:` row at the end. `Particulars` = dealer ledger name.
- Unique key: `(vch_no, date)`. Store `tally_receipts(vch_no, date, dealer_id, amount, upload_id)`.
- Why it's needed: Export 1 omits fully cleared bills, so a receipt that clears a bill completely disappears from it. The register is the only place the app sees every receipt, to auto-close my logged payments.
- No group vouchers export is needed. Bounces are already netted in Export 1.

### 2.4 My manual payment log (in-app form)
Fields: dealer (dropdown from master, never free text), mode (`BT` = NEFT/RTGS/UPI, `CASH`), amount, payment_date, reference (UTR, optional), proof image (optional), note.
Status: `OPEN` → `POSTED` (auto, on matching) | `CANCELLED` (manual).
The form must take under 10 seconds to fill on mobile.

### 2.5 PDCs from my cheque reconciliation system
- Create an adapter interface `fetchCheques(sinceDate) -> [{cheque_no, bank, party_name, amount, cheque_date, status}]`, with status in `HOLDING | DEPOSITED | CLEARED | BOUNCED`.
- Implement a stub/mock for now. I'll wire the real API later.
- Map `party_name` → dealer via `Cheque System Name`. Show unmapped cheques in the Manual check list.

---

## 3. Processing logic (run after every Tally upload, in this order)

### 3.1 Bounces (read from Export 1, no detection needed)
Tally already offsets bounces: the accountant reverses a bounced receipt with a **Payment** voucher, which appears in Export 1 as a **`Boo <n>` bill (Dr)**. Its voucher-detail line shows `Payment <vch no>`. So Tally O/S already includes the amount the dealer owes again.
- Label every `Boo` bill on the dealer screen "Bounced / reversed receipt: dealer owes again".
- If a logged payment or PDC of the same dealer and amount (±₹1) exists within 10 days before the Boo date, mark it `BOUNCED`.

### 3.2 Match my logged payments to Tally receipts
For each OPEN payment, oldest first, find a Tally `Receipt` voucher where:
- same dealer
- amount within ±₹10
- receipt date between payment_date − 2 days and payment_date + 20 days
- not already matched

Exactly one candidate → set the payment to `POSTED` and store the voucher key. More than one → leave it OPEN and add it to Manual check ("Ambiguous match"). A payment still OPEN more than 5 days after payment_date → flag it `STALE`.

### 3.3 Suspected duplicate receipts → Manual check (never auto-fix)
Flag a pair of receipts R1, R2 in Export 2 when:
- same dealer, amount within ±₹1, dates within 7 days of each other, and
- the dealer has NO `Boo` bill (Payment reversal) of that amount dated between or on R1/R2. If one exists, it's a bounce + re-payment, not a duplicate.

Label it `POSSIBLE DUPLICATE`. Also flag `CREDIT BALANCE` when a dealer's signed Export 1 total is Cr and isn't explained by credit notes (CN/SC refs).

Flags do NOT change any balance. They only appear in the Manual check list.

---

## 4. Daily dealer screen

Header: `Tally as of: <as_of_date of latest Export 1>` · `Vouchers loaded to: <max date of Export 2>`

One row per active dealer (exclude `Exclude From Chase = Y`):

| Column | Definition |
|---|---|
| Dealer | Dealer Name (Town) |
| Tally O/S | Sum of signed pending amounts from the latest Export 1 |
| Received, not in Tally | Sum of my OPEN payments for the dealer, plus its CLEARED cheques that Tally has no receipt for yet (same dealer, amount ±₹10, receipt dated cheque date − 2 … + 20 days, not already matched to a payment or an earlier cheque; only cheques dated from the start of the Receipt Register uploads) |
| PDCs held | Count, amount and next cheque date of HOLDING/DEPOSITED cheques |
| Effective O/S | Tally O/S − Received not in Tally |
| Overdue (amount · days) | The dealer's positive pending bills that are past due, as amount · days overdue (counted to today), bills overdue by the same days added together, oldest first |
| Action | `CLEAR` if Effective O/S ≤ 0 · otherwise, taking only the overdue part (overdue bills less payments not in Tally and credit balances, which settle the oldest first): `NOT DUE till <next due date>` if none is overdue · `WAIT till <next PDC date>` if PDCs held ≥ the overdue part · `CHASE` otherwise. If a bill that is not overdue has no due date, all of Effective O/S counts as overdue |

Sort: CHASE first, by Effective O/S descending.

Two small lists above the table:
- **PDCs due today/tomorrow** (to deposit)
- **Stale payments** (logged more than 5 days ago, still not in Tally)

**At the bottom: "Manual check"**, one line per flag: type (Possible duplicate / Credit balance / Ambiguous match / Unmapped cheque / New dealer), dealer, voucher no(s), dates, amounts, and a one-line reason. Each item has a "Reviewed" toggle with an optional note. Reviewed items hide but stay stored, and aren't re-flagged unless the underlying receipts change.

---

## 5. Acceptance tests (use real sample data in `/samples/`)

1. Parse `GrpBills.xlsx` (as of 17-Nov-26): grand pending total 5,195,763. Chandra Pharma: A000021 pending 50, adjusted by Receipt 3458. Shraddha: A000003 pending 19,144 + `Boo 104059` pending 70,039 (DEBIT) = 89,183. M S Distributors: `Boo 338558` from Payment 488, 250,000, pending 51,664 after Receipt 4121 (198,336). Katyayani: no pending bills.
2. M S Distributors `Boo 338558` and Shraddha `Boo 104059` show on the dealer screen labelled "Bounced / reversed receipt".
3. Log a BT for Kunj Medical Agency, 47,040, dated 16-Nov-26 → it auto-matches receipt 5342 and becomes POSTED.
4. Log a BT with no matching receipt → stays OPEN, and becomes STALE after 5 days.
5. Re-upload the same Receipt Register twice → no duplicate rows (window reload works).
6. Delete one receipt from a re-exported file → it disappears from the app.

Write the parsers as pure functions with unit tests on these samples before building any UI.

---

## 6. Build order
1. Dealer master table + CSV seed import
2. Export 1 parser + snapshot storage (+ tests)
3. Export 2 (Receipt Register) parser + 60-day window reload (+ tests)
4. Payment log form
5. Cheque-system adapter (stub)
6. Processing: bounce detection → payment matching → duplicate flags
7. Daily dealer screen + Manual check list
