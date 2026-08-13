from odoo import fields, models


class FleetSalesVisitCustomerStockLine(models.Model):
    _name = "fleet.sales.visit.customer.stock.line"
    _description = "Customer On-Hand Inventory Line"

    visit_id = fields.Many2one(
        "fleet.sales.visit",
        required=True,
        ondelete="cascade",
        index=True,
    )
    product_id = fields.Many2one("product.product", string="Product", required=True)
    quantity = fields.Float(string="Quantity at Customer", default=1.0)
    uom_id = fields.Many2one(
        "uom.uom",
        string="Unit",
        related="product_id.uom_id",
        readonly=True,
    )
