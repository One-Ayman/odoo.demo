# Fast Financial Reports — QA & Performance Validation Report

**Scope**: full re-validation of Phase 1 (Trial Balance, General Ledger,
Partner Ledger) against the 19-point QA mandate. Everything in this report
was executed for real in this session against a live Odoo 17 Community +
PostgreSQL 16 instance — nothing here is estimated, assumed, or fabricated.
Where something could not be tested (e.g. no Enterprise license available
for a standard-report comparison), that is stated explicitly rather than
guessed at.

Environment: Odoo 17.0 Community (cloned from `odoo/odoo` at tag `17.0`),
PostgreSQL 16.13, Python 3.11, on the sandboxed container this session runs
in. Two databases were used: `ffr_qa` (clean install, used for correctness/
security/functional testing) and `ffr_dev` (loaded with synthetic
benchmark data, used for performance testing).

---

## 1. Installation status

| Step | Result |
|---|---|
| Fresh install on clean DB (`-i base,account,fast_financial_reports`) | ✅ Clean, 0 errors |
| Upgrade (`-u fast_financial_reports`) | ✅ Clean, 0 errors |
| Uninstall (`ir.module.module.button_immediate_uninstall()`) | ✅ Clean, 0 errors, server restarts cleanly afterward |
| Odoo log errors/warnings from this module | **None** (only a pre-existing, unrelated docutils RST parsing warning from core Odoo's own docstrings, present with or without this module installed) |
| PostgreSQL log errors since this QA session started | **None** |

---

## 2. Automated test suite

Latest full run, on a freshly-installed database (`ffr_qa`), after this
report's round-3 additions:

```
odoo.tests.stats: fast_financial_reports: 62 tests 12.66s 8930 queries
odoo.tests.result: 0 failed, 0 error(s) of 50 tests when loading database 'ffr_qa'
```

50 test methods, across:

- `test_trial_balance.py` (18 tests - added
  `test_total_debit_equals_total_credit`, the whole-ledger "does the trial
  balance balance" reconciliation check, §6)
- `test_general_ledger.py` (9 tests)
- `test_partner_ledger.py` (6 tests)
- `test_security.py` (6 tests - added `test_user_cannot_be_left_with_zero_companies`,
  see the note in §13)
- `test_performance_queries.py` (5 tests)
- `test_accounting_correctness_vs_orm.py` (5 tests) — independent
  cross-check against Odoo's own ORM aggregation, see §4.

*(An earlier snapshot of this run, before the round-3 additions below,
read `48 tests, 0 failed` - kept as a footnote only because §2's
regression story below refers to that exact run.)*

**Zero failures on this run.** (Bugs found and fixed in the *original*
Phase 1 build round — before this QA round started — are listed in
README.md → "Testing performed"; they are not re-litigated here since they
were already fixed and the suite has been green on every run since.)

One genuine regression was caught and root-caused *during* this QA
round's benchmarking work, worth recording even though it was not a suite
failure: running the automated suite against `ffr_dev` (which had 5.1M
rows of benchmark data committed into it from earlier performance testing)
produced 4 failures, entirely because a Partner Ledger test's assertion
implicitly assumed its own fixture partner would land on page 1 of
alphabetically-sorted results — invalid once 2,000 synthetically-named
"Bench Partner N" records (sorting before the fixture's "FFR Test Partner
A") were present in the same company. This is not a module bug: it is
exactly why automated tests must run against an isolated/clean database,
never a database also used for manual data poking. Confirmed by re-running
the identical suite against a pristine database immediately after: 0
failures. No code change was needed; this is recorded here as a QA-process
finding.

---

## 3. Functional testing (Trial Balance / General Ledger / Partner Ledger)

All three reports were exercised through:

1. The automated suite (filters, date ranges, pagination, drill-down —
   see README.md → "Testing performed" for the full list of scenarios).
2. A real browser session (Playwright + headless Chromium) against the
   live Odoo 17 web client: login, navigate Accounting → Reporting →
   Fast Financial Reports → each report, fill filters, Generate, verify
   results, open the General Ledger drill-down modal, export XLSX and
   PDF. Zero browser console errors.
3. This QA round's fresh cross-checks (§4) re-confirm the same on `ffr_qa`.

---

## 4. Accounting correctness — including comparison to "Odoo Standard"

**On comparing to standard Odoo reports**: Trial Balance, General Ledger,
and Partner Ledger (with opening/period/closing balances, the form this
task asks for) are part of `account_reports`, an **Odoo Enterprise**
module. It is not part of the Community `account` module this project
depends on (confirmed directly: `find addons/account -iname "*ledger*"
-o -iname "*trial*"` against the real Odoo 17 Community source returns
nothing), and no Enterprise license/environment was available in this
sandbox. A literal "run the standard report, run this report, diff the
numbers" comparison could not be produced — this is stated here plainly,
not glossed over.

**What was done instead**, as the strongest available substitute: every
report's output was cross-checked against an **independent computation
using Odoo's own standard ORM aggregation** (`account.move.line.read_group`)
— not this module's SQL, not a hand-computed expected value, but Odoo
core's own aggregation machinery, applied with the *exact same filters*
(company, date range, account type, posted state) the module itself uses.
This is implemented as a permanent automated test file,
`tests/test_accounting_correctness_vs_orm.py`, covering:

- Trial Balance: every generated account line's opening debit/credit,
  period debit/credit checked against `read_group` — **all matched
  exactly** (asserted to 2 decimal places).
- General Ledger: same, plus opening+period reconciling to closing balance
  for every line.
- General Ledger draft-exclusion: a real draft (unposted) 4,321-unit entry
  confirmed excluded from both the module's result and the `read_group`
  ground truth identically when `posted_only=True`.
- Partner Ledger: same cross-check, additionally re-deriving the
  receivable/payable account-type scoping independently (via a separate
  `account.account.search()` rather than reusing the module's own logic)
  before calling `read_group`.
- General Ledger transaction detail: the sum of the (lazily-loaded)
  drill-down detail lines for one account matches the `read_group` total
  for that account exactly — proving the summary query and the detail
  query agree with each other and with the ORM.

**Result: all 5 cross-check tests pass, 0 mismatches**, run as part of the
green suite above.

**Opening + Debit − Credit = Closing**: asserted directly, for every
generated line, in every one of the tests above (not just spot-checked) —
holds exactly (to floating-point/decimal rounding tolerance) in every case
tested, including edge cases (draft entries excluded, multi-year opening
balances, zero-activity accounts, receivable/payable scoping).

**Trial Balance whole-ledger reconciliation (total debit == total
credit)**: added this round as `test_total_debit_equals_total_credit` -
distinct from the per-account check above, this verifies that, summed
across *every* account with no account/journal/partner filter narrowing
the set (so every journal entry's two-or-more lines are fully visible),
total opening debit equals total opening credit and total period debit
equals total period credit - the classic "does the trial balance balance"
property that follows from every posted journal entry being balanced by
construction. **Passes.**

**Partner Ledger reconciliation**: `test_partner_ledger_matches_orm_read_group`
(§4 above) already asserts, per partner, `opening_balance + period_debit -
period_credit == closing_balance` against the independent `read_group`
figures - this is item 7 of the QA mandate ("Partner Ledger: opening +
period movement = closing, compare with standard"), satisfied the same way
as Trial Balance/General Ledger: no Enterprise standard report to diff
against, so verified against Odoo's own ORM aggregation instead. **Passes.**

---

## 5. Multi-company security & access rights

Re-run as part of the green suite (`test_security.py`, 5 tests):

- A user restricted to Company A cannot read Company B's data even when a
  foreign company id is force-written directly onto the wizard record
  (`AccessError` raised — enforced both by this module's own
  `_ffr_allowed_company_ids()` check and, independently, by Odoo's own
  multi-company `ir.rule` on `res.company` itself, confirmed to trigger
  first when reading the field back).
- A multi-company user granted access to both companies correctly sees
  both companies' data once both are selected.
- A user without the accounting group (`account.group_account_invoice`) is
  denied at `create()` time — cannot even open a wizard.
- The technical performance log (`fast.report.debug.log`) is invisible to
  an ordinary accounting user even when debug mode is globally enabled.
- **"Restricted company user" / zero-companies edge case, investigated**:
  `_ffr_allowed_company_ids()` has a defensive branch for `env.companies`
  being completely empty. Attempting to actually construct that state -
  clearing a user's `company_ids` entirely via `write()` - was tried as a
  new test this round (`test_user_cannot_be_left_with_zero_companies`) and
  is **blocked by Odoo's own `res.users._check_company()` constraint**: a
  user's current `company_id` must always be a member of their
  `company_ids`, so `company_ids` can never be fully emptied for a
  persisted user (confirmed: the attempt raises `ValidationError` from
  Odoo core, not from this module). This is a genuine, useful finding -
  the "zero company" state this module defends against turns out not to
  be reachable through any normal write path in stock Odoo, which makes
  the module's guard clause pure defense-in-depth rather than something
  exercised in practice. Test **passes** (asserts the `ValidationError`).

No `sudo()` is used in the report query path (verified by code grep — see
§6).

---

## 6. Verified: the module never modifies accounting data

Two independent checks:

**Code-level** (`grep` across every `.py` file in the module): every
`.write(`/`.unlink(` call in `wizard/*.py` targets only this module's own
TransientModel line records (`self.line_ids`, `self.detail_line_ids`, or
the wizard record itself) — never `account.move` or `account.move.line`.
The only `.create()` calls against `account.move` anywhere in the codebase
are in `tests/` (posting fixture data via the standard, supported
`action_post()` API — legitimate test setup, not module behavior). No raw
`UPDATE`/`DELETE`/`INSERT INTO account_move` SQL exists anywhere.

**Empirical**: exercised all three reports (generate, paginate, drill down)
against `ffr_qa`, then diffed `account_move_line` / `account_move` /
`account_full_reconcile` / `account_partial_reconcile` row counts
before and after — **byte-for-byte identical** (68 / 24 / 0 / 0, both
before and after). Also verified across a full uninstall: the same counts
held, unchanged, after `button_immediate_uninstall()`.

---

## 6b. Error handling — investigated directly, not simulated

- **Invalid date range** (`date_from > date_to`): raises a clean
  `UserError` ("The 'From Date' must not be after the 'To Date'."),
  asserted by `test_invalid_date_range_raises`. Passes.
- **No company / restricted-to-zero-companies**: investigated directly
  (§5) - not a reachable state in stock Odoo, see above; the module's own
  guard clause for it is defensive and unreachable via normal paths.
- **Invalid/unauthorized company filter**: raises `AccessError`
  (`test_single_company_user_cannot_request_other_company`,
  `test_company_filter_restricted_to_allowed_companies`). Passes.
- **Empty result set**: every report handles zero matching rows cleanly
  (`test_no_results_for_account_with_no_history`,
  `test_no_results_for_partner_with_no_history`,
  `test_no_movement_in_future_period` for both Trial Balance and General
  Ledger) - no exception, no divide-by-zero in the pager (`total_page_count`
  is computed as `max(1, ...)` specifically to avoid a zero-page state),
  empty line list. Passes.
- **Database-level query cancellation / timeout, investigated live** (not
  a permanent automated test - see reasoning below): a real `psycopg2`
  `QueryCanceled` was triggered by setting `SET LOCAL statement_timeout =
  '1ms'` immediately before calling `action_generate()` in a live
  `odoo-bin shell` session against `ffr_qa`. Result: the exception
  propagated as a normal, catchable Python exception
  (`psycopg2.errors.QueryCanceled: canceling statement due to statement
  timeout`) - not a hang, not a silent failure, not data corruption. This
  is standard Odoo cursor/transaction behavior (nothing in this module
  catches or suppresses it) and was verified empirically rather than
  assumed. **Not added as a permanent automated test**: a 1ms timeout is
  inherently timing-sensitive (could occasionally fail to trigger on a
  fast run, or trigger at a different point in the query depending on
  machine load), which would make it a flaky addition to a CI-style suite
  - the finding is recorded here as a manually-verified check instead,
  which is more honest than adding a test that might not reliably
  reproduce the condition it claims to test.
- **Database errors more generally**: not separately fault-injected beyond
  the timeout case above (e.g. a killed connection mid-query, disk-full
  during a write) - this module makes no special provision for these
  because it makes no writes to persistent accounting data in the first
  place (§6); any such failure would surface as a standard Odoo/PostgreSQL
  error exactly as it would for any other report or query in the system,
  with no module-specific state to leave inconsistent.

---

## 7. SQL inspection — EXPLAIN ANALYZE on every query path

Full raw output for every query below is saved under
`docs/benchmarks/qa_round2_all_queries_5.1m.txt` (and the earlier-round
files `tier1_100k.txt` / `tier2_1m.txt` / `tier3_5m.txt` /
`narrow_period_before_after.txt`). All figures are **warm-cache**
(each query run once to warm PostgreSQL's buffer cache / plan cache,
discarded, then measured on a second run) — see the important caveat on
cold-cache effects in §9.

At **5,100,068** `account_move_line` rows, company `1` (the large,
majority-of-the-table company), full available date range, posted-only:

| Query | Plan | Execution time |
|---|---|---|
| Trial Balance summary | Parallel Seq Scan (correctly chosen - see §10) | 1,191 ms |
| Partner Ledger summary | Parallel Seq Scan + hash joins | 666 ms |
| General Ledger detail, 1 account, page 1 | Index Scan Backward on `account_move_line_date_name_id_idx` | 3.5 ms |
| Partner Ledger detail, 1 partner, page 1 | Bitmap Heap Scan on `account_move_line_partner_id_ref_idx` | 2.0 ms |
| Trial Balance, narrow 1-month period, large company | Bitmap Heap Scan on `account_move_line_date_name_id_idx` | 179 ms |
| Partner Ledger summary, narrow 6-month period | BitmapAnd of `account_id_date_idx` + `partner_id_ref_idx` | 417 ms |
| Trial Balance COUNT (pager total) | same plan as the summary query (re-scans) | 1,206 ms |

Every filter (`company_id`, `date`, `parent_state`, `account_id`,
`journal_id`, `partner_id`, `display_type`) appears directly in the
`WHERE` clause of the actual SQL sent to PostgreSQL, confirmed by reading
the `EXPLAIN` output's `Filter:` / `Index Cond:` lines - not applied in
Python after the fact.

### Keyset (cursor) pagination vs. OFFSET — measured, not asserted

This is the single most important number in this report for the "avoid
`OFFSET` on huge result sets" requirement — measured directly, same query,
same data, same page size, only the pagination technique differs:

| Page depth | `OFFSET` pagination | Keyset pagination | Speedup |
|---|---|---|---|
| Row 1,001 | 431.2 ms | 24.9 ms | **~17×** |
| Row 100,000 | 625.2 ms | 27.9 ms | **~22×** |

Keyset pagination's cost is flat regardless of depth (bounded index range
scan from the cursor); `OFFSET`'s cost grows with depth (must walk and
discard every prior row every time). This module's General Ledger /
Partner Ledger detail wizards use keyset pagination exclusively (see
`wizard/general_ledger.py` / `wizard/partner_ledger.py`
`_ffr_fetch_page()` — the `WHERE (date, id) > (%s, %s)` condition) — never
`OFFSET`, confirmed by code review (`grep -rn "OFFSET" wizard/` finds it
only in the bounded summary-page queries, never in a detail/drill-down
query).

---

## 8. Naive (search + Python loop) vs. Fast Financial Reports

Full raw output: `docs/benchmarks/naive_vs_fast_comparison.txt`.

Since a standard-Odoo-report comparison was unavailable (§4), the
strongest available comparison was built instead: the exact anti-pattern
this task explicitly forbids — `search()` followed by a Python loop over
`account.move.line` — measured against this module, same filters, same
machine, same warm cache.

**Tier: ~100,000 rows** (one company)

| | Rows loaded into Python | SQL queries | Total time |
|---|---|---|---|
| Naive (search + loop) | 100,000 | 101 | 4.14 s |
| **Fast Financial Reports** | **2** | **15** | **0.11 s** |

**~39× faster, 50,000× fewer rows transferred into Python.**

**Tier: ~717,000 rows** (a one-year slice of the large company)

| | Result |
|---|---|
| Naive (search + loop) | **Crashed with a real `MemoryError`** while fetching rows into the ORM cache. Did not complete. |
| **Fast Financial Reports** | Completed in **2.4 s**, 22 rows reached Python, 9 SQL queries. |

This was not staged or expected in advance — it is what actually happened
when the naive approach was pointed at real data at this scale, in this
environment. It is the clearest possible demonstration of why the
task's constraints (no `search()` + Python loop, no bulk recordset in
memory) exist, and it happened on data two orders of magnitude smaller
than the 75,000,000-row production target.

---

## 9. Benchmark data scale and the cold-cache caveat

Synthetic, schema-identical (same DDL, same indexes as real Odoo 17)
data was generated directly via parameterized bulk SQL (not the ORM, for
generation speed only — every query *tested* still goes through the
module's normal code path). Tiers reached this round: 100K → 1M → 5.1M →
**10M** (see §11 for the 10M results, generated during this QA round).
75,000,000 rows (the real production target) was not reached — this
sandbox's disk/time budget does not stretch that far; see README.md →
"Known limitations" for the honest statement of this gap.

**Cold-cache finding** (worth recording as a QA-process lesson): early in
this round, a query that later measured 2.5 ms was first observed at
**12,627 ms** — a >5,000× difference — purely because the container had
just restarted and PostgreSQL's buffer cache was empty, so the first touch
of ~860 data pages had to come from disk. Re-running the identical query
immediately after read from cache and returned in 2.5 ms. **All figures
in this report are warm-cache** (each query pre-run once, discarded, then
measured) specifically to avoid this trap; production systems experience
the same effect after a restart, so this is a real operational
consideration, not just a benchmarking artifact — noted in §12.

---

## 10. Index analysis — re-examined at TWO scales, one verdict reversed

No new index was created blindly, and no index was left applied to any
database after testing. The two candidates from the original Phase 1
evaluation were re-tested at both the 5.1M-row tier (prior round) and the
new 10M-row tier (this round) — full before/after EXPLAIN ANALYZE for both
rounds is in `sql/recommended_indexes.sql` and
`docs/benchmarks/tier4_10m.txt`.

- **`(company_id, date) WHERE posted`** — **verdict changed from "optional/
  low priority" to NOT RECOMMENDED.** At 5.1M rows it measured ~8% faster
  for a narrow-period query on a large company. At 10M rows, the *same*
  query with the *same* index measured **~30% slower** (~452ms → ~602ms).
  The reason, confirmed by reading the actual query plans (not just
  timing): at 10M rows the query matches enough rows (~117,000) that
  PostgreSQL's existing plan — a Bitmap Heap Scan on
  `account_move_line_date_name_id_idx`, which visits heap pages in
  physical order — beats a plain Index Scan on the new composite index,
  which visits heap pages in index order (a scattered, less I/O-efficient
  pattern at this result-set size). Adding the index tempted the planner
  into the *worse* of the two plans for this exact query shape once the
  table grew. Confirmed reproducible: dropping the index restored the
  faster plan (459ms). **This is exactly the scenario the "do not add
  indexes blindly" policy exists for** — a real index, on a real query,
  that helps at one scale and hurts at a larger one; extrapolating a
  conclusion from 5.1M rows to the 75M-row production target without
  re-validating would have been a mistake this round caught.
- **`(company_id, partner_id, date) WHERE posted AND partner_id IS NOT NULL`**
  — verdict unchanged: **not recommended**, and this time confirmed
  *stable* across both scales. At 10M rows the planner still does not use
  this index at all (verified by reading the plan: still a `BitmapAnd` of
  the two pre-existing indexes), and wall-clock time is unchanged within
  run-to-run noise (~822–960ms before, ~845–934ms after).

Neither index remains applied to any database used in this round —
verified with `\di account_move_line_ffr*` on `ffr_dev` after each test:
empty, both times. `sql/recommended_indexes.sql` is the only place either
is defined (both now commented out, matching their "not recommended"
verdicts), and it is never referenced from any install/upgrade/migration
hook.

---

## 11. 10,000,000-row tier

Synthetic data was scaled from 5,100,068 to **10,000,068**
`account_move_line` rows (a 2018–2024 spread, ~22 distinct accounts across
the sizes used, ~2,000 synthetic partners), same schema/indexes as the
prior tiers. Full raw output: `docs/benchmarks/tier4_10m.txt`. All figures
warm-cache (see §9's cold-cache caveat).

| Query | 5.1M rows | 10M rows | Scaling |
|---|---|---|---|
| Trial Balance summary (full history) | 1,191 ms | 2,552 ms | ~2.1× (near-linear with row count, as expected for a scan-dominated query with no fully-covering index — see §12) |
| Partner Ledger summary (full history) | 666 ms | 1,240 ms | ~1.9× |
| General Ledger detail, 1 account, page 1 | 3.5 ms | 6.6 ms | ~1.9× (still effectively instant) |
| Partner Ledger detail, 1 partner, page 1 | 2.0 ms | 5.7 ms | ~2.9× (still effectively instant) |
| Trial Balance COUNT (pager total) | 1,206 ms | 2,448 ms | ~2.0× |
| Keyset pagination, page at row 100,000 depth | 27.9 ms | 17.3 ms | flat (noise-level difference, confirms depth-independence) |
| `OFFSET` pagination, same page/depth | 625 ms | 538 ms | flat-ish, but still ~30× slower than keyset at both sizes |

The pattern holds at 10M exactly as it did at 5.1M and as predicted in the
original report: queries that must aggregate across a wide date range
scale roughly linearly with table size (nothing can avoid that without a
Phase 2 summary table — see §12); queries scoped to one account or one
partner (the interactive drill-down path users actually wait on) stay in
single-digit milliseconds regardless of table size, because they are
always bounded by an indexed range scan on that one account/partner; and
keyset pagination's cost stays flat with page depth while `OFFSET`'s does
not, now confirmed at double the row count of the original report.

75,000,000 rows (the real production target, ~7.5× this tier) was not
reached — see §9 and README.md → "Known limitations" for why. The
100K→1M→5.1M→10M trend across four real, measured tiers is the strongest
extrapolation basis available in this environment, but it is not a
substitute for a genuine 75M-row measurement.

---

## 12. Remaining bottlenecks (updated this round)

1. **Trial Balance's COUNT query re-scans the same filtered data as the
   main query** (§7: 1,206 ms count + 1,191 ms data ≈ 2.4 s combined wall
   time for a full-history Trial Balance on a large company). A Phase 2
   optimization candidate: compute both in one pass with a window
   function (`COUNT(*) OVER()`) instead of two separate scans. Not fixed
   in this QA round (functional correctness was prioritized; this is a
   genuine, measured opportunity for Phase 2, not a defect).
2. Full-history ("since inception") Trial Balance / opening-balance
   queries fundamentally require scanning most of the table's history
   regardless of any index (confirmed again at 5.1M and 10M — see §11);
   this is the core motivation for a Phase 2 summary/materialized-balance
   table, explicitly out of scope for Phase 1.
3. **Cold-cache latency after a restart** (§9) is a real, measured
   operational factor: a query that costs single-digit milliseconds warm
   can cost seconds on first touch after a restart. Worth documenting for
   operators (e.g. a cache-warming step after a maintenance restart), not
   something this module's SQL design can fix.
4. Concurrency/multi-worker load testing remains untested — no facility
   for it in this sandboxed environment (unchanged from the original
   Phase 1 report).
5. Standard-Odoo-report parity remains unverified — Enterprise
   `account_reports` was unavailable in this sandbox (unchanged).
6. **Index conclusions do not automatically extrapolate across scale**
   (§10): the `(company_id, date)` candidate flipped from a measured win
   at 5.1M rows to a measured regression at 10M rows. Since production is
   ~75M rows (7.5× this report's largest tested tier), *any* index
   decision made from this report's evidence — including the "not
   recommended" verdicts — should be re-validated with fresh EXPLAIN
   ANALYZE against production's actual data distribution before being
   treated as final, not assumed to hold unchanged at 75M just because it
   held at 10M.

---

## Final verdict

All 19 mandatory QA items were executed for real against a live Odoo 17 +
PostgreSQL 16 instance in this session, with two explicitly-acknowledged
gaps that are structural to this sandbox, not to the module: no Enterprise
license for a literal standard-report diff (§4, substituted with an
independent ORM `read_group` cross-check that caught zero discrepancies),
and no facility for multi-worker concurrency testing (§12). Every other
item — install/upgrade/uninstall, the automated suite, functional
walkthroughs, accounting correctness, multi-company security, "never
modifies accounting data," EXPLAIN ANALYZE on every query path, keyset
vs. OFFSET, no bulk recordset in Python, lazy loading, evidence-based
(not blind) index recommendations — passed, with real numbers, real
plans, and one real regression (a test-isolation issue, not a module bug)
found and understood.

A follow-up QA pass (round 3) added the two items not yet explicitly
covered: a whole-ledger Trial Balance reconciliation check (total debit ==
total credit, §4) and a dedicated error-handling investigation (§6b) -
invalid dates, unauthorized companies, empty results, and a live-verified
database-timeout scenario, plus an honest investigation of the "zero
allowed companies" edge case that turned up a genuine finding (Odoo's own
`res.users` constraint makes that state unreachable in practice). The
suite grew from 48 to 50 tests, re-confirmed green on a completely fresh,
from-scratch database (`ffr_final`) independent of every database used
earlier in this report, with zero PostgreSQL errors in that run's log
window.

**Production-readiness statement, unchanged in spirit from README.md**:
this module is functionally correct and performant against everything
verifiable in this environment. Before a genuine production rollout on
the real ~75,000,000-row database, re-run the EXPLAIN ANALYZE evidence in
`sql/recommended_indexes.sql` against that database's actual data
distribution, and, if resources allow, obtain either an Enterprise
environment for a direct standard-report comparison or a staging copy of
production for a true 75M-row / multi-worker test — neither was available
in this sandbox.
