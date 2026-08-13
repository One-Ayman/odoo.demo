from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResUsers(models.Model):
    _inherit = "res.users"

    supervisor_id = fields.Many2one(
        "res.users",
        string="Supervisor",
        help="Direct manager in the Fleet Sales reporting line "
        "(Salesman -> Supervisor -> Regional Manager).",
    )
    region_id = fields.Many2one(
        "fleet.sales.region",
        string="Fleet Sales Region",
        help="Territory this user is scoped to as Supervisor or Regional Manager.",
    )

    @api.constrains("supervisor_id")
    def _check_supervisor_not_self(self):
        for user in self:
            if user.supervisor_id and user.supervisor_id.id == user.id:
                raise ValidationError(_("A user cannot be their own supervisor."))

    @api.constrains("supervisor_id")
    def _check_supervisor_group(self):
        supervisor_group = self.env.ref(
            "fleet_sales_core.group_fleet_sales_supervisor", raise_if_not_found=False
        )
        if not supervisor_group:
            return
        for user in self:
            if user.supervisor_id and supervisor_group not in user.supervisor_id.all_group_ids:
                raise ValidationError(
                    _(
                        "%(supervisor)s cannot be set as a supervisor: they are not in the "
                        "Fleet Sales Supervisor group (or higher).",
                        supervisor=user.supervisor_id.name,
                    )
                )
