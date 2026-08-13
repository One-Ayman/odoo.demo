{
    "name": "Fleet Sales - Core",
    "version": "19.0.1.0.0",
    "summary": "Regions, sectors, reporting hierarchy, approval workflow and security groups for the Fleet Sales suite",
    "description": """
Fleet Sales - Core
===================
Foundation module for the Fleet Sales / Van Sales suite. Provides:

* Region and Sector master data.
* The Salesman -> Supervisor -> Regional Manager -> Finance -> General
  Manager security-group hierarchy shared by every fleet_sales_* module.
* A reusable approval workflow (fleet.approval.mixin) used by New Customer
  and New POS Location requests, and by discount/credit approvals in later
  phases.
* The res.users / res.partner fields (region, sector, salesman, supervisor)
  every other fleet_sales_* module relies on.

No standard Odoo model is modified beyond adding fields; no core files are
touched. Depends only on base and mail so it can be installed with nothing
else from the suite.
""",
    "category": "Sales",
    "author": "Fleet Sales Project",
    "license": "LGPL-3",
    "depends": ["base", "mail", "base_setup"],
    "data": [
        "security/fleet_sales_security.xml",
        "security/ir.model.access.csv",
        "security/fleet_sales_record_rules.xml",
        "views/fleet_sales_region_views.xml",
        "views/fleet_sales_sector_views.xml",
        "views/fleet_sales_customer_request_views.xml",
        "views/fleet_sales_pos_request_views.xml",
        "views/res_users_views.xml",
        "views/res_config_settings_views.xml",
        "views/fleet_sales_menus.xml",
    ],
    "demo": [
        "demo/fleet_sales_demo.xml",
    ],
    "installable": True,
    "application": True,
}
