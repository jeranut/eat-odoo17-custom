from odoo import models, api, fields, _
from odoo.exceptions import UserError

class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    def action_create_payments(self):
        payment_date = self.payment_date or fields.Date.context_today(self)

        # ───────────────
        # Paiement fournisseur CASH
        # ───────────────
        if self.payment_type == "outbound" and self.partner_type == "supplier" and self.journal_id.type == "cash":
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

        # ───────────────
        # Paiement fournisseur MOBILE MONEY
        # ───────────────
        operator = self.env['mobile.money.operator'].search([
            ('journal_id', '=', self.journal_id.id),
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
        ], limit=1)
        if self.payment_type == "outbound" and self.partner_type == "supplier" and operator:
            # Récupération du dernier solde Mobile Money
            last_balance = self.env['account.daily.balance.mobile'].search(
                [
                    ('company_id', '=', self.company_id.id),
                    ('operator_id', '=', operator.id),
                    ('date', '<=', payment_date),
                ],
                order='date desc',
                limit=1
            )

            # Créer la balance si elle n'existe pas ou si elle est clôturée
            if not last_balance or last_balance.etats == 'cloturer':
                last_balance = self.env['account.daily.balance.mobile'].create({
                    'date': payment_date,
                    'company_id': self.company_id.id,
                    'operator_id': operator.id,
                    'ancien_solde': last_balance.nouveau_solde if last_balance else 0.0
                })

            # Mettre à jour la balance pour calculer le nouveau solde
            if hasattr(last_balance, 'action_update_totals_mobile'):
                last_balance.action_update_totals_mobile()

            # Vérification du solde disponible
            projected_new_balance = last_balance.nouveau_solde - self.amount
            if projected_new_balance < 0:
                raise UserError(_(
                    f"Paiement Mobile Money impossible !\n\n"
                    f"Solde disponible : {last_balance.nouveau_solde:,.2f} {self.currency_id.symbol}\n"
                    f"Montant du paiement : {self.amount:,.2f} {self.currency_id.symbol}\n\n"
                    f"Le solde deviendrait négatif ({projected_new_balance:,.2f} {self.currency_id.symbol})"
                ))

            # Mettre à jour la balance pour enregistrer le paiement automatiquement
            last_balance.action_update_totals_mobile()

        # ───────────────
        # Créer le paiement réel via la méthode originale
        # ───────────────
        return super(AccountPaymentRegister, self).action_create_payments()
