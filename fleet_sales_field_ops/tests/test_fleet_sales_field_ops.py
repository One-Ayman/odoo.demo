from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestFleetSalesFieldOps(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.salesman = cls.env["res.users"].create(
            {
                "name": "Field Salesman",
                "login": "field_salesman_test",
                "email": "field_salesman_test@example.com",
                "groups_id": [
                    (
                        4,
                        cls.env.ref(
                            "fleet_sales_core.group_fleet_sales_salesman"
                        ).id,
                    )
                ],
                "warehouse_id": cls.warehouse.id,
            }
        )
        cls.customer = cls.env["res.partner"].create(
            {
                "name": "Al Rawabi Test Grocery",
                "is_company": True,
                "partner_latitude": 24.7136,
                "partner_longitude": 46.6753,
                "enforce_visit_geofence": True,
                "visit_geofence_radius": 150,
            }
        )
        cls.product = cls.env["product.product"].search(
            [("type", "=", "product")], limit=1
        )

    def _make_visit(self, **extra):
        vals = {
            "partner_id": self.customer.id,
            "salesman_id": self.salesman.id,
        }
        vals.update(extra)
        return self.env["fleet.sales.visit"].create(vals)

    def test_check_in_blocked_when_too_far(self):
        """Check-in must be refused when the device is outside the
        customer's configured geofence radius."""
        visit = self._make_visit(
            check_in_latitude=24.8000,  # ~10km away from the customer
            check_in_longitude=46.6753,
        )
        with self.assertRaises(UserError):
            visit.action_check_in()
        self.assertEqual(visit.state, "draft")

    def test_check_in_allowed_when_close(self):
        """Check-in succeeds when within the configured radius."""
        visit = self._make_visit(
            check_in_latitude=24.7137,  # a few meters away
            check_in_longitude=46.6754,
        )
        visit.action_check_in()
        self.assertEqual(visit.state, "checked_in")

    def test_check_in_ignores_geofence_when_disabled(self):
        """A customer with geofence checking turned off allows check-in
        from anywhere, even with no location captured at all."""
        self.customer.enforce_visit_geofence = False
        visit = self._make_visit()
        visit.action_check_in()
        self.assertEqual(visit.state, "checked_in")

    def test_start_order_blocked_without_warehouse(self):
        """A salesman with no Field Warehouse configured can't start an
        order from a visit."""
        self.salesman.warehouse_id = False
        visit = self._make_visit()
        visit.action_check_in()
        with self.assertRaises(UserError):
            visit.action_start_order()

    def test_warehouse_stock_hard_block(self):
        """An order from a visit is blocked outright -- not partially
        confirmed -- when the salesman's warehouse can't cover a line."""
        visit = self._make_visit()
        visit.action_check_in()
        visit.action_start_order()
        order = visit.sale_order_id
        # Ask for far more than could plausibly be on hand.
        self.env["sale.order.line"].create(
            {
                "order_id": order.id,
                "product_id": self.product.id,
                "product_uom_qty": 1_000_000,
            }
        )
        with self.assertRaises(UserError):
            order._fleet_sales_check_warehouse_stock()
        self.assertEqual(order.state, "draft")

    def test_visit_successful_from_payment_only(self):
        """A visit with no sale but a registered collection still counts
        as successful."""
        visit = self._make_visit()
        self.assertFalse(visit.is_successful)
        self.env["account.payment"].create(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": self.customer.id,
                "amount": 100.0,
                "visit_id": visit.id,
            }
        )
        self.assertTrue(visit.is_successful)

    def test_credit_limit_warning_is_nonblocking(self):
        """Exceeding the credit limit produces a warning message but does
        not raise -- the salesman is still allowed to proceed."""
        self.customer.credit_limit = 100.0
        visit = self._make_visit()
        visit.action_check_in()
        visit.action_start_order()
        order = visit.sale_order_id
        self.env["sale.order.line"].create(
            {
                "order_id": order.id,
                "product_id": self.product.id,
                "product_uom_qty": 1,
                "price_unit": 10_000.0,
            }
        )
        # Should not raise, even though the order total is well past
        # the 100.0 credit limit set above.
        visit._check_credit_limit_warning(order)
        self.assertTrue(visit.credit_warning)
