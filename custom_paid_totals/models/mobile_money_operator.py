# -*- coding: utf-8 -*-
from odoo import api, fields, models


class MobileMoneyOperator(models.Model):
    _name = 'mobile.money.operator'
    _description = 'Configuration d’un journal de trésorerie'
    _order = 'name'
    _check_company_auto = True

    name = fields.Char(string='Nom', required=True)
    code = fields.Char(string='Code', required=True)
    journal_id = fields.Many2one(
        'account.journal',
        string='Journal bancaire',
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]",
        check_company=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Société',
        required=True,
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(default=True)
    treasury_action_id = fields.Many2one(
        'ir.actions.act_window',
        string='Action du journal',
        copy=False,
        readonly=True,
        ondelete='set null',
    )
    treasury_menu_id = fields.Many2one(
        'ir.ui.menu',
        string='Menu du journal',
        copy=False,
        readonly=True,
        ondelete='set null',
    )

    _sql_constraints = [
        (
            'unique_code_company',
            'unique(code, company_id)',
            'Le code du journal doit être unique par société.',
        ),
        (
            'unique_journal_company',
            'unique(journal_id, company_id)',
            'Un journal bancaire ne peut être configuré qu’une seule fois par société.',
        ),
    ]

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if 'company_id' in fields_list:
            defaults['company_id'] = self.env.company.id
        return defaults

    def _sync_treasury_menu(self):
        parent_menu = self.env.ref('custom_paid_totals.menu_paid_totals_list')
        user_group = self.env.ref('custom_paid_totals.group_paid_totals_user')
        action_model = self.env['ir.actions.act_window'].sudo()
        menu_model = self.env['ir.ui.menu'].sudo()
        active_languages = self.env['res.lang'].sudo().search([('active', '=', True)]).mapped('code')

        for journal_config in self:
            menu_name = journal_config.name or journal_config.journal_id.name
            action_vals = {
                'name': menu_name,
                'res_model': 'account.daily.balance.mobile',
                'view_mode': 'tree,form',
                'domain': repr([
                    ('company_id', '=', journal_config.company_id.id),
                    ('operator_id', '=', journal_config.id),
                ]),
                'context': repr({
                    'default_company_id': journal_config.company_id.id,
                    'default_operator_id': journal_config.id,
                }),
            }
            action = journal_config.treasury_action_id.sudo()
            if action:
                action.write(action_vals)
            else:
                action = action_model.create(action_vals)
                journal_config.sudo().treasury_action_id = action
            for language in active_languages:
                action.with_context(lang=language).write({'name': menu_name})

            menu_vals = {
                'name': menu_name,
                'parent_id': parent_menu.id,
                'action': 'ir.actions.act_window,%s' % action.id,
                'sequence': 10,
                'active': journal_config.active,
                'groups_id': [(6, 0, [user_group.id])],
            }
            menu = journal_config.treasury_menu_id.sudo()
            if menu:
                menu.write(menu_vals)
            else:
                menu = menu_model.create(menu_vals)
                journal_config.sudo().treasury_menu_id = menu
            for language in active_languages:
                menu.with_context(lang=language).write({'name': menu_name})

    @api.model
    def _sync_all_treasury_menus(self):
        self.with_context(active_test=False).search([])._sync_treasury_menu()
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_treasury_menu()
        return records

    def write(self, vals):
        result = super().write(vals)
        if {'name', 'journal_id', 'company_id', 'active'} & set(vals):
            self._sync_treasury_menu()
        return result

    def unlink(self):
        menus = self.mapped('treasury_menu_id').sudo()
        actions = self.mapped('treasury_action_id').sudo()
        result = super().unlink()
        menus.unlink()
        actions.unlink()
        return result
