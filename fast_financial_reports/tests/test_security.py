from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged

from .common import FastFinancialReportsCommon


@tagged("post_install", "-at_install", "fast_financial_reports")
class TestFastFinancialReportsSecurity(FastFinancialReportsCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_b = cls.env["res.company"].create({"name": "FFR Security Co B"})
        cls.account_bank_b = cls.env["account.account"].create({
            "code": "SEC1000", "name": "Company B Bank", "account_type": "asset_cash",
            "company_id": cls.company_b.id,
        })
        cls.account_income_b = cls.env["account.account"].create({
            "code": "SEC4000", "name": "Company B Income", "account_type": "income",
            "company_id": cls.company_b.id,
        })
        cls.journal_b = cls.env["account.journal"].create({
            "name": "Company B Journal", "code": "SECJ", "type": "general",
            "company_id": cls.company_b.id,
        })
        move_b = cls.env["account.move"].create({
            "move_type": "entry", "journal_id": cls.journal_b.id, "date": "2024-01-15",
            "line_ids": [
                (0, 0, {"account_id": cls.account_bank_b.id, "name": "B", "debit": 500, "credit": 0}),
                (0, 0, {"account_id": cls.account_income_b.id, "name": "B", "debit": 0, "credit": 500}),
            ],
        })
        move_b.action_post()

        cls._post_entry(cls, "2024-01-05", [
            (cls.account_bank, 100, 0, None), (cls.account_income, 0, 100, None),
        ])

        cls.accountant_group = cls.env.ref("account.group_account_invoice")
        cls.user_company_a_only = cls.env["res.users"].create({
            "name": "FFR Company A User", "login": "ffr_company_a_user",
            "email": "ffr_company_a_user@example.com",
            "groups_id": [(6, 0, [cls.env.ref("base.group_user").id, cls.accountant_group.id])],
            "company_id": cls.company.id,
            "company_ids": [(6, 0, [cls.company.id])],
        })
        cls.user_no_accounting = cls.env["res.users"].create({
            "name": "FFR No Accounting User", "login": "ffr_no_accounting_user",
            "email": "ffr_no_accounting_user@example.com",
            "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
        })

    def test_single_company_user_cannot_request_other_company(self):
        # Requesting a company outside of what the user is allowed to see is
        # denied in depth: Odoo's own multi-company rule on res.company
        # already blocks *reading back* such an id from the wizard, and our
        # own _ffr_allowed_company_ids() check blocks it a second time even
        # if that first layer were ever bypassed (e.g. via sudo()).
        with self.assertRaises(AccessError):
            wizard = self.env["fast.trial.balance.wizard"].with_user(self.user_company_a_only).create({
                "date_from": "2024-01-01", "date_to": "2024-12-31",
                "company_ids": [(6, 0, [self.company_b.id])],
            })
            wizard.action_generate()

    def test_single_company_user_sees_only_own_company_by_default(self):
        wizard = self.env["fast.trial.balance.wizard"].with_user(self.user_company_a_only).create({
            "date_from": "2024-01-01", "date_to": "2024-12-31",
        })
        wizard.action_generate()
        self.assertNotIn(self.account_bank_b, wizard.line_ids.account_id)
        self.assertIn(self.account_bank, wizard.line_ids.account_id)

    def test_multi_company_user_can_see_both_when_both_selected(self):
        multi_user = self.user_company_a_only
        multi_user.write({"company_ids": [(6, 0, [self.company.id, self.company_b.id])]})
        wizard = self.env["fast.trial.balance.wizard"].with_user(multi_user).create({
            "date_from": "2024-01-01", "date_to": "2024-12-31",
            "company_ids": [(6, 0, [self.company.id, self.company_b.id])],
        })
        wizard.action_generate()
        self.assertIn(self.account_bank_b, wizard.line_ids.account_id)
        self.assertIn(self.account_bank, wizard.line_ids.account_id)

    def test_user_without_accounting_group_denied(self):
        with self.assertRaises(AccessError):
            self.env["fast.trial.balance.wizard"].with_user(self.user_no_accounting).create({
                "date_from": "2024-01-01", "date_to": "2024-12-31",
            })

    def test_user_cannot_be_left_with_zero_companies(self):
        """Error-handling edge case, investigated: _ffr_allowed_company_ids()
        has a defensive branch for env.companies being completely empty
        ("You do not have access to any company"). Attempting to actually
        construct that state - clearing a user's company_ids entirely -
        was tried here and confirmed to be blocked by Odoo's own
        res.users._check_company() constraint (a user's current
        company_id must always be a member of their company_ids, so
        company_ids can never be emptied for a persisted user). This is
        itself a real guarantee worth asserting: the "zero company" state
        this module defends against is not reachable through any normal
        write, which is exactly what makes the module's own guard clause
        pure defense-in-depth rather than something reachable in practice.
        """
        with self.assertRaises(ValidationError):
            self.user_company_a_only.write({"company_ids": [(5, 0, 0)]})

    def test_debug_log_hidden_from_ordinary_accountant(self):
        self.env["ir.config_parameter"].sudo().set_param("fast_financial_reports.debug_mode", "True")
        wizard = self.env["fast.trial.balance.wizard"].with_user(self.user_company_a_only).create({
            "date_from": "2024-01-01", "date_to": "2024-12-31",
        })
        wizard.action_generate()
        self.assertTrue(self.env["fast.report.debug.log"].sudo().search([]))
        with self.assertRaises(AccessError):
            self.env["fast.report.debug.log"].with_user(self.user_company_a_only).search([])
