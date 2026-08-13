from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FleetSalesCustomerRequest(models.Model):
    _name = "fleet.sales.customer.request"
    _inherit = ["fleet.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _description = "New Customer Request"
    _order = "create_date desc"

    name = fields.Char(string="Customer Name", required=True, tracking=True)
    vat = fields.Char(string="VAT / Tax ID", tracking=True)
    mobile = fields.Char(tracking=True)
    commercial_registration = fields.Char(string="Commercial Registration", tracking=True)
    sector_id = fields.Many2one("fleet.sales.sector", string="Sector")
    region_id = fields.Many2one("fleet.sales.region", string="Region")
    proposed_salesman_id = fields.Many2one(
        "res.users", string="Assigned Salesman", default=lambda self: self.env.user
    )
    created_partner_id = fields.Many2one(
        "res.partner", string="Created Customer", readonly=True, copy=False
    )
    duplicate_warning = fields.Text(readonly=True, copy=False)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )

    def _required_approval_group_xmlid(self):
        return "fleet_sales_core.group_fleet_sales_supervisor"

    def action_submit(self):
        for record in self:
            record._check_hard_duplicate()
            record.duplicate_warning = record._compute_soft_duplicate_warning()
        return super().action_submit()

    def _check_hard_duplicate(self):
        for record in self:
            if not record.vat:
                continue
            existing = self.env["res.partner"].search(
                [("vat", "=", record.vat), ("vat", "!=", False)], limit=1
            )
            if existing:
                raise UserError(
                    _(
                        "A customer with VAT %(vat)s already exists (%(name)s). "
                        "This request cannot be submitted as a new customer.",
                        vat=record.vat,
                        name=existing.name,
                    )
                )

    def _compute_soft_duplicate_warning(self):
        self.ensure_one()
        clauses = []
        if self.mobile:
            clauses.append(("mobile", "=", self.mobile))
        if self.commercial_registration:
            clauses.append(("commercial_registration", "=", self.commercial_registration))
        if self.name:
            clauses.append(("name", "=ilike", self.name))
        if not clauses:
            return False
        domain = (["|"] * (len(clauses) - 1)) + clauses if len(clauses) > 1 else clauses
        matches = self.env["res.partner"].search(domain, limit=5)
        if not matches:
            return False
        return _("Possible duplicates found (not blocking): %s") % ", ".join(matches.mapped("name"))

    def _apply_approval(self):
        for record in self:
            record._check_hard_duplicate()
            # sudo: creating a Contact requires the Contact/Creation group,
            # which a Supervisor does not otherwise need. _check_can_decide()
            # already verified the caller is allowed to approve this specific
            # request before we ever reach this point, so this is the
            # narrow, already-authorized side effect of that decision, not a
            # bypass of it.
            partner = self.env["res.partner"].sudo().create(
                {
                    "name": record.name,
                    "vat": record.vat,
                    "mobile": record.mobile,
                    "commercial_registration": record.commercial_registration,
                    "is_company": True,
                    "sector_id": record.sector_id.id,
                    "region_id": record.region_id.id,
                    "salesman_id": record.proposed_salesman_id.id,
                    "company_id": record.company_id.id,
                }
            )
            record.created_partner_id = partner.id

    def action_view_created_partner(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "view_mode": "form",
            "res_id": self.created_partner_id.id,
        }
