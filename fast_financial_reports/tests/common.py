from odoo.tests.common import TransactionCase


class FastFinancialReportsCommon(TransactionCase):
    """Shared fixtures: a self-contained mini chart of accounts, journal,
    partners and a helper to post journal entries on arbitrary dates, so
    tests do not depend on demo data being installed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        cls.account_income = cls._create_account(cls, "TST4000", "Test Income", "income")
        cls.account_expense = cls._create_account(cls, "TST5000", "Test Expense", "expense")
        cls.account_receivable = cls._create_account(cls, "TST1100", "Test Receivable", "asset_receivable", reconcile=True)
        cls.account_payable = cls._create_account(cls, "TST2100", "Test Payable", "liability_payable", reconcile=True)
        cls.account_bank = cls._create_account(cls, "TST1000", "Test Bank", "asset_cash")

        cls.journal_misc = cls.env["account.journal"].create({
            "name": "Test Miscellaneous Journal",
            "code": "TSTM",
            "type": "general",
            "company_id": cls.company.id,
        })
        cls.journal_sales = cls.env["account.journal"].create({
            "name": "Test Sales Journal",
            "code": "TSTS",
            "type": "sale",
            "company_id": cls.company.id,
        })

        cls.partner_a = cls.env["res.partner"].create({"name": "FFR Test Partner A"})
        cls.partner_b = cls.env["res.partner"].create({"name": "FFR Test Partner B"})

    @staticmethod
    def _create_account(cls, code, name, account_type, reconcile=False):
        return cls.env["account.account"].create({
            "code": code,
            "name": name,
            "account_type": account_type,
            "reconcile": reconcile,
        })

    def _post_entry(self, date, lines, journal=None, move_type="entry", partner_id=False):
        """lines: list of (account, debit, credit, partner) tuples."""
        move = self.env["account.move"].create({
            "move_type": move_type,
            "journal_id": (journal or self.journal_misc).id,
            "date": date,
            "partner_id": partner_id or False,
            "line_ids": [
                (0, 0, {
                    "account_id": account.id,
                    "name": "Test line",
                    "debit": debit,
                    "credit": credit,
                    "partner_id": (partner.id if partner else False),
                })
                for account, debit, credit, partner in lines
            ],
        })
        move.action_post()
        return move
