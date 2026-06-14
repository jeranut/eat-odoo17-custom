from odoo import models, api, _
from odoo.exceptions import UserError
from datetime import date


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    def action_create_payments(self):

        journal = self.journal_id
        journal_name = journal.name.strip().lower() if journal and journal.name else ""

        # Restriction uniquement pour Paiement fournisseur via MOBILE MONEY
        if (
            journal.type == "bank"
            and journal_name == "mobile money"
            and self.payment_type == "outbound"
            and self.partner_type == "supplier"
        ):
            today = date.today()

            balance = self.env['account.daily.balance.mobile'].search([
                ('date', '=', today),
                ('company_id', '=', self.company_id.id),
            ], limit=1)
            if not balance:
                raise UserError(_("⚠ Aucun rapport Mobile Money n'existe pour aujourd'hui.\n"
                                  "Veuillez générer ou initialiser le solde de Mobile Money avant ce paiement."))

            projected_new_balance = balance.nouveau_solde - self.amount

            if projected_new_balance < 0:
                raise UserError(_(
                    f"Paiement Mobile Money impossible !\n\n"
                    f"Solde disponible : {balance.nouveau_solde:,.2f} {self.currency_id.symbol}\n"
                    f"Montant du paiement : {self.amount:,.2f} {self.currency_id.symbol}\n\n"
                    f"Le solde deviendrait négatif ({projected_new_balance:,.2f} {self.currency_id.symbol})"
                ))

        return super(AccountPaymentRegister, self).action_create_payments()
