# Copyright 2026
# License AGPL-3.0 or later
{
    "name": "Sale Purchase Stock Inter Company Reverse",
    "summary": "Create a purchase order from an inter-company sale and prepare receipt from delivery",
    "version": "17.0.1.0.0",
    "category": "Sales/Purchase",
    "author": "SysAdaptPro, OCA style",
    "license": "AGPL-3",
    "depends": [
        "sale_management",
        "purchase_stock",
        "stock",
    ],
    "data": [
        "views/res_company_views.xml",
        "views/sale_order_views.xml",
        "views/purchase_order_views.xml",
        "views/stock_picking_views.xml",
    ],
    "installable": True,
    "application": False,
}
