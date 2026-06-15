# -*- coding: utf-8 -*-
{
    "name": "Vendor Unpaid Supplier Report",
    "summary": "Impression PDF de l'état des impayés fournisseurs",
    "version": "17.0.1.4.0",
    "category": "Accounting/Accounting",
    "author": "SysAdaptPro",
    "license": "LGPL-3",
    "depends": ["account"],
    "data": [
        "security/ir.model.access.csv",
        "report/vendor_unpaid_supplier_report_templates.xml",
        "report/vendor_unpaid_supplier_report_actions.xml",
        "wizard/vendor_unpaid_supplier_report_wizard_views.xml",
        "views/account_move_views.xml",
    ],
    "installable": True,
    "application": False,
}
