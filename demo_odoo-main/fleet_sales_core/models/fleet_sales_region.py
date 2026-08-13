from odoo import fields, models


class FleetSalesRegion(models.Model):
    _name = "fleet.sales.region"
    _description = "Fleet Sales Region"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    manager_id = fields.Many2one(
        "res.users",
        string="Regional Manager",
        help="User in the Regional Manager (or higher) group responsible for this region",
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )

    _code_company_uniq = models.Constraint(
        "unique(code, company_id)",
        "The region code must be unique per company.",
    )
