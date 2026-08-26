import io

import xlsxwriter

from odoo import http
from odoo.http import request

#: Odoo model + column headers for each exportable report. Columns must be
#: the exact aliases used by each wizard's ``_ffr_export_sql()``.
#:
#: Every Opening/Period/Ending (or Closing) balance is the already
#: net-split Debit/Credit pair the SQL computes (see
#: ``FastReportSqlMixin._ffr_net_split_sql``) - never a combined
#: "Balance" column and never an "Entry Count"/"Number of Entries"
#: column anywhere in this module.
_EXPORT_SPECS = {
    "trial_balance": (
        "fast.trial.balance.wizard",
        [
            ("account_code", "Account Code"), ("account_name", "Account Name"),
            ("opening_debit", "Opening Debit"), ("opening_credit", "Opening Credit"),
            ("period_debit", "Period Debit"), ("period_credit", "Period Credit"),
            ("ending_debit", "Ending Debit"), ("ending_credit", "Ending Credit"),
        ],
    ),
    "general_ledger": (
        "fast.general.ledger.wizard",
        [
            ("account_code", "Account Code"), ("account_name", "Account Name"),
            ("opening_debit", "Opening Debit"), ("opening_credit", "Opening Credit"),
            ("period_debit", "Period Debit"), ("period_credit", "Period Credit"),
            ("ending_debit", "Ending Debit"), ("ending_credit", "Ending Credit"),
        ],
    ),
    "partner_ledger": (
        "fast.partner.ledger.wizard",
        [
            ("partner_name", "Partner"),
            ("opening_debit", "Opening Debit"), ("opening_credit", "Opening Credit"),
            ("period_debit", "Period Debit"), ("period_credit", "Period Credit"),
            ("closing_debit", "Closing Debit"), ("closing_credit", "Closing Credit"),
        ],
    ),
}


class FastFinancialReportsController(http.Controller):

    @http.route(
        "/fast_financial_reports/export/<string:report_key>/xlsx/<int:wizard_id>",
        type="http", auth="user", methods=["GET"],
    )
    def export_xlsx(self, report_key, wizard_id, **kwargs):
        spec = _EXPORT_SPECS.get(report_key)
        if not spec:
            return request.not_found()
        model_name, columns = spec

        wizard = request.env[model_name].browse(wizard_id).exists()
        # Defense in depth: TransientModel access rights already scope this,
        # but a report may only ever be exported by the user who ran it.
        if not wizard or wizard.create_uid.id != request.env.uid:
            return request.not_found()

        sql, _company_ids = wizard._ffr_export_sql()

        buffer = io.BytesIO()
        # constant_memory=True makes xlsxwriter flush each row to disk as
        # soon as it is written, instead of keeping the whole worksheet
        # in memory - this is what keeps the export memory-safe regardless
        # of how many accounts/partners match the filters.
        workbook = xlsxwriter.Workbook(buffer, {"in_memory": True, "constant_memory": True})
        worksheet = workbook.add_worksheet(report_key[:31])
        header_format = workbook.add_format({"bold": True})

        for col_index, (_key, label) in enumerate(columns):
            worksheet.write(0, col_index, label, header_format)

        row_index = 1
        # Stream rows straight from the database cursor in bounded chunks
        # (see FastReportSqlMixin._ffr_iter_chunks) instead of fetchall(),
        # so no giant Python list of rows is ever built in memory.
        for db_columns, chunk in wizard._ffr_iter_chunks(sql):
            col_positions = [db_columns.index(key) for key, _label in columns]
            for db_row in chunk:
                for out_col, db_col in enumerate(col_positions):
                    worksheet.write(row_index, out_col, db_row[db_col])
                row_index += 1

        workbook.close()
        buffer.seek(0)
        content = buffer.read()

        filename = "%s_%s.xlsx" % (report_key, wizard_id)
        headers = [
            ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("Content-Disposition", 'attachment; filename="%s"' % filename),
            ("Content-Length", len(content)),
        ]
        return request.make_response(content, headers=headers)
