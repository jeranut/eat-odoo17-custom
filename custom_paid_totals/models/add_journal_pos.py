from odoo import models, api

class PosSession(models.Model):
    _inherit = "pos.session"

    def action_pos_session_close(self, balancing_account=False, amount_to_balance=0, bank_payment_method_diffs=None):
        res = super(PosSession, self).action_pos_session_close(
            balancing_account, amount_to_balance, bank_payment_method_diffs
        )

        payments = self.order_ids.payment_ids
        totals = {}
        mobile_totals = {}
        for p in payments:
            journal_name = p.payment_method_id.name.strip().lower()
            totals[journal_name] = totals.get(journal_name, 0) + p.amount
            operator = self.env["mobile.money.operator"].search([
                ("journal_id", "=", p.payment_method_id.journal_id.id),
                ("company_id", "=", self.company_id.id),
                ("active", "=", True),
            ], limit=1)
            if operator:
                mobile_totals[operator] = mobile_totals.get(operator, 0) + p.amount

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
                    'categorie': "RECETTE POS CASH",
                    "libelle": libelle,
                    "payment": "cash",
                    "debit": 0.00,
                    "credit": amount,
                    "company_id": company_id,
                })

                balance.action_update_totals()

        for operator, amount in mobile_totals.items():
            if amount <= 0:
                continue

            balance_mobile = self.env["account.daily.balance.mobile"].search([
                ("date", "=", self.start_at.date()),
                ("company_id", "=", self.company_id.id),
                ("operator_id", "=", operator.id),
            ], limit=1)

            if not balance_mobile:
                balance_mobile = self.env["account.daily.balance.mobile"].create({
                    "date": self.start_at.date(),
                    "company_id": self.company_id.id,
                    "operator_id": operator.id,
                })

            self.env["account.daily.balance.mobile.line"].create({
                "balance_id": balance_mobile.id,
                "reference": self.name,
                'categorie': "RECETTE POS MOBILE",
                "libelle": "RECETTE RESTAURANT",
                "payment": "mobile",
                "debit": 0.0,
                "credit": amount,
                "regule_badge": "",
                "company_id": self.company_id.id,
            })

            balance_mobile.action_update_totals_mobile()

        self.cash_register_total_entry_encoding = 0.0
        self.cash_register_balance_end_real = 0.0

        return res
