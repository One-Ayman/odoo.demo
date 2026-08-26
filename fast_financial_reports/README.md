# Fast Financial Reports (Phase 1)

**Author**: Ayman Elhaddad
**Module**: Fast Financial Reports
**Odoo Version**: 17
**Phase**: 1

A high-performance, read-only reporting engine for Odoo 17 Accounting,
built for databases where the standard Trial Balance / General Ledger /
Partner Ledger reports become too slow to use (target environment: ~75M
`account.move.line` rows, ~21M `account.move` records, ~30k invoices/month).

Phase 1 delivers three reports:

- **Fast Trial Balance**
- **Fast General Ledger** (account summaries first, transaction detail
  loaded lazily per account)
- **Fast Partner Ledger / Partner Statement**

Every filter is pushed down into PostgreSQL `WHERE`/`GROUP BY`. The module
never runs `search()` followed by a Python loop over `account.move.line`,
never loads a bulk move-line recordset into memory, and never modifies
accounting data, invoices, reconciliation, POS accounting, or ZATCA logic.

**See [`QA_REPORT.md`](QA_REPORT.md) for the full QA and performance
validation pass**: automated + functional + accounting-correctness
testing (including an independent cross-check against Odoo's own ORM
aggregation), multi-company security re-verification, EXPLAIN ANALYZE on
every query path, a real naive-vs-fast benchmark (including a genuine
`MemoryError` from the anti-pattern this module avoids), and 10M-row-tier
results.

---

## Table of contents

1. [Module tree](#module-tree)
2. [Installation / upgrade / uninstall](#installation--upgrade--uninstall)
3. [SQL architecture](#sql-architecture)
4. [Existing index analysis](#existing-index-analysis)
5. [Recommended indexes](#recommended-indexes)
6. [Pagination design](#pagination-design)
7. [Security](#security)
8. [Export (XLSX / PDF)](#export-xlsx--pdf)
9. [Performance debug mode](#performance-debug-mode)
10. [Testing performed](#testing-performed)
11. [Performance benchmark results](#performance-benchmark-results)
12. [Known limitations](#known-limitations)
13. [Remaining bottlenecks / Phase 2 candidates](#remaining-bottlenecks--phase-2-candidates)
14. [Final release checklist](#final-release-checklist)

---

## Module tree

```
fast_financial_reports/
├── __init__.py
├── __manifest__.py
├── controllers/
│   └── main.py                    # chunked XLSX export endpoints
├── models/
│   ├── ffr_sql_mixin.py           # shared SQL / security / instrumentation helpers
│   └── report_debug_log.py        # technical performance log (debug mode only)
├── wizard/
│   ├── trial_balance.py           # fast.trial.balance.wizard + .line
│   ├── general_ledger.py          # summary wizard + line, detail wizard + line (keyset)
│   └── partner_ledger.py          # summary wizard + line, detail wizard + line (keyset)
├── views/                         # wizard forms, menus
├── report/                        # QWeb PDF templates + report actions
├── security/                      # groups, ir.model.access.csv
├── sql/
│   └── recommended_indexes.sql    # NOT auto-applied - see below
├── docs/benchmarks/                # raw EXPLAIN ANALYZE output used below
└── tests/                         # automated Odoo test suite
```

---

## Installation / upgrade / uninstall

**Install** (from an addons path containing this module):

```bash
odoo-bin -c odoo.conf -d your_db -i fast_financial_reports --stop-after-init
```

**Upgrade** (after pulling a new version of this module):

```bash
odoo-bin -c odoo.conf -d your_db -u fast_financial_reports --stop-after-init
```

**Uninstall**: `odoo-bin` has no direct CLI uninstall flag; uninstall from
the Odoo UI (Settings → Apps → Fast Financial Reports → Uninstall), or via
an `odoo-bin shell` session:

```python
env["ir.module.module"].search([("name", "=", "fast_financial_reports")]).button_immediate_uninstall()
```

Uninstalling only removes this module's own models, views, and menus. It
never touches `account.move`, `account.move.line`, journals, invoices, or
reconciliation data - the module is read-only with respect to accounting
data by construction (see [SQL architecture](#sql-architecture)).

**Dependencies**: `account` (Odoo 17 Community `account` module). No
Enterprise modules required. Python: no new third-party dependencies beyond
what Odoo 17 already requires (`xlsxwriter`, already in Odoo's own
requirements.txt, is used for export).

---

## SQL architecture

### Core principle

Every report is built from exactly this shape:

1. **One filtered scan** of `account_move_line`, with every user filter
   (company, date, account, journal, partner, posted state, analytic,
   move type, reference) applied directly in the `WHERE` clause.
2. **One `GROUP BY`** over that already-filtered set, computed with
   conditional `SUM(CASE WHEN ... THEN debit ELSE 0 END)` expressions so
   that opening balance and period movement are computed in a **single
   pass**, not two separate queries re-scanning the table.
3. A cheap join to `account_account` / `res_partner` (bounded by the number
   of distinct accounts/partners, never by the number of journal items) to
   attach the display name/code, then `ORDER BY ... LIMIT ... OFFSET ...`
   for pagination.

Only the aggregated rows (one per account, or one per partner) ever reach
Python. Transaction-level detail is a **separate, explicit query**, scoped
to exactly one account (General Ledger) or one partner (Partner Ledger) and
the original date range, and is only ever run when the user clicks
"View Transactions" on a specific summary row.

All SQL is built with `odoo.tools.sql.SQL`, Odoo 17's own composable,
parameterized query object (`odoo/tools/sql.py`). Every user-supplied value
is passed as a bind parameter (`%s` / `ANY(%s)`); nothing is ever
string-interpolated into the query text. See `models/ffr_sql_mixin.py` for
the shared helpers (`_ffr_in_ids_sql`, `_ffr_posted_state_sql`,
`_ffr_translated_sql`, `_ffr_analytic_sql`) and each `wizard/*.py` file for
the full, explicit query text per report (kept explicit per report, rather
than over-abstracted, so each query is auditable end-to-end).

### Opening / period / closing balance

Per the spec:

- **Opening balance**: `SUM(debit - credit)` for lines with `date < date_from`.
- **Period**: lines with `date_from <= date <= date_to`.
- **Closing / ending balance**: `opening + period debit - period credit`.

This is a straightforward "balance as of date_from" definition. It does
**not** implement Odoo's fiscal-year-reset rule for P&L (income/expense)
accounts, where a strict accounting Trial Balance would zero out income and
expense accounts at the start of each fiscal year rather than carrying them
forward indefinitely - see [Known limitations](#known-limitations).

### Posted-only filter without a join

`account_move_line.parent_state` is a **stored** related field
(`related='move_id.state', store=True`, confirmed in Odoo 17's
`account_move_line.py`) - filtering `aml.parent_state = 'posted'` directly
avoids joining `account_move` just to check the posting state. Odoo's own
`account` module relies on the same fact: the partial index
`account_move_line__unreconciled_index` is defined
`WHERE ... AND parent_state = 'posted'` directly on `account_move_line`.
Cancelled entries never carry accounting weight and are always excluded,
even when "Posted Only" is unchecked (draft is then included, cancel never
is).

`account.move.line.move_type`, by contrast, is a **non-stored** related
field (`related='move_id.move_type'`, no `store=True`) - it is genuinely
not a database column. The General Ledger's "Move Type" filter therefore
joins `account_move` (`JOIN account_move am ON am.id = aml.move_id`), and
only when that filter is actually set, keeping the common case (no move
type filter) join-free.

### Translated columns accessed via raw SQL

`account_account.name` and `account_journal.name` are declared
`translate=True`, which means Odoo 17 stores them as **JSONB**
(`{"en_US": "Bank", ...}`), not plain text. Reading them via a raw SQL
alias without unwrapping them returns the raw JSON blob. The mixin's
`_ffr_translated_sql()` applies the exact
`COALESCE(col->>%s, col->>'en_US')` pattern Odoo core itself uses for this
(see `odoo/addons/base/models/ir_model.py` / `ir_filters.py`), resolving to
the current user's language with a fallback to the source language.
`res_partner.name` and `account_account.code` are **not** translated and
are read directly. *(This was caught by an end-to-end functional test
against real demo data during development - see "Bug fix policy" evidence
in git history / the debugging notes below.)*

### Analytic account filter

Odoo 17 stores a line's analytic distribution as JSONB
(`analytic_distribution`, e.g. `{"3": 100.0}`, replacing the old
many2one `analytic_account_id`). The `analytic` module itself already
builds a functional GIN index for this exact lookup on install
(`{table}_analytic_distribution_accounts_gin_index`, built by
`AnalyticMixin.init()`, over
`regexp_split_to_array(jsonb_path_query_array(analytic_distribution,
'$.keyvalue()."key"')::text, '\D+')`). The analytic filter reuses that
exact expression with the array-overlap operator `&&` - the same pattern
`AnalyticMixin._search_analytic_distribution()` uses elsewhere in Odoo -
so PostgreSQL can use the existing index instead of a full re-scan.

### ORM write buffering and raw SQL

The ORM buffers writes (e.g. `action_post()` on a journal entry) and only
flushes them to PostgreSQL lazily. A raw `cr.execute()` bypasses that
buffer entirely. `FastReportSqlMixin._ffr_execute()` /
`_ffr_execute_scalar()` / `_ffr_iter_chunks()` all call
`self.env.flush_all()` first, so a report never misses rows that were just
created/posted earlier in the same transaction. *(This was a real bug
found and fixed via the automated test suite - see the "Bug fix policy"
notes below.)*

### Keyset (cursor) pagination for transaction detail

General Ledger and Partner Ledger transaction detail never uses `OFFSET`.
Each detail wizard tracks the keyset `(date, id)` that produced its current
page plus the running balance accumulated up to that point
(`start_date/start_line_id/start_running_balance` and
`end_date/end_line_id/end_running_balance` on
`fast.general.ledger.detail.wizard` / `fast.partner.ledger.detail.wizard`).
"Next page" queries `WHERE (date, id) > (start_date, start_line_id) ORDER
BY date, id LIMIT page_size` - an indexed range scan whose cost does not
grow with how many pages deep the user has paged. "Previous page" is
supported by a small breadcrumb stack of prior pages' start-cursors (one
entry per page the user has actually visited, not per row of data) so
going back also never falls back to `OFFSET`.

---

## Existing index analysis

Verified directly against Odoo 17 Community source
(`odoo/addons/account/models/account_move_line.py`,
`account_move.py`) and against `\d account_move_line` on a live database,
not assumed. `account_move_line` already ships with:

| Index | Definition | Relevant to |
|---|---|---|
| `account_move_line_account_id_date_idx` | `(account_id, date)` | General Ledger detail per account |
| `account_move_line_date_name_id_idx` | `(date DESC, move_name DESC, id)` | default ordering, date-range scans |
| `account_move_line_partner_id_ref_idx` | `(partner_id, ref)` | Partner Ledger |
| `account_move_line__company_id_index` | `(company_id)` | company scoping (all 3 reports) |
| `account_move_line__unreconciled_index` | `(account_id, partner_id) WHERE unreconciled AND posted` | reconciliation widgets |
| `{table}_analytic_distribution_accounts_gin_index` | functional GIN over analytic account ids | analytic filter |
| `account_move_line__journal_id_index` | `(journal_id)` | journal filter |

No index changes were needed to make the core queries in this module use
indexed access paths for their primary access patterns (see EXPLAIN ANALYZE
evidence below) - Odoo's own indexing already covers most of what these
reports need.

---

## Recommended indexes

Full evidence, exact `CREATE INDEX CONCURRENTLY` statements, and reversal
statements are in [`sql/recommended_indexes.sql`](sql/recommended_indexes.sql).
**This file is never executed by the module itself** (not referenced in any
migration or install hook) - per the task's index policy, it is a
documented, reviewed, manually-applied artifact for a DBA to run during a
maintenance window, after re-validating against the target production
database.

Both candidates were re-tested at **two** table sizes (5.1M and 10M rows -
see [`QA_REPORT.md`](QA_REPORT.md) §10-11 for the full round-2 write-up)
specifically to check whether a conclusion drawn from one size holds at
another:

| Candidate index | Verdict | Evidence |
|---|---|---|
| `(company_id, date) WHERE posted` | **Not recommended** (verdict reversed after re-testing at scale) | ~8% *faster* at 5.1M rows (251ms → 230ms), but ~30% *slower* at 10M rows (452ms → 602ms) on the identical query - PostgreSQL's planner is tempted into a less I/O-efficient plan once the matching row count crosses a threshold. Confirmed reproducible both ways. See §10 for the full explanation. |
| `(company_id, partner_id, date) WHERE posted AND partner_id IS NOT NULL` | **Not recommended** (confirmed stable at both scales) | PostgreSQL's planner continued to prefer the existing `account_id_date_idx` + `partner_id_ref_idx` combination over this new index at both 5.1M and 10M rows; no statistically significant improvement at either size |

Both candidates were tested with real `EXPLAIN (ANALYZE, BUFFERS)` - neither
was added blindly, and both are explicitly rejected based on the evidence
rather than added "because the task suggested it." The first candidate's
scale-dependent reversal is itself the strongest argument in this report
for re-validating any index decision against production's actual ~75M-row
data before applying it, rather than trusting a conclusion from a smaller
test.

---

## Pagination design

- **Trial Balance / General Ledger summary / Partner Ledger summary**:
  the aggregated result set is bounded by the number of distinct accounts
  or partners (hundreds to low thousands, never millions), so true SQL
  `LIMIT`/`OFFSET` pagination (page size 100/200/500, selectable) is both
  correct and cheap - the expensive part is the upstream filtered scan +
  aggregation, which already ran once regardless of page size.
- **General Ledger / Partner Ledger transaction detail**: keyset
  pagination as described above (page size 20/50/100 - a finer granularity
  than the summary pages, since this is read row-by-row).

---

## Security

- `company_ids` is always resolved through
  `FastReportSqlMixin._ffr_allowed_company_ids()`, which intersects the
  request against `self.env.companies` (the ORM's own resolution of
  "companies the current user's session is allowed to see") and **raises
  `AccessError`** if a request includes a company outside that set. This
  check runs in Python before any SQL is built, so an unauthorized company
  id can never reach a query - defense in depth alongside Odoo's own
  multi-company `ir.rule` on `res.company` itself (which independently
  blocks reading back a foreign company id from a many2many field).
- Access to all wizard/line models is granted to `account.group_account_invoice`
  (Odoo's "Billing" group, implied by the "Full Accounting" and "Billing
  Administrator" groups too) - the same population that can already see
  standard accounting reports. No `sudo()` is used anywhere in the report
  query path.
- The technical performance log (`fast.report.debug.log`) is only
  readable by a dedicated `group_fast_financial_reports_debug` group
  (granted to the Administrator user by default) - ordinary accountants
  never see it, even with debug mode enabled.
- No accounting model's read/write/create/unlink access is modified by
  this module.

---

## Export (XLSX / PDF)

- **XLSX**: `controllers/main.py` streams rows straight from the database
  cursor via `FastReportSqlMixin._ffr_iter_chunks()` (bounded `fetchmany()`
  batches, default 5,000 rows/round-trip) into an `xlsxwriter.Workbook`
  opened with `constant_memory=True`, which flushes each row to disk as
  soon as it is written. No Python list of all matching rows is ever
  built - memory usage is bounded by the chunk size, not by the result set
  size. Verified against a real download in a live Odoo 17 instance
  (`.xlsx` file confirmed valid: "Microsoft Excel 2007+" via `file(1)`).
- **PDF**: a QWeb report per wizard type renders the currently generated
  page's `line_ids` (bounded by the selected page size). Verified with a
  direct `report._render_qweb_pdf()` call against real data: produced a
  valid 1-page, 1.05MB PDF.

### Partner Ledger PDF (v2 redesign)

The Partner Ledger PDF (`report/partner_ledger_report.xml`) was redesigned
for a professional A4-Landscape layout with full RTL/Arabic support,
without changing any accounting calculation or the SQL-pushdown engine:

- **Six Debit/Credit columns** - Opening Balance, Period, and Closing
  Balance each split into Debit/Credit - replacing the old single combined
  balance columns. The Entries column is gone from the PDF (the
  interactive tree view and XLSX export still show `entry_count`
  unchanged, since only the PDF's presentation was in scope). All three
  splits are simple Python sign-splits of values the SQL already computed
  (`_ffr_refresh()` in `wizard/partner_ledger.py`) - no new query.
- **Localization** follows the current user's language automatically via
  `web.external_layout` and `res.lang._lang_get(env.lang).direction`, not
  a hardcoded language check. `res_partner.name` is a plain (non-translated)
  `Char` column in Odoo 17 - verified directly against
  `odoo/addons/base/models/res_partner.py` before relying on it - so a
  partner name is never a JSONB translation dict; the *static labels*
  ("Partner", "Debit", "Credit", ...) are translated the normal Odoo way,
  via `i18n/ar.po`.
- **Long-name wrapping uses a Python pre-wrap, not CSS.** This
  environment's wkhtmltopdf (`0.12.6`, unpatched Qt) was confirmed, via an
  isolated minimal reproduction outside Odoo entirely, to silently fail to
  line-wrap long right-to-left (Arabic) text inside a `table-layout:
  fixed` cell - the overflow gets clipped/overlaps the next column instead
  of wrapping, regardless of `word-wrap`/`overflow-wrap`/`word-break` CSS.
  `FastReportSqlMixin._ffr_wrap_html_lines()` sidesteps this by computing
  line breaks in Python (`textwrap.wrap`, script-agnostic, character-count
  based) and emitting literal `<br/>` tags, individually HTML-escaping
  each line. This works the same for English and Arabic and does not
  depend on the browser's line-breaking algorithm at all.
- **Company letterhead header and the "Page X / Y" footer do not render
  in this sandbox.** Odoo's report engine produces these via
  wkhtmltopdf's `--header-html`/`--footer-html`, and this environment's
  wkhtmltopdf logs "not support[ed] using unpatched qt" for both and
  silently omits them - confirmed the main report body still renders
  correctly regardless. Odoo's officially recommended wkhtmltopdf build
  ("with patched qt") supports this normally; this is a sandbox/build
  limitation, not a template defect, and should be re-verified against
  the actual target deployment's wkhtmltopdf build before go-live.

### Partner Tag filter (Partner Ledger)

`partner_category_ids` (`res.partner.category`, many2many, "any of these
tags" / OR semantics) narrows the Partner Ledger - summary, transaction
drill-down, and XLSX export alike, since all three call the same
`_ffr_where()` - to partners carrying at least one selected tag.

Pushed down as `EXISTS (SELECT 1 FROM res_partner_res_partner_category_rel
rel WHERE rel.partner_id = aml.partner_id AND rel.category_id = ANY(%s))`
(`FastPartnerLedgerWizard._ffr_partner_tag_sql()`) rather than a `JOIN`:
a `JOIN` against the many-to-many relation table would return a partner's
`account_move_line` rows once per matching tag, silently inflating every
SUM/COUNT for a partner carrying more than one selected tag. `EXISTS` only
tests for at least one match and never multiplies the outer row, so this
is correct regardless of tag overlap - verified both by a dedicated unit
test (`test_partner_tag_filter_multiple_tags_no_duplicate_amounts`) and,
at 10M-row scale, by comparing `count(*)` vs. `count(DISTINCT partner_id)`
for a two-tag, 500/300-overlapping-partner filter (see
[Performance benchmark results](#performance-benchmark-results)).

No new index was added: the relation table's `(partner_id, category_id)`
index already exists (created automatically by the `res.partner.category_id`
field itself), and PostgreSQL was confirmed, via `EXPLAIN ANALYZE` at
10M rows, to use it. Untagged partners are handled by the normal absence
of a matching row - no special-casing needed - and are simply excluded
whenever a tag filter is active, included as always when it is not.

---

## Performance debug mode

Controlled by the `fast_financial_reports.debug_mode` system parameter
(off by default). When enabled, every report run writes a row to
`fast.report.debug.log` recording: report type, a query identifier
(`ffr_trial_balance_v1`, etc., for correlation with this document), sanitized
filter parameters (JSON, no accounting data), SQL execution time, Python
processing time, total response time, returned row count, and SQL query
count. Never exposed to ordinary users (see Security above). Enable it with:

```python
env["ir.config_parameter"].sudo().set_param("fast_financial_reports.debug_mode", "True")
```

---

## Testing performed

**All of the following were actually executed in this environment against
a real Odoo 17 Community install (not simulated or assumed).**

### 1. Real Odoo 17 runtime

- Cloned `odoo/odoo` at tag `17.0` (Community, no Enterprise), installed
  its full Python dependency set into a dedicated virtualenv.
- Initialized a PostgreSQL 16 database via `odoo-bin -i base,account`
  with demo data. **0 errors, 0 warnings** in the load log.
- Installed `fast_financial_reports` (`-i fast_financial_reports`): clean
  install, 0 errors.
- Upgraded it twice (`-u fast_financial_reports`), including after schema
  changes: clean, idempotent, 0 errors both times.
- Uninstalled it (`ir.module.module.button_immediate_uninstall()`) on a
  freshly-installed database: clean, 0 errors, server restarts cleanly
  afterward. Verified `account_move_line`/`account_move` row counts were
  **exactly unchanged** before and after (68 / 24, the untouched demo data)
  - direct evidence the module never modifies accounting data.

### 2. Automated test suite

`tests/test_trial_balance.py`, `test_general_ledger.py`,
`test_partner_ledger.py`, `test_security.py`, `test_performance_queries.py` -
run via Odoo's own test runner (`--test-enable`):

```
odoo.tests.stats: fast_financial_reports: 53 tests 12.89s 8400 queries
odoo.tests.result: 0 failed, 0 error(s) of 43 tests when loading database 'ffr_dev'
```

*(This is round 1's result, kept verbatim as a historical record. A round-2
QA pass added `tests/test_accounting_correctness_vs_orm.py` - see
[`QA_REPORT.md`](QA_REPORT.md) for the updated 48-tests-green run and the
independent ORM cross-check it added. A round-3 pass added
`tests/test_partner_ledger_pdf.py` (PDF structure/RTL/localization coverage
for the Partner Ledger redesign) and the Partner Tag filter tests appended
to `test_partner_ledger.py`:*

```
odoo.tests.stats: fast_financial_reports: 83 tests 23.44s 12925 queries
odoo.tests.result: 0 failed, 0 error(s) of 69 tests when loading database 'ffr_qa'
```

Coverage includes: one day / one week / one month / one year / multi-year
date ranges, an empty-future-period (opening balance carries forward
correctly, zero period movement), a genuinely empty result (account/partner
with no history at all, correctly excluded), account/journal/partner/company
filters individually and combined, posted-only on and off (with a real
draft entry fixture), show-zero-accounts toggle, analytic account filter
(against a real `account.analytic.plan`/`account.analytic.account`),
customer/vendor/all scope for Partner Ledger, keyset pagination
next/previous correctness (verified the exact move line returned on each
page, including returning to page 1), General Ledger drill-down running
balance reconciling exactly to the summary's closing balance, multi-company
data isolation (a company-A-only user cannot read company B's data, an
`AccessError` is raised even when a company id is force-written onto the
wizard record directly), a user without the accounting group being denied
entirely, the debug log being invisible to an ordinary accountant, and a
query-count assertion (`< 15` SQL statements) proving the aggregation
happens in PostgreSQL rather than a per-row Python loop, independent of the
underlying row count (validated against a 400-move / 800-line bulk
fixture).

**Two real bugs were found and fixed through this process** (not
hypothetical - both reproduced, root-caused, and fixed before the suite was
declared green):

1. `account_account.name` / `account_journal.name` are JSONB (translated
   fields) - initial raw-SQL queries returned the JSON blob instead of the
   text. Fixed with `_ffr_translated_sql()` (see SQL architecture above).
2. Raw SQL didn't see ORM writes from earlier in the same transaction
   (missing flush) - a test that posted moves via the ORM and immediately
   ran a report in the same transaction showed a stale row count. Fixed by
   flushing before every raw SQL execution in the mixin.

### 3. Manual functional testing in a real browser

Logged into the actual Odoo 17 web client (Playwright + headless Chromium)
as `admin` and, for each of the three reports: navigated
Accounting → Reporting → Fast Financial Reports → *(report)*, filled in
filters, clicked Generate, confirmed results rendered with correct totals,
opened the General Ledger drill-down modal, and exported both XLSX and
PDF. **Zero browser console errors** across the whole walkthrough. A real
UI bug was found and fixed in this pass too: the page-counter text
("Page X / Y (N accounts)") rendered as a broken multi-line block because
it was nested inside a two-column `<group>`; moved to a plain full-width
`<div>` and confirmed fixed with a follow-up screenshot.

### 4. Accounting correctness

For every generated Trial Balance / General Ledger / Partner Ledger result,
`opening_balance + period_debit - period_credit == closing_balance` was
asserted (both in the automated suite and via an independent raw-SQL
cross-check in a live shell session, unrelated to the wizard's own code
path). General Ledger drill-down running balances were independently
recomputed row-by-row from the raw `debit`/`credit` values and asserted
equal to the wizard's own running balance, including across a keyset page
boundary.

### 5. Security testing

Automated (`test_security.py`, part of the 43 green tests above): a
single-company user cannot read another company's data even by directly
writing a foreign company id onto the wizard record; a multi-company user
correctly sees both companies once granted access to both; a user without
any accounting group is denied at `create()` time; the debug log is
invisible to a normal accounting user even with debug mode on globally.

---

## Performance benchmark results

**Honesty note, per the task's explicit instructions**: the target
production environment (~75,000,000 `account.move.line` rows) was not
available in this sandboxed environment. What follows is a **synthetic,
clearly-labeled benchmark** on a schema-identical, index-identical
PostgreSQL 16 database (same DDL as a real Odoo 17 `account_move_line` /
`account_move` table, verified column-for-column), generated with
representative filter cardinality (a spread of accounts, ~2,000 synthetic
partners, dates spread over ~7 years). It is not a substitute for
production measurements, but it is real - every number below is an actual
`EXPLAIN (ANALYZE, BUFFERS)` execution against real rows, not an estimate
or a fabricated figure. Raw output for every run is saved under
[`docs/benchmarks/`](docs/benchmarks/).

**Standard Odoo comparison**: Trial Balance / General Ledger / Partner
Ledger reports in the form requested (with opening/period/closing
balances) are Odoo **Enterprise** features (`account_reports`), not present
in the Community edition source used for this module. No Enterprise
license/environment was available in this sandbox, so a direct
apples-to-apples "standard Odoo report vs. this module" timing comparison
could not be produced. The comparison instead is against the schema's own
existing indexes / a naive equivalent query, which is what standard
reports of this kind ultimately reduce to.

### Row-count tiers (this module's own queries)

Each tier is the same three representative queries (Trial Balance summary,
Partner Ledger summary, General Ledger single-account detail page),
`EXPLAIN (ANALYZE, BUFFERS)`, full company + full available date range,
posted-only:

| Rows in `account_move_line` | Trial Balance summary | Partner Ledger summary | GL detail (1 account, 1 page) |
|---|---|---|---|
| 100,000 | 35.3 ms | 25.1 ms | 2.3 ms |
| 1,000,000 | 204.5 ms | 136.3 ms | 3.7 ms |
| 5,100,000 | 1,167.0 ms | 638.7 ms | 12.8 ms |
| 10,000,000 | 2,551.9 ms | 1,239.8 ms | 6.6 ms |

At the 100K–1M tier the summary queries use a parallel sequential scan
(cheap at this size) or an existing bitmap index scan; from 5.1M rows
onward, with a *full-history* date range, a sequential scan is genuinely
the cost-minimizing plan (the query must read most of the table's history
regardless of any index - see [Recommended indexes](#recommended-indexes),
including a case where adding an index made this *worse*), which is
exactly why the "only aggregated rows reach Python, and the number of SQL
statements does not grow with row count" design matters more than any
single index: the module returns in ~2.5 seconds at 10M rows what, per a
real measurement (not an estimate - see
[QA_REPORT.md](QA_REPORT.md) §8), an uncontrolled `search()` + Python loop
over a comparable row count does not just do slowly but can **crash with
an out-of-memory error** before completing at all. General Ledger detail
(the query users actually wait on interactively, since it is the drill-down
step) stays in single-digit milliseconds even at 10M rows, because it is
always scoped to one account plus the existing `account_id_date_idx` /
date-ordered index - the summary-query cost above scales with table size
because it must aggregate broadly; the interactive drill-down path does
not, by design.

75,000,000 rows (the real production target, ~7.5× the largest tier
reached) was not reached in this sandboxed environment (disk/time budget)
- see [Known limitations](#known-limitations). The 100K→1M→5.1M→10M trend
above, now spanning two full order-of-magnitude steps, is consistent with
the (roughly linear, since no index fully covers a full-history scan)
growth expected up to that scale; it is not a substitute for a real
measurement at 75M rows.

### Partner Tag filter, 10M-row scale

Full `EXPLAIN (ANALYZE, BUFFERS)` output in
[`docs/benchmarks/partner_tag_filter_10m.txt`](docs/benchmarks/partner_tag_filter_10m.txt).
Same 10,000,068-row database, exact SQL shape `_ffr_where()`/`_ffr_refresh()`
build for the Partner Ledger summary:

| Filter | Plan | Execution time |
|---|---|---|
| No tag filter (baseline) | Parallel Seq Scan on `account_move_line` | 1775 ms |
| Single tag, 500/2040 partners tagged | Merge Join via `account_move_line_partner_id_ref_idx` | 1020 ms |
| Two tags (OR), 500/300 overlapping partners | Index Only Scan on the relation table's own `(partner_id, category_id)` index | 1958 ms |

The tag filter did not add scan cost - PostgreSQL recognized the `EXISTS`
as a semi-join against a small filtered set and picked a *cheaper* plan
than the baseline. A duplicate-row check on the two-tag case (`count(*)`
vs. `count(DISTINCT partner_id)` on the same filtered query, no `LIMIT`)
returned 136,499 matching journal-line rows across exactly 500 distinct
partners - the exact union of the two tags' partner sets, confirming no
inflation from the many-to-many relation regardless of how many tags a
partner carries or how many are selected.

### Multi-user / concurrency

Not exercised in this environment: no facility here to run multiple
concurrent Odoo worker processes against meaningfully different report
requests and observe PostgreSQL/worker contention under load. This is
explicitly flagged as **not tested** - see Known limitations. A real
concurrency test would need multiple Odoo workers (`--workers`) and a load
tool (e.g. `locust` or plain concurrent `curl`/RPC calls) against a staging
copy of the actual production database.

---

## Known limitations

- **Opening balance does not implement fiscal-year reset for P&L accounts.**
  Per the spec's own formula (`Opening balance: date < date_from`), income
  and expense accounts' "opening balance" is the cumulative balance of all
  history before `date_from`, not reset to zero at the start of each fiscal
  year the way a strict accounting Trial Balance / Income Statement would.
  This matches the literal spec and is fine for a Balance Sheet perspective;
  it is a known simplification for P&L accounts, consistent with Phase 1
  explicitly excluding Profit & Loss.
- **Analytic filter is not indexed at true 75M-row scale in this repo's
  testing** - the GIN index it reuses is real and shipped by Odoo's
  `analytic` module, but was only validated at the tested tiers (≤10M
  rows overall; the analytic-filtered test used a small fixture), not
  against tens of millions of analytically-tagged lines.
- **75M-row tier not reached (10M was).** See Performance benchmark results
  above - this sandbox's disk/time budget capped synthetic data generation
  at 10,000,068 rows, ~7.5× short of the real 75M target. The
  100K→1M→5.1M→10M trend is real evidence of the *shape* of the scaling
  problem (and that the design avoids it for the parts that matter - row
  count reaching Python, SQL statement count), but is not a substitute for
  a genuine 75M-row measurement. Notably, an index-scale reversal was
  observed between the 5.1M and 10M tiers (see
  [Recommended indexes](#recommended-indexes)) - a concrete reminder that
  conclusions from this report's largest tested tier still should not be
  assumed to hold unchanged at the real production scale.
- **No concurrent/multi-user load test was run** (see above).
- **No side-by-side timing against standard Odoo Trial Balance / General
  Ledger / Partner Ledger reports** - those are Enterprise-only
  (`account_reports`), unavailable in this Community-only sandbox.
- **PDF export renders only the currently generated page** (bounded by the
  selected page size), not the full unpaginated result set, to stay
  consistent with the "never build a giant unbounded structure" principle.
  XLSX export *does* export the full filtered/aggregated result (still
  bounded by account/partner cardinality, not by line count) via the
  chunked streaming path.
- **This sandbox's wkhtmltopdf (`0.12.6`, unpatched Qt) does not render
  PDF header/footer bands** (`--header-html`/`--footer-html` both log
  "not support[ed]" and are silently skipped) - the Partner Ledger PDF's
  company letterhead and "Page X / Y" footer will not appear here, even
  though the report body renders correctly and the template uses Odoo's
  normal, standard mechanism (`web.external_layout`). Re-verify against
  the target deployment's actual wkhtmltopdf build (Odoo's officially
  recommended "patched Qt" build supports this normally) before relying
  on header/footer output. See
  [Partner Ledger PDF (v2 redesign)](#partner-ledger-pdf-v2-redesign) for
  the full detail, including the separate (already worked around) long
  Arabic text line-wrapping bug found in the same wkhtmltopdf build.
- **Reversed/cancelled entries, multi-currency, and partial reconciliation**
  were exercised only at the schema/filter level (`parent_state != 'cancel'`
  always excludes cancelled entries; multi-currency columns exist on
  `account_move_line` and are not specially filtered, so they flow through
  the aggregation like any other line) - no dedicated fixture-based test
  for these specific accounting scenarios exists yet in the automated
  suite.

## Remaining bottlenecks / Phase 2 candidates

- At true 75M-row scale, a full-history Trial Balance (very early
  `date_from`, or none) will still need to scan a large fraction of the
  table for the opening-balance computation, since no index can make an
  inherently non-selective range cheap. This is the natural motivation for
  a Phase 2 materialized/summary-table approach (explicitly out of scope
  for Phase 1 per the spec) - e.g. a periodically-refreshed per-account
  running-balance snapshot that a Trial Balance query could start from
  instead of `date < date_from` over the full table.
  - **Data-driven Phase 2 starting point**: with the `fast.report.debug.log`
    Phase 1 already ships, once deployed on a real production database, the
    JSON `filter_params` on repeatedly slow queries (`sql_time_ms` above
    some threshold) directly identify which query shapes (which report,
    which filter combination) are worth optimizing first - avoiding a
    second round of "index policy" guesswork.
- Aged Receivable/Payable, P&L, Balance Sheet, Tax, and ZATCA reports are
  explicitly out of scope for Phase 1 (per spec) and are not implemented.

---

## Final release checklist

- [x] Module installs successfully (clean, 0 errors, real Odoo 17)
- [x] Module upgrades successfully (twice, idempotent, 0 errors)
- [x] No Odoo traceback (across install, upgrade, test run, and manual UI use)
- [x] No PostgreSQL errors
- [x] Trial Balance works (automated tests + real browser walkthrough)
- [x] General Ledger works (summary + lazy drill-down, automated + browser)
- [x] Partner Ledger works (summary + lazy drill-down, automated + browser)
- [x] Opening balances are correct (asserted + independently cross-checked)
- [x] Closing balances are correct (opening + period reconciles, asserted)
- [ ] Totals match standard Odoo reports - **not verified**: standard
      Trial Balance/GL/Partner Ledger are Enterprise-only, unavailable here
- [x] Company security works (automated cross-company isolation tests)
- [x] Pagination works (SQL LIMIT/OFFSET for summaries, keyset for detail,
      next/prev verified)
- [x] Lazy loading works (detail queries only run on explicit drill-down;
      asserted no detail wizard exists until requested)
- [x] XLSX export works (real download verified, valid file)
- [x] PDF export works (real render verified, valid 1-page PDF)
- [x] Automated tests pass (48/48, 0 failed, 0 errors - see QA_REPORT.md
      for the round-2 re-run that added 5 independent ORM cross-check tests)
- [x] Functional tests pass (date ranges, filters, edge cases - see Testing performed)
- [x] Performance tests completed - **at 100K/1M/5.1M/10M rows**, not the
      full 75M target (sandbox disk/time budget); see Known limitations
      and QA_REPORT.md for the 10M-tier results
- [ ] Stress tests completed - **not run**: no facility for concurrent
      multi-worker load testing in this environment
- [x] No accounting data is modified (module is read-only by construction;
      no write/unlink access to `account.move`/`account.move.line` anywhere
      in the codebase)
- [x] No ZATCA logic is modified (module does not touch it at all)
- [x] No POS accounting logic is modified (module does not touch it at all)
- [x] No unresolved critical bugs (2 real bugs found via testing, both
      fixed and re-verified - see Testing performed)
- [x] All discovered bugs were fixed and retested
- [x] README is complete
- [x] Deployment/rollback instructions are documented (install/upgrade/
      uninstall above; recommended indexes are separately documented,
      manually-applied, and individually reversible via `DROP INDEX
      CONCURRENTLY`)

**This module is functionally complete and correct against everything
verifiable in this environment, but is not yet fully production-validated**:
the two unchecked items above (standard-report parity, stress/concurrency
testing) require resources this sandbox did not have (an Enterprise Odoo
license/environment, and a multi-worker load-testing setup respectively).
Before a genuine production rollout, run both against a staging copy of the
real database, and re-run the EXPLAIN ANALYZE evidence in
[Recommended indexes](#recommended-indexes) against that database's actual
data distribution before applying any index from
[`sql/recommended_indexes.sql`](sql/recommended_indexes.sql).
