# -*- coding: utf-8 -*-
{
    "name": "Xprinter Invoice Print (Flask)",
    "version": "17.0.1.0.0",
    "summary": "Imprime les factures client via un service Flask (Xprinter ESC/POS)",
    "author": "You",
    "license": "LGPL-3",
    "depends": ["account", "product"],
    "data": ["views/account_move_views.xml", "security/ir.model.access.csv"],
    "external_dependencies": {"python": ["requests"]},
    "installable": True,
}
