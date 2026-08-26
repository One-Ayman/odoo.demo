import json
import time

from odoo import api, fields, models
from odoo.tools.sql import SQL

PAGE_SIZE_SELECTION = [("100", "100"), ("200", "200"), ("500", "500")]
#: Transaction-detail pages are naturally read row-by-row, so a smaller
#: granularity than the account-summary page sizes above is offered.
DETAIL_PAGE_SIZE_SELECTION = [("20", "20"), ("50", "50"), ("100", "100")]

PARTNER_TYPE_SELECTION = [
    ("all", "All"),
    ("customer", "Customer (Receivable)"),
    ("supplier", "Vendor (Payable)"),
]


class FastPartnerLedgerWizard(models.TransientModel):
    """Fast Partner Ledger / Partner Statement - step 1: per-partner
    summaries only, using the same single-pass conditional-SUM aggregation
    as the Trial Balance / General Ledger (see wizard/trial_balance.py).

    "Customer" / "Vendor" scope the ledger to receivable-type
    (account_type = 'asset_receivable') or payable-type
    (account_type = 'liability_payable') accounts respectively, matching
    what Odoo itself considers a partner's customer or vendor ledger; "All"
    includes both. The Account filter, if set, narrows this further.

    Every Opening/Period/Closing balance is collapsed to its NET value,
    sign-split back into Debit/Credit (see
    FastReportSqlMixin._ffr_net_split_sql) - a bucket with both debit and
    credit movement never shows both sides at once, only its net.
    """
    _name = "fast.partner.ledger.wizard"
    _inherit = "fast.report.sql.mixin"
    _description = "Fast Partner Ledger"

    company_ids = fields.Many2many(
        "res.company", string="Companies",
        default=lambda self: self.env.companies,
    )
    date_from = fields.Date(required=True, default=lambda self: fields.Date.context_today(self).replace(month=1, day=1))
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    partner_ids = fields.Many2many("res.partner", string="Partners")
    partner_category_ids = fields.Many2many(
        "res.partner.category", string="Partner Tags",
        help="Only include partners carrying at least one of the selected "
             "tags. Selecting several tags matches partners with ANY of "
             "them (OR), not all of them. Leave empty to include all "
             "partners regardless of tags.",
    )
    account_ids = fields.Many2many("account.account", string="Accounts")
    journal_ids = fields.Many2many("account.journal", string="Journals")
    partner_type = fields.Selection(PARTNER_TYPE_SELECTION, default="all", required=True, string="Type")
    posted_only = fields.Boolean(string="Posted Entries Only", default=True)
    page_size = fields.Selection(PAGE_SIZE_SELECTION, default="100", required=True, string="Rows per Page")
    page = fields.Integer(default=1)
    total_partner_count = fields.Integer(readonly=True)
    total_page_count = fields.Integer(readonly=True, compute="_compute_total_page_count")
    line_ids = fields.One2many("fast.partner.ledger.line", "wizard_id", string="Partner Summaries")
    generated = fields.Boolean(default=False)

    last_sql_time_ms = fields.Float(readonly=True, string="SQL Time (ms)")
    last_total_time_ms = fields.Float(readonly=True, string="Total Time (ms)")

    # Page totals for the PDF's Total row. Computed once in Python from the
    # already-fetched (bounded, single-page) ``line_ids`` in ``_ffr_refresh``
    # - no extra SQL query - and stored as real Monetary fields purely so the
    # QWeb report can render them with ``t-field`` and get the same
    # locale-correct number formatting (decimal/thousands separator) as
    # every other amount on the page, instead of a hardcoded '%.2f'.
    company_currency_id = fields.Many2one("res.currency", compute="_compute_company_currency_id")
    total_opening_debit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    total_opening_credit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    total_period_debit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    total_period_credit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    total_closing_debit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    total_closing_credit = fields.Monetary(readonly=True, currency_field="company_currency_id")

    @api.depends("company_ids")
    def _compute_company_currency_id(self):
        for wiz in self:
            wiz.company_currency_id = self.env.company.currency_id

    @api.depends("total_partner_count", "page_size")
    def _compute_total_page_count(self):
        for wiz in self:
            size = int(wiz.page_size or 100)
            wiz.total_page_count = max(1, (wiz.total_partner_count + size - 1) // size)

    def _ffr_account_type_sql(self):
        if self.partner_type == "customer":
            return SQL("aa.account_type = 'asset_receivable'")
        if self.partner_type == "supplier":
            return SQL("aa.account_type = 'liability_payable'")
        return SQL("aa.account_type IN ('asset_receivable', 'liability_payable')")

    def _ffr_partner_tag_sql(self):
        """Optional Partner Tag (``res.partner.category``) filter, pushed
        down as an ``EXISTS`` semi-join against the partner/tag relation
        table rather than a ``JOIN``.

        ``res_partner_res_partner_category_rel`` is a many-to-many table, so
        a partner carrying several of the selected tags would make a plain
        ``JOIN`` return that partner's ``account_move_line`` rows once per
        matching tag - silently inflating every SUM/COUNT in the report.
        ``EXISTS`` only ever tests for at least one match and never
        multiplies the outer row, so this is correct regardless of how many
        tags overlap. It also short-circuits (stops at the first match) and
        can use the relation table's ``(partner_id, category_id)`` index
        (created by the ``res.partner.category_id`` field itself), so it
        never requires a full scan of the relation table.

        ``self.partner_category_ids`` already accepts multiple tags (OR
        semantics, i.e. "any of these tags") - the initial UI exposes
        picking one, but no query/model change is needed to support more.
        """
        tag_ids = self.partner_category_ids.ids
        if not tag_ids:
            return SQL("1=1")
        return SQL(
            "EXISTS (SELECT 1 FROM res_partner_res_partner_category_rel rel "
            "WHERE rel.partner_id = aml.partner_id AND rel.category_id = ANY(%s))",
            list(set(tag_ids)),
        )

    def _ffr_where(self, extra_partner_id=None, join_account=True):
        self._ffr_check_dates(self.date_from, self.date_to)
        company_ids = self._ffr_allowed_company_ids(self.company_ids.ids)
        partner_ids = [extra_partner_id] if extra_partner_id else self.partner_ids.ids
        conditions = [
            SQL("aml.company_id = ANY(%s)", list(company_ids)),
            SQL("aml.partner_id IS NOT NULL"),
            self._ffr_posted_state_sql(self.posted_only),
            SQL("(aml.display_type IS NULL OR aml.display_type NOT IN ('line_section', 'line_note'))"),
            self._ffr_in_ids_sql("aml.partner_id", partner_ids),
            self._ffr_in_ids_sql("aml.account_id", self.account_ids.ids),
            self._ffr_in_ids_sql("aml.journal_id", self.journal_ids.ids),
            self._ffr_partner_tag_sql(),
        ]
        if join_account:
            conditions.append(self._ffr_account_type_sql())
        return SQL(" AND ").join(conditions), company_ids

    def _ffr_grouped_sql(self):
        """(grouped_sql, having_sql, company_ids) shared by the interactive
        query and the XLSX export - gross debit/credit sums per bucket,
        net-split at the final SELECT layer (see ``_ffr_net_split_select``)
        so the two never drift apart."""
        where_sql, company_ids = self._ffr_where()
        filtered_sql = SQL(
            "SELECT aml.partner_id, aml.debit, aml.credit, aml.date "
            "FROM account_move_line aml "
            "JOIN account_account aa ON aa.id = aml.account_id "
            "WHERE %s",
            where_sql,
        )
        grouped_sql = SQL(
            "SELECT partner_id, "
            "SUM(CASE WHEN date < %s THEN debit ELSE 0 END) AS opening_debit_gross, "
            "SUM(CASE WHEN date < %s THEN credit ELSE 0 END) AS opening_credit_gross, "
            "SUM(CASE WHEN date BETWEEN %s AND %s THEN debit ELSE 0 END) AS period_debit_gross, "
            "SUM(CASE WHEN date BETWEEN %s AND %s THEN credit ELSE 0 END) AS period_credit_gross "
            "FROM (%s) filtered "
            "GROUP BY partner_id",
            self.date_from, self.date_from,
            self.date_from, self.date_to,
            self.date_from, self.date_to,
            filtered_sql,
        )
        having_sql = SQL(
            "WHERE g.opening_debit_gross != 0 OR g.opening_credit_gross != 0 "
            "OR g.period_debit_gross != 0 OR g.period_credit_gross != 0"
        )
        return grouped_sql, having_sql, company_ids

    def _ffr_net_split_select(self):
        """The six net-split Debit/Credit SQL fragments (Opening, Period,
        Closing), reused identically by the interactive query and the
        XLSX export."""
        opening_net = SQL("g.opening_debit_gross - g.opening_credit_gross")
        period_net = SQL("g.period_debit_gross - g.period_credit_gross")
        closing_net = SQL("(%s) + (%s)", opening_net, period_net)
        opening_debit, opening_credit = self._ffr_net_split_sql(opening_net)
        period_debit, period_credit = self._ffr_net_split_sql(period_net)
        closing_debit, closing_credit = self._ffr_net_split_sql(closing_net)
        return SQL(
            "%s AS opening_debit, %s AS opening_credit, "
            "%s AS period_debit, %s AS period_credit, "
            "%s AS closing_debit, %s AS closing_credit",
            opening_debit, opening_credit, period_debit, period_credit,
            closing_debit, closing_credit,
        )

    def _ffr_export_sql(self):
        """Full (unpaginated) partner-summary result set, for XLSX export."""
        grouped_sql, having_sql, company_ids = self._ffr_grouped_sql()
        return SQL(
            "SELECT rp.name AS partner_name, %s "
            "FROM (%s) g JOIN res_partner rp ON rp.id = g.partner_id %s "
            "ORDER BY rp.name",
            self._ffr_net_split_select(), grouped_sql, having_sql,
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
        grouped_sql, having_sql, company_ids = self._ffr_grouped_sql()

        size = int(self.page_size)
        offset = (self.page - 1) * size
        count_sql = SQL("SELECT COUNT(*) FROM (%s) g %s", grouped_sql, having_sql)
        total = self._ffr_execute_scalar(count_sql) or 0

        final_sql = SQL(
            "SELECT g.partner_id, rp.name AS partner_name, %s "
            "FROM (%s) g JOIN res_partner rp ON rp.id = g.partner_id %s "
            "ORDER BY rp.name LIMIT %s OFFSET %s",
            self._ffr_net_split_select(), grouped_sql, having_sql, size, offset,
        )
        rows, sql_time_ms = self._ffr_execute(final_sql)

        self.line_ids.unlink()
        vals_list = []
        for seq, row in enumerate(rows):
            vals_list.append({
                "wizard_id": self.id,
                "sequence": seq,
                "partner_id": row["partner_id"],
                "partner_name": row["partner_name"],
                "opening_debit": row["opening_debit"],
                "opening_credit": row["opening_credit"],
                "period_debit": row["period_debit"],
                "period_credit": row["period_credit"],
                "closing_debit": row["closing_debit"],
                "closing_credit": row["closing_credit"],
            })
        if vals_list:
            self.env["fast.partner.ledger.line"].create(vals_list)

        total_time_ms = (time.perf_counter() - t0) * 1000.0
        self.write({
            "total_partner_count": total,
            "generated": True,
            "last_sql_time_ms": sql_time_ms,
            "last_total_time_ms": total_time_ms,
            # Sums over this page's already-fetched vals_list (bounded by
            # page_size) - not a new query.
            "total_opening_debit": sum(v["opening_debit"] for v in vals_list),
            "total_opening_credit": sum(v["opening_credit"] for v in vals_list),
            "total_period_debit": sum(v["period_debit"] for v in vals_list),
            "total_period_credit": sum(v["period_credit"] for v in vals_list),
            "total_closing_debit": sum(v["closing_debit"] for v in vals_list),
            "total_closing_credit": sum(v["closing_credit"] for v in vals_list),
        })
        self._ffr_log_debug(
            report_type="partner_ledger_summary",
            query_id="ffr_partner_ledger_summary_v1",
            company_ids=company_ids,
            params={
                "date_from": str(self.date_from), "date_to": str(self.date_to),
                "partner_ids": self.partner_ids.ids, "account_ids": self.account_ids.ids,
                "journal_ids": self.journal_ids.ids, "partner_type": self.partner_type,
                "partner_category_ids": self.partner_category_ids.ids,
                "posted_only": self.posted_only, "page": self.page, "page_size": self.page_size,
            },
            sql_time_ms=sql_time_ms,
            processing_time_ms=total_time_ms - sql_time_ms,
            total_time_ms=total_time_ms,
            row_count=len(rows),
            query_count=2,
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "fast.partner.ledger.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_export_xlsx(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": "/fast_financial_reports/export/partner_ledger/xlsx/%s" % self.id,
            "target": "self",
        }

    def action_export_pdf(self):
        self.ensure_one()
        return self.env.ref("fast_financial_reports.action_report_partner_ledger").report_action(self)


class FastPartnerLedgerLine(models.TransientModel):
    _name = "fast.partner.ledger.line"
    _description = "Fast Partner Ledger - Partner Summary Line"
    _order = "sequence, partner_name"

    wizard_id = fields.Many2one("fast.partner.ledger.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer()
    partner_id = fields.Many2one("res.partner", readonly=True)
    partner_name = fields.Char(readonly=True)
    opening_debit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    opening_credit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    period_debit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    period_credit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    closing_debit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    closing_credit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    company_currency_id = fields.Many2one("res.currency", compute="_compute_company_currency_id")

    @api.depends("wizard_id")
    def _compute_company_currency_id(self):
        for line in self:
            line.company_currency_id = self.env.company.currency_id

    def action_view_transactions(self):
        self.ensure_one()
        detail = self.env["fast.partner.ledger.detail.wizard"].create({
            "parent_wizard_id": self.wizard_id.id,
            "partner_id": self.partner_id.id,
            "partner_name": self.partner_name,
            # opening_debit/opening_credit are this line's sign-split NET
            # opening balance display, not two separate movements -
            # recombine them to seed the detail's running balance.
            "opening_balance": self.opening_debit - self.opening_credit,
        })
        detail.action_load_first_page()
        return {
            "type": "ir.actions.act_window",
            "res_model": "fast.partner.ledger.detail.wizard",
            "res_id": detail.id,
            "view_mode": "form",
            "target": "new",
        }


class FastPartnerLedgerDetailWizard(models.TransientModel):
    """Transaction-level drill-down for a single partner and the original
    date range, using keyset (cursor) pagination - identical technique to
    fast.general.ledger.detail.wizard, see there for the full explanation."""
    _name = "fast.partner.ledger.detail.wizard"
    _inherit = "fast.report.sql.mixin"
    _description = "Fast Partner Ledger - Transaction Detail"

    parent_wizard_id = fields.Many2one("fast.partner.ledger.wizard", required=True, ondelete="cascade")
    partner_id = fields.Many2one("res.partner", readonly=True)
    partner_name = fields.Char(readonly=True)
    opening_balance = fields.Monetary(readonly=True, currency_field="company_currency_id")
    company_currency_id = fields.Many2one("res.currency", compute="_compute_company_currency_id")
    page_size = fields.Selection(DETAIL_PAGE_SIZE_SELECTION, default="20", required=True, string="Rows per Page")
    page_number = fields.Integer(default=1, readonly=True)
    has_next_page = fields.Boolean(readonly=True)
    has_prev_page = fields.Boolean(readonly=True, compute="_compute_has_prev_page")
    start_date = fields.Date(readonly=True)
    start_line_id = fields.Integer(readonly=True)
    start_running_balance = fields.Monetary(readonly=True, currency_field="company_currency_id")
    end_date = fields.Date(readonly=True)
    end_line_id = fields.Integer(readonly=True)
    end_running_balance = fields.Monetary(readonly=True, currency_field="company_currency_id")
    cursor_stack = fields.Text(default="[]")
    detail_line_ids = fields.One2many("fast.partner.ledger.detail.line", "detail_wizard_id")

    @api.depends("parent_wizard_id")
    def _compute_company_currency_id(self):
        for wiz in self:
            wiz.company_currency_id = self.env.company.currency_id

    @api.depends("cursor_stack")
    def _compute_has_prev_page(self):
        for wiz in self:
            wiz.has_prev_page = bool(json.loads(wiz.cursor_stack or "[]"))

    def _ffr_fetch_page(self, start_date, start_line_id):
        parent = self.parent_wizard_id
        where_sql, company_ids = parent._ffr_where(extra_partner_id=self.partner_id.id)
        if start_date is not None and start_line_id is not None:
            where_sql = SQL(
                "%s AND (aml.date, aml.id) > (%s, %s)",
                where_sql, start_date, start_line_id,
            )
        size = int(self.page_size)
        final_sql = SQL(
            "SELECT aml.id, aml.date, j.code AS journal_code, aml.move_name, "
            "aml.ref, aml.name AS label, aml.debit, aml.credit "
            "FROM account_move_line aml "
            "JOIN account_account aa ON aa.id = aml.account_id "
            "JOIN account_journal j ON j.id = aml.journal_id "
            "WHERE %s "
            "ORDER BY aml.date, aml.id "
            "LIMIT %s",
            where_sql, size + 1,
        )
        rows, sql_time_ms = self._ffr_execute(final_sql)
        has_next = len(rows) > size
        rows = rows[:size]
        return rows, has_next, sql_time_ms, company_ids

    def _ffr_load_page(self, start_date, start_line_id, start_running_balance):
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
                "label": row["label"],
                "debit": row["debit"],
                "credit": row["credit"],
                "running_balance": running,
            })
            end_date, end_id = row["date"], row["id"]
        if vals_list:
            self.env["fast.partner.ledger.detail.line"].create(vals_list)

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
            report_type="partner_ledger_detail",
            query_id="ffr_partner_ledger_detail_v1",
            company_ids=company_ids,
            params={"partner_id": self.partner_id.id, "page_size": self.page_size},
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


class FastPartnerLedgerDetailLine(models.TransientModel):
    _name = "fast.partner.ledger.detail.line"
    _description = "Fast Partner Ledger - Transaction Line"
    _order = "sequence"

    detail_wizard_id = fields.Many2one("fast.partner.ledger.detail.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer()
    move_line_id = fields.Many2one("account.move.line", readonly=True)
    date = fields.Date(readonly=True)
    journal_code = fields.Char(readonly=True)
    move_name = fields.Char(readonly=True, string="Move")
    ref = fields.Char(readonly=True, string="Reference")
    label = fields.Char(readonly=True)
    debit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    credit = fields.Monetary(readonly=True, currency_field="company_currency_id")
    running_balance = fields.Monetary(readonly=True, currency_field="company_currency_id")
    company_currency_id = fields.Many2one("res.currency", compute="_compute_company_currency_id")

    @api.depends("detail_wizard_id")
    def _compute_company_currency_id(self):
        for line in self:
            line.company_currency_id = self.env.company.currency_id
