from odoo import fields, models


class FastReportDebugLog(models.Model):
    """Technical performance log for the Fast Financial Reports engine.

    Rows are only written when the ``fast_financial_reports.debug_mode``
    system parameter is enabled. Ordinary users never see this model: it is
    only exposed to the technical/debug security group.
    """
    _name = "fast.report.debug.log"
    _description = "Fast Financial Reports - Performance Debug Log"
    _order = "create_date desc"
    _log_access = True

    report_type = fields.Selection(
        selection=[
            ("trial_balance", "Trial Balance"),
            ("general_ledger_summary", "General Ledger - Summary"),
            ("general_ledger_detail", "General Ledger - Detail"),
            ("partner_ledger_summary", "Partner Ledger - Summary"),
            ("partner_ledger_detail", "Partner Ledger - Detail"),
        ],
        required=True,
        index=True,
    )
    query_id = fields.Char(
        string="Query Identifier",
        help="Short technical identifier of the SQL query template that was executed, "
             "for correlation with the SQL architecture documentation.",
    )
    user_id = fields.Many2one("res.users", required=True, index=True)
    company_ids = fields.Many2many("res.company", string="Companies")
    filter_params = fields.Text(
        string="Filter Parameters",
        help="JSON dump of the sanitized filter parameters used for this report run "
             "(no accounting data, only filter values).",
    )
    sql_time_ms = fields.Float(string="SQL Execution Time (ms)")
    processing_time_ms = fields.Float(string="Python Processing Time (ms)")
    total_time_ms = fields.Float(string="Total Response Time (ms)")
    row_count = fields.Integer(string="Returned Row Count")
    query_count = fields.Integer(string="SQL Query Count")
