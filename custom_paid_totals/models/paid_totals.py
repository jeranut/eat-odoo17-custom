from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import timedelta
from datetime import datetime


class AccountDailyBalance(models.Model):
    _name = 'account.daily.balance'
    _description = 'Rapport journalier Débit/Crédit'
    _rec_name = 'date'
    _check_company_auto = True

    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, readonly=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    total_debit = fields.Float(string='Total Débit', readonly=True)
    total_credit = fields.Float(string='Total Crédit', readonly=True)
    ancien_solde = fields.Float(string='Ancien solde', readonly=True)
    nouveau_solde = fields.Float(string='Nouveau solde', readonly=True)
    show_lines = fields.Boolean(string='Afficher les lignes', default=False)
    line_ids = fields.One2many('account.daily.balance.line', 'balance_id', string='Détails')

    _sql_constraints = [
        ('unique_date_company', 'unique(date, company_id)', 'Une seule ligne est autorisée par jour et par société.')
    ]

    etat = fields.Selection(
        [('ouvert', 'OUVERT ✏️'), ('cloturer', '🔒 CLOTURER')],
        string="État",
        default='ouvert',
        readonly=True,
        store=True
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
        store=True,
        readonly=True
    )

    def action_cloturer(self):
        self.ensure_one()

        if self.etat == 'cloturer':
            raise UserError(_("Le journal est déjà clôturé."))

        # Mettre simplement la balance à l'état CLOTURER
        self.etat = 'cloturer'
        return True

    from odoo import models, fields, _
    from odoo.exceptions import UserError

    class CloturerBalanceWizard(models.TransientModel):
        _name = 'cloturer.balance.wizard'
        _description = 'Wizard Clôturer toutes les balances'

        def action_confirm_cloture(self):
            self.ensure_one()
            today = fields.Date.context_today(self)

            # ---------------------------------------------------------
            # Vérification : empêcher la clôture si une session POS est ouverte
            # ---------------------------------------------------------
            open_pos_session = self.env['pos.session'].search([
                ('state', 'in', ['opening_control', 'opened']),
                ('company_id', '=', self.env.company.id)
            ], limit=1)

            if open_pos_session:
                raise UserError(_(
                    "Impossible de clôturer les balances.\n\n"
                    "Une session Point de Vente est encore ouverte :\n"
                    f"- Session : {open_pos_session.name}\n"
                    f"- Utilisateur : {open_pos_session.user_id.name}\n\n"
                    "Veuillez d'abord fermer la session POS."
                ))

            # ---------------------------------------------------------
            # Clôturer toutes les balances classiques ouvertes du jour
            # ---------------------------------------------------------
            balances_classiques = self.env['account.daily.balance'].search([
                ('etat', '=', 'ouvert'),
                ('date', '<=', today),
                ('company_id', '=', self.env.company.id)  # filtrage par société
            ])
            for balance in balances_classiques:
                balance.etat = 'cloturer'

            # ---------------------------------------------------------
            # Clôturer toutes les balances Mobile Money ouvertes du jour
            # ---------------------------------------------------------
            balances_mobile = self.env['account.daily.balance.mobile'].search([
                ('etats', '=', 'ouvert'),
                ('date', '<=', today),
                ('company_id', '=', self.env.company.id)  # filtrage par société
            ])
            for mobile_balance in balances_mobile:
                mobile_balance.etats = 'cloturer'

            return {'type': 'ir.actions.act_window_close'}

    @api.model
    def default_get(self, fields_list):
        today = fields.Date.context_today(self)
        last_balance = self.search(
            [('company_id', '=', self.env.company.id)],
            order="date desc",
            limit=1
        )

        if last_balance:
            if last_balance.date == today:
                if last_balance.etat == 'cloturer':
                    raise UserError(_(
                        "Le journal du jour est déjà clôturé.\n"
                        "Veuillez créer une nouvelle balance après 00:00 h."
                    ))
                else:
                    raise UserError(_(
                        "L’exercice du jour a déjà été créé et est encore ouvert.\n"
                        "Veuillez utiliser la balance existante pour ajouter les opérations."
                    ))
            elif last_balance.date < today and last_balance.etat == 'ouvert':
                raise UserError(_(
                    "Le journal de la dernière balance n'est pas encore clôturé.\n"
                    "Veuillez d'abord clôturer le journal précédent."
                ))

        return super(AccountDailyBalance, self).default_get(fields_list)

    @api.model
    def create(self, vals):
        """Créer ou utiliser la balance du jour."""
        today = fields.Date.context_today(self)
        company_id = vals.get('company_id') or self.env.company.id

        # Vérifier si la balance d'aujourd'hui existe déjà
        today_balance = self.search([
            ('company_id', '=', company_id),
            ('date', '=', today)
        ], limit=1)

        if today_balance:
            # Retourner la balance existante pour ajouter les factures
            today_balance.action_update_totals()
            return today_balance

        # Récupérer la dernière balance pour cette société
        last_balance = self.search([
            ('company_id', '=', company_id)
        ], order='date desc', limit=1)

        if not last_balance or last_balance.etat == 'cloturer':
            # Créer une nouvelle balance
            vals['ancien_solde'] = last_balance.nouveau_solde if last_balance else 0.0
            vals['company_id'] = company_id
            return super().create(vals)

        # Si la dernière balance est ouverte → utiliser la balance existante
        last_balance.action_update_totals()
        return last_balance

    def action_update_totals(self):
        for record in self:
            today = fields.Date.context_today(self)

            if record.etat == 'cloturer':
                raise UserError(_("Journal déjà clôturé, impossible de recalculer."))

            # Récupérer la dernière balance existante pour la même société
            last_balance = self.search([
                ('company_id', '=', record.company_id.id),
                ('id', '!=', record.id)
            ], order='date desc', limit=1)

            if last_balance and last_balance.nouveau_solde is not None:
                record.ancien_solde = last_balance.nouveau_solde
            elif not record.ancien_solde or record.ancien_solde == 0:
                # Si aucune balance précédente, demander le solde initial
                return {
                    'type': 'ir.actions.act_window',
                    'name': _('Saisir le solde initial'),
                    'res_model': 'account.daily.balance.init.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {'default_balance_id': record.id},
                }

            total_credit = 0
            total_debit = 0

            # ───────────────
            # Factures clients CASH
            # ───────────────
            last_balance = self.search(
                [('company_id', '=', record.company_id.id)],
                order='date desc',
                limit=1
            )

            # Ajouter uniquement si la balance est ouverte
            # ───────────────
            # Factures clients CASH uniquement
            # ───────────────
            if record.etat == 'ouvert':
                # Dernière balance clôturée
                last_closed_balance = self.search([
                    ('company_id', '=', record.company_id.id),
                    ('etat', '=', 'cloturer')
                ], order='date desc', limit=1)

                start_date = last_closed_balance.date if last_closed_balance else record.date

                # Récupérer toutes les factures payées en cash depuis la dernière balance clôturée
                client_invoices = self.env['account.move'].search([
                    ('move_type', '=', 'out_invoice'),
                    ('payment_state', '=', 'paid'),
                    ('state', '=', 'posted'),
                    ('invoice_date', '>=', start_date),
                    ('company_id', '=', record.company_id.id),
                ])

                total_credit = 0
                for inv in client_invoices:
                    payments = inv._get_reconciled_payments()
                    payment = payments[0] if payments else False

                    if not payment or payment.journal_id.type != "cash":
                        continue

                    # Vérifier si la facture existe déjà dans n'importe quelle balance
                    existing = self.env['account.daily.balance.line'].search([
                        ('reference', '=', inv.name),
                        ('balance_id.company_id', '=', record.company_id.id),
                    ], limit=1)

                    if existing:
                        if existing.balance_id.etat == 'ouvert':
                            # Mise à jour si la facture est dans une balance ouverte
                            existing.write({
                                'balance_id': record.id,
                                'categorie': "FACTURE CLIENT",
                                'libelle': inv.journal_label,
                                'payment': "cash",
                                'debit': 0.0,
                                'credit': inv.amount_total,
                            })
                            total_credit += inv.amount_total
                        # Si la facture est dans une balance clôturée, on ne fait rien
                        continue

                    # Créer une nouvelle ligne si elle n'existe dans aucune balance
                    self.env['account.daily.balance.line'].create({
                        'balance_id': record.id,
                        'reference': inv.name,
                        'categorie': "FACTURE CLIENT",
                        'libelle': inv.journal_label,
                        'payment': "cash",
                        'debit': 0.0,
                        'credit': inv.amount_total,
                    })
                    total_credit += inv.amount_total

            # total_credit contient maintenant la somme des factures clients cash ajoutées ou mises à jour

            # Factures fournisseurs CASH uniquement (filtrées par company)
            if record.etat == 'ouvert':

                # Dernière balance clôturée
                last_closed_balance = self.search([
                    ('company_id', '=', record.company_id.id),
                    ('etat', '=', 'cloturer')
                ], order='date desc', limit=1)

                start_date = last_closed_balance.date if last_closed_balance else record.date

                # Récupérer toutes les factures fournisseurs payées en cash depuis la dernière balance clôturée
                vendor_bills = self.env['account.move'].search([
                    ('move_type', '=', 'in_invoice'),
                    ('payment_state', '=', 'paid'),
                    ('state', '=', 'posted'),
                    ('invoice_date', '>=', start_date),
                    ('company_id', '=', record.company_id.id),
                ])

                total_debit = 0
                for bill in vendor_bills:
                    payments = bill._get_reconciled_payments()
                    payment = payments[0] if payments else False

                    if not payment or payment.journal_id.type != "cash":
                        continue

                    # Vérifier si la facture existe déjà dans n'importe quelle balance
                    existing = self.env['account.daily.balance.line'].search([
                        ('reference', '=', bill.name),
                        ('balance_id.company_id', '=', record.company_id.id),
                    ], limit=1)

                    if existing:
                        if existing.balance_id.etat == 'ouvert':
                            # Mise à jour si la facture se trouve dans une balance ouverte
                            existing.write({
                                'balance_id': record.id,
                                'categorie': "FACTURE FOURNISSEUR",
                                'libelle': bill.journal_label,
                                'payment': "cash",
                                'debit': bill.amount_total,
                                'credit': 0.0,
                            })
                            total_debit += bill.amount_total
                        # Si elle est dans une balance clôturée → ne rien faire
                        continue

                    # Créer une nouvelle ligne si elle n'existe nulle part
                    self.env['account.daily.balance.line'].create({
                        'balance_id': record.id,
                        'reference': bill.name,
                        'categorie': "FACTURE FOURNISSEUR",
                        'libelle': bill.journal_label,
                        'payment': "cash",
                        'debit': bill.amount_total,
                        'credit': 0.0,
                    })
                    total_debit += bill.amount_total

            current_year = datetime.now().year

            # Dépenses RH (filtrées par company)
            # ───────────────
            # Dépenses RH
            # Dépenses RH
            if record.etat == 'ouvert':
                # Dernière balance clôturée
                last_closed_balance = self.search([
                    ('company_id', '=', record.company_id.id),
                    ('etat', '=', 'cloturer')
                ], order='date desc', limit=1)

                start_date = last_closed_balance.date if last_closed_balance else fields.Date.context_today(self)

                # Récupérer toutes les dépenses RH validées depuis la dernière balance clôturée
                hr_expenses = self.env['hr.expense'].search([
                    ('state', '=', 'done'),
                    ('company_id', '=', record.company_id.id),
                    ('date', '>=', start_date),
                ])

                total_debit_expenses = 0
                current_year = datetime.now().year
                last_line = self.env['account.daily.balance.line'].search([
                    ('reference', 'like', f"DEP/{current_year}/%"),
                    ('balance_id.company_id', '=', record.company_id.id)
                ], order="reference desc", limit=1)
                last_number = int(last_line.reference.split('/')[-1]) if last_line else 0

                for exp in hr_expenses:
                    # Vérifier si déjà dans une balance
                    existing = self.env['account.daily.balance.line'].search([
                        ('expense_id', '=', exp.id),
                        ('balance_id.company_id', '=', record.company_id.id),
                    ], limit=1)

                    if existing:
                        # Si déjà dans une balance ouverte → mise à jour
                        if existing.balance_id.etat == 'ouvert':
                            existing.write({
                                'balance_id': record.id,
                                'categorie': exp.product_id.name or "",
                                'libelle': f"Dépense - {exp.name}",
                                'payment': 'cash',
                                'debit': exp.total_amount,
                                'credit': 0.0,
                            })
                            total_debit_expenses += exp.total_amount
                        # Si dans une balance clôturée → ignorer
                        continue

                    # Sinon créer une nouvelle ligne
                    last_number += 1
                    new_ref = f"DEP/{current_year}/{last_number:05d}"
                    self.env['account.daily.balance.line'].create({
                        'balance_id': record.id,
                        'expense_id': exp.id,
                        'reference': new_ref,
                        'categorie': exp.product_id.name or "",
                        'libelle': f"Dépense - {exp.name}",
                        'payment': 'cash',
                        'debit': exp.total_amount,
                        'credit': 0.0,
                    })
                    total_debit_expenses += exp.total_amount

                record.total_debit += total_debit_expenses

                # Mettre à jour total_debit dans la balance
                record.total_debit += total_debit

            # recalcul des totaux (plus fiable : lire lignes de la balance courante)
            total_credit = sum(record.line_ids.mapped('credit'))
            total_debit = sum(record.line_ids.mapped('debit'))

            nouveau_solde = record.ancien_solde + (total_credit - total_debit)

            record.write({
                'total_debit': total_debit,
                'total_credit': total_credit,
                'nouveau_solde': nouveau_solde,
                'show_lines': True,
            })

    def action_update_totals_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Veuillez entrer la description de la recette et le montant'),
            'res_model': 'update.totals.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_balance_id': self.id},
        }


class UpdateTotalsWizard(models.TransientModel):
    _name = 'update.totals.wizard'
    _description = 'Wizard Mettre à jour les totaux'

    balance_id = fields.Many2one('account.daily.balance', string='Balance liée')
    recette = fields.Float(string="Montant RECETTE", required=True)
    libelle = fields.Char(string='Libellé', default='RECETTE')

    def action_confirm(self):
        self.ensure_one()

        if not self.balance_id:
            raise UserError(_("Aucune balance n'est liée au wizard."))

        if self.recette <= 0:
            raise UserError(_("Veuillez saisir un montant supérieur à 0."))

        from datetime import datetime
        current_year = datetime.now().year

        # Filtrer les références REC pour la même company que la balance
        last_line = self.env['account.daily.balance.line'].search(
            [
                ('reference', 'like', f"REC/{current_year}/%"),
                ('company_id', '=', self.balance_id.company_id.id)
            ],
            order="reference desc",
            limit=1
        )

        if last_line:
            last_number = int(last_line.reference.split('/')[-1])
            new_number = last_number + 1
        else:
            new_number = 1

        new_ref = "REC/%s/%05d" % (current_year, new_number)

        self.env['account.daily.balance.line'].create({
            'balance_id': self.balance_id.id,
            'reference': new_ref,
            'categorie': "ENCAISSEMENT MANUEL",
            'libelle': self.libelle,
            'payment': 'cash',
            'debit': 0.0,
            'credit': self.recette,
        })

        self.balance_id.action_update_totals()

        return {'type': 'ir.actions.act_window_close'}


class AccountDailyBalanceLine(models.Model):
    _name = 'account.daily.balance.line'
    _description = 'Ligne du rapport journalier Débit/Crédit'
    _order = 'id asc'
    _rec_name = 'reference'

    balance_id = fields.Many2one('account.daily.balance', string='Balance', ondelete='cascade')
    reference = fields.Char(string='REFERENCE FACTURE')
    libelle = fields.Char(string='LIBELLE')
    payment = fields.Char(string='PAYMENT')
    debit = fields.Float(string='DEBIT')
    credit = fields.Float(string='CREDIT')
    regule_badge = fields.Char(string="Badge", compute="_compute_regule_badge", store=True)
    origin_line_id = fields.Many2one(
        'account.daily.balance.line',
        string="Ligne d'origine",
        readonly=True
    )
    expense_id = fields.Many2one(
        'hr.expense',
        string='Dépense RH',
        readonly=True,
    )
    categorie = fields.Char(string="Catégorie")
    # company_id lié à la balance pour compatibilité multientreprise
    company_id = fields.Many2one('res.company', related='balance_id.company_id', store=True, readonly=True)

    @api.depends('balance_id.line_ids.origin_line_id', 'balance_id.line_ids.libelle')
    def _compute_regule_badge(self):
        for line in self:
            # S'il s'agit d'une ligne REGULE elle-même → pas de badge
            if line.libelle == 'REGULE':
                line.regule_badge = ''
                continue

            # Compter les régules liées à cette ligne
            regulated = self.env['account.daily.balance.line'].search_count([
                ('origin_line_id', '=', line.id),
                ('libelle', '=', 'REGULE'),
                ('company_id', '=', line.company_id.id),
            ])

            line.regule_badge = "REGULE" if regulated >= 1 else ""


class AccountDailyBalanceInitWizard(models.TransientModel):
    _name = 'account.daily.balance.init.wizard'
    _description = 'Wizard pour initialiser le solde'

    balance_id = fields.Many2one('account.daily.balance', string='Balance liée')
    initial_balance = fields.Float(string='Solde initial', required=True)

    def action_confirm(self):
        if not self.balance_id:
            raise UserError(_("Aucune balance liée au wizard."))

        self.balance_id.ancien_solde = self.initial_balance
        self.balance_id.action_update_totals()
        return {'type': 'ir.actions.act_window_close'}


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    journal_type = fields.Char(string="Journal Type", readonly=True)

    @api.onchange('journal_id')
    def _onchange_journal_type(self):
        self.journal_type = self.journal_id.type if self.journal_id else ""

    def action_create_payments(self):
        payments = super(AccountPaymentRegister, self).action_create_payments()

        today = fields.Date.context_today(self)

        # CASH
        if self.journal_id.type == "cash":
            balance = self.env['account.daily.balance'].search([
                ('date', '=', today),
                ('company_id', '=', self.env.company.id),
            ], limit=1)
            if not balance:
                balance = self.env['account.daily.balance'].create({
                    'date': today,
                    'company_id': self.env.company.id
                })
            balance.action_update_totals()

        # MOBILE MONEY
        if self.journal_id.type == "bank" and self.journal_id.name.lower() == "mobile money":
            balance_mobile = self.env['account.daily.balance.mobile'].search([
                ('date', '=', today),
                ('company_id', '=', self.env.company.id),
            ], limit=1)
            if not balance_mobile:
                balance_mobile = self.env['account.daily.balance.mobile'].create({
                    'date': today,
                    'company_id': self.env.company.id
                })
            balance_mobile.action_update_totals_mobile()

        return payments


class HrExpenseSheet(models.Model):
    _inherit = 'hr.expense.sheet'

    def action_sheet_move_create(self):
        res = super(HrExpenseSheet, self).action_sheet_move_create()

        for sheet in self:
            company_id = sheet.company_id.id or self.env.company.id
            today = fields.Date.context_today(self)

            # Utiliser la logique de création ou récupération de la balance
            balance_model = self.env['account.daily.balance']
            balance = balance_model.search([
                ('company_id', '=', company_id),
                ('date', '=', today)
            ], limit=1)

            if balance:
                # Si balance du jour existe déjà
                balance.action_update_totals()
            else:
                # Récupérer la dernière balance pour cette société
                last_balance = balance_model.search([
                    ('company_id', '=', company_id)
                ], order='date desc', limit=1)

                if not last_balance or last_balance.etat == 'cloturer':
                    vals = {
                        'date': today,
                        'company_id': company_id,
                        'ancien_solde': last_balance.nouveau_solde if last_balance else 0.0
                    }
                    balance = balance_model.create(vals)
                else:
                    # Si la dernière balance est ouverte → utiliser la balance existante
                    balance = last_balance

                balance.action_update_totals()

        return res


# ------------------------------------------------------
# 🔹 Wizard Régulation
# ------------------------------------------------------
class ReguleWizard(models.TransientModel):
    _name = 'regule.wizard'
    _description = "Wizard Regule"

    balance_id = fields.Many2one('account.daily.balance', string="Balance", required=True)
    reference_id = fields.Many2one(
        'account.daily.balance.line',
        string="Référence",
        required=True
    )
    montant = fields.Float(string="Montant", readonly=True, store=True)
    company_id = fields.Many2one('res.company', string="Société",
                                 related='balance_id.company_id', store=True, readonly=True)

    # ───────────────────────────────────────────────
    # Filtrer référence pour n'afficher que non régulés
    # ───────────────────────────────────────────────
    @api.onchange('balance_id')
    def _onchange_balance_id(self):
        if not self.balance_id:
            return {}

        # References déjà régulées
        reguled_refs = self.balance_id.line_ids.filtered(
            lambda l: l.libelle == 'REGULE'
        ).mapped('reference')

        return {
            'domain': {
                'reference_id': [
                    ('balance_id', '=', self.balance_id.id),
                    ('company_id', '=', self.balance_id.company_id.id),
                    ('libelle', '!=', 'REGULE'),
                    ('reference', 'not in', reguled_refs)
                ]
            }
        }

    # Remplissage automatique du montant
    @api.onchange('reference_id')
    def _onchange_reference_id(self):
        if self.reference_id:
            self.montant = abs(self.reference_id.debit or self.reference_id.credit or 0)

    # ───────────────────────────────────────────────
    # CONFIRMATION REGULE
    # ───────────────────────────────────────────────
    from odoo import fields, _
    from odoo.exceptions import UserError

    def action_confirm_regule(self):
        self.ensure_one()

        # Interdire régulation de REGULE
        if self.reference_id.libelle == 'REGULE':
            raise UserError(_("Impossible de réguler une ligne REGULE."))

        # Interdire régule d'un jour passé
        if self.balance_id.etat == 'cloturer':
            raise UserError(_("Journal déjà clôturé, régulation impossible."))

        # Compter toutes les régules liées à cette référence
        regule_count = self.env['account.daily.balance.line'].search_count([
            ('balance_id', '=', self.balance_id.id),
            ('reference', '=', self.reference_id.reference),
            ('libelle', '=', 'REGULE'),
            ('company_id', '=', self.balance_id.company_id.id),
        ])

        if regule_count >= 1:
            raise UserError(_("Cette référence a déjà été régulée, opération impossible."))

        montant = abs(self.reference_id.debit or self.reference_id.credit or 0)

        # Déterminer direction mouvement
        if self.reference_id.credit > 0:
            debit = montant
            credit = 0.0
        else:
            debit = 0.0
            credit = montant

        # Création ligne REGULE (une seule)
        self.env['account.daily.balance.line'].create({
            'balance_id': self.balance_id.id,
            'reference': self.reference_id.reference,
            'libelle': 'REGULE',
            'payment': self.reference_id.payment,
            'debit': debit,
            'credit': credit,
            'origin_line_id': self.reference_id.id,
        })

        # Annulation facture ou paiement ou dépense
        invoice = self.env['account.move'].search([
            ('name', '=', self.reference_id.reference),
            ('company_id', '=', self.balance_id.company_id.id),
        ], limit=1)

        if invoice and invoice.state not in ('cancel'):
            invoice.button_cancel()
        else:
            payment = self.env['account.payment'].search([
                ('name', '=', self.reference_id.reference),
                ('company_id', '=', self.balance_id.company_id.id)
            ], limit=1)
            if payment and payment.state != 'cancelled':
                payment.action_cancel()

            expense = self.env['hr.expense.sheet'].search([
                ('name', '=', self.reference_id.reference),
                ('company_id', '=', self.balance_id.company_id.id)
            ], limit=1)
            if expense and expense.payment_state != 'reversed':
                expense.write({'payment_state': 'reversed'})

        # Mise à jour totaux balance
        self.balance_id.action_update_totals()

        return {'type': 'ir.actions.act_window_close'}
