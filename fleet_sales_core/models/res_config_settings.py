from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    fleet_sales_inactive_warning_days = fields.Integer(
        string="Inactive Customer Warning (days)",
        config_parameter="fleet_sales_core.inactive_warning_days",
        default=30,
        help="Show an inactivity warning on a POS location after this many days without an order.",
    )
    fleet_sales_inactive_days = fields.Integer(
        string="Inactive Customer Threshold (days)",
        config_parameter="fleet_sales_core.inactive_days",
        default=60,
        help="Flag a POS location as inactive after this many days without an order.",
    )
