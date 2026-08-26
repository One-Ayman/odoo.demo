{
    "name": "Fast Financial Reports",
    "summary": "High-performance, SQL-pushdown Trial Balance, General Ledger and "
               "Partner Ledger for very large accounting databases.",
    "description": """
Fast Financial Reports (Phase 1)
=================================

A read-only reporting engine for Odoo Accounting designed for databases with
tens of millions of ``account.move.line`` records, where the standard
Trial Balance / General Ledger / Partner Ledger reports become too slow.

Phase 1 delivers:

* Fast Trial Balance
* Fast General Ledger (summary first, lazy-loaded transaction detail)
* Fast Partner Ledger / Partner Statement

All filtering and aggregation is pushed down to PostgreSQL (WHERE + GROUP BY).
The module never loads bulk ``account.move.line`` recordsets into Python and
never uses ``search()`` followed by a Python loop over accounting data.

The module is strictly read-only with respect to accounting data: it does not
modify ``account.move``, ``account.move.line``, journals, reconciliation,
POS accounting or ZATCA logic in any way.
    """,
    "version": "17.0.1.0.0",
    "category": "Accounting/Accounting",
    "license": "LGPL-3",
    "author": "Ayman Elhaddad",
    "depends": ["account"],
    "data": [
        "security/fast_financial_reports_security.xml",
        "security/ir.model.access.csv",
        "views/trial_balance_views.xml",
        "views/general_ledger_views.xml",
        "views/partner_ledger_views.xml",
        "views/report_debug_log_views.xml",
        "views/fast_financial_reports_menus.xml",
        "report/trial_balance_report.xml",
        "report/general_ledger_report.xml",
        "report/partner_ledger_report.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
