from odoo import fields, models


class FleetSalesSector(models.Model):
    _name = "fleet.sales.sector"
    _description = "Fleet Sales Customer Sector"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )

    _name_company_uniq = models.Constraint(
        "unique(name, company_id)",
        "The sector name must be unique per company.",
    )
