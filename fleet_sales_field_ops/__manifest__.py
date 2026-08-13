{
    "name": "Fleet Sales - Field Operations",
    "version": "19.0.1.0.0",
    "summary": "Geofenced visit check-in, on-visit order/delivery/invoice, "
    "cash & Mada collections, warehouse-scoped stock, and credit-limit "
    "warnings for the Fleet Sales suite",
    "description": """
Fleet Sales - Field Operations
================================
Extends Fleet Sales - Core with everything that happens once a salesman is
actually standing in front of a customer:

* fleet.sales.visit -- a check-in that can be geofenced to the customer's
  registered location, per customer (radius and on/off both configurable
  on the customer record).
* Shelf photos / visit attachments captured on the visit itself.
* A single action that confirms the order, validates the delivery and
  posts the invoice in one step, with Order / Delivery / Invoice smart
  buttons on the visit.
* Cash and Mada (card) collection buttons: cash posts immediately against
  the salesman's own cash journal; Mada books a draft receipt voucher
  against the company's card journal for Finance to review and post --
  it never posts directly.
* Orders placed from a visit are forced onto the salesman's assigned
  Field Warehouse and blocked outright if that warehouse can't cover the
  order.
* A nonblocking credit-limit warning shown to the salesman before the
  order is confirmed if the customer's outstanding balance would exceed
  their credit limit.
* A Visit Report (pivot/graph) splitting visits into successful
  (has a confirmed sale or a payment) and unsuccessful.

Depends on fleet_sales_core for regions, sectors, the salesman hierarchy
and its security groups; no group or model from Core is redefined here.
""",
    "category": "Sales",
    "author": "Fleet Sales Project",
    "license": "LGPL-3",
    "depends": ["fleet_sales_core", "sale_management", "stock", "account"],
    "data": [
        "security/fleet_sales_field_ops_security.xml",
        "security/ir.model.access.csv",
        "data/fleet_sales_visit_sequence.xml",
        "views/res_users_views.xml",
        "views/res_partner_views.xml",
        "views/res_config_settings_views.xml",
        "views/stock_warehouse_views.xml",
        "views/fleet_sales_visit_views.xml",
        "views/fleet_sales_visit_report_views.xml",
        "views/fleet_sales_field_ops_menus.xml",
    ],
    "demo": [
        "demo/fleet_sales_field_ops_demo.xml",
    ],
    "installable": True,
    "application": False,
}
