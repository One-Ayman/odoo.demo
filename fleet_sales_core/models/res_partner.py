from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    # Odoo 19's base res.partner only has `phone`, not a separate `mobile`
    # field (removed from core). Fleet Sales needs a distinct mobile number
    # for field contact and for duplicate-customer matching, so it's added
    # here rather than assumed to exist.
    mobile = fields.Char(string="Mobile")
    commercial_registration = fields.Char(string="Commercial Registration")
    sector_id = fields.Many2one("fleet.sales.sector", string="Sector")
    region_id = fields.Many2one("fleet.sales.region", string="Region")
    salesman_id = fields.Many2one(
        "res.users",
        string="Assigned Salesman",
        help="Default Fleet Sales representative for this customer or POS location.",
    )
    is_pos_location = fields.Boolean(
        string="Is a POS Location",
        help="A physical point of sale / kiosk belonging to a customer. "
        "Sales, visits, invoices and collections are tracked against this "
        "contact directly; the receivable itself still rolls up to the "
        "commercial customer through Odoo's standard partner accounting.",
    )
    visit_frequency_days = fields.Integer(
        string="Visit Frequency (days)",
        default=7,
        help="Target number of days between two visits to this POS location.",
    )

    @api.onchange("parent_id", "is_pos_location")
    def _onchange_parent_id_pos_location(self):
        for partner in self:
            if partner.is_pos_location and partner.parent_id:
                parent = partner.parent_id
                if not partner.sector_id:
                    partner.sector_id = parent.sector_id
                if not partner.region_id:
                    partner.region_id = parent.region_id
                if not partner.salesman_id:
                    partner.salesman_id = parent.salesman_id
