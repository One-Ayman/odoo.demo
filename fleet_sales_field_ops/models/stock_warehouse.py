from odoo import fields, models


class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    fleet_sales_allow_negative_stock = fields.Boolean(
        string="Allow Negative Stock (Field Sales)",
        default=False,
        help="If enabled, orders placed from a Fleet Sales visit against "
        "this warehouse are allowed to confirm even if a product doesn't "
        "have enough quantity on hand -- the stock check that normally "
        "blocks confirmation outright is skipped for this warehouse. "
        "Leave off (the default) to keep the hard stock block.",
    )
