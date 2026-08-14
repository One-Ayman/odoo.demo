from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FleetSalesRouteCopyWizard(models.TransientModel):
    _name = "fleet.sales.route.copy.wizard"
    _description = "Copy Route to Other Days"

    route_id = fields.Many2one(
        "fleet.sales.route", required=True, default=lambda self: self._default_route()
    )
    line_ids = fields.One2many(
        "fleet.sales.route.copy.wizard.line", "wizard_id", string="Dates"
    )

    def _default_route(self):
        return self.env.context.get("active_id")

    def action_copy(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Add at least one date to copy this route to."))
        new_routes = self.env["fleet.sales.route"]
        for line in self.line_ids:
            new_routes |= self.route_id.copy(
                {
                    "date": line.date,
                    "state": "draft",
                    "current_latitude": 0.0,
                    "current_longitude": 0.0,
                }
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Copied Routes"),
            "res_model": "fleet.sales.route",
            "view_mode": "list,form",
            "domain": [("id", "in", new_routes.ids)],
        }


class FleetSalesRouteCopyWizardLine(models.TransientModel):
    _name = "fleet.sales.route.copy.wizard.line"
    _description = "Copy Route to Other Days - Date Line"

    wizard_id = fields.Many2one(
        "fleet.sales.route.copy.wizard", required=True, ondelete="cascade"
    )
    date = fields.Date(required=True)
