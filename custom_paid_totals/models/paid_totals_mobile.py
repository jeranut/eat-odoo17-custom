# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import timedelta, datetime


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    # Ajout du type mobile
    type = fields.Selection(
        selection_add=[('mobile', 'Mobile')],
        ondelete={'mobile': 'cascade'}
    )

    @api.model
    def create(self, vals):
        journal = super(AccountJournal, self).create(vals)

        if vals.get('type') == 'mobile':
            manual_out = self.env.ref('account.account_payment_method_manual_out', raise_if_not_found=False)
            manual_in = self.env.ref('account.account_payment_method_manual_in', raise_if_not_found=False)

            if manual_out:
                journal.payment_method_line_ids.create({
                    'journal_id': journal.id,
                    'payment_method_id': manual_out.id,
                    'payment_type': 'outbound'
                })

            if manual_in:
                journal.payment_method_line_ids.create({
                    'journal_id': journal.id,
                    'payment_method_id': manual_in.id,
                    'payment_type': 'inbound'
                })

        return journal


# -------------------------
# Journal Mobile principal
# -------------------------
class AccountDailyBalanceMobile(models.Model):
    _name = 'account.daily.balance.mobile'
    _description = 'Rapport journalier Débit/Crédit Mobile Money'
    _rec_name = 'date'

    date = fields.Date(string='Date', required=True, default=fields.Date.context_today, readonly=True)
    total_debit = fields.Float(string='Total Débit', readonly=True)
    total_credit = fields.Float(string='Total Crédit', readonly=True)
    ancien_solde = fields.Float(string='Ancien solde', readonly=True)
    nouveau_solde = fields.Float(string='Nouveau solde', readonly=True)
    show_lines = fields.Boolean(string='Afficher les lignes', default=False)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company.id
    )

    line_ids = fields.One2many('account.daily.balance.mobile.line', 'balance_id', string='Détails')

    _sql_constraints = [
        ('unique_date_mobile', 'unique(date, company_id)', 'Une seule ligne Mobile Money par jour et par entreprise.')
    ]
    etats = fields.Selection(
        [('ouvert', 'OUVERT ✏️'), ('cloturer', '🔒 CLOTURER')],
        string="État",
        default='ouvert',
        readonly=True
    )

    def action_open_retrait_wizard(self):
        return {
            "name": _("Veuillez entrer la description et la référence de la transaction et le montant"),
            "type": "ir.actions.act_window",
            "res_model": "retrait.wizard",
            "view_mode": "form",
            "target": "new",
        }

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
                if last_balance.etats == 'cloturer':
                    raise UserError(_(
                        "Le journal Mobile du jour est déjà clôturé.\n"
                        "Veuillez créer une nouvelle balance après 00:00 h."
                    ))
                else:
                    raise UserError(_(
                        "L’exercice mobile du jour a déjà été créé et est encore ouvert.\n"
                        "Veuillez utiliser la balance existante pour ajouter les opérations."
                    ))
            elif last_balance.date < today and last_balance.etats == 'ouvert':
                raise UserError(_(
                    "Le journal Mobile de la dernière balance n'est pas encore clôturé.\n"
                    "Veuillez d'abord clôturer le journal précédent."
                ))

        return super(AccountDailyBalanceMobile, self).default_get(fields_list)

    @api.model
    def create(self, vals):
        """Créer ou réutiliser la balance Mobile Money du jour."""
        today = fields.Date.context_today(self)
        company_id = vals.get('company_id') or self.env.company.id

        # 1) Vérifier si une balance du jour existe déjà
        today_balance = self.search([
            ('company_id', '=', company_id),
            ('date', '=', today)
        ], limit=1)

        if today_balance:
            # Si elle existe : on met à jour et on la renvoie
            today_balance.action_update_totals_mobile()
            return today_balance

        # 2) Récupérer la dernière balance
        last_balance = self.search([
            ('company_id', '=', company_id)
        ], order="date desc", limit=1)

        # 3) Déterminer la date fournie ou utiliser aujourd'hui
        date_record = vals.get('date')
        if date_record:
            if isinstance(date_record, str):
                date_record = fields.Date.from_string(date_record)
        else:
            date_record = today
            vals['date'] = today

        # 4) Cas où aucune balance précédente n'existe ou la dernière est déjà clôturée
        if not last_balance or last_balance.etats == 'cloturer':
            # Ancien solde = dernier nouveau solde, sinon 0
            vals['ancien_solde'] = last_balance.nouveau_solde if last_balance else 0.0
            vals['company_id'] = company_id
            return super().create(vals)

        # 5) Si la dernière balance est ouverte mais date < date du jour → on ne crée pas
        if last_balance.date < date_record and last_balance.etats == 'ouvert':
            # On utilise la balance ouverte existante
            last_balance.action_update_totals_mobile()
            return last_balance

        # 6) Si la dernière balance est d'hier et clôturée → nouvelle balance avec nouvel ancien_solde
        if last_balance.date == date_record - timedelta(days=1):
            vals['ancien_solde'] = last_balance.nouveau_solde
            vals['company_id'] = company_id
            return super().create(vals)

        # 7) Cas général (nouvelle date sans dépendance)
        vals['ancien_solde'] = last_balance.nouveau_solde
        vals['company_id'] = company_id
        return super().create(vals)

    def action_update_totals_mobile(self):
        for record in self:
            # Vérifier que le journal est ouvert
            if record.etats != 'ouvert':
                raise UserError(_("Journal déjà clôturé, impossible de recalculer."))

            # Ancien solde depuis la dernière balance clôturée
            last_closed_balance = self.search([
                ('company_id', '=', record.company_id.id),
                ('etats', '=', 'cloturer')
            ], order='date desc', limit=1)
            record.ancien_solde = last_closed_balance.nouveau_solde if last_closed_balance else 0.0

            start_date = last_closed_balance.date + timedelta(days=1) if last_closed_balance else record.date

            # Précharger toutes les lignes de la balance en cours
            existing_lines = self.env['account.daily.balance.mobile.line'].search([
                ('balance_id', '=', record.id)
            ])
            existing_refs = {line.reference: line for line in existing_lines}

            # Précharger toutes les références des lignes dans les balances clôturées pour les ignorer
            closed_lines = self.env['account.daily.balance.mobile.line'].search([
                ('balance_id.etats', '=', 'cloturer'),
                ('company_id', '=', record.company_id.id)
            ])
            closed_refs = set(closed_lines.mapped('reference'))

            batch_vals = []

            # ───────────────
            # Factures clients Mobile Money
            # ───────────────
            client_invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('payment_state', '=', 'paid'),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', start_date),
                ('company_id', '=', record.company_id.id),
            ])

            for inv in client_invoices:
                payments = inv._get_reconciled_payments()
                payment = payments[0] if payments else False
                if not payment or not (
                        payment.journal_id.type == "bank" and
                        payment.journal_id.name and
                        payment.journal_id.name.strip().lower() == "mobile money"
                ):
                    continue

                # Ignorer si déjà dans une balance clôturée
                if inv.name in closed_refs:
                    continue

                # Mettre à jour si déjà dans la balance en cours
                if inv.name in existing_refs:
                    existing_line = existing_refs[inv.name]
                    existing_line.write({
                        'categorie': "FACTURE CLIENT",
                        'libelle': getattr(inv, 'journal_label', inv.name),
                        'payment': "mobile",
                        'debit': 0.0,
                        'credit': inv.amount_total,
                    })
                    continue

                # Nouvelle ligne à créer
                batch_vals.append({
                    'balance_id': record.id,
                    'categorie': "FACTURE CLIENT",
                    'reference': inv.name,
                    'libelle': getattr(inv, 'journal_label', inv.name),
                    'payment': "mobile",
                    'debit': 0.0,
                    'credit': inv.amount_total,
                    'company_id': record.company_id.id,
                })

            # ───────────────
            # Factures fournisseurs Mobile Money
            # ───────────────
            vendor_bills = self.env['account.move'].search([
                ('move_type', '=', 'in_invoice'),
                ('payment_state', '=', 'paid'),
                ('state', '=', 'posted'),
                ('invoice_date', '>=', start_date),
                ('company_id', '=', record.company_id.id),
            ])

            for bill in vendor_bills:
                payments = bill._get_reconciled_payments()
                payment = payments[0] if payments else False
                if not payment or not (
                        payment.journal_id.type == "bank" and
                        payment.journal_id.name and
                        payment.journal_id.name.strip().lower() == "mobile money"
                ):
                    continue

                # Ignorer si déjà dans une balance clôturée
                if bill.name in closed_refs:
                    continue

                # Mettre à jour si déjà dans la balance en cours
                if bill.name in existing_refs:
                    existing_line = existing_refs[bill.name]
                    existing_line.write({
                        'categorie': "FACTURE FOURNISSEUR",
                        'libelle': getattr(bill, 'journal_label', bill.name),
                        'payment': "mobile",
                        'debit': bill.amount_total,
                        'credit': 0.0,
                    })
                    continue

                # Nouvelle ligne à créer
                batch_vals.append({
                    'balance_id': record.id,
                    'categorie': "FACTURE FOURNISSEUR",
                    'reference': bill.name,
                    'libelle': getattr(bill, 'journal_label', bill.name),
                    'payment': "mobile",
                    'debit': bill.amount_total,
                    'credit': 0.0,
                    'company_id': record.company_id.id,
                })

            # Créer toutes les nouvelles lignes en batch
            if batch_vals:
                self.env['account.daily.balance.mobile.line'].create(batch_vals)

            # ───────────────
            # Recalcul des totaux
            # ───────────────
            total_credit = sum(record.line_ids.mapped('credit'))
            total_debit = sum(record.line_ids.mapped('debit'))
            record.nouveau_solde = record.ancien_solde + (total_credit - total_debit)

            # Mise à jour des totaux dans la balance
            record.write({
                'total_credit': total_credit,
                'total_debit': total_debit,
                'show_lines': True,
            })

    def action_update_totals_wizard_mobile(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Veuillez entrer la description et la référence de la recette et le montant'),
            'res_model': 'update.totals.mobile.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_balance_id': self.id},
        }

    def action_init_solde_mobile(self):
        """Ouvre le wizard d'initialisation du solde pour ce journal mobile."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Saisir le solde initial Mobile Money'),
            'res_model': 'account.daily.balance.mobile.init.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_balance_id': self.id},
        }


# -------------------------
# Wizard REC Mobile
# -------------------------
class UpdateTotalsMobileWizard(models.TransientModel):
    _name = 'update.totals.mobile.wizard'
    _description = 'Wizard Mettre à jour les totaux Mobile'

    balance_id = fields.Many2one('account.daily.balance.mobile', string='Balance liée')
    recette = fields.Float(string="Montant RECETTE", required=True)
    libelle = fields.Char(string='Libellé', default='RECETTE')
    def action_confirm(self):
        self.ensure_one()
        if not self.balance_id:
            raise UserError(_("Aucune balance n'est liée au wizard."))

        if self.recette <= 0:
            raise UserError(_("Veuillez saisir un montant supérieur à 0."))

        current_year = datetime.now().year

        last_line = self.env['account.daily.balance.mobile.line'].search([
            ('reference', 'like', f"REC-MM/{current_year}/%"),
            ('company_id', '=', self.balance_id.company_id.id),
        ], order="reference desc", limit=1)

        if last_line:
            try:
                last_number = int(last_line.reference.split('/')[-1])
            except Exception:
                last_number = 0
            new_number = last_number + 1
        else:
            new_number = 1

        new_ref = "REC-MM/%s/%05d" % (current_year, new_number)

        self.env['account.daily.balance.mobile.line'].create({
            'balance_id': self.balance_id.id,
            'reference': new_ref,
            'categorie': "DEPOT",
            'libelle': self.libelle,
            'payment': 'mobile',
            'debit': 0.0,
            'credit': self.recette,
        })

        # Recalculer
        self.balance_id.action_update_totals_mobile()
        return {'type': 'ir.actions.act_window_close'}


# -------------------------
# Lignes Mobile
# -------------------------
class AccountDailyBalanceMobileLine(models.Model):
    _name = 'account.daily.balance.mobile.line'
    _description = 'Ligne du journal Mobile Money'
    _order = 'id asc'
    _rec_name = 'reference'

    balance_id = fields.Many2one('account.daily.balance.mobile', string='Balance', ondelete='cascade')
    reference = fields.Char(string='REFERENCE FACTURE')
    libelle = fields.Char(string='LIBELLE')
    payment = fields.Char(string='PAYMENT')
    debit = fields.Float(string='DEBIT')
    credit = fields.Float(string='CREDIT')
    regule_badge = fields.Char(string="Badge", compute="_compute_regule_badge", store=True)
    origin_line_id = fields.Many2one('account.daily.balance.mobile.line', string="Ligne d'origine", readonly=True)
    categorie = fields.Char(string="Catégorie")
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company.id,
        required=True
    )

    @api.depends('balance_id.line_ids.origin_line_id', 'balance_id.line_ids.libelle')
    def _compute_regule_badge(self):
        for line in self:
            if line.libelle == 'REGULE':
                line.regule_badge = ''
                continue

            regulated = self.env['account.daily.balance.mobile.line'].search_count([
                ('origin_line_id', '=', line.id),
                ('libelle', '=', 'REGULE'),
                ('company_id', '=', line.company_id.id),
            ])
            line.regule_badge = "REGULE" if regulated >= 1 else ""


# -------------------------
# Init wizard Mobile
# -------------------------
class AccountDailyBalanceMobileInitWizard(models.TransientModel):
    _name = 'account.daily.balance.mobile.init.wizard'
    _description = 'Wizard pour initialiser le solde Mobile'

    balance_id = fields.Many2one('account.daily.balance.mobile', string='Balance liée')
    initial_balance = fields.Float(string='Solde initial', required=True)

    def action_confirm(self):
        if not self.balance_id:
            raise UserError(_("Aucune balance liée au wizard."))
        self.balance_id.ancien_solde = self.initial_balance
        self.balance_id.action_update_totals_mobile()
        return {'type': 'ir.actions.act_window_close'}


# -------------------------
# Wizard Régule Mobile
# -------------------------
class ReguleMobileWizard(models.TransientModel):
    _name = 'regule.mobile.wizard'
    _description = "Wizard Regule Mobile"

    balance_id = fields.Many2one('account.daily.balance.mobile', string="Balance", required=True)
    reference_id = fields.Many2one('account.daily.balance.mobile.line', string="Référence", required=True)
    montant = fields.Float(string="Montant", readonly=True, store=True)
    company_id = fields.Many2one('res.company', string="Société",
                                 related='balance_id.company_id', store=True, readonly=True)

    @api.onchange('balance_id')
    def _onchange_balance_id(self):
        if not self.balance_id:
            return {}
        reguled_refs = self.balance_id.line_ids.filtered(lambda l: l.libelle == 'REGULE').mapped('reference')
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

    @api.onchange('reference_id')
    def _onchange_reference_id(self):
        if self.reference_id:
            self.montant = abs(self.reference_id.debit or self.reference_id.credit or 0)

    def action_confirm_regule(self):
        self.ensure_one()
        if self.reference_id.libelle == 'REGULE':
            raise UserError(_("Impossible de réguler une ligne REGULE."))

        if self.balance_id.etats == 'cloturer':
            raise UserError(_("Journal déjà clôturé, régulation impossible."))

        regule_count = self.env['account.daily.balance.mobile.line'].search_count([
            ('balance_id', '=', self.balance_id.id),
            ('reference', '=', self.reference_id.reference),
            ('libelle', '=', 'REGULE'),
            ('company_id', '=', self.balance_id.company_id.id),
        ])
        if regule_count >= 1:
            raise UserError(_("Cette référence a déjà été régulée, opération impossible."))

        montant = abs(self.reference_id.debit or self.reference_id.credit or 0)
        if self.reference_id.credit > 0:
            debit = montant
            credit = 0.0
        else:
            debit = 0.0
            credit = montant

        # Création ligne REGULE
        self.env['account.daily.balance.mobile.line'].create({
            'balance_id': self.balance_id.id,
            'reference': self.reference_id.reference,
            'libelle': 'REGULE',
            'payment': self.reference_id.payment,
            'debit': debit,
            'credit': credit,
            'origin_line_id': self.reference_id.id,
        })

        # Annulation facture/paiement/dépense si trouvée
        invoice = self.env['account.move'].search([
            ('name', '=', self.reference_id.reference),
            ('company_id', '=', self.balance_id.company_id.id),
        ], limit=1)
        if invoice and invoice.state not in ('cancel'):
            try:
                invoice.button_cancel()
            except Exception:
                pass
        else:
            payment = self.env['account.payment'].search([
                ('name', '=', self.reference_id.reference),
                ('company_id', '=', self.balance_id.company_id.id),
            ], limit=1)
            if payment and payment.state != 'cancelled':
                try:
                    payment.action_cancel()
                except Exception:
                    pass

            expense = self.env['hr.expense.sheet'].search([
                ('name', '=', self.reference_id.reference),
                ('company_id', '=', self.balance_id.company_id.id)
            ], limit=1)
            if expense and expense.payment_state != 'reversed':
                expense.write({'payment_state': 'reversed'})

        # Mise à jour totaux
        self.balance_id.action_update_totals_mobile()
        return {'type': 'ir.actions.act_window_close'}


class RetraitWizard(models.TransientModel):
    _name = "retrait.wizard"
    _description = "Wizard Retrait Mobile Money"

    reference = fields.Char(string="Référence", readonly=True)
    motif = fields.Char(string="Motif", required=True)
    montant = fields.Float(string="Montant", required=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company
    )

    def _generate_reference(self):
        current_year = datetime.now().year
        prefix = f"RET/{current_year}/"

        last_line = self.env["account.daily.balance.mobile.line"].search(
            [("reference", "like", prefix + "%"), ("company_id", "=", self.env.company.id)],
            order="id desc",
            limit=1
        )

        if last_line:
            last_number = int(last_line.reference.split("/")[-1])
            new_number = last_number + 1
        else:
            new_number = 1

        return prefix + str(new_number).zfill(5)

    @api.model
    def default_get(self, fields):
        res = super().default_get(fields)
        res["reference"] = self._generate_reference()
        return res

    def action_confirm_retrait(self):
        today = fields.Date.today()

        # On récupère la dernière balance, ouverte ou clôturée
        last_balance = self.env["account.daily.balance.mobile"].search(
            [('company_id', '=', self.env.company.id)],
            order='date desc',
            limit=1
        )

        if not last_balance:
            raise UserError(_("Aucune balance Mobile Money n'existe. Veuillez en créer une."))

        # 🔵 SI la dernière balance est OUVERTE → on travaille dessus
        if last_balance.etats == 'ouvert':
            balance_obj = last_balance

        else:
            # 🔵 SI elle est CLOTURÉE → on crée une nouvelle balance pour aujourd’hui
            balance_obj = self.env["account.daily.balance.mobile"].create({
                'date': today,
                'company_id': self.env.company.id,
                'ancien_solde': last_balance.nouveau_solde,
            })

        # Vérification du solde
        if self.montant > balance_obj.nouveau_solde:
            raise UserError(_("Solde mobile money insuffisant."))

        # Enregistrement de la ligne de retrait
        line_vals = {
            "balance_id": balance_obj.id,
            "reference": self.reference,
            "libelle": self.motif,
            "categorie": "RETRAIT",
            "payment": "mobile",
            "debit": self.montant,
            "credit": 0.0,
            "regule_badge": "",
            "company_id": balance_obj.company_id.id,
        }

        self.env["account.daily.balance.mobile.line"].create(line_vals)

        # Mise à jour du solde
        balance_obj.action_update_totals_mobile()

        return {"type": "ir.actions.act_window_close"}
