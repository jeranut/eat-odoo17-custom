# -*- coding: utf-8 -*-
from copy import deepcopy

from odoo import models


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def load_menus(self, debug):
        menus = deepcopy(super().load_menus(debug))
        hidden_menu_ids = set(self.env['mobile.money.operator'].sudo().with_context(
            active_test=False,
        ).search([
            ('treasury_menu_id', '!=', False),
            ('company_id', '!=', self.env.company.id),
        ]).mapped('treasury_menu_id').ids)

        pending_menu_ids = list(hidden_menu_ids)
        while pending_menu_ids:
            menu_id = pending_menu_ids.pop()
            child_ids = set(menus.get(menu_id, {}).get('children', [])) - hidden_menu_ids
            hidden_menu_ids.update(child_ids)
            pending_menu_ids.extend(child_ids)

        for menu_id in hidden_menu_ids:
            menus.pop(menu_id, None)
        for menu in menus.values():
            menu['children'] = [
                child_id for child_id in menu.get('children', [])
                if child_id not in hidden_menu_ids
            ]

        return menus
