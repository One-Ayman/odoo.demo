from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FleetSalesPosRequest(models.Model):
    _name = "fleet.sales.pos.request"
    _inherit = ["fleet.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _description = "New POS Location Request"
    _order = "create_date desc"

    customer_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
        domain=[("is_pos_location", "=", False)],
        tracking=True,
    )
    name = fields.Char(string="POS Location Name", required=True, tracking=True)
    street = fields.Char(string="Address")
    city = fields.Char()
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    sector_id = fields.Many2one("fleet.sales.sector", string="Sector")
    region_id = fields.Many2one("fleet.sales.region", string="Region")
    salesman_id = fields.Many2one("res.users", string="Assigned Salesman")
    visit_frequency_days = fields.Integer(default=7)
    created_location_id = fields.Many2one(
        "res.partner", string="Created POS Location", readonly=True, copy=False
    )

    def _required_approval_group_xmlid(self):
        return "fleet_sales_core.group_fleet_sales_supervisor"

    @api.onchange("customer_id")
    def _onchange_customer_id(self):
        for record in self:
            if record.customer_id:
                record.sector_id = record.sector_id or record.customer_id.sector_id
                record.region_id = record.region_id or record.customer_id.region_id
                record.salesman_id = record.salesman_id or record.customer_id.salesman_id

    def action_submit(self):
        for record in self:
            if not record.customer_id:
                raise UserError(_("Select the customer this POS location belongs to."))
        return super().action_submit()

    def _apply_approval(self):
        for record in self:
            # sudo: see the matching comment in fleet_sales_customer_request
            # -- creating a Contact needs a group the approver doesn't
            # otherwise hold; _check_can_decide() already authorized this.
            location = self.env["res.partner"].sudo().create(
                {
                    "name": record.name,
                    "parent_id": record.customer_id.id,
                    "type": "other",
                    "is_pos_location": True,
                    "street": record.street,
                    "city": record.city,
                    "partner_latitude": record.latitude,
                    "partner_longitude": record.longitude,
                    "sector_id": (record.sector_id or record.customer_id.sector_id).id,
                    "region_id": (record.region_id or record.customer_id.region_id).id,
                    "salesman_id": (record.salesman_id or record.customer_id.salesman_id).id,
                    "visit_frequency_days": record.visit_frequency_days,
                    "company_id": record.customer_id.company_id.id,
                }
            )
            record.created_location_id = location.id

    def action_view_created_location(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "view_mode": "form",
            "res_id": self.created_location_id.id,
        }
