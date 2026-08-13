from odoo import _, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    visit_id = fields.Many2one(
        "fleet.sales.visit",
        string="Fleet Sales Visit",
        readonly=True,
        copy=False,
        help="The field visit this order was created from, if any.",
    )

    def _fleet_sales_check_warehouse_stock(self):
        """Hard-block confirmation if the order's warehouse can't cover
        every line. Only applies to orders created from a Fleet Sales
        visit -- a salesman's field warehouse is a hard constraint of the
        field-sales process, not a change to how Odoo sales work in
        general, so orders with no visit_id are left untouched.
        """
        for order in self:
            if not order.visit_id:
                continue
            warehouse = order.warehouse_id
            if not warehouse:
                raise UserError(
                    _("This order has no warehouse set; it can't be "
                      "confirmed from a field visit.")
                )
            shortages = []
            for line in order.order_line.filtered(
                lambda l: l.product_id.type == "product" and not l.display_type
            ):
                available = line.product_id.with_context(
                    warehouse=warehouse.id
                ).qty_available
                if available < line.product_uom_qty:
                    shortages.append(
                        _(
                            "%(product)s: needs %(needed)s, only "
                            "%(available)s available in %(warehouse)s",
                            product=line.product_id.display_name,
                            needed=line.product_uom_qty,
                            available=available,
                            warehouse=warehouse.name,
                        )
                    )
            if shortages:
                raise UserError(
                    _(
                        "Not enough stock in %(warehouse)s to confirm this "
                        "order:\n%(lines)s",
                        warehouse=warehouse.name,
                        lines="\n".join(shortages),
                    )
                )
