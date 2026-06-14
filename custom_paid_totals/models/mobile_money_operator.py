# -*- coding: utf-8 -*-
from odoo import fields, models


class MobileMoneyOperator(models.Model):
    _name = 'mobile.money.operator'
    _description = 'Opérateur Mobile Money'
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

    _sql_constraints = [
        (
            'unique_code_company',
            'unique(code, company_id)',
            'Le code de l’opérateur doit être unique par société.',
        ),
        (
            'unique_journal_company',
            'unique(journal_id, company_id)',
            'Un journal bancaire ne peut être lié qu’à un seul opérateur Mobile Money par société.',
        ),
    ]
