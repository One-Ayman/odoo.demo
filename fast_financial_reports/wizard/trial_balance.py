import time

from odoo import api, fields, models
from odoo.tools.sql import SQL

PAGE_SIZE_SELECTION = [("100", "100"), ("200", "200"), ("500", "500")]


class FastTrialBalanceWizard(models.TransientModel):
    """Fast Trial Balance.

    Query design (see README "SQL architecture" for the full explanation
    and EXPLAIN ANALYZE evidence):

    1. ``filtered``  - one indexed range scan of account_move_line with every
       user filter applied in the WHERE clause (company, date <= date_to,
       posted state, account/journal/partner/analytic).
    2. ``grouped``   - a single GROUP BY over that already-filtered set that
       computes opening (date < date_from) and period (date >= date_from)
       debit/credit with conditional SUM(), in one pass - not two queries.
    3. The final SELECT joins the small, aggregated result (at most: number
       of accounts in the chart of accounts) to account_account for the
       code/name, and paginates with ORDER BY code LIMIT/OFFSET.

    Only the aggregated rows (one per account) ever reach Python.
    """
    _name = "fast.trial.balance.wizard"
    _inherit = "fast.report.sql.mixin"
    _description = "Fast Trial Balance"

    company_ids = fields.Many2many(
        "res.company", string="Companies",
        default=lambda self: self.env.companies,
    )
    date_from = fields.Date(required=True, default=lambda self: fields.Date.context_today(self).replace(month=1, day=1))
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    account_ids = fields.Many2many("account.account", string="Accounts")
    journal_ids = fields.Many2many("account.journal", string="Journals")
    partner_ids = fields.Many2many("res.partner", string="Partners")
    analytic_account_id = fields.Many2one("account.analytic.account", string="Analytic Account")
    posted_only = fields.Boolean(string="Posted Entries Only", default=True)
    show_zero = fields.Boolean(string="Show Zero Accounts", default=False)
    page_size = fields.Selection(PAGE_SIZE_SELECTION, default="100", required=True, string="Rows per Page")
    page = fields.Integer(default=1)
    total_account_count = fields.Integer(readonly=True)
    total_page_count = fields.Integer(readonly=True, compute="_compute_total_page_count")
    line_ids = fields.One2many("fast.trial.balance.line", "wizard_id", string="Trial Balance")
    generated = fields.Boolean(default=False)

    last_sql_time_ms = fields.Float(readonly=True, string="SQL Time (ms)")
    last_total_time_ms = fields.Float(readonly=True, string="Total Time (ms)")

    @api.depends("total_account_count", "page_size")
    def _compute_total_page_count(self):
        for wiz in self:
            size = int(wiz.page_size or 100)
            wiz.total_page_count = max(1, (wiz.total_account_count + size - 1) // size)

    # ------------------------------------------------------------------
    # SQL
    # ------------------------------------------------------------------
    def _ffr_where(self):
        self._ffr_check_dates(self.date_from, self.date_to)
        company_ids = self._ffr_allowed_company_ids(self.company_ids.ids)
        conditions = [
            SQL("aml.company_id = ANY(%s)", list(company_ids)),
            SQL("aml.date <= %s", self.date_to),
            self._ffr_posted_state_sql(self.posted_only),
            SQL("(aml.display_type IS NULL OR aml.display_type NOT IN ('line_section', 'line_note'))"),
            self._ffr_in_ids_sql("aml.account_id", self.account_ids.ids),
            self._ffr_in_ids_sql("aml.journal_id", self.journal_ids.ids),
            self._ffr_in_ids_sql("aml.partner_id", self.partner_ids.ids),
            self._ffr_analytic_sql(self.analytic_account_id.id),
        ]
        return SQL(" AND ").join(conditions), company_ids

    def _ffr_grouped_sql(self, where_sql):
        filtered_sql = SQL(
            "SELECT aml.account_id, aml.debit, aml.credit, aml.date "
            "FROM account_move_line aml WHERE %s",
            where_sql,
        )
        return SQL(
            "SELECT account_id, "
            "SUM(CASE WHEN date < %s THEN debit ELSE 0 END) AS opening_debit, "
            "SUM(CASE WHEN date < %s THEN credit ELSE 0 END) AS opening_credit, "
            "SUM(CASE WHEN date >= %s THEN debit ELSE 0 END) AS period_debit, "
            "SUM(CASE WHEN date >= %s THEN credit ELSE 0 END) AS period_credit, "
            "COUNT(*) AS entry_count "
            "FROM (%s) filtered "
            "GROUP BY account_id",
            self.date_from, self.date_from, self.date_from, self.date_from,
            filtered_sql,
        )

    def _ffr_having_sql(self):
        if self.show_zero:
            return SQL("")
        return SQL(
            "WHERE g.opening_debit != 0 OR g.opening_credit != 0 "
            "OR g.period_debit != 0 OR g.period_credit != 0"
        )

    def _ffr_export_sql(self):
        """Full (unpaginated) result set for XLSX export, in the exact
        order the interactive report uses, so the export always matches
        what the user has been paging through."""
        where_sql, company_ids = self._ffr_where()
        grouped_sql = self._ffr_grouped_sql(where_sql)
        having_sql = self._ffr_having_sql()
        return SQL(
            "SELECT aa.code AS account_code, %s AS account_name, "
            "g.opening_debit, g.opening_credit, (g.opening_debit - g.opening_credit) AS opening_balance, "
            "g.period_debit, g.period_credit, (g.period_debit - g.period_credit) AS period_balance, "
            "(g.opening_debit - g.opening_credit + g.period_debit - g.period_credit) AS ending_balance "
            "FROM (%s) g JOIN account_account aa ON aa.id = g.account_id %s "
            "ORDER BY aa.code",
            self._ffr_translated_sql("aa.name"), grouped_sql, having_sql,
        ), company_ids

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
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
        where_sql, company_ids = self._ffr_where()
        grouped_sql = self._ffr_grouped_sql(where_sql)
        having_sql = self._ffr_having_sql()
        size = int(self.page_size)
        offset = (self.page - 1) * size

        count_sql = SQL("SELECT COUNT(*) FROM (%s) g %s", grouped_sql, having_sql)
        total = self._ffr_execute_scalar(count_sql) or 0

        final_sql = SQL(
            "SELECT g.account_id, aa.code AS account_code, %s AS account_name, "
            "g.opening_debit, g.opening_credit, g.period_debit, g.period_credit, g.entry_count "
            "FROM (%s) g JOIN account_account aa ON aa.id = g.account_id %s "
            "ORDER BY aa.code LIMIT %s OFFSET %s",
            self._ffr_translated_sql("aa.name"), grouped_sql, having_sql, size, offset,
        )
        rows, sql_time_ms = self._ffr_execute(final_sql)

        self.line_ids.unlink()
        vals_list = []
        for seq, row in enumerate(rows):
            opening_balance = row["opening_debit"] - row["opening_credit"]
            period_balance = row["period_debit"] - row["period_credit"]
            vals_list.append({
                "wizard_id": self.id,
                "sequence": seq,
                "account_id": row["account_id"],
                "account_code": row["account_code"],
                "account_name": row["account_name"],
                "opening_debit": row["opening_debit"],
                "opening_credit": row["opening_credit"],
                "opening_balance": opening_balance,
                "period_debit": row["period_debit"],
                "period_credit": row["period_credit"],
                "period_balance": period_balance,
                "ending_balance": opening_balance + period_balance,
                "entry_count": row["entry_count"],
            })
        if vals_list:
            self.env["fast.trial.balance.line"].create(vals_list)

        total_time_ms = (time.perf_counter() - t0) * 1000.0
        self.write({
            "total_account_count": total,
            "generated": True,
            "last_sql_time_ms": sql_time_ms,
            "last_total_time_ms": total_time_ms,
        })
        self._ffr_log_debug(
            report_type="trial_balance",
            query_id="ffr_trial_balance_v1",
            company_ids=company_ids,
            params={
                "date_from": str(self.date_from), "date_to": str(self.date_to),
                "account_ids": self.account_ids.ids, "journal_ids": self.journal_ids.ids,
                "partner_ids": self.partner_ids.ids, "posted_only": self.posted_only,
                "show_zero": self.show_zero, "page": self.page, "page_size": self.page_size,
            },
            sql_time_ms=sql_time_ms,
            processing_time_ms=total_time_ms - sql_time_ms,
            total_time_ms=total_time_ms,
            row_count=len(rows),
            query_count=2,
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "fast.trial.balance.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_export_xlsx(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": "/fast_financial_reports/export/trial_balance/xlsx/%s" % self.id,
            "target": "self",
        }

    def action_export_pdf(self):
        self.ensure_one()
        return self.env.ref("fast_financial_reports.action_report_trial_balance").report_action(self)


class FastTrialBalanceLine(models.TransientModel):
    _name = "fast.trial.balance.line"
    _description = "Fast Trial Balance - Line"
    _order = "sequence, account_code"

    wizard_id = fields.Many2one("fast.trial.balance.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer()
    account_id = fields.Many2one("account.account", readonly=True)
    account_code = fields.Char(readonly=True)
    account_name = fields.Char(readonly=True)
    opening_debit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    opening_credit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    opening_balance = fields.Monetary(readonly=True, currency_field="company_currency_id")
    period_debit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    period_credit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    period_balance = fields.Monetary(readonly=True, currency_field="company_currency_id")
    ending_balance = fields.Monetary(readonly=True, currency_field="company_currency_id")
    entry_count = fields.Integer(readonly=True)
    company_currency_id = fields.Many2one(
        "res.currency", compute="_compute_company_currency_id",
    )

    @api.depends("wizard_id")
    def _compute_company_currency_id(self):
        for line in self:
            line.company_currency_id = self.env.company.currency_id
