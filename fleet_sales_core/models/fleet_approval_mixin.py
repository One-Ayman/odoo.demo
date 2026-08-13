from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FleetApprovalMixin(models.AbstractModel):
    """Shared draft -> submitted -> approved/rejected workflow.

    Concrete models (New Customer Request, New POS Request, and later the
    discount/credit-limit approvals) inherit this instead of each
    reimplementing the same state machine. Subclasses override
    ``_apply_approval`` to perform their side effect (e.g. create a
    partner) and ``_required_approval_group_xmlid`` to name the group
    allowed to decide.
    """

    _name = "fleet.approval.mixin"
    _description = "Fleet Sales Approval Workflow"

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    requested_by = fields.Many2one(
        "res.users", string="Requested By", default=lambda self: self.env.user, tracking=True
    )
    request_date = fields.Datetime(string="Submitted On")
    approver_id = fields.Many2one("res.users", string="Decided By", tracking=True)
    decision_date = fields.Datetime(string="Decided On")
    reason = fields.Text(string="Reason / Notes")

    def _required_approval_group_xmlid(self):
        """Override to return the xmlid of the group allowed to approve/reject."""
        return False

    def _apply_approval(self):
        """Override to perform the side effect of an approval (e.g. create a partner)."""
        return

    def action_submit(self):
        for record in self:
            if record.state != "draft":
                raise UserError(_("Only draft requests can be submitted."))
            record.write({"state": "submitted", "request_date": fields.Datetime.now()})
            record._notify_approvers()
        return True

    def action_approve(self):
        self._check_can_decide()
        for record in self:
            if record.state != "submitted":
                raise UserError(_("Only submitted requests can be approved."))
            record.write(
                {
                    "state": "approved",
                    "approver_id": self.env.user.id,
                    "decision_date": fields.Datetime.now(),
                }
            )
            record._apply_approval()
        return True

    def action_reject(self, reason=None):
        self._check_can_decide()
        for record in self:
            if record.state != "submitted":
                raise UserError(_("Only submitted requests can be rejected."))
            values = {
                "state": "rejected",
                "approver_id": self.env.user.id,
                "decision_date": fields.Datetime.now(),
            }
            if reason:
                values["reason"] = reason
            record.write(values)
        return True

    def _check_can_decide(self):
        if self.env.su:
            # Superuser context (data loading, system automations): the
            # group check below is a business rule for interactive users,
            # not an access-control layer -- ir.model.access/ir.rule already
            # guard the underlying write.
            return
        group_xmlid = self._required_approval_group_xmlid()
        if not group_xmlid:
            return
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        if group and group not in self.env.user.all_group_ids:
            raise UserError(_("You are not allowed to approve or reject this request."))

    def _notify_approvers(self):
        """Override to post an activity/message to the right approver(s)."""
        return
