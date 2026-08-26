from odoo.tests import tagged

from .common import FastFinancialReportsCommon


@tagged("post_install", "-at_install", "fast_financial_reports")
class TestFastPartnerLedger(FastFinancialReportsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # partner_a has BOTH a debit (200) and a credit (80) movement
        # within the same period, deliberately, to exercise net-only
        # display.
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

    def _line_for(self, wizard, partner):
        return wizard.line_ids.filtered(lambda l: l.partner_id == partner)

    def test_customer_balance(self):
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31", partner_type="customer")
        line = wizard.line_ids.filtered(lambda l: l.partner_id == self.partner_a)
        # 200 - 80 = 120, net debit.
        self.assertAlmostEqual(line.closing_debit, 120.0, places=2)
        self.assertAlmostEqual(line.closing_credit, 0.0, places=2)

    def test_vendor_balance(self):
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31", partner_type="supplier")
        line = wizard.line_ids.filtered(lambda l: l.partner_id == self.partner_b)
        self.assertAlmostEqual(line.closing_debit, 0.0, places=2)
        self.assertAlmostEqual(line.closing_credit, 150.0, places=2)

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

    # ------------------------------------------------------------------
    # Net-balance display rule (Opening/Period/Closing never both sides)
    # ------------------------------------------------------------------
    def test_net_balance_never_shows_both_debit_and_credit_together(self):
        """User-mandated rule: every Opening/Period/Closing balance must
        show the NET balance only. partner_a has both a debit (200) and a
        credit (80) movement within the same period; the report must show
        Debit=120 / Credit=0, never Debit=200 AND Credit=80 together."""
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31", partner_type="all")
        line_a = self._line_for(wizard, self.partner_a)
        self.assertAlmostEqual(line_a.period_debit, 120.0, places=2)
        self.assertAlmostEqual(line_a.period_credit, 0.0, places=2)
        for line in wizard.line_ids:
            self.assertTrue(
                line.opening_debit == 0.0 or line.opening_credit == 0.0,
                "opening_debit and opening_credit must never both be non-zero (partner %s)" % line.partner_name,
            )
            self.assertTrue(
                line.period_debit == 0.0 or line.period_credit == 0.0,
                "period_debit and period_credit must never both be non-zero (partner %s)" % line.partner_name,
            )
            self.assertTrue(
                line.closing_debit == 0.0 or line.closing_credit == 0.0,
                "closing_debit and closing_credit must never both be non-zero (partner %s)" % line.partner_name,
            )

    def test_net_balance_debit_heavy_bucket_shows_debit_only(self):
        """Explicit worked example matching the requirement: gross debit
        10,000 / credit 7,000 in the same period must display as
        Debit=3,000 / Credit=0, never both gross amounts."""
        partner_c = self.env["res.partner"].create({"name": "FFR Net Split Partner C"})
        self._post_entry("2024-05-01", [
            (self.account_receivable, 10000, 0, partner_c), (self.account_income, 0, 10000, None),
        ], partner_id=partner_c.id)
        self._post_entry("2024-05-02", [
            (self.account_receivable, 0, 7000, partner_c), (self.account_bank, 7000, 0, None),
        ], partner_id=partner_c.id)
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31", partner_type="all")
        line = self._line_for(wizard, partner_c)
        self.assertAlmostEqual(line.period_debit, 3000.0, places=2)
        self.assertAlmostEqual(line.period_credit, 0.0, places=2)

    def test_net_balance_credit_heavy_bucket_shows_credit_only(self):
        """Same rule, opposite sign: gross debit 7,000 / credit 10,000
        must display as Debit=0 / Credit=3,000."""
        partner_d = self.env["res.partner"].create({"name": "FFR Net Split Partner D"})
        self._post_entry("2024-07-01", [
            (self.account_receivable, 7000, 0, partner_d), (self.account_income, 0, 7000, None),
        ], partner_id=partner_d.id)
        self._post_entry("2024-07-02", [
            (self.account_receivable, 0, 10000, partner_d), (self.account_bank, 10000, 0, None),
        ], partner_id=partner_d.id)
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31", partner_type="all")
        line = self._line_for(wizard, partner_d)
        self.assertAlmostEqual(line.period_debit, 0.0, places=2)
        self.assertAlmostEqual(line.period_credit, 3000.0, places=2)

    def test_net_balance_opening_credit_heavy_shows_credit_only(self):
        """The same net-only rule applies to the Opening bucket, not just
        Period: a partner whose activity BEFORE date_from nets to a
        credit balance must show Opening Credit only."""
        partner_e = self.env["res.partner"].create({"name": "FFR Net Split Partner E"})
        self._post_entry("2023-01-01", [
            (self.account_receivable, 4000, 0, partner_e), (self.account_income, 0, 4000, None),
        ], partner_id=partner_e.id)
        self._post_entry("2023-02-01", [
            (self.account_receivable, 0, 9000, partner_e), (self.account_bank, 9000, 0, None),
        ], partner_id=partner_e.id)
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31", partner_type="all")
        line = self._line_for(wizard, partner_e)
        self.assertAlmostEqual(line.opening_debit, 0.0, places=2)
        self.assertAlmostEqual(line.opening_credit, 5000.0, places=2)

    # ------------------------------------------------------------------
    # Partner Tag filter
    # ------------------------------------------------------------------
    def test_partner_tag_filter_includes_only_tagged_partners(self):
        vip = self.env["res.partner.category"].create({"name": "FFR VIP"})
        self.partner_a.category_id = [(4, vip.id)]
        # partner_b deliberately left untagged.
        wizard = self._generate(
            date_from="2024-01-01", date_to="2024-12-31", partner_type="all",
            partner_category_ids=[(6, 0, [vip.id])],
        )
        self.assertEqual(wizard.line_ids.partner_id, self.partner_a)
        self.assertNotIn(self.partner_b, wizard.line_ids.partner_id)

    def test_partner_tag_filter_excludes_untagged_partner_entirely(self):
        vip = self.env["res.partner.category"].create({"name": "FFR VIP 2"})
        self.partner_a.category_id = [(4, vip.id)]
        wizard = self._generate(
            date_from="2024-01-01", date_to="2024-12-31", partner_type="all",
            partner_category_ids=[(6, 0, [vip.id])],
        )
        self.assertEqual(wizard.total_partner_count, 1)

    def test_partner_tag_filter_empty_returns_all_partners(self):
        # No tag selected at all -> behaves exactly as before the feature
        # existed (every partner in scope, tagged or not).
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31", partner_type="all")
        partners = wizard.line_ids.partner_id
        self.assertIn(self.partner_a, partners)
        self.assertIn(self.partner_b, partners)

    def test_partner_tag_filter_combined_with_other_filters(self):
        """The tag filter must narrow results together with (not instead
        of) the existing partner_type/date/company filters."""
        vip = self.env["res.partner.category"].create({"name": "FFR VIP 3"})
        self.partner_a.category_id = [(4, vip.id)]
        self.partner_b.category_id = [(4, vip.id)]
        # Both partners carry the tag, but only partner_a is a customer
        # (asset_receivable) - the type filter must still apply.
        wizard = self._generate(
            date_from="2024-01-01", date_to="2024-12-31", partner_type="customer",
            partner_category_ids=[(6, 0, [vip.id])],
        )
        self.assertEqual(wizard.line_ids.partner_id, self.partner_a)

    def test_partner_tag_filter_multiple_tags_no_duplicate_amounts(self):
        """A partner carrying several of the selected tags must appear
        exactly once, with correct (non-doubled) totals - proves the
        EXISTS-based semi-join, not a duplicating JOIN, is used."""
        tag1 = self.env["res.partner.category"].create({"name": "FFR Tag One"})
        tag2 = self.env["res.partner.category"].create({"name": "FFR Tag Two"})
        self.partner_a.category_id = [(6, 0, [tag1.id, tag2.id])]
        wizard = self._generate(
            date_from="2024-01-01", date_to="2024-12-31", partner_type="customer",
            partner_category_ids=[(6, 0, [tag1.id, tag2.id])],
        )
        lines = wizard.line_ids.filtered(lambda l: l.partner_id == self.partner_a)
        self.assertEqual(len(lines), 1, "partner with 2 matching tags must appear exactly once")
        # 200 - 80 = 120, net debit, not doubled.
        self.assertAlmostEqual(lines.closing_debit, 120.0, places=2)
        self.assertAlmostEqual(lines.closing_credit, 0.0, places=2)

    def test_partner_tag_filter_applies_to_drill_down_detail(self):
        vip = self.env["res.partner.category"].create({"name": "FFR VIP 4"})
        self.partner_a.category_id = [(4, vip.id)]
        wizard = self._generate(
            date_from="2024-01-01", date_to="2024-12-31", partner_type="all",
            partner_category_ids=[(6, 0, [vip.id])],
        )
        line_a = wizard.line_ids.filtered(lambda l: l.partner_id == self.partner_a)
        action = line_a.action_view_transactions()
        detail = self.env["fast.partner.ledger.detail.wizard"].browse(action["res_id"])
        self.assertEqual(len(detail.detail_line_ids), 2)

    def test_partner_tag_filter_xlsx_export_sql_respects_tag(self):
        vip = self.env["res.partner.category"].create({"name": "FFR VIP 5"})
        self.partner_a.category_id = [(4, vip.id)]
        wizard = self._generate(
            date_from="2024-01-01", date_to="2024-12-31", partner_type="all",
            partner_category_ids=[(6, 0, [vip.id])],
        )
        sql, _company_ids = wizard._ffr_export_sql()
        rows, _sql_time_ms = wizard._ffr_execute(sql)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["partner_name"], self.partner_a.name)

    def test_xlsx_export_sql_has_no_entry_count_column(self):
        """The XLSX export must never expose an Entry Count / Number of
        Entries column - the net-split Debit/Credit columns are the only
        thing this report shows for Opening/Period/Closing."""
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31", partner_type="all")
        sql, _company_ids = wizard._ffr_export_sql()
        rows, _sql_time_ms = wizard._ffr_execute(sql)
        self.assertTrue(rows)
        self.assertNotIn("entry_count", rows[0].keys())
        expected_keys = {
            "partner_name", "opening_debit", "opening_credit",
            "period_debit", "period_credit", "closing_debit", "closing_credit",
        }
        self.assertEqual(set(rows[0].keys()), expected_keys)
