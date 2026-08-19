"""Cross-check Fast Financial Reports totals against an INDEPENDENT
computation using Odoo's own standard ORM aggregation (`read_group`),
applying the exact same filters (company, date range, accounts, journals,
partners, posted state).

Why `read_group` and not the standard Trial Balance / General Ledger /
Partner Ledger reports: those reports (`account_reports`) are an Odoo
*Enterprise* module and are not part of the Community `account` module this
project depends on, so they are not installable/comparable in this
environment. `read_group` is itself standard Odoo ORM machinery (not part
of this module, not using any of this module's SQL) - it is the strongest
independent ground truth available in a Community-only environment, and it
exercises a genuinely different code path (ORM query building instead of
this module's hand-written SQL) so any bug in the SQL that produced a wrong
number would very likely disagree with it.
"""
from odoo.tests import tagged

from .common import FastFinancialReportsCommon


@tagged("post_install", "-at_install", "fast_financial_reports")
class TestAccountingCorrectnessVsOrm(FastFinancialReportsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._post_entry(cls, "2022-11-01", [
            (cls.account_bank, 500, 0, None), (cls.account_income, 0, 500, None),
        ])
        cls._post_entry(cls, "2023-03-15", [
            (cls.account_expense, 75, 0, None), (cls.account_bank, 0, 75, None),
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
        cls._post_entry(cls, "2024-07-20", [
            (cls.account_receivable, 0, 60, cls.partner_a), (cls.account_bank, 60, 0, None),
        ], partner_id=cls.partner_a.id)
        cls._post_entry(cls, "2024-08-01", [
            (cls.account_payable, 0, 90, cls.partner_b), (cls.account_expense, 90, 0, None),
        ], partner_id=cls.partner_b.id)
        # A draft entry: must be excluded from the read_group ground truth
        # too when posted_only=True, exactly like the module's own filter.
        cls.env["account.move"].create({
            "move_type": "entry", "journal_id": cls.journal_misc.id, "date": "2024-01-06",
            "line_ids": [
                (0, 0, {"account_id": cls.account_bank.id, "name": "Draft", "debit": 4321, "credit": 0}),
                (0, 0, {"account_id": cls.account_income.id, "name": "Draft", "debit": 0, "credit": 4321}),
            ],
        })

    def _orm_balance(self, account, date_field_domain, posted_only=True):
        """Independent ORM computation of SUM(debit), SUM(credit) for one
        account under a date condition, using account.move.line.read_group
        - standard Odoo aggregation, not this module's SQL."""
        domain = [("account_id", "=", account.id), ("company_id", "=", self.company.id)]
        domain += date_field_domain
        domain += [("parent_state", "=", "posted")] if posted_only else [("parent_state", "!=", "cancel")]
        groups = self.env["account.move.line"].read_group(domain, ["debit:sum", "credit:sum"], [])
        if not groups:
            return 0.0, 0.0
        return groups[0]["debit"] or 0.0, groups[0]["credit"] or 0.0

    def test_trial_balance_matches_orm_read_group(self):
        wizard = self.env["fast.trial.balance.wizard"].create({
            "date_from": "2024-01-01", "date_to": "2024-12-31",
            "company_ids": [(6, 0, [self.company.id])],
        })
        wizard.action_generate()
        self.assertTrue(wizard.line_ids, "expected at least one account line to cross-check")
        for line in wizard.line_ids:
            orm_opening_debit, orm_opening_credit = self._orm_balance(
                line.account_id, [("date", "<", "2024-01-01")],
            )
            orm_period_debit, orm_period_credit = self._orm_balance(
                line.account_id, [("date", ">=", "2024-01-01"), ("date", "<=", "2024-12-31")],
            )
            self.assertAlmostEqual(line.opening_debit, orm_opening_debit, places=2,
                                    msg="opening_debit mismatch for %s" % line.account_code)
            self.assertAlmostEqual(line.opening_credit, orm_opening_credit, places=2,
                                    msg="opening_credit mismatch for %s" % line.account_code)
            self.assertAlmostEqual(line.period_debit, orm_period_debit, places=2,
                                    msg="period_debit mismatch for %s" % line.account_code)
            self.assertAlmostEqual(line.period_credit, orm_period_credit, places=2,
                                    msg="period_credit mismatch for %s" % line.account_code)
            # Opening + Debit - Credit = Closing, the spec's own formula.
            self.assertAlmostEqual(
                line.opening_balance + line.period_debit - line.period_credit,
                line.ending_balance, places=2,
            )

    def test_general_ledger_matches_orm_read_group(self):
        wizard = self.env["fast.general.ledger.wizard"].create({
            "date_from": "2024-01-01", "date_to": "2024-12-31",
            "company_ids": [(6, 0, [self.company.id])],
        })
        wizard.action_generate()
        self.assertTrue(wizard.line_ids)
        for line in wizard.line_ids:
            orm_opening_debit, orm_opening_credit = self._orm_balance(
                line.account_id, [("date", "<", "2024-01-01")],
            )
            orm_opening = orm_opening_debit - orm_opening_credit
            orm_period_debit, orm_period_credit = self._orm_balance(
                line.account_id, [("date", ">=", "2024-01-01"), ("date", "<=", "2024-12-31")],
            )
            self.assertAlmostEqual(line.opening_balance, orm_opening, places=2,
                                    msg="opening_balance mismatch for %s" % line.account_code)
            self.assertAlmostEqual(line.period_debit, orm_period_debit, places=2)
            self.assertAlmostEqual(line.period_credit, orm_period_credit, places=2)
            self.assertAlmostEqual(
                line.opening_balance + line.period_debit - line.period_credit,
                line.closing_balance, places=2,
            )

    def test_general_ledger_draft_excluded_matches_orm(self):
        wizard = self.env["fast.general.ledger.wizard"].create({
            "date_from": "2024-01-01", "date_to": "2024-12-31",
            "company_ids": [(6, 0, [self.company.id])], "posted_only": True,
        })
        wizard.action_generate()
        bank_line = wizard.line_ids.filtered(lambda l: l.account_id == self.account_bank)
        orm_debit, orm_credit = self._orm_balance(
            self.account_bank, [("date", ">=", "2024-01-01"), ("date", "<=", "2024-12-31")],
            posted_only=True,
        )
        # The 4321 draft entry must be excluded from both sides alike.
        self.assertNotAlmostEqual(bank_line.period_debit, 100.0 + 4321.0, places=2)
        self.assertAlmostEqual(bank_line.period_debit, orm_debit, places=2)
        self.assertAlmostEqual(bank_line.period_credit, orm_credit, places=2)

    def test_partner_ledger_matches_orm_read_group(self):
        wizard = self.env["fast.partner.ledger.wizard"].create({
            "date_from": "2024-01-01", "date_to": "2024-12-31",
            "company_ids": [(6, 0, [self.company.id])], "partner_type": "all",
        })
        wizard.action_generate()
        self.assertTrue(wizard.line_ids)
        receivable_payable_ids = self.env["account.account"].search([
            ("company_id", "=", self.company.id),
            ("account_type", "in", ("asset_receivable", "liability_payable")),
        ]).ids
        for line in wizard.line_ids:
            base_domain = [
                ("partner_id", "=", line.partner_id.id),
                ("company_id", "=", self.company.id),
                ("account_id", "in", receivable_payable_ids),
                ("parent_state", "=", "posted"),
            ]
            opening = self.env["account.move.line"].read_group(
                base_domain + [("date", "<", "2024-01-01")], ["debit:sum", "credit:sum"], [],
            )
            period = self.env["account.move.line"].read_group(
                base_domain + [("date", ">=", "2024-01-01"), ("date", "<=", "2024-12-31")],
                ["debit:sum", "credit:sum"], [],
            )
            orm_opening_debit = opening[0]["debit"] if opening else 0.0
            orm_opening_credit = opening[0]["credit"] if opening else 0.0
            orm_period_debit = period[0]["debit"] if period else 0.0
            orm_period_credit = period[0]["credit"] if period else 0.0

            self.assertAlmostEqual(line.opening_debit, orm_opening_debit, places=2,
                                    msg="opening_debit mismatch for partner %s" % line.partner_name)
            self.assertAlmostEqual(line.opening_credit, orm_opening_credit, places=2)
            self.assertAlmostEqual(line.period_debit, orm_period_debit, places=2)
            self.assertAlmostEqual(line.period_credit, orm_period_credit, places=2)
            opening_balance = orm_opening_debit - orm_opening_credit
            self.assertAlmostEqual(
                opening_balance + line.period_debit - line.period_credit,
                line.closing_balance, places=2,
            )

    def test_general_ledger_detail_lines_match_orm_total(self):
        """Sum of the (lazily loaded) transaction detail for one account
        must equal the ORM-computed period debit/credit for that account -
        proving the drill-down query and the summary query agree."""
        wizard = self.env["fast.general.ledger.wizard"].create({
            "date_from": "2024-01-01", "date_to": "2024-12-31",
            "company_ids": [(6, 0, [self.company.id])],
        })
        wizard.action_generate()
        bank_line = wizard.line_ids.filtered(lambda l: l.account_id == self.account_bank)
        action = bank_line.action_view_transactions()
        detail = self.env["fast.general.ledger.detail.wizard"].browse(action["res_id"])
        self.assertTrue(detail.detail_line_ids)

        orm_debit, orm_credit = self._orm_balance(
            self.account_bank, [("date", ">=", "2024-01-01"), ("date", "<=", "2024-12-31")],
        )
        detail_debit = sum(detail.detail_line_ids.mapped("debit"))
        detail_credit = sum(detail.detail_line_ids.mapped("credit"))
        self.assertAlmostEqual(detail_debit, orm_debit, places=2)
        self.assertAlmostEqual(detail_credit, orm_credit, places=2)
