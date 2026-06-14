from odoo import models, api, _
from odoo.exceptions import UserError
from datetime import date


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    def action_create_payments(self):

        journal_type = self.journal_id.type

        # Restriction uniquement pour Paiement fournisseur + CASH
        if journal_type == "cash" and self.payment_type == "outbound" and self.partner_type == "supplier":

            today = date.today()

            balance = self.env['account.daily.balance'].search([
                ('date', '=', today),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
            if not balance:
                raise UserError(_("⚠ Aucun rapport journalier n'existe pour aujourd'hui. "
                                  "Veuillez générer le rapport avant toute opération de paiement."))

            projected_new_balance = balance.nouveau_solde - self.amount

            if projected_new_balance < 0:
                raise UserError(_(
                    f"Paiement CASH impossible !\n\n"
                    f"Solde disponible : {balance.nouveau_solde:,.2f} {self.currency_id.symbol}\n"
                    f"Montant du paiement : {self.amount:,.2f} {self.currency_id.symbol}\n\n"
                    f"Le solde deviendrait négatif ({projected_new_balance:,.2f} {self.currency_id.symbol})"
                ))

        return super(AccountPaymentRegister, self).action_create_payments()
