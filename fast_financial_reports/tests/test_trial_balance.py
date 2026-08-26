from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import FastFinancialReportsCommon


@tagged("post_install", "-at_install", "fast_financial_reports")
class TestFastTrialBalance(FastFinancialReportsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Prior year: opening balance contributor.
        cls._post_entry(cls, "2023-12-20", [
            (cls.account_bank, 300, 0, None), (cls.account_income, 0, 300, None),
        ])
        # Current year, several dates spanning day/week/month. Bank has
        # BOTH a debit (100) and a credit (50) movement within the same
        # January period, deliberately, to exercise net-only display.
        cls._post_entry(cls, "2024-01-05", [
            (cls.account_bank, 100, 0, None), (cls.account_income, 0, 100, None),
        ])
        cls._post_entry(cls, "2024-01-10", [
            (cls.account_expense, 50, 0, None), (cls.account_bank, 0, 50, None),
        ])
        cls._post_entry(cls, "2024-06-15", [
            (cls.account_receivable, 200, 0, cls.partner_a), (cls.account_income, 0, 200, None),
        ], journal=cls.journal_sales, partner_id=cls.partner_a.id)
        # Next year.
        cls._post_entry(cls, "2025-02-01", [
            (cls.account_bank, 20, 0, None), (cls.account_expense, 0, 20, None),
        ])
        # A DRAFT entry that must be excluded when posted_only=True.
        cls.draft_move = cls.env["account.move"].create({
            "move_type": "entry",
            "journal_id": cls.journal_misc.id,
            "date": "2024-01-06",
            "line_ids": [
                (0, 0, {"account_id": cls.account_bank.id, "name": "Draft", "debit": 9999, "credit": 0}),
                (0, 0, {"account_id": cls.account_income.id, "name": "Draft", "debit": 0, "credit": 9999}),
            ],
        })

    def _generate(self, **vals):
        vals.setdefault("company_ids", [(6, 0, [self.company.id])])
        wizard = self.env["fast.trial.balance.wizard"].create(vals)
        wizard.action_generate()
        return wizard

    def _line_for(self, wizard, account):
        return wizard.line_ids.filtered(lambda l: l.account_id == account)

    # -- accounting correctness -----------------------------------------
    def test_total_debit_equals_total_credit(self):
        """Whole-ledger reconciliation: every posted journal entry is
        balanced (debit == credit) by construction, so summed across ALL
        accounts (no account/journal/partner filter narrowing the set to a
        partial view of any move), total opening debit must equal total
        opening credit, and total period debit must equal total period
        credit. This still holds even though each line's own debit/credit
        is now net-split (never both sides at once): summing net_i =
        debit_i - credit_i over every account telescopes back to
        (total gross debit) - (total gross credit), which is 0 for a
        balanced ledger, so the positive and negative parts summed
        separately are still equal."""
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31", show_zero=True)
        total_opening_debit = sum(wizard.line_ids.mapped("opening_debit"))
        total_opening_credit = sum(wizard.line_ids.mapped("opening_credit"))
        total_period_debit = sum(wizard.line_ids.mapped("period_debit"))
        total_period_credit = sum(wizard.line_ids.mapped("period_credit"))
        self.assertAlmostEqual(total_opening_debit, total_opening_credit, places=2)
        self.assertAlmostEqual(total_period_debit, total_period_credit, places=2)

    def test_opening_period_ending_reconcile(self):
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31")
        for line in wizard.line_ids:
            opening_net = line.opening_debit - line.opening_credit
            period_net = line.period_debit - line.period_credit
            ending_net = line.ending_debit - line.ending_credit
            self.assertAlmostEqual(opening_net + period_net, ending_net, places=2)

    def test_opening_balance_carried_from_prior_year(self):
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31")
        bank_line = self._line_for(wizard, self.account_bank)
        # 300 (2023) + 100 (2024-01-05) - 50 (2024-01-10): opening excludes
        # 2024 moves, so opening is 300 debit only.
        self.assertAlmostEqual(bank_line.opening_debit, 300.0, places=2)
        self.assertAlmostEqual(bank_line.opening_credit, 0.0, places=2)
        # Period: gross 100 debit / 50 credit -> NET 50 debit, 0 credit.
        self.assertAlmostEqual(bank_line.period_debit, 50.0, places=2)
        self.assertAlmostEqual(bank_line.period_credit, 0.0, places=2)

    # -- net-balance display rule (Opening/Period/Ending never both sides) --
    def test_net_balance_never_shows_both_debit_and_credit_together(self):
        """User-mandated rule: every Opening/Period/Ending balance must
        show the NET balance only. The bank account has both a debit
        (100) and a credit (50) movement within the same period; the
        report must show Debit=50 / Credit=0, never Debit=100 AND
        Credit=50 together."""
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31", show_zero=True)
        bank_line = self._line_for(wizard, self.account_bank)
        self.assertAlmostEqual(bank_line.period_debit, 50.0, places=2)
        self.assertAlmostEqual(bank_line.period_credit, 0.0, places=2)
        for line in wizard.line_ids:
            self.assertTrue(
                line.opening_debit == 0.0 or line.opening_credit == 0.0,
                "opening_debit and opening_credit must never both be non-zero (account %s)" % line.account_code,
            )
            self.assertTrue(
                line.period_debit == 0.0 or line.period_credit == 0.0,
                "period_debit and period_credit must never both be non-zero (account %s)" % line.account_code,
            )
            self.assertTrue(
                line.ending_debit == 0.0 or line.ending_credit == 0.0,
                "ending_debit and ending_credit must never both be non-zero (account %s)" % line.account_code,
            )

    def test_net_balance_debit_heavy_bucket_shows_debit_only(self):
        """Explicit worked example matching the requirement: gross debit
        10,000 / credit 7,000 in the same period must display as
        Debit=3,000 / Credit=0, never both gross amounts."""
        net_account = self.env["account.account"].create({
            "code": "TSTNET1", "name": "FFR Net Split Debit Heavy", "account_type": "asset_cash",
        })
        self._post_entry("2024-05-01", [
            (net_account, 10000, 0, None), (self.account_income, 0, 10000, None),
        ])
        self._post_entry("2024-05-02", [
            (net_account, 0, 7000, None), (self.account_expense, 7000, 0, None),
        ])
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31")
        line = self._line_for(wizard, net_account)
        self.assertAlmostEqual(line.period_debit, 3000.0, places=2)
        self.assertAlmostEqual(line.period_credit, 0.0, places=2)

    def test_net_balance_credit_heavy_bucket_shows_credit_only(self):
        """Same rule, opposite sign: gross debit 7,000 / credit 10,000
        must display as Debit=0 / Credit=3,000."""
        net_account = self.env["account.account"].create({
            "code": "TSTNET2", "name": "FFR Net Split Credit Heavy", "account_type": "asset_cash",
        })
        self._post_entry("2024-07-01", [
            (net_account, 7000, 0, None), (self.account_income, 0, 7000, None),
        ])
        self._post_entry("2024-07-02", [
            (net_account, 0, 10000, None), (self.account_expense, 10000, 0, None),
        ])
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31")
        line = self._line_for(wizard, net_account)
        self.assertAlmostEqual(line.period_debit, 0.0, places=2)
        self.assertAlmostEqual(line.period_credit, 3000.0, places=2)

    def test_net_balance_opening_credit_heavy_shows_credit_only(self):
        """The same net-only rule applies to the Opening bucket, not just
        Period: an account whose activity BEFORE date_from nets to a
        credit balance must show Opening Credit only."""
        net_account = self.env["account.account"].create({
            "code": "TSTNET3", "name": "FFR Net Split Opening Credit Heavy", "account_type": "asset_cash",
        })
        self._post_entry("2023-01-01", [
            (net_account, 4000, 0, None), (self.account_income, 0, 4000, None),
        ])
        self._post_entry("2023-02-01", [
            (net_account, 0, 9000, None), (self.account_expense, 9000, 0, None),
        ])
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31")
        line = self._line_for(wizard, net_account)
        self.assertAlmostEqual(line.opening_debit, 0.0, places=2)
        self.assertAlmostEqual(line.opening_credit, 5000.0, places=2)

    # -- date range coverage ---------------------------------------------
    def test_one_day_range(self):
        wizard = self._generate(date_from="2024-01-05", date_to="2024-01-05")
        bank_line = self._line_for(wizard, self.account_bank)
        self.assertAlmostEqual(bank_line.period_debit, 100.0, places=2)
        self.assertAlmostEqual(bank_line.period_credit, 0.0, places=2)

    def test_one_week_range(self):
        wizard = self._generate(date_from="2024-01-01", date_to="2024-01-07")
        bank_line = self._line_for(wizard, self.account_bank)
        self.assertAlmostEqual(bank_line.period_debit, 100.0, places=2)

    def test_one_month_range(self):
        wizard = self._generate(date_from="2024-01-01", date_to="2024-01-31")
        bank_line = self._line_for(wizard, self.account_bank)
        # Gross 100 debit / 50 credit within January -> NET 50 debit.
        self.assertAlmostEqual(bank_line.period_debit, 50.0, places=2)
        self.assertAlmostEqual(bank_line.period_credit, 0.0, places=2)

    def test_one_year_range(self):
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31")
        income_line = self._line_for(wizard, self.account_income)
        self.assertAlmostEqual(income_line.period_credit, 300.0, places=2)  # 100 + 200

    def test_multi_year_range(self):
        wizard = self._generate(date_from="2023-01-01", date_to="2025-12-31")
        bank_line = self._line_for(wizard, self.account_bank)
        self.assertAlmostEqual(bank_line.opening_debit, 0.0, places=2)
        self.assertAlmostEqual(bank_line.opening_credit, 0.0, places=2)
        # Gross 420 debit / 50 credit across 2023-2025 -> NET 370 debit.
        self.assertAlmostEqual(bank_line.period_debit, 370.0, places=2)
        self.assertAlmostEqual(bank_line.period_credit, 0.0, places=2)

    def test_future_period_has_no_period_movement(self):
        # Opening balances still carry forward (correct trial-balance
        # semantics) but no line may show any *period* debit/credit, since
        # nothing was posted in 2030.
        wizard = self._generate(date_from="2030-01-01", date_to="2030-12-31")
        for line in wizard.line_ids:
            self.assertAlmostEqual(line.period_debit, 0.0, places=2)
            self.assertAlmostEqual(line.period_credit, 0.0, places=2)

    def test_no_results_for_account_with_no_history(self):
        empty_account = self.env["account.account"].create({
            "code": "TST8888", "name": "Never Used Account", "account_type": "expense",
        })
        wizard = self._generate(
            date_from="2024-01-01", date_to="2024-12-31",
            account_ids=[(6, 0, [empty_account.id])], show_zero=False,
        )
        self.assertEqual(wizard.total_account_count, 0)
        self.assertFalse(wizard.line_ids)

    def test_invalid_date_range_raises(self):
        with self.assertRaises(UserError):
            self._generate(date_from="2024-12-31", date_to="2024-01-01")

    # -- filters -----------------------------------------------------------
    def test_account_filter(self):
        wizard = self._generate(
            date_from="2024-01-01", date_to="2024-12-31",
            account_ids=[(6, 0, [self.account_bank.id])],
        )
        self.assertEqual(wizard.total_account_count, 1)
        self.assertEqual(wizard.line_ids.account_id, self.account_bank)

    def test_analytic_account_filter(self):
        plan = self.env["account.analytic.plan"].create({"name": "FFR Test Plan"})
        analytic_account = self.env["account.analytic.account"].create({
            "name": "FFR Test Analytic", "plan_id": plan.id,
        })
        move = self.env["account.move"].create({
            "move_type": "entry", "journal_id": self.journal_misc.id, "date": "2024-04-01",
            "line_ids": [
                (0, 0, {
                    "account_id": self.account_expense.id, "name": "Analytic line",
                    "debit": 42.0, "credit": 0.0,
                    "analytic_distribution": {str(analytic_account.id): 100.0},
                }),
                (0, 0, {"account_id": self.account_bank.id, "name": "Analytic line", "debit": 0.0, "credit": 42.0}),
            ],
        })
        move.action_post()

        wizard = self._generate(
            date_from="2024-01-01", date_to="2024-12-31",
            analytic_account_id=analytic_account.id,
        )
        self.assertEqual(wizard.line_ids.account_id, self.account_expense)
        self.assertAlmostEqual(wizard.line_ids.period_debit, 42.0, places=2)

    def test_journal_filter(self):
        wizard = self._generate(
            date_from="2024-01-01", date_to="2024-12-31",
            journal_ids=[(6, 0, [self.journal_sales.id])],
        )
        # Only the receivable/income lines from the sales-journal entry.
        accounts = wizard.line_ids.account_id
        self.assertIn(self.account_receivable, accounts)
        self.assertNotIn(self.account_bank, accounts)

    def test_partner_filter(self):
        wizard = self._generate(
            date_from="2024-01-01", date_to="2024-12-31",
            partner_ids=[(6, 0, [self.partner_a.id])],
        )
        self.assertEqual(wizard.line_ids.account_id, self.account_receivable)

    def test_posted_only_excludes_draft(self):
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31", posted_only=True)
        bank_line = self._line_for(wizard, self.account_bank)
        self.assertNotAlmostEqual(bank_line.period_debit, 10099.0, places=2)

    def test_posted_only_false_includes_draft(self):
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31", posted_only=False)
        bank_line = self._line_for(wizard, self.account_bank)
        # Gross debit 100+9999=10099, credit 50 -> NET 10049 debit.
        self.assertAlmostEqual(bank_line.period_debit, 10049.0, places=2)
        self.assertAlmostEqual(bank_line.period_credit, 0.0, places=2)

    def test_show_zero_accounts(self):
        # A dedicated account with zero everywhere in-range.
        zero_account = self.env["account.account"].create({
            "code": "TST9999", "name": "Zero Account", "account_type": "expense",
        })
        wizard_hidden = self._generate(date_from="2024-01-01", date_to="2024-12-31", show_zero=False)
        self.assertNotIn(zero_account, wizard_hidden.line_ids.account_id)

    def test_company_filter_restricted_to_allowed_companies(self):
        other_company = self.env["res.company"].create({"name": "FFR Other Co"})
        # res.company.create() auto-grants the *creating* user access to the
        # new company (see odoo/addons/base/models/res_company.py) - revoke
        # it again so this test genuinely exercises "a company outside of
        # env.companies", matching the deeper multi-user checks in
        # test_security.py.
        self.env.user.write({"company_ids": [(3, other_company.id)]})
        wizard = self.env["fast.trial.balance.wizard"].create({
            "date_from": "2024-01-01", "date_to": "2024-12-31",
        })
        with self.assertRaises(AccessError):
            wizard.company_ids = [(6, 0, [other_company.id])]
            wizard.action_generate()

    # -- pagination ----------------------------------------------------
    def test_pagination_page_size(self):
        wizard = self._generate(date_from="2024-01-01", date_to="2024-12-31", page_size="100")
        self.assertGreaterEqual(wizard.total_account_count, 1)
        self.assertEqual(wizard.page, 1)
