from odoo.tests import tagged

from .common import FastFinancialReportsCommon


@tagged("post_install", "-at_install", "fast_financial_reports")
class TestFastPartnerLedger(FastFinancialReportsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._post_entry(cls, "2024-01-05", [
            (cls.account_receivable, 200, 0, cls.partner_a), (cls.account_income, 0, 200, None),
        ], partner_id=cls.partner_a.id)
        cls._post_entry(cls, "2024-02-10", [
            (cls.account_receivable, 0, 80, cls.partner_a), (cls.account_bank, 80, 0, None),
        ], partner_id=cls.partner_a.id)
        cls._post_entry(cls, "2024-03-01", [
            (cls.account_payable, 0, 150, cls.partner_b), (cls.account_expense, 150, 0, None),
        ], partner_id=cls.partner_b.id)

    def _generate(self, **vals):
        vals.setdefault("company_ids", [(6, 0, [self.company.id])])
        wizard = self.env["fast.partner.ledger.wizard"].create(vals)
        wizard.action_generate()
        return wizard

    def test_customer_balance(self):
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31", partner_type="customer")
        line = wizard.line_ids.filtered(lambda l: l.partner_id == self.partner_a)
        self.assertAlmostEqual(line.closing_balance, 120.0, places=2)  # 200 - 80

    def test_vendor_balance(self):
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31", partner_type="supplier")
        line = wizard.line_ids.filtered(lambda l: l.partner_id == self.partner_b)
        self.assertAlmostEqual(line.closing_balance, -150.0, places=2)

    def test_all_scope_includes_both(self):
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31", partner_type="all")
        partners = wizard.line_ids.partner_id
        self.assertIn(self.partner_a, partners)
        self.assertIn(self.partner_b, partners)

    def test_partner_filter_scopes_detail_query(self):
        wizard = self._generate(
            date_from="2024-01-01", date_to="2024-12-31",
            partner_ids=[(6, 0, [self.partner_a.id])],
        )
        self.assertEqual(wizard.line_ids.partner_id, self.partner_a)

    def test_drill_down_detail_only_for_selected_partner(self):
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31", partner_type="all")
        line_a = wizard.line_ids.filtered(lambda l: l.partner_id == self.partner_a)
        action = line_a.action_view_transactions()
        detail = self.env["fast.partner.ledger.detail.wizard"].browse(action["res_id"])
        self.assertEqual(len(detail.detail_line_ids), 2)
        self.assertAlmostEqual(detail.detail_line_ids[-1].running_balance, 120.0, places=2)

    def test_no_movement_in_future_period(self):
        # Opening balances still carry forward, but no line may show any
        # period debit/credit in a year with no postings at all.
        wizard = self._generate(date_from="2030-01-01", date_to="2030-12-31")
        for line in wizard.line_ids:
            self.assertAlmostEqual(line.period_debit, 0.0, places=2)
            self.assertAlmostEqual(line.period_credit, 0.0, places=2)

    def test_no_results_for_partner_with_no_history(self):
        empty_partner = self.env["res.partner"].create({"name": "FFR Never Invoiced"})
        wizard = self._generate(
            date_from="2024-01-01", date_to="2024-12-31",
            partner_ids=[(6, 0, [empty_partner.id])],
        )
        self.assertEqual(wizard.total_partner_count, 0)
        self.assertFalse(wizard.line_ids)
