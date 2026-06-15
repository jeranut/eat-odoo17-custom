# -*- coding: utf-8 -*-
from copy import deepcopy

from odoo import models


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def load_menus(self, debug):
        menus = deepcopy(super().load_menus(debug))
        parent_menu = self.env.ref('custom_paid_totals.menu_paid_totals_list')
        all_operator_menus = self.sudo().with_context(active_test=False).search([
            ('parent_id', '=', parent_menu.id),
        ]).filtered(
            lambda menu: (
                menu.action
                and menu.action._name == 'ir.actions.act_window'
                and menu.action.res_model == 'account.daily.balance.mobile'
            )
        )
        allowed_menu_ids = set(self.env['mobile.money.operator'].sudo().search([
            ('company_id', '=', self.env.company.id),
            ('treasury_menu_id', '!=', False),
        ]).mapped('treasury_menu_id').ids)
        hidden_menu_ids = set(all_operator_menus.ids) - allowed_menu_ids

        hidden_menu_ids.update(self.env['mobile.money.operator'].sudo().with_context(
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
