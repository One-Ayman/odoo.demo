import math

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class FleetSalesVisit(models.Model):
    _name = "fleet.sales.visit"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Fleet Sales Field Visit"
    _order = "create_date desc"

    name = fields.Char(
        string="Reference", default="New", copy=False, readonly=True
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer / POS Location",
        required=True,
        tracking=True,
    )
    salesman_id = fields.Many2one(
        "res.users",
        string="Salesman",
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
    )
    region_id = fields.Many2one(
        related="partner_id.region_id", store=True, string="Region"
    )
    sector_id = fields.Many2one(
        related="partner_id.sector_id", store=True, string="Sector"
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("checked_in", "Checked In"),
            ("closed", "Closed"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )

    # --- Geofenced check-in -------------------------------------------
    check_in_datetime = fields.Datetime(string="Checked In On", readonly=True)
    check_in_latitude = fields.Float(
        string="Check-in Latitude", digits=(10, 7),
        help="Captured from the salesman's device when checking in.",
    )
    check_in_longitude = fields.Float(
        string="Check-in Longitude", digits=(10, 7),
        help="Captured from the salesman's device when checking in.",
    )
    distance_to_customer = fields.Float(
        string="Distance to Customer (m)",
        compute="_compute_distance_to_customer",
        help="Distance between the check-in location and the customer's "
        "registered location. 0 until both locations are known.",
    )

    # --- Visit evidence --------------------------------------------------
    photo_ids = fields.Many2many(
        "ir.attachment",
        "fleet_sales_visit_attachment_rel",
        "visit_id",
        "attachment_id",
        string="Shelf Photos / Attachments",
    )

    # --- Sales flow --------------------------------------------------------
    sale_order_id = fields.Many2one(
        "sale.order", string="Order", readonly=True, copy=False, tracking=True
    )
    picking_ids = fields.One2many(
        related="sale_order_id.picking_ids", string="Deliveries"
    )
    invoice_ids = fields.Many2many(
        related="sale_order_id.invoice_ids", string="Invoices"
    )
    payment_ids = fields.One2many(
        "account.payment", "visit_id", string="Collections"
    )
    credit_warning = fields.Text(string="Credit Limit Warning", readonly=True)

    # --- Outcome ---------------------------------------------------------
    is_successful = fields.Boolean(
        string="Successful Visit",
        compute="_compute_is_successful",
        store=True,
        help="A visit is successful if it produced a confirmed sale or at "
        "least one collection (cash posted, or Mada awaiting review).",
    )

    order_count = fields.Integer(compute="_compute_counts")
    delivery_count = fields.Integer(compute="_compute_counts")
    invoice_count = fields.Integer(compute="_compute_counts")
    payment_count = fields.Integer(compute="_compute_counts")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "fleet.sales.visit"
                ) or "New"
        return super().create(vals_list)

    @api.depends(
        "check_in_latitude",
        "check_in_longitude",
        "partner_id.partner_latitude",
        "partner_id.partner_longitude",
    )
    def _compute_distance_to_customer(self):
        for record in self:
            partner = record.partner_id
            if (
                record.check_in_latitude
                and record.check_in_longitude
                and partner.partner_latitude
                and partner.partner_longitude
            ):
                record.distance_to_customer = self._haversine_distance_m(
                    record.check_in_latitude,
                    record.check_in_longitude,
                    partner.partner_latitude,
                    partner.partner_longitude,
                )
            else:
                record.distance_to_customer = 0.0

    @api.depends("sale_order_id.state", "payment_ids", "payment_ids.state")
    def _compute_is_successful(self):
        for record in self:
            has_confirmed_sale = record.sale_order_id.state in ("sale", "done")
            has_collection = bool(
                record.payment_ids.filtered(
                    lambda p: p.state in ("draft", "posted", "in_process")
                )
            )
            record.is_successful = has_confirmed_sale or has_collection

    def _compute_counts(self):
        for record in self:
            record.order_count = 1 if record.sale_order_id else 0
            record.delivery_count = len(record.picking_ids)
            record.invoice_count = len(record.invoice_ids)
            record.payment_count = len(record.payment_ids)

    @staticmethod
    def _haversine_distance_m(lat1, lon1, lat2, lon2):
        earth_radius_m = 6371000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        d_phi = math.radians(lat2 - lat1)
        d_lambda = math.radians(lon2 - lon1)
        a = (
            math.sin(d_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
        )
        return 2 * earth_radius_m * math.asin(math.sqrt(a))

    # --- Check-in ----------------------------------------------------------
    def action_check_in(self):
        for record in self:
            if record.state != "draft":
                raise UserError(_("Only draft visits can be checked in."))
            partner = record.partner_id
            if partner.enforce_visit_geofence:
                if not record.check_in_latitude or not record.check_in_longitude:
                    raise UserError(
                        _(
                            "This customer requires a location check. "
                            "Enable location on your device and try again."
                        )
                    )
                if not partner.partner_latitude or not partner.partner_longitude:
                    raise UserError(
                        _(
                            "%(customer)s has no registered location, so "
                            "location can't be verified. Ask an "
                            "administrator to set one, or turn off "
                            "location check for this customer.",
                            customer=partner.name,
                        )
                    )
                distance = record.distance_to_customer
                if distance > partner.visit_geofence_radius:
                    raise UserError(
                        _(
                            "You are %(distance)s m away from %(customer)s. "
                            "You must be within %(radius)s m to check in.",
                            distance=int(distance),
                            customer=partner.name,
                            radius=partner.visit_geofence_radius,
                        )
                    )
            record.write(
                {"state": "checked_in", "check_in_datetime": fields.Datetime.now()}
            )

    # --- Order / delivery / invoice, one action ----------------------------
    def action_start_order(self):
        self.ensure_one()
        if self.state != "checked_in":
            raise UserError(_("Check in to the visit before starting an order."))
        if self.sale_order_id:
            raise UserError(_("This visit already has an order."))
        if not self.salesman_id.warehouse_id:
            raise UserError(
                _(
                    "%(salesman)s has no Field Warehouse set. Ask an "
                    "administrator to configure one on their user profile "
                    "before selling.",
                    salesman=self.salesman_id.name,
                )
            )
        order = self.env["sale.order"].create(
            {
                "partner_id": self.partner_id.id,
                "user_id": self.salesman_id.id,
                "warehouse_id": self.salesman_id.warehouse_id.id,
                "visit_id": self.id,
                "company_id": self.company_id.id,
            }
        )
        self.sale_order_id = order.id
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "view_mode": "form",
            "res_id": order.id,
        }

    def action_process_sale(self):
        """Confirm the order, validate its delivery and post its invoice
        in one step. Also where the (nonblocking) credit-limit warning is
        raised, computed before the order is confirmed so the salesman
        sees it before, not after, the sale goes through.
        """
        self.ensure_one()
        order = self.sale_order_id
        if not order:
            raise UserError(_("Start an order first."))
        if not order.order_line:
            raise UserError(_("Add at least one product to the order first."))
        if order.state not in ("draft", "sent"):
            raise UserError(_("This order was already processed."))

        self._check_credit_limit_warning(order)

        order._fleet_sales_check_warehouse_stock()
        order.action_confirm()

        for picking in order.picking_ids.filtered(
            lambda p: p.state not in ("done", "cancel")
        ):
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            picking.with_context(
                skip_backorder=True,
                picking_ids_not_to_backorder=picking.ids,
            ).button_validate()

        invoices = order._create_invoices()
        invoices.action_post()

        self.state = "closed"

        message = _("Order confirmed, delivered and invoiced.")
        notif_type = "success"
        sticky = False
        if self.credit_warning:
            message = "%s %s" % (self.credit_warning, message)
            notif_type = "warning"
            sticky = True

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Order processed"),
                "message": message,
                "type": notif_type,
                "sticky": sticky,
            },
        }

    def _check_credit_limit_warning(self, order):
        self.ensure_one()
        partner = order.partner_id.commercial_partner_id
        if not partner.credit_limit:
            self.credit_warning = False
            return
        projected_balance = partner.credit + order.amount_total
        if projected_balance > partner.credit_limit:
            message = _(
                "Warning: %(customer)s will be over their credit limit "
                "(%(balance)s of %(limit)s allowed) after this sale.",
                customer=partner.name,
                balance=projected_balance,
                limit=partner.credit_limit,
            )
            self.credit_warning = message
            self.message_post(body=message)
        else:
            self.credit_warning = False

    # --- Collections: cash posts, Mada stays a draft voucher ---------------
    def _get_default_payment_amount(self):
        self.ensure_one()
        if self.sale_order_id and self.sale_order_id.invoice_ids:
            posted = self.sale_order_id.invoice_ids.filtered(
                lambda m: m.state == "posted"
            )
            return sum(posted.mapped("amount_residual"))
        return 0.0

    def action_register_cash_payment(self):
        self.ensure_one()
        journal = self.salesman_id.cash_journal_id
        if not journal:
            raise UserError(
                _(
                    "%(salesman)s has no Cash Journal assigned. Ask "
                    "Finance to set one up on their user profile.",
                    salesman=self.salesman_id.name,
                )
            )
        payment = self.env["account.payment"].create(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": self.partner_id.commercial_partner_id.id,
                "amount": self._get_default_payment_amount(),
                "journal_id": journal.id,
                "visit_id": self.id,
                "memo": _("Field collection (cash) - %s") % self.display_name,
            }
        )
        payment.action_post()
        return self._open_payment(payment)

    def action_register_mada_payment(self):
        self.ensure_one()
        journal = self.company_id.fleet_sales_mada_journal_id
        if not journal:
            raise UserError(
                _(
                    "No Mada / Card journal is configured. Ask an "
                    "administrator to set one in Settings > Fleet Sales."
                )
            )
        payment = self.env["account.payment"].create(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": self.partner_id.commercial_partner_id.id,
                "amount": self._get_default_payment_amount(),
                "journal_id": journal.id,
                "visit_id": self.id,
                "memo": _(
                    "Field collection (Mada, pending Finance review) - %s"
                )
                % self.display_name,
            }
        )
        # Left in draft deliberately: a Mada collection is only a receipt
        # voucher until Finance reviews and posts it -- never posted here.
        return self._open_payment(payment)

    def _open_payment(self, payment):
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.payment",
            "view_mode": "form",
            "res_id": payment.id,
        }

    # --- Smart button openers ----------------------------------------------
    def action_view_order(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "view_mode": "form",
            "res_id": self.sale_order_id.id,
        }

    def action_view_deliveries(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "view_mode": "list,form",
            "domain": [("id", "in", self.picking_ids.ids)],
        }

    def action_view_invoices(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", self.invoice_ids.ids)],
        }

    def action_view_payments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.payment",
            "view_mode": "list,form",
            "domain": [("id", "in", self.payment_ids.ids)],
        }
