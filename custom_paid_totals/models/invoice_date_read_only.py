from odoo import models, fields, api


class AccountMove(models.Model):
    _inherit = "account.move"

    invoice_date = fields.Date(
        string="Date de la facture",
        default=fields.Date.context_today,
        readonly=True
    )

    @api.model
    def default_get(self, fields_list):
        res = super(AccountMove, self).default_get(fields_list)
        if 'invoice_date' in fields_list and not res.get('invoice_date'):
            res['invoice_date'] = fields.Date.context_today(self)
        return res
