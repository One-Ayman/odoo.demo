from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Field Warehouse",
        help="The warehouse this salesman physically carries stock in. "
        "Every order created from one of their Fleet Sales visits is "
        "forced onto this warehouse and is blocked outright if it can't "
        "cover the order.",
    )
    cash_journal_id = fields.Many2one(
        "account.journal",
        string="Field Cash Journal",
        domain=[("type", "=", "cash")],
        help="Cash journal this salesman's field collections are booked "
        "against. Set up in Accounting by Finance in advance, then "
        "assigned to the salesman here -- the system never creates a "
        "journal on its own.",
    )
