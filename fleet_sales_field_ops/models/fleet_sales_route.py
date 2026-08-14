from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FleetSalesRoute(models.Model):
    _name = "fleet.sales.route"
    _inherit = ["mail.thread"]
    _description = "Fleet Sales Daily Route"
    _order = "date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    salesman_id = fields.Many2one(
        "res.users",
        string="Salesman",
        required=True,
        tracking=True,
        default=lambda self: self.env.user,
        domain=lambda self: [
            (
                "group_ids",
                "in",
                self.env.ref("fleet_sales_core.group_fleet_sales_salesman").id,
            )
        ],
    )
    date = fields.Date(
        required=True, tracking=True, default=fields.Date.context_today
    )
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed")],
        default="draft",
        tracking=True,
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    stop_ids = fields.One2many("fleet.sales.route.stop", "route_id", string="Stops")
    stop_count = fields.Integer(compute="_compute_counts")
    done_count = fields.Integer(compute="_compute_counts")

    is_own_route = fields.Boolean(
        compute="_compute_is_own_route",
        help="True when the current user is this route's own salesman -- "
        "used to keep the location capture / nearest-neighbor ordering "
        "tools on the salesman's own screen only.",
    )
    current_latitude = fields.Float(
        string="My Current Latitude", digits=(10, 7)
    )
    current_longitude = fields.Float(
        string="My Current Longitude", digits=(10, 7)
    )

    @api.depends("salesman_id", "date")
    def _compute_name(self):
        for route in self:
            route.name = "%s - %s" % (
                route.salesman_id.name or _("New"),
                route.date or "",
            )

    @api.depends("stop_ids", "stop_ids.status")
    def _compute_counts(self):
        for route in self:
            route.stop_count = len(route.stop_ids)
            route.done_count = len(
                route.stop_ids.filtered(lambda s: s.status == "done")
            )

    def _compute_is_own_route(self):
        for route in self:
            route.is_own_route = route.salesman_id == self.env.user

    def action_confirm(self):
        for route in self:
            if not route.stop_ids:
                raise UserError(_("Add at least one stop before confirming."))
            route.state = "confirmed"

    def action_reset_draft(self):
        self.state = "draft"

    def action_order_by_nearest(self):
        """Reorder this route's stops with a simple nearest-neighbor walk
        starting from the salesman's captured current location. Not a full
        route-optimization solve -- just a practical, easy-to-explain
        greedy ordering that's good enough for a handful of daily stops.
        """
        self.ensure_one()
        if not self.current_latitude or not self.current_longitude:
            raise UserError(
                _("Capture your current location before ordering by nearest.")
            )
        haversine = self.env["fleet.sales.visit"]._haversine_distance_m

        with_coords = self.stop_ids.filtered(
            lambda s: s.partner_id.partner_latitude and s.partner_id.partner_longitude
        )
        without_coords = self.stop_ids - with_coords

        remaining = list(with_coords)
        ordered = []
        cur_lat, cur_lng = self.current_latitude, self.current_longitude
        while remaining:
            nearest = min(
                remaining,
                key=lambda s: haversine(
                    cur_lat,
                    cur_lng,
                    s.partner_id.partner_latitude,
                    s.partner_id.partner_longitude,
                ),
            )
            ordered.append(nearest)
            remaining.remove(nearest)
            cur_lat = nearest.partner_id.partner_latitude
            cur_lng = nearest.partner_id.partner_longitude

        sequence = 10
        for stop in ordered:
            stop.sequence = sequence
            sequence += 10
        for stop in without_coords:
            stop.sequence = sequence
            sequence += 10

        message = _("Stops reordered by nearest location.")
        if without_coords:
            message = _(
                "%(message)s %(count)s stop(s) with no registered customer "
                "location were left at the end.",
                message=message,
                count=len(without_coords),
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Route reordered"),
                "message": message,
                "type": "success" if not without_coords else "warning",
                "sticky": False,
            },
        }
