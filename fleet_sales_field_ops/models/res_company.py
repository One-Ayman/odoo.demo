from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    fleet_sales_mada_journal_id = fields.Many2one(
        "account.journal",
        string="Mada / Card Collections Journal",
        domain=[("type", "=", "bank")],
        help="Bank journal used for Mada (card) collections registered "
        "from Fleet Sales visits. Payments booked to this journal from a "
        "visit are always created as draft receipt vouchers -- Finance "
        "must review and post them; the salesman's action never posts a "
        "bank payment directly.",
    )
