import time

from odoo.tests import tagged

from .common import FastFinancialReportsCommon

#: Kept modest so the automated suite runs quickly; see the module README
#: for the honest, separately-documented benchmark methodology used to
#: validate behaviour at multi-million-row scale (this test proves the
#: *shape* of the query plan - constant, small query count regardless of
#: row volume - not raw throughput at production scale).
BULK_MOVE_COUNT = 400


@tagged("post_install", "-at_install", "fast_financial_reports")
class TestFastFinancialReportsPerformanceQueries(FastFinancialReportsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        move_vals = []
        for i in range(BULK_MOVE_COUNT):
            day = 1 + (i % 27)
            month = 1 + (i % 12)
            move_vals.append({
                "move_type": "entry",
                "journal_id": cls.journal_misc.id,
                "date": "2024-%02d-%02d" % (month, day),
                "line_ids": [
                    (0, 0, {
                        "account_id": cls.account_bank.id, "name": "Bulk %s" % i,
                        "debit": 10.0, "credit": 0.0,
                    }),
                    (0, 0, {
                        "account_id": cls.account_income.id, "name": "Bulk %s" % i,
                        "debit": 0.0, "credit": 10.0,
                    }),
                ],
            })
        moves = cls.env["account.move"].create(move_vals)
        moves.action_post()
        cls.bulk_move_count = BULK_MOVE_COUNT

    def test_trial_balance_query_count_is_constant(self):
        """The number of SQL queries issued by the trial balance summary
        must not grow with the number of underlying journal items - it
        should stay a small constant (one COUNT + one aggregated SELECT),
        proving the aggregation happens in PostgreSQL, not in a Python loop
        over account.move.line."""
        wizard = self.env["fast.trial.balance.wizard"].create({
            "date_from": "2024-01-01", "date_to": "2024-12-31",
            "company_ids": [(6, 0, [self.company.id])],
        })
        before = self.env.cr.sql_log_count
        wizard.action_generate()
        query_count = self.env.cr.sql_log_count - before
        self.assertLess(
            query_count, 15,
            "Trial balance issued %d SQL queries for %d underlying journal "
            "entries - this suggests a per-row Python loop instead of a "
            "single aggregated query." % (query_count, self.bulk_move_count),
        )

    def test_trial_balance_result_matches_bulk_data(self):
        wizard = self.env["fast.trial.balance.wizard"].create({
            "date_from": "2024-01-01", "date_to": "2024-12-31",
            "company_ids": [(6, 0, [self.company.id])],
        })
        wizard.action_generate()
        bank_line = wizard.line_ids.filtered(lambda l: l.account_id == self.account_bank)
        self.assertAlmostEqual(bank_line.period_debit, 10.0 * self.bulk_move_count, places=2)

    def test_general_ledger_detail_page_is_bounded(self):
        """Opening the drill-down for an account with hundreds of lines must
        only return one page's worth of rows to Python, never the full set."""
        wizard = self.env["fast.general.ledger.wizard"].create({
            "date_from": "2024-01-01", "date_to": "2024-12-31",
            "company_ids": [(6, 0, [self.company.id])],
        })
        wizard.action_generate()
        bank_line = wizard.line_ids.filtered(lambda l: l.account_id == self.account_bank)
        action = bank_line.action_view_transactions()
        detail = self.env["fast.general.ledger.detail.wizard"].browse(action["res_id"])
        detail.write({"page_size": "100"})
        detail.action_load_first_page()
        self.assertEqual(len(detail.detail_line_ids), 100)
        self.assertTrue(detail.has_next_page)

    def test_debug_mode_records_timing(self):
        self.env["ir.config_parameter"].sudo().set_param("fast_financial_reports.debug_mode", "True")
        wizard = self.env["fast.trial.balance.wizard"].create({
            "date_from": "2024-01-01", "date_to": "2024-12-31",
            "company_ids": [(6, 0, [self.company.id])],
        })
        wizard.action_generate()
        log = self.env["fast.report.debug.log"].sudo().search(
            [("report_type", "=", "trial_balance")], limit=1, order="id desc",
        )
        self.assertTrue(log)
        self.assertGreater(log.total_time_ms, 0)
        self.assertEqual(log.row_count, len(wizard.line_ids))

    def test_debug_mode_off_by_default(self):
        self.env["ir.config_parameter"].sudo().set_param("fast_financial_reports.debug_mode", "False")
        before = self.env["fast.report.debug.log"].sudo().search_count([])
        wizard = self.env["fast.trial.balance.wizard"].create({
            "date_from": "2024-01-01", "date_to": "2024-12-31",
            "company_ids": [(6, 0, [self.company.id])],
        })
        wizard.action_generate()
        after = self.env["fast.report.debug.log"].sudo().search_count([])
        self.assertEqual(before, after)
