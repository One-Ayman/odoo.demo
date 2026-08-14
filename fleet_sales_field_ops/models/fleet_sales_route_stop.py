from odoo import api, fields, models


class FleetSalesRouteStop(models.Model):
    _name = "fleet.sales.route.stop"
    _description = "Fleet Sales Route Stop"
    _order = "route_id, sequence, id"

    route_id = fields.Many2one(
        "fleet.sales.route", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=10)
    partner_id = fields.Many2one("res.partner", string="Customer", required=True)
    planned_time = fields.Char(
        string="Planned Time",
        help="Free-text planned time slot, e.g. '9:00 AM'. Informational only.",
    )
    visit_id = fields.Many2one(
        "fleet.sales.visit",
        string="Visit",
        readonly=True,
        copy=False,
        help="Filled in automatically once this stop's visit is started.",
    )
    status = fields.Selection(
        [("scheduled", "Scheduled"), ("done", "Done")],
        compute="_compute_status",
        store=True,
    )
    salesman_id = fields.Many2one(related="route_id.salesman_id", store=True)
    date = fields.Date(related="route_id.date", store=True)

    @api.depends("visit_id")
    def _compute_status(self):
        for stop in self:
            stop.status = "done" if stop.visit_id else "scheduled"

    def action_start_visit(self):
        self.ensure_one()
        if self.visit_id:
            return {
                "type": "ir.actions.act_window",
                "res_model": "fleet.sales.visit",
                "view_mode": "form",
                "res_id": self.visit_id.id,
            }
        visit = self.env["fleet.sales.visit"].create(
            {
                "partner_id": self.partner_id.id,
                "salesman_id": self.route_id.salesman_id.id,
            }
        )
        self.visit_id = visit.id
        return {
            "type": "ir.actions.act_window",
            "res_model": "fleet.sales.visit",
            "view_mode": "form",
            "res_id": visit.id,
        }
