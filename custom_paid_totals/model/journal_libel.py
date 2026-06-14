from odoo import models, fields

class AccountMove(models.Model):
    _inherit = 'account.move'

    journal_label = fields.Char(string="Libellé du journal")
