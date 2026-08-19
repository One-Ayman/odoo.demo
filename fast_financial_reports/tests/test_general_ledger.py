from odoo.tests import tagged

from .common import FastFinancialReportsCommon


@tagged("post_install", "-at_install", "fast_financial_reports")
class TestFastGeneralLedger(FastFinancialReportsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._post_entry(cls, "2023-12-20", [
            (cls.account_bank, 300, 0, None), (cls.account_income, 0, 300, None),
        ])
        cls._post_entry(cls, "2024-01-05", [
            (cls.account_bank, 100, 0, None), (cls.account_income, 0, 100, None),
        ])
        cls._post_entry(cls, "2024-01-10", [
            (cls.account_expense, 50, 0, None), (cls.account_bank, 0, 50, None),
        ])
        cls._post_entry(cls, "2024-06-15", [
            (cls.account_receivable, 200, 0, cls.partner_a), (cls.account_income, 0, 200, None),
        ], journal=cls.journal_sales, partner_id=cls.partner_a.id)

    def _generate(self, **vals):
        vals.setdefault("company_ids", [(6, 0, [self.company.id])])
        wizard = self.env["fast.general.ledger.wizard"].create(vals)
        wizard.action_generate()
        return wizard

    def test_summary_totals_reconcile(self):
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31")
        for line in wizard.line_ids:
            self.assertAlmostEqual(
                line.opening_balance + line.period_debit - line.period_credit,
                line.closing_balance, places=2,
            )

    def test_summary_does_not_load_detail(self):
        """The step-1 summary query must never touch transaction detail: no
        detail wizard/lines should exist until the user explicitly opens
        one account."""
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31")
        self.assertFalse(self.env["fast.general.ledger.detail.wizard"].search([
            ("parent_wizard_id", "=", wizard.id),
        ]))

    def test_drill_down_running_balance(self):
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31")
        bank_line = wizard.line_ids.filtered(lambda l: l.account_id == self.account_bank)
        action = bank_line.action_view_transactions()
        detail = self.env["fast.general.ledger.detail.wizard"].browse(action["res_id"])
        self.assertEqual(len(detail.detail_line_ids), 2)
        running = bank_line.opening_balance
        for line in detail.detail_line_ids:
            running += line.debit - line.credit
            self.assertAlmostEqual(line.running_balance, running, places=2)
        self.assertAlmostEqual(running, bank_line.closing_balance, places=2)

    def test_keyset_pagination_next_prev(self):
        # A dedicated account with enough postings to span two 20-row pages.
        many_account = self.env["account.account"].create({
            "code": "TSTMANY", "name": "Many Lines Account", "account_type": "expense",
        })
        for day in range(1, 26):
            self._post_entry("2024-03-%02d" % day, [
                (many_account, 5.0, 0.0, None), (self.account_income, 0.0, 5.0, None),
            ])
        wizard = self._generate(
            date_from="2024-01-01", date_to="2024-12-31",
            account_ids=[(6, 0, [many_account.id])],
        )
        line = wizard.line_ids.filtered(lambda l: l.account_id == many_account)
        action = line.action_view_transactions()
        detail = self.env["fast.general.ledger.detail.wizard"].browse(action["res_id"])
        self.assertEqual(len(detail.detail_line_ids), 20)
        self.assertTrue(detail.has_next_page)
        first_page_line = detail.detail_line_ids[0].move_line_id
        detail.action_next_page()
        self.assertEqual(len(detail.detail_line_ids), 5)
        second_page_line = detail.detail_line_ids[0].move_line_id
        self.assertNotEqual(first_page_line, second_page_line)
        detail.action_prev_page()
        self.assertEqual(detail.detail_line_ids[0].move_line_id, first_page_line)

    def test_move_type_filter_requires_join_but_works(self):
        wizard = self._generate(
            date_from="2024-01-01", date_to="2024-12-31", move_type="entry",
        )
        self.assertTrue(wizard.total_account_count)

    def test_no_movement_in_future_period(self):
        # Opening balances still carry forward, but no line may show any
        # period debit/credit in a year with no postings at all.
        wizard = self._generate(date_from="2030-01-01", date_to="2030-12-31")
        for line in wizard.line_ids:
            self.assertAlmostEqual(line.period_debit, 0.0, places=2)
            self.assertAlmostEqual(line.period_credit, 0.0, places=2)

    def test_no_results_for_account_with_no_history(self):
        empty_account = self.env["account.account"].create({
            "code": "TSTGLEMPTY", "name": "Never Used", "account_type": "expense",
        })
        wizard = self._generate(
            date_from="2024-01-01", date_to="2024-12-31",
            account_ids=[(6, 0, [empty_account.id])],
        )
        self.assertEqual(wizard.total_account_count, 0)
        self.assertFalse(wizard.line_ids)
        self.assertFalse(wizard.line_ids)
