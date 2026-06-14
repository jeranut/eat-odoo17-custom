from odoo import models, api, _
from odoo.exceptions import UserError
from datetime import date

class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    def action_create_payments(self):
        # Restriction uniquement pour paiement fournisseur CASH
        if self.payment_type == "outbound" and self.partner_type == "supplier" and self.journal_id.type == "cash":
            today = date.today()
            last_balance = self.env['account.daily.balance'].search(
                [('company_id', '=', self.company_id.id)],
                order='date desc',
                limit=1
            )

            if not last_balance:
                raise UserError(_("⚠ Aucun rapport journalier n'existe pour aujourd'hui. "
                                  "Veuillez générer le rapport avant toute opération de paiement."))

            if last_balance.etat == 'cloturer':
                raise UserError(_("Le journal quotidien est déjà clôturé. "
                                  "Impossible d'ajouter un paiement dans cette balance."))

            projected_new_balance = last_balance.nouveau_solde - self.amount
            if projected_new_balance < 0:
                raise UserError(_(
                    f"Paiement CASH impossible !\n\n"
                    f"Solde disponible : {last_balance.nouveau_solde:,.2f} {self.currency_id.symbol}\n"
                    f"Montant du paiement : {self.amount:,.2f} {self.currency_id.symbol}\n\n"
                    f"Le solde deviendrait négatif ({projected_new_balance:,.2f} {self.currency_id.symbol})"
                ))

        # Créer le paiement réel
        return super(AccountPaymentRegister, self).action_create_payments()
