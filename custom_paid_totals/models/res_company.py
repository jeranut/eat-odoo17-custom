from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    advance_payment_account_id = fields.Many2one(
        "account.account",
        string="Compte d'attente avance sur payment",
        domain="[('deprecated', '=', False)]",
    )
