"""Shared SQL / security / instrumentation helpers for the Fast Financial
Reports engine.

Design rules enforced here (see module README, section "SQL architecture"):

* Every filter is pushed down into the WHERE clause of a single aggregated
  SQL query. We never run ``search()`` and then loop over the resulting
  recordset in Python for reporting purposes.
* All SQL is built with :class:`odoo.tools.sql.SQL`, which is the framework's
  own composable, parameterized query object (see ``odoo/tools/sql.py``).
  User-supplied values are always passed as bind parameters, never
  string-interpolated into the query text.
* Multi-company / record-rule security is enforced in Python *before* the
  query is built: the set of company ids used in the SQL is always the
  intersection of what the user asked for and ``self.env.companies``
  (the companies the current user is actually allowed to see), regardless
  of what a wizard record stores on disk or what an RPC caller might send.
"""
import json
import logging
import time
from contextlib import contextmanager

from odoo import _, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.sql import SQL

_logger = logging.getLogger(__name__)

#: rows fetched per database round-trip when streaming large result sets
#: (exports). Keeps memory usage bounded regardless of how many rows match.
FFR_EXPORT_CHUNK_SIZE = 5000


class FastReportSqlMixin(models.AbstractModel):
    """Reusable helpers mixed into every Fast Financial Reports wizard."""
    _name = "fast.report.sql.mixin"
    _description = "Fast Financial Reports - SQL / Security Helpers"

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    def _ffr_allowed_company_ids(self, requested_company_ids):
        """Return the tuple of company ids the query is allowed to read.

        ``self.env.companies`` is the ORM's own resolution of "companies the
        current user has access to in this session" (``res.users.company_ids``
        intersected with the active company selector) -- this is the same
        set the standard Odoo UI restricts multi-company users to. We never
        let a filter widen that set: any id requested outside of it is
        rejected rather than silently dropped, since silently dropping could
        mask a bug that leaks data across companies.
        """
        allowed = set(self.env.companies.ids)
        if not allowed:
            raise AccessError(_("You do not have access to any company."))
        if not requested_company_ids:
            return tuple(allowed)
        requested = set(requested_company_ids)
        if not requested.issubset(allowed):
            raise AccessError(_(
                "You do not have access to one or more of the selected companies."
            ))
        return tuple(requested)

    # ------------------------------------------------------------------
    # Common SQL fragments (account_move_line is always aliased "aml")
    # ------------------------------------------------------------------
    def _ffr_posted_state_sql(self, posted_only):
        """``parent_state`` is a *stored* related field on account.move.line
        (related='move_id.state', store=True) - filtering on it directly
        avoids joining account_move just to check the posting state.
        Cancelled entries never carry accounting weight and are always
        excluded, even when "Posted Only" is off (draft included).
        """
        if posted_only:
            return SQL("aml.parent_state = 'posted'")
        return SQL("aml.parent_state != 'cancel'")

    def _ffr_in_ids_sql(self, column_sql, ids):
        """``column = ANY(%s)`` filter, or an always-true SQL(1=1) fragment
        when no ids are given (i.e. the filter is not active)."""
        if not ids:
            return SQL("1=1")
        return SQL("%s = ANY(%s)", SQL(column_sql), list(set(ids)))

    def _ffr_translated_sql(self, column_sql):
        """SQL fragment resolving a *translated* Char/Text column (stored as
        JSONB ``{lang: value}`` in Odoo 17) to the current user's language,
        falling back to the source language ('en_US'). This is the same
        ``COALESCE(col->>%s, col->>'en_US')`` pattern Odoo core itself uses
        for raw-SQL access to translatable fields (see e.g.
        ``odoo/addons/base/models/ir_model.py`` / ``ir_filters.py``).
        Only use this for columns declared with ``translate=True``
        (e.g. account_account.name, account_journal.name) - plain Char
        columns (e.g. res_partner.name, account_account.code) must NOT be
        wrapped this way, they are already plain text.
        """
        lang = self.env.lang or "en_US"
        column = SQL(column_sql)
        return SQL("COALESCE(%s->>%s, %s->>'en_US')", column, lang, column)

    def _ffr_analytic_sql(self, analytic_account_id):
        """Optional analytic account filter.

        In Odoo 17 analytic distribution on a journal item is stored as a
        JSONB column (``analytic_distribution``), e.g. ``{"3": 100.0}``
        mapping analytic account id -> percentage; it replaced the old
        many2one ``analytic_account_id``. The ``analytic`` module itself
        already creates a functional GIN index for exactly this lookup
        (see ``account_move_line_analytic_distribution_accounts_gin_index``,
        built by ``AnalyticMixin.init()``) over
        ``regexp_split_to_array(jsonb_path_query_array(analytic_distribution,
        '$.keyvalue()."key"')::text, '\\D+')`` - an array of the
        distribution's analytic account ids as text. We reuse that exact
        expression with the array-overlap operator ``&&`` (the same pattern
        ``AnalyticMixin._search_analytic_distribution()`` uses for analytic
        domains elsewhere in Odoo) so PostgreSQL can use that existing index
        instead of scanning every already-matched row.
        """
        if not analytic_account_id:
            return SQL("1=1")
        array_expr = SQL(
            r"""regexp_split_to_array(jsonb_path_query_array(aml.analytic_distribution, '$.keyvalue()."key"')::text, '\D+')"""
        )
        return SQL("%s && %s", array_expr, [str(analytic_account_id)])

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------
    @contextmanager
    def _ffr_timer(self):
        """Millisecond wall-clock timer usable as ``with self._ffr_timer() as t:``.
        After the block, ``t()`` returns the elapsed time in milliseconds.
        """
        start = time.perf_counter()
        holder = {"end": None}

        def _elapsed():
            end = holder["end"] if holder["end"] is not None else time.perf_counter()
            return (end - start) * 1000.0

        try:
            yield _elapsed
        finally:
            holder["end"] = time.perf_counter()

    def _ffr_flush(self):
        """Flush any pending ORM writes to the database before running raw
        SQL. The ORM buffers writes (e.g. posting a journal entry) and only
        sends them to PostgreSQL lazily; a raw ``cr.execute()`` bypasses that
        buffer entirely, so without an explicit flush a report could miss
        rows that were just created/posted earlier in the same transaction.
        """
        self.env.flush_all()

    def _ffr_execute(self, sql):
        """Execute a parameterized :class:`SQL` statement and return
        ``(rows_as_dict_list, sql_time_ms)``. Intended for aggregate queries
        whose result set is small (bounded by the number of accounts /
        partners / a single page of transactions) - never for raw,
        unaggregated line-level scans.
        """
        self._ffr_flush()
        cr = self.env.cr
        start = time.perf_counter()
        cr.execute(sql)
        rows = cr.dictfetchall()
        sql_time_ms = (time.perf_counter() - start) * 1000.0
        return rows, sql_time_ms

    def _ffr_execute_scalar(self, sql):
        self._ffr_flush()
        cr = self.env.cr
        cr.execute(sql)
        row = cr.fetchone()
        return row[0] if row else None

    def _ffr_iter_chunks(self, sql, chunk_size=FFR_EXPORT_CHUNK_SIZE):
        """Stream a query's results in bounded-size chunks using
        ``fetchmany()`` instead of ``fetchall()``, so exports never build a
        giant Python list in memory regardless of how many rows match.
        """
        self._ffr_flush()
        cr = self.env.cr
        cr.execute(sql)
        columns = [d[0] for d in cr.description]
        while True:
            rows = cr.fetchmany(chunk_size)
            if not rows:
                break
            yield columns, rows

    # ------------------------------------------------------------------
    # Debug / performance instrumentation
    # ------------------------------------------------------------------
    def _ffr_debug_enabled(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "fast_financial_reports.debug_mode"
        ) in ("True", "true", "1", True)

    def _ffr_log_debug(self, report_type, query_id, company_ids, params,
                        sql_time_ms, processing_time_ms, total_time_ms,
                        row_count, query_count=1):
        """Record a performance sample. No-op unless debug mode is enabled
        via the ``fast_financial_reports.debug_mode`` system parameter, and
        never visible to ordinary users (see security groups).
        """
        if not self._ffr_debug_enabled():
            return
        try:
            safe_params = json.loads(json.dumps(params, default=str))
            self.env["fast.report.debug.log"].sudo().create({
                "report_type": report_type,
                "query_id": query_id,
                "user_id": self.env.uid,
                "company_ids": [(6, 0, list(company_ids))],
                "filter_params": json.dumps(safe_params, indent=2),
                "sql_time_ms": sql_time_ms,
                "processing_time_ms": processing_time_ms,
                "total_time_ms": total_time_ms,
                "row_count": row_count,
                "query_count": query_count,
            })
        except Exception:  # pragma: no cover - logging must never break a report
            _logger.exception("Fast Financial Reports: failed to write debug log")

    # ------------------------------------------------------------------
    # Misc validation
    # ------------------------------------------------------------------
    def _ffr_check_dates(self, date_from, date_to):
        if date_from and date_to and date_from > date_to:
            raise UserError(_("The 'From Date' must not be after the 'To Date'."))
