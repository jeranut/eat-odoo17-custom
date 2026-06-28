from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    advance_payment_account_id = fields.Many2one(
        "account.account",
        related="company_id.advance_payment_account_id",
        readonly=False,
        string="Compte d'attente avance sur payment",
    )


class CustomPaidAdvancePaymentSettings(models.TransientModel):
    _name = "custom.paid.advance.payment.settings"
    _description = "Configuration des avances sur payment"

    company_id = fields.Many2one(
        "res.company",
        string="Société",
        required=True,
        default=lambda self: self.env.company,
    )
    advance_payment_account_id = fields.Many2one(
        "account.account",
        related="company_id.advance_payment_account_id",
        readonly=False,
        string="Compte d'attente avance sur payment",
    )

    def action_save(self):
        return {"type": "ir.actions.act_window_close"}
