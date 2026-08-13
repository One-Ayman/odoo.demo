from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    visit_id = fields.Many2one(
        "fleet.sales.visit",
        string="Fleet Sales Visit",
        readonly=True,
        copy=False,
        help="The field visit this collection was registered from, if any.",
    )
