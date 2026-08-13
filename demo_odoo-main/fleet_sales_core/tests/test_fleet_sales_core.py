from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFleetSalesCore(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Region = cls.env["fleet.sales.region"]
        Sector = cls.env["fleet.sales.sector"]
        Users = cls.env["res.users"].with_context(no_reset_password=True)

        cls.group_salesman = cls.env.ref("fleet_sales_core.group_fleet_sales_salesman")
        cls.group_supervisor = cls.env.ref("fleet_sales_core.group_fleet_sales_supervisor")
        cls.group_regional = cls.env.ref("fleet_sales_core.group_fleet_sales_regional_manager")
        cls.group_finance = cls.env.ref("fleet_sales_core.group_fleet_sales_finance")
        cls.group_gm = cls.env.ref("fleet_sales_core.group_fleet_sales_general_manager")

        cls.region_central = Region.create({"name": "Central Test Region", "code": "TCEN"})
        cls.region_western = Region.create({"name": "Western Test Region", "code": "TWES"})
        cls.sector_grocery = Sector.create({"name": "Test Grocery"})

        cls.user_gm = Users.create(
            {
                "name": "Test GM",
                "login": "test.gm@fleetsales.test",
                "email": "test.gm@fleetsales.test",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id, cls.group_gm.id])],
            }
        )
        cls.user_regional = Users.create(
            {
                "name": "Test Regional Manager",
                "login": "test.rm@fleetsales.test",
                "email": "test.rm@fleetsales.test",
                "region_id": cls.region_central.id,
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id, cls.group_regional.id])],
            }
        )
        cls.user_supervisor = Users.create(
            {
                "name": "Test Supervisor",
                "login": "test.sup@fleetsales.test",
                "email": "test.sup@fleetsales.test",
                "region_id": cls.region_central.id,
                "supervisor_id": cls.user_regional.id,
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id, cls.group_supervisor.id])],
            }
        )
        cls.user_salesman = Users.create(
            {
                "name": "Test Salesman",
                "login": "test.sales1@fleetsales.test",
                "email": "test.sales1@fleetsales.test",
                "region_id": cls.region_central.id,
                "supervisor_id": cls.user_supervisor.id,
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id, cls.group_salesman.id])],
            }
        )
        cls.user_salesman_2 = Users.create(
            {
                "name": "Test Salesman 2",
                "login": "test.sales2@fleetsales.test",
                "email": "test.sales2@fleetsales.test",
                "region_id": cls.region_central.id,
                "supervisor_id": cls.user_supervisor.id,
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id, cls.group_salesman.id])],
            }
        )

    def test_region_sector_creation(self):
        self.assertEqual(self.region_central.code, "TCEN")
        self.assertTrue(self.sector_grocery.active)

    def test_supervisor_hierarchy(self):
        self.assertEqual(self.user_salesman.supervisor_id, self.user_supervisor)
        self.assertEqual(self.user_supervisor.supervisor_id, self.user_regional)
        with self.assertRaises(ValidationError):
            self.user_salesman.supervisor_id = self.user_salesman

    def test_supervisor_must_be_in_supervisor_group(self):
        with self.assertRaises(ValidationError):
            self.user_salesman_2.supervisor_id = self.user_salesman

    def test_group_implication(self):
        # A Regional Manager automatically holds the Supervisor and Salesman groups
        self.assertIn(self.group_supervisor, self.user_regional.all_group_ids)
        self.assertIn(self.group_salesman, self.user_regional.all_group_ids)
        # A General Manager automatically holds Finance too
        self.assertIn(self.group_finance, self.user_gm.all_group_ids)

    def test_customer_request_approval_creates_partner(self):
        request = self.env["fleet.sales.customer.request"].with_user(self.user_salesman).create(
            {
                "name": "Test New Customer",
                "vat": "TESTVAT001",
                "sector_id": self.sector_grocery.id,
                "region_id": self.region_central.id,
                "proposed_salesman_id": self.user_salesman.id,
            }
        )
        request.with_user(self.user_salesman).action_submit()
        self.assertEqual(request.state, "submitted")
        request.with_user(self.user_supervisor).action_approve()
        self.assertEqual(request.state, "approved")
        self.assertTrue(request.created_partner_id)
        self.assertEqual(request.created_partner_id.vat, "TESTVAT001")
        self.assertEqual(request.created_partner_id.salesman_id, self.user_salesman)

    def test_customer_request_duplicate_vat_blocked(self):
        self.env["res.partner"].create({"name": "Existing Co", "vat": "DUPVAT001"})
        request = self.env["fleet.sales.customer.request"].create(
            {"name": "Duplicate Attempt", "vat": "DUPVAT001"}
        )
        with self.assertRaises(UserError):
            request.action_submit()

    def test_customer_request_approve_requires_supervisor_group(self):
        request = self.env["fleet.sales.customer.request"].create({"name": "Needs Approval"})
        request.action_submit()
        with self.assertRaises(UserError):
            request.with_user(self.user_salesman).action_approve()

    def test_pos_request_approval_creates_child_location(self):
        customer = self.env["res.partner"].create(
            {
                "name": "Parent Test Customer",
                "is_company": True,
                "sector_id": self.sector_grocery.id,
                "region_id": self.region_central.id,
                "salesman_id": self.user_salesman.id,
            }
        )
        pos_request = self.env["fleet.sales.pos.request"].with_user(self.user_salesman).create(
            {
                "name": "Test Kiosk",
                "customer_id": customer.id,
                "street": "King Fahd Road",
                "city": "Riyadh",
                "latitude": 24.7136,
                "longitude": 46.6753,
            }
        )
        pos_request.with_user(self.user_salesman).action_submit()
        pos_request.with_user(self.user_supervisor).action_approve()
        location = pos_request.created_location_id
        self.assertTrue(location)
        self.assertTrue(location.is_pos_location)
        self.assertEqual(location.parent_id, customer)
        # Sector/region/salesman default from the parent customer
        self.assertEqual(location.sector_id, self.sector_grocery)
        self.assertEqual(location.salesman_id, self.user_salesman)

    def test_record_rule_salesman_sees_own_requests_only(self):
        req_1 = self.env["fleet.sales.customer.request"].with_user(self.user_salesman).create(
            {"name": "Salesman 1 request"}
        )
        req_2 = self.env["fleet.sales.customer.request"].with_user(self.user_salesman_2).create(
            {"name": "Salesman 2 request"}
        )
        visible_to_salesman_1 = (
            self.env["fleet.sales.customer.request"]
            .with_user(self.user_salesman)
            .search([("id", "in", [req_1.id, req_2.id])])
        )
        self.assertEqual(visible_to_salesman_1, req_1)

        visible_to_supervisor = (
            self.env["fleet.sales.customer.request"]
            .with_user(self.user_supervisor)
            .search([("id", "in", [req_1.id, req_2.id])])
        )
        self.assertEqual(visible_to_supervisor, req_1 | req_2)

    def test_record_rule_salesman_cannot_read_others_request(self):
        req_2 = self.env["fleet.sales.customer.request"].with_user(self.user_salesman_2).create(
            {"name": "Salesman 2 private request"}
        )
        with self.assertRaises(AccessError):
            req_2.with_user(self.user_salesman).read(["name"])

    def test_settings_defaults(self):
        settings = self.env["res.config.settings"].create({})
        self.assertEqual(settings.fleet_sales_inactive_warning_days, 30)
        self.assertEqual(settings.fleet_sales_inactive_days, 60)
        settings.fleet_sales_inactive_warning_days = 45
        settings.execute()
        self.assertEqual(
            self.env["ir.config_parameter"].sudo().get_param(
                "fleet_sales_core.inactive_warning_days"
            ),
            "45",
        )
