from datetime import datetime, time

from odoo import _, api, fields, models


class FleetSalesVisitReportWizard(models.TransientModel):
    _name = "fleet.sales.visit.report.wizard"
    _description = "Visit Report Filters"

    salesman_id = fields.Many2one(
        "res.users",
        string="Salesman",
        help="Leave empty to include every salesman.",
        domain=lambda self: [
            (
                "group_ids",
                "in",
                self.env.ref("fleet_sales_core.group_fleet_sales_salesman").id,
            )
        ],
    )
    date_from = fields.Date(
        string="From",
        default=lambda self: fields.Date.context_today(self).replace(day=1),
        required=True,
    )
    date_to = fields.Date(
        string="To", default=fields.Date.context_today, required=True
    )

    def action_view_report(self):
        self.ensure_one()
        domain = [("state", "=", "closed")]
        if self.salesman_id:
            domain.append(("salesman_id", "=", self.salesman_id.id))
        if self.date_from:
            domain.append(
                ("check_in_datetime", ">=", datetime.combine(self.date_from, time.min))
            )
        if self.date_to:
            domain.append(
                ("check_in_datetime", "<=", datetime.combine(self.date_to, time.max))
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Visit Report"),
            "res_model": "fleet.sales.visit",
            "view_mode": "list",
            "views": [
                (
                    self.env.ref(
                        "fleet_sales_field_ops.view_fleet_sales_visit_report_list"
                    ).id,
                    "list",
                )
            ],
            "domain": domain,
            "context": {"create": False, "edit": False},
        }
