from odoo import models, fields, api, _
from datetime import date


class AccountMove(models.Model):
    _inherit = "account.move"

    invoice_date = fields.Date(
        string="Date de la facture",
        default=lambda self: date.today(),
        readonly=True
    )

    @api.model
    def default_get(self, fields_list):
        res = super(AccountMove, self).default_get(fields_list)
        res['invoice_date'] = date.today()
        return res

    def action_register_payment(self):
        # Mettre à jour automatiquement invoice_date si différente de today's date
        for move in self:
            if move.invoice_date != date.today():
                move.write({'invoice_date': date.today()})

        # ensuite appeler le comportement normal
        return super(AccountMove, self).action_register_payment()