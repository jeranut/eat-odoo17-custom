from odoo import models, api

class PosSession(models.Model):
    _inherit = "pos.session"

    def action_pos_session_close(self, balancing_account=False, amount_to_balance=0, bank_payment_method_diffs=None):
        res = super(PosSession, self).action_pos_session_close(
            balancing_account, amount_to_balance, bank_payment_method_diffs
        )

        payments = self.order_ids.payment_ids
        totals = {}
        for p in payments:
            journal_name = p.payment_method_id.name.strip().lower()
            totals[journal_name] = totals.get(journal_name, 0) + p.amount

        for journal, amount in totals.items():
            if amount <= 0:
                continue

            reference = self.name
            libelle = "RECETTE RESTAURANT"
            company_id = self.company_id.id
            today = self.start_at.date()

            # CASH
            if journal == "espèces restaurant":
                balance = self.env["account.daily.balance"].search([
                    ("date", "=", today),
                    ("company_id", "=", company_id),
                ], limit=1)

                if not balance:
                    balance = self.env["account.daily.balance"].create({
                        "date": today,
                        "company_id": company_id,
                    })

                self.env["account.daily.balance.line"].create({
                    "balance_id": balance.id,
                    "reference": reference,
                    "libelle": libelle,
                    "payment": "cash",
                    "debit": 0.00,
                    "credit": amount,
                    "company_id": company_id,
                })

                balance.action_update_totals()

            # MOBILE
            if journal in ["mvola", "mobile", "orange money", "airtel money"]:
                balance_mobile = self.env["account.daily.balance.mobile"].search([
                    ("date", "=", today),
                    ("company_id", "=", company_id),
                ], limit=1)

                if not balance_mobile:
                    balance_mobile = self.env["account.daily.balance.mobile"].create({
                        "date": today,
                        "company_id": company_id,
                    })

                self.env["account.daily.balance.mobile.line"].create({
                    "balance_id": balance_mobile.id,
                    "reference": reference,
                    "libelle": libelle,
                    "payment": "mobile",
                    "debit": 0.0,
                    "credit": amount,
                    "regule_badge": "",
                    "company_id": company_id,
                })

                balance_mobile.action_update_totals_mobile()

        self.cash_register_total_entry_encoding = 0.0
        self.cash_register_balance_end_real = 0.0

        return res
