import json
import time

from odoo import api, fields, models
from odoo.tools.sql import SQL

PAGE_SIZE_SELECTION = [("100", "100"), ("200", "200"), ("500", "500")]
#: Transaction-detail pages are naturally read row-by-row, so a smaller
#: granularity than the account-summary page sizes above is offered.
DETAIL_PAGE_SIZE_SELECTION = [("20", "20"), ("50", "50"), ("100", "100")]

MOVE_TYPE_SELECTION = [
    ("entry", "Journal Entry"),
    ("out_invoice", "Customer Invoice"),
    ("out_refund", "Customer Credit Note"),
    ("in_invoice", "Vendor Bill"),
    ("in_refund", "Vendor Credit Note"),
    ("out_receipt", "Sales Receipt"),
    ("in_receipt", "Purchase Receipt"),
]


class FastGeneralLedgerWizard(models.TransientModel):
    """Fast General Ledger - step 1: account summaries only.

    Exactly like the Trial Balance query (see wizard/trial_balance.py for
    the full explanation), except grouping additionally exposes an
    "Ending Balance" and "Entry Count" per account. Transaction-level detail
    is intentionally NOT queried here: it is only fetched, one account at a
    time, when the user opens that account (see FastGeneralLedgerDetailWizard).
    """
    _name = "fast.general.ledger.wizard"
    _inherit = "fast.report.sql.mixin"
    _description = "Fast General Ledger"

    company_ids = fields.Many2many(
        "res.company", string="Companies",
        default=lambda self: self.env.companies,
    )
    date_from = fields.Date(required=True, default=lambda self: fields.Date.context_today(self).replace(month=1, day=1))
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    account_ids = fields.Many2many("account.account", string="Accounts")
    journal_ids = fields.Many2many("account.journal", string="Journals")
    partner_ids = fields.Many2many("res.partner", string="Partners")
    posted_only = fields.Boolean(string="Posted Entries Only", default=True)
    move_type = fields.Selection(MOVE_TYPE_SELECTION, string="Move Type")
    reference = fields.Char(string="Reference")
    page_size = fields.Selection(PAGE_SIZE_SELECTION, default="100", required=True, string="Rows per Page")
    page = fields.Integer(default=1)
    total_account_count = fields.Integer(readonly=True)
    total_page_count = fields.Integer(readonly=True, compute="_compute_total_page_count")
    line_ids = fields.One2many("fast.general.ledger.line", "wizard_id", string="Account Summaries")
    generated = fields.Boolean(default=False)

    last_sql_time_ms = fields.Float(readonly=True, string="SQL Time (ms)")
    last_total_time_ms = fields.Float(readonly=True, string="Total Time (ms)")

    @api.depends("total_account_count", "page_size")
    def _compute_total_page_count(self):
        for wiz in self:
            size = int(wiz.page_size or 100)
            wiz.total_page_count = max(1, (wiz.total_account_count + size - 1) // size)

    def _ffr_needs_move_join(self):
        return bool(self.move_type)

    def _ffr_where(self, extra_account_id=None):
        self._ffr_check_dates(self.date_from, self.date_to)
        company_ids = self._ffr_allowed_company_ids(self.company_ids.ids)
        account_ids = [extra_account_id] if extra_account_id else self.account_ids.ids
        conditions = [
            SQL("aml.company_id = ANY(%s)", list(company_ids)),
            SQL("aml.date BETWEEN %s AND %s", self.date_from, self.date_to),
            self._ffr_posted_state_sql(self.posted_only),
            SQL("(aml.display_type IS NULL OR aml.display_type NOT IN ('line_section', 'line_note'))"),
            self._ffr_in_ids_sql("aml.account_id", account_ids),
            self._ffr_in_ids_sql("aml.journal_id", self.journal_ids.ids),
            self._ffr_in_ids_sql("aml.partner_id", self.partner_ids.ids),
        ]
        if self.reference:
            like = "%%%s%%" % self.reference.replace("%", r"\%")
            conditions.append(SQL("(aml.ref ILIKE %s OR aml.move_name ILIKE %s)", like, like))
        if self.move_type:
            # move_type is a *non-stored* related field on account.move.line
            # (related='move_id.move_type', no store=True) so it is not a
            # real column - filtering on it requires joining account_move.
            conditions.append(SQL("am.move_type = %s", self.move_type))
        return SQL(" AND ").join(conditions), company_ids, bool(self.move_type)

    def _ffr_opening_where(self, extra_account_id=None):
        """Same filter set but for the opening balance (date < date_from,
        no upper bound needed since it is implied)."""
        company_ids = self._ffr_allowed_company_ids(self.company_ids.ids)
        account_ids = [extra_account_id] if extra_account_id else self.account_ids.ids
        conditions = [
            SQL("aml.company_id = ANY(%s)", list(company_ids)),
            SQL("aml.date < %s", self.date_from),
            self._ffr_posted_state_sql(self.posted_only),
            SQL("(aml.display_type IS NULL OR aml.display_type NOT IN ('line_section', 'line_note'))"),
            self._ffr_in_ids_sql("aml.account_id", account_ids),
            self._ffr_in_ids_sql("aml.journal_id", self.journal_ids.ids),
            self._ffr_in_ids_sql("aml.partner_id", self.partner_ids.ids),
        ]
        return SQL(" AND ").join(conditions)

    def _ffr_export_sql(self):
        """Full (unpaginated) account-summary result set, for XLSX export."""
        where_sql, company_ids, needs_join = self._ffr_where()
        opening_where_sql = self._ffr_opening_where()
        join_sql = SQL("JOIN account_move am ON am.id = aml.move_id") if needs_join else SQL("")

        opening_sql = SQL(
            "SELECT account_id, SUM(debit) - SUM(credit) AS opening_balance "
            "FROM account_move_line aml WHERE %s GROUP BY account_id",
            opening_where_sql,
        )
        period_sql = SQL(
            "SELECT aml.account_id, SUM(aml.debit) AS period_debit, SUM(aml.credit) AS period_credit, "
            "COUNT(*) AS entry_count "
            "FROM account_move_line aml %s WHERE %s GROUP BY aml.account_id",
            join_sql, where_sql,
        )
        grouped_sql = SQL(
            "SELECT COALESCE(o.account_id, p.account_id) AS account_id, "
            "COALESCE(o.opening_balance, 0) AS opening_balance, "
            "COALESCE(p.period_debit, 0) AS period_debit, "
            "COALESCE(p.period_credit, 0) AS period_credit, "
            "COALESCE(p.entry_count, 0) AS entry_count "
            "FROM (%s) o FULL OUTER JOIN (%s) p ON p.account_id = o.account_id",
            opening_sql, period_sql,
        )
        having_sql = SQL("WHERE g.opening_balance != 0 OR g.period_debit != 0 OR g.period_credit != 0")
        return SQL(
            "SELECT aa.code AS account_code, %s AS account_name, "
            "g.opening_balance, g.period_debit, g.period_credit, "
            "(g.opening_balance + g.period_debit - g.period_credit) AS closing_balance, g.entry_count "
            "FROM (%s) g JOIN account_account aa ON aa.id = g.account_id %s "
            "ORDER BY aa.code",
            self._ffr_translated_sql("aa.name"), grouped_sql, having_sql,
        ), company_ids

    def action_generate(self):
        self.ensure_one()
        self.page = 1
        return self._ffr_refresh()

    def action_next_page(self):
        self.ensure_one()
        if self.page < self.total_page_count:
            self.page += 1
        return self._ffr_refresh()

    def action_prev_page(self):
        self.ensure_one()
        if self.page > 1:
            self.page -= 1
        return self._ffr_refresh()

    def _ffr_refresh(self):
        self.ensure_one()
        t0 = time.perf_counter()
        where_sql, company_ids, needs_join = self._ffr_where()
        opening_where_sql = self._ffr_opening_where()
        join_sql = SQL("JOIN account_move am ON am.id = aml.move_id") if needs_join else SQL("")

        opening_sql = SQL(
            "SELECT account_id, SUM(debit) - SUM(credit) AS opening_balance "
            "FROM account_move_line aml WHERE %s GROUP BY account_id",
            opening_where_sql,
        )
        period_sql = SQL(
            "SELECT aml.account_id, SUM(aml.debit) AS period_debit, SUM(aml.credit) AS period_credit, "
            "COUNT(*) AS entry_count "
            "FROM account_move_line aml %s WHERE %s GROUP BY aml.account_id",
            join_sql, where_sql,
        )
        # FULL OUTER JOIN: an account can have an opening balance with zero
        # movement this period, or movement this period with no prior
        # opening balance - both must appear.
        grouped_sql = SQL(
            "SELECT COALESCE(o.account_id, p.account_id) AS account_id, "
            "COALESCE(o.opening_balance, 0) AS opening_balance, "
            "COALESCE(p.period_debit, 0) AS period_debit, "
            "COALESCE(p.period_credit, 0) AS period_credit, "
            "COALESCE(p.entry_count, 0) AS entry_count "
            "FROM (%s) o FULL OUTER JOIN (%s) p ON p.account_id = o.account_id",
            opening_sql, period_sql,
        )
        having_sql = SQL("WHERE g.opening_balance != 0 OR g.period_debit != 0 OR g.period_credit != 0")

        size = int(self.page_size)
        offset = (self.page - 1) * size
        count_sql = SQL("SELECT COUNT(*) FROM (%s) g %s", grouped_sql, having_sql)
        total = self._ffr_execute_scalar(count_sql) or 0

        final_sql = SQL(
            "SELECT g.account_id, aa.code AS account_code, %s AS account_name, "
            "g.opening_balance, g.period_debit, g.period_credit, g.entry_count "
            "FROM (%s) g JOIN account_account aa ON aa.id = g.account_id %s "
            "ORDER BY aa.code LIMIT %s OFFSET %s",
            self._ffr_translated_sql("aa.name"), grouped_sql, having_sql, size, offset,
        )
        rows, sql_time_ms = self._ffr_execute(final_sql)

        self.line_ids.unlink()
        vals_list = []
        for seq, row in enumerate(rows):
            closing_balance = row["opening_balance"] + row["period_debit"] - row["period_credit"]
            vals_list.append({
                "wizard_id": self.id,
                "sequence": seq,
                "account_id": row["account_id"],
                "account_code": row["account_code"],
                "account_name": row["account_name"],
                "opening_balance": row["opening_balance"],
                "period_debit": row["period_debit"],
                "period_credit": row["period_credit"],
                "closing_balance": closing_balance,
                "entry_count": row["entry_count"],
            })
        if vals_list:
            self.env["fast.general.ledger.line"].create(vals_list)

        total_time_ms = (time.perf_counter() - t0) * 1000.0
        self.write({
            "total_account_count": total,
            "generated": True,
            "last_sql_time_ms": sql_time_ms,
            "last_total_time_ms": total_time_ms,
        })
        self._ffr_log_debug(
            report_type="general_ledger_summary",
            query_id="ffr_general_ledger_summary_v1",
            company_ids=company_ids,
            params={
                "date_from": str(self.date_from), "date_to": str(self.date_to),
                "account_ids": self.account_ids.ids, "journal_ids": self.journal_ids.ids,
                "partner_ids": self.partner_ids.ids, "posted_only": self.posted_only,
                "move_type": self.move_type, "reference": self.reference,
                "page": self.page, "page_size": self.page_size,
            },
            sql_time_ms=sql_time_ms,
            processing_time_ms=total_time_ms - sql_time_ms,
            total_time_ms=total_time_ms,
            row_count=len(rows),
            query_count=3,
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "fast.general.ledger.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_export_xlsx(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": "/fast_financial_reports/export/general_ledger/xlsx/%s" % self.id,
            "target": "self",
        }

    def action_export_pdf(self):
        self.ensure_one()
        return self.env.ref("fast_financial_reports.action_report_general_ledger").report_action(self)


class FastGeneralLedgerLine(models.TransientModel):
    _name = "fast.general.ledger.line"
    _description = "Fast General Ledger - Account Summary Line"
    _order = "sequence, account_code"

    wizard_id = fields.Many2one("fast.general.ledger.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer()
    account_id = fields.Many2one("account.account", readonly=True)
    account_code = fields.Char(readonly=True)
    account_name = fields.Char(readonly=True)
    opening_balance = fields.Monetary(readonly=True, currency_field="company_currency_id")
    period_debit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    period_credit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    closing_balance = fields.Monetary(readonly=True, currency_field="company_currency_id")
    entry_count = fields.Integer(readonly=True)
    company_currency_id = fields.Many2one("res.currency", compute="_compute_company_currency_id")

    @api.depends("wizard_id")
    def _compute_company_currency_id(self):
        for line in self:
            line.company_currency_id = self.env.company.currency_id

    def action_view_transactions(self):
        """Lazily load transaction-level detail for THIS account only, the
        moment (and only the moment) the user asks for it."""
        self.ensure_one()
        detail = self.env["fast.general.ledger.detail.wizard"].create({
            "parent_wizard_id": self.wizard_id.id,
            "account_id": self.account_id.id,
            "account_code": self.account_code,
            "account_name": self.account_name,
            "opening_balance": self.opening_balance,
        })
        detail.action_load_first_page()
        return {
            "type": "ir.actions.act_window",
            "res_model": "fast.general.ledger.detail.wizard",
            "res_id": detail.id,
            "view_mode": "form",
            "target": "new",
        }


class FastGeneralLedgerDetailWizard(models.TransientModel):
    """Transaction-level drill-down for a single account, using keyset
    (cursor) pagination on (date, id) instead of OFFSET, so opening page N
    costs the same as opening page 1 no matter how deep N is."""
    _name = "fast.general.ledger.detail.wizard"
    _inherit = "fast.report.sql.mixin"
    _description = "Fast General Ledger - Transaction Detail"

    parent_wizard_id = fields.Many2one("fast.general.ledger.wizard", required=True, ondelete="cascade")
    account_id = fields.Many2one("account.account", readonly=True)
    account_code = fields.Char(readonly=True)
    account_name = fields.Char(readonly=True)
    opening_balance = fields.Monetary(readonly=True, currency_field="company_currency_id")
    company_currency_id = fields.Many2one("res.currency", compute="_compute_company_currency_id")
    page_size = fields.Selection(DETAIL_PAGE_SIZE_SELECTION, default="20", required=True, string="Rows per Page")
    page_number = fields.Integer(default=1, readonly=True)
    has_next_page = fields.Boolean(readonly=True)
    has_prev_page = fields.Boolean(readonly=True, compute="_compute_has_prev_page")
    # Keyset cursor state describing the CURRENT page: the exclusive lower
    # bound (date, id) and running balance it was fetched FROM ("start"),
    # and the (date, id)/running balance of its own last row ("end" - this
    # is exactly the "start" state to use for the next page). Both "start"
    # values are None for page 1.
    start_date = fields.Date(readonly=True)
    start_line_id = fields.Integer(readonly=True)
    start_running_balance = fields.Monetary(readonly=True, currency_field="company_currency_id")
    end_date = fields.Date(readonly=True)
    end_line_id = fields.Integer(readonly=True)
    end_running_balance = fields.Monetary(readonly=True, currency_field="company_currency_id")
    # Breadcrumb stack of prior pages' "start" state, to support "Previous
    # Page" purely via keyset re-fetch, never OFFSET. Small: one entry per
    # page the user has actually visited, not per row of data.
    cursor_stack = fields.Text(default="[]")
    detail_line_ids = fields.One2many("fast.general.ledger.detail.line", "detail_wizard_id")

    @api.depends("parent_wizard_id")
    def _compute_company_currency_id(self):
        for wiz in self:
            wiz.company_currency_id = self.env.company.currency_id

    @api.depends("cursor_stack")
    def _compute_has_prev_page(self):
        for wiz in self:
            wiz.has_prev_page = bool(json.loads(wiz.cursor_stack or "[]"))

    def _ffr_fetch_page(self, cursor_date, cursor_line_id):
        parent = self.parent_wizard_id
        where_sql, company_ids, needs_join = parent._ffr_where(extra_account_id=self.account_id.id)
        join_sql = SQL("JOIN account_move am ON am.id = aml.move_id") if needs_join else SQL("")
        if cursor_date is not None and cursor_line_id is not None:
            where_sql = SQL(
                "%s AND (aml.date, aml.id) > (%s, %s)",
                where_sql, cursor_date, cursor_line_id,
            )
        size = int(self.page_size)
        final_sql = SQL(
            "SELECT aml.id, aml.date, j.code AS journal_code, aml.move_name, "
            "aml.ref, p.name AS partner_name, aml.name AS label, aml.debit, aml.credit "
            "FROM account_move_line aml "
            "JOIN account_journal j ON j.id = aml.journal_id "
            "LEFT JOIN res_partner p ON p.id = aml.partner_id "
            "%s WHERE %s "
            "ORDER BY aml.date, aml.id "
            "LIMIT %s",
            join_sql, where_sql, size + 1,  # fetch one extra row to know if there's a next page
        )
        rows, sql_time_ms = self._ffr_execute(final_sql)
        has_next = len(rows) > size
        rows = rows[:size]
        return rows, has_next, sql_time_ms, company_ids

    def _ffr_load_page(self, start_date, start_line_id, start_running_balance):
        """Fetch and display the page that starts right after the keyset
        cursor (start_date, start_line_id), carrying start_running_balance
        as the running balance of everything before it. Updates the wizard's
        "start" and "end" cursor fields so Next/Previous can chain off it."""
        t0 = time.perf_counter()
        rows, has_next, sql_time_ms, company_ids = self._ffr_fetch_page(start_date, start_line_id)

        self.detail_line_ids.unlink()
        running = start_running_balance
        vals_list = []
        end_date, end_id = start_date, start_line_id
        for seq, row in enumerate(rows):
            running += row["debit"] - row["credit"]
            vals_list.append({
                "detail_wizard_id": self.id,
                "sequence": seq,
                "move_line_id": row["id"],
                "date": row["date"],
                "journal_code": row["journal_code"],
                "move_name": row["move_name"],
                "ref": row["ref"],
                "partner_name": row["partner_name"],
                "label": row["label"],
                "debit": row["debit"],
                "credit": row["credit"],
                "running_balance": running,
            })
            end_date, end_id = row["date"], row["id"]
        if vals_list:
            self.env["fast.general.ledger.detail.line"].create(vals_list)

        total_time_ms = (time.perf_counter() - t0) * 1000.0
        self.write({
            "start_date": start_date,
            "start_line_id": start_line_id,
            "start_running_balance": start_running_balance,
            "end_date": end_date,
            "end_line_id": end_id,
            "end_running_balance": running,
            "has_next_page": has_next,
        })
        self._ffr_log_debug(
            report_type="general_ledger_detail",
            query_id="ffr_general_ledger_detail_v1",
            company_ids=company_ids,
            params={"account_id": self.account_id.id, "page_size": self.page_size},
            sql_time_ms=sql_time_ms,
            processing_time_ms=total_time_ms - sql_time_ms,
            total_time_ms=total_time_ms,
            row_count=len(rows),
            query_count=1,
        )

    def action_load_first_page(self):
        self.ensure_one()
        self.cursor_stack = "[]"
        self.page_number = 1
        self._ffr_load_page(None, None, self.opening_balance)

    def action_next_page(self):
        self.ensure_one()
        if not self.has_next_page:
            return
        stack = json.loads(self.cursor_stack or "[]")
        # Remember how to re-fetch the page we are leaving.
        stack.append([
            str(self.start_date) if self.start_date else None,
            self.start_line_id,
            self.start_running_balance,
        ])
        self.cursor_stack = json.dumps(stack)
        self.page_number += 1
        self._ffr_load_page(self.end_date, self.end_line_id, self.end_running_balance)

    def action_prev_page(self):
        self.ensure_one()
        stack = json.loads(self.cursor_stack or "[]")
        if not stack:
            return
        prev_date, prev_id, prev_running = stack.pop()
        self.cursor_stack = json.dumps(stack)
        self.page_number -= 1
        cursor_date = fields.Date.from_string(prev_date) if prev_date else None
        self._ffr_load_page(cursor_date, prev_id, prev_running)


class FastGeneralLedgerDetailLine(models.TransientModel):
    _name = "fast.general.ledger.detail.line"
    _description = "Fast General Ledger - Transaction Line"
    _order = "sequence"

    detail_wizard_id = fields.Many2one("fast.general.ledger.detail.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer()
    move_line_id = fields.Many2one("account.move.line", readonly=True)
    date = fields.Date(readonly=True)
    journal_code = fields.Char(readonly=True)
    move_name = fields.Char(readonly=True, string="Move")
    ref = fields.Char(readonly=True, string="Reference")
    partner_name = fields.Char(readonly=True, string="Partner")
    label = fields.Char(readonly=True)
    debit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    credit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    running_balance = fields.Monetary(readonly=True, currency_field="company_currency_id")
    company_currency_id = fields.Many2one("res.currency", compute="_compute_company_currency_id")

    @api.depends("detail_wizard_id")
    def _compute_company_currency_id(self):
        for line in self:
            line.company_currency_id = self.env.company.currency_id
