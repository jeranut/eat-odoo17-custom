from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero


ADVANCE_LABEL = "AVANCE SUR PAYMENT"
SG_EAT_DEPOT_COMPANY_NAME = "SG-EAT DEPOT"
ADVANCE_COMPANY_ERROR = "La fonctionnalité Avance sur Payment est disponible uniquement pour SG-EAT DEPOT."


class CustomPaidAdvancePayment(models.Model):
    _name = 'custom.paid.advance.payment'
    _description = "Avance sur Payment"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'payment_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Référence',
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _('New'),
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Société',
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Client',
        required=True,
        tracking=True,
        check_company=True,
    )
    amount = fields.Monetary(string="Montant du payment", required=True, tracking=True)
    used_amount = fields.Monetary(string='Montant utilisé', tracking=True)
    residual_amount = fields.Monetary(
        string='Solde disponible',
        compute='_compute_residual_amount',
        store=True,
        tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Devise',
        required=True,
        default=lambda self: self.env.company.currency_id,
        tracking=True,
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Journal à utiliser',
        required=True,
        domain="[('company_id', '=', company_id), ('type', 'in', ('cash', 'bank'))]",
        check_company=True,
        tracking=True,
    )
    payment_date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    move_id = fields.Many2one(
        'account.move',
        string='Mouvement comptable généré',
        readonly=True,
        check_company=True,
    )
    invoice_ids = fields.Many2many(
        'account.move',
        'custom_paid_advance_payment_invoice_rel',
        'advance_id',
        'invoice_id',
        string="Factures où l'avance est utilisée",
        readonly=True,
        check_company=True,
    )
    state = fields.Selection(
        [
            ('draft', 'Brouillon'),
            ('paid', 'Payé'),
            ('partial', 'Partiellement utilisé'),
            ('used', 'Utilisé'),
            ('cancelled', 'Annulé'),
        ],
        string='État',
        default='draft',
        required=True,
        tracking=True,
    )
    note = fields.Text(string='Note')

    def _is_sg_eat_depot_company(self, company=None):
        company = company or self.company_id or self.env.company
        return company.name == SG_EAT_DEPOT_COMPANY_NAME

    def _check_sg_eat_depot_company(self):
        for advance in self:
            if not advance._is_sg_eat_depot_company(advance.company_id):
                raise UserError(_(ADVANCE_COMPANY_ERROR))

    def _get_advance_label(self):
        self.ensure_one()
        partner_name = self.partner_id.display_name or ""
        return "%s - %s" % (ADVANCE_LABEL, partner_name)

    @api.depends('amount', 'used_amount')
    def _compute_residual_amount(self):
        for advance in self:
            advance.residual_amount = advance.amount - advance.used_amount

    @api.onchange('company_id')
    def _onchange_company_id(self):
        for advance in self:
            advance.currency_id = advance.company_id.currency_id
            if advance.journal_id.company_id != advance.company_id:
                advance.journal_id = False

    @api.constrains('amount', 'used_amount')
    def _check_amounts(self):
        for advance in self:
            if advance.amount <= 0:
                raise ValidationError(_("Le montant de l'avance doit être supérieur à 0."))
            if advance.used_amount < 0:
                raise ValidationError(_("Le montant utilisé ne peut pas être négatif."))
            if float_compare(
                advance.used_amount,
                advance.amount,
                precision_rounding=advance.currency_id.rounding,
            ) > 0:
                raise ValidationError(_("Le montant utilisé ne peut pas dépasser le montant de l'avance."))

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env['ir.sequence'].sudo()
        for vals in vals_list:
            company = self.env['res.company'].browse(vals.get('company_id') or self.env.company.id)
            if not self._is_sg_eat_depot_company(company):
                raise UserError(_(ADVANCE_COMPANY_ERROR))
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = sequence.next_by_code('custom.paid.advance.payment') or _('New')
            if vals.get('company_id') and not vals.get('currency_id'):
                vals['currency_id'] = self.env['res.company'].browse(vals['company_id']).currency_id.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('company_id'):
            company = self.env['res.company'].browse(vals['company_id'])
            if not self._is_sg_eat_depot_company(company):
                raise UserError(_(ADVANCE_COMPANY_ERROR))
        else:
            self._check_sg_eat_depot_company()
        result = super().write(vals)
        if {'amount', 'used_amount', 'state'} & set(vals):
            self._refresh_usage_state()
        return result

    def action_pay(self):
        self.ensure_one()
        self._check_sg_eat_depot_company()
        if self.state != 'draft':
            raise UserError(_("Seules les avances en brouillon peuvent être payées."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Confirmation avance sur payment"),
            'res_model': 'custom.paid.advance.payment.confirm.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_advance_id': self.id},
        }

    def action_cancel(self):
        for advance in self:
            if advance.state in ('partial', 'used'):
                raise UserError(_("Une avance déjà imputée ne peut pas être annulée."))
            advance.state = 'cancelled'
            advance.message_post(body=_("Avance annulée."))

    def _get_liquidity_account(self):
        self.ensure_one()
        account = (
            self.journal_id.default_account_id
            or self.journal_id.inbound_payment_method_line_ids.payment_account_id[:1]
            or self.journal_id.outbound_payment_method_line_ids.payment_account_id[:1]
        )
        if not account:
            raise UserError(_(
                "Veuillez configurer un compte de liquidité sur le journal %(journal)s.",
                journal=self.journal_id.display_name,
            ))
        return account

    def _get_advance_account(self):
        self.ensure_one()
        account = self.company_id.advance_payment_account_id
        if not account:
            raise UserError(_("Veuillez configurer le compte d'attente des avances sur payment pour cette société."))
        return account

    def _prepare_payment_move_vals(self):
        self.ensure_one()
        liquidity_account = self._get_liquidity_account()
        advance_account = self._get_advance_account()
        label = self._get_advance_label()
        return {
            'move_type': 'entry',
            'date': self.payment_date,
            'journal_id': self.journal_id.id,
            'company_id': self.company_id.id,
            'ref': label,
            'line_ids': [
                (0, 0, {
                    'name': label,
                    'account_id': liquidity_account.id,
                    'partner_id': self.partner_id.id,
                    'debit': self.amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': label,
                    'account_id': advance_account.id,
                    'partner_id': self.partner_id.id,
                    'debit': 0.0,
                    'credit': self.amount,
                }),
            ],
        }

    def _confirm_payment(self):
        for advance in self:
            advance._check_sg_eat_depot_company()
            if advance.state != 'draft':
                raise UserError(_("Seules les avances en brouillon peuvent être payées."))
            move = self.env['account.move'].with_company(advance.company_id).create(
                advance._prepare_payment_move_vals()
            )
            move.action_post()
            advance.write({'move_id': move.id, 'state': 'paid'})
            advance._sync_treasury_balance_line(
                cash_balance=self.env.context.get('advance_cash_balance_id'),
                bank_balance=self.env.context.get('advance_bank_balance_id'),
            )
            advance.message_post(body=_(
                "Paiement de l'avance enregistré avec le libellé %s.",
                advance._get_advance_label(),
            ))
        return True

    def _sync_treasury_balance_line(self, cash_balance=False, bank_balance=False):
        for advance in self:
            if not advance.move_id:
                continue
            operator = self.env['mobile.money.operator'].search([
                ('journal_id', '=', advance.journal_id.id),
                ('company_id', '=', advance.company_id.id),
                ('active', '=', True),
            ], limit=1)
            if operator:
                balance = self.env['account.daily.balance.mobile'].browse(bank_balance).exists()
                if not balance:
                    balance = self.env['account.daily.balance.mobile'].create({
                        'date': advance.payment_date,
                        'company_id': advance.company_id.id,
                        'operator_id': operator.id,
                    })
                self.env['account.daily.balance.mobile.line']._upsert_advance_payment(balance, advance)
                balance.action_update_totals_mobile()
            elif advance.journal_id.type == 'cash':
                balance = self.env['account.daily.balance'].browse(cash_balance).exists()
                if not balance:
                    balance = self.env['account.daily.balance'].create({
                        'date': advance.payment_date,
                        'company_id': advance.company_id.id,
                    })
                self.env['account.daily.balance.line']._upsert_advance_payment(balance, advance)
                balance.action_update_totals()

    def _refresh_usage_state(self):
        for advance in self.filtered(lambda record: record.state not in ('draft', 'cancelled')):
            if float_is_zero(advance.residual_amount, precision_rounding=advance.currency_id.rounding):
                state = 'used'
            elif float_compare(
                advance.used_amount,
                0.0,
                precision_rounding=advance.currency_id.rounding,
            ) > 0:
                state = 'partial'
            else:
                state = 'paid'
            if advance.state != state:
                super(CustomPaidAdvancePayment, advance).write({'state': state})

    def _consume_amount(self, amount, invoices):
        self.ensure_one()
        self._check_sg_eat_depot_company()
        if any(invoice.company_id != self.company_id for invoice in invoices):
            raise UserError(_("L'avance doit appartenir à la même société que la facture."))
        if amount <= 0:
            return 0.0
        amount_to_use = min(amount, self.residual_amount)
        if float_is_zero(amount_to_use, precision_rounding=self.currency_id.rounding):
            return 0.0
        self.write({
            'used_amount': self.used_amount + amount_to_use,
            'invoice_ids': [(4, invoice.id) for invoice in invoices],
        })
        self.message_post(body=_("Imputation de %(amount).2f sur facture(s) : %(invoices)s.",
                                 amount=amount_to_use,
                                 invoices=', '.join(invoices.mapped('name'))))
        return amount_to_use


class CustomPaidAdvancePaymentConfirmWizard(models.TransientModel):
    _name = 'custom.paid.advance.payment.confirm.wizard'
    _description = "Confirmation d'avance sur payment"

    advance_id = fields.Many2one('custom.paid.advance.payment', required=True, readonly=True)
    message = fields.Text(
        readonly=True,
        default=lambda self: _(
            "Confirmez-vous l'enregistrement de cette avance sur payment ?\n"
            "Cette opération créera un mouvement dans le journal sélectionné avec le libellé "
            "AVANCE SUR PAYMENT et impactera le solde du jour."
        ),
    )

    def action_confirm(self):
        self.ensure_one()
        if not self.advance_id._is_sg_eat_depot_company(self.advance_id.company_id):
            raise UserError(_(ADVANCE_COMPANY_ERROR))
        self.advance_id._confirm_payment()
        return {'type': 'ir.actions.act_window_close'}


class CustomPaidAdvancePaymentJournalWizard(models.TransientModel):
    _name = 'custom.paid.advance.payment.journal.wizard'
    _description = "Avance sur Payment depuis un journal de trésorerie"

    cash_balance_id = fields.Many2one('account.daily.balance', readonly=True)
    bank_balance_id = fields.Many2one('account.daily.balance.mobile', readonly=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True)
    journal_id = fields.Many2one('account.journal', required=True, readonly=True)
    payment_date = fields.Date(required=True, readonly=True)
    partner_id = fields.Many2one('res.partner', string='Client', required=True)
    amount = fields.Monetary(string="Montant de l'avance", required=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', readonly=True)

    def _is_sg_eat_depot_company(self, company=None):
        company = company or self.company_id or self.env.company
        return company.name == SG_EAT_DEPOT_COMPANY_NAME

    @api.constrains('amount')
    def _check_amount(self):
        for wizard in self:
            if wizard.amount <= 0:
                raise ValidationError(_("Le montant de l'avance doit être supérieur à 0."))

    def action_confirm(self):
        self.ensure_one()
        if not self._is_sg_eat_depot_company(self.company_id):
            raise UserError(_(ADVANCE_COMPANY_ERROR))
        advance = self.env['custom.paid.advance.payment'].sudo().create({
            'company_id': self.company_id.id,
            'partner_id': self.partner_id.id,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'journal_id': self.journal_id.id,
            'payment_date': self.payment_date,
        })
        advance.with_context(
            advance_cash_balance_id=self.cash_balance_id.id,
            advance_bank_balance_id=self.bank_balance_id.id,
        )._confirm_payment()
        return {'type': 'ir.actions.act_window_close'}


class AccountDailyBalance(models.Model):
    _inherit = 'account.daily.balance'

    show_advance_payment_button = fields.Boolean(
        compute='_compute_show_advance_payment_button',
        string="Afficher le bouton Avance sur Payment",
    )

    def _is_sg_eat_depot_company(self):
        self.ensure_one()
        return self.company_id.name == SG_EAT_DEPOT_COMPANY_NAME

    @api.depends('company_id')
    def _compute_show_advance_payment_button(self):
        for balance in self:
            balance.show_advance_payment_button = balance.company_id.name == SG_EAT_DEPOT_COMPANY_NAME

    def _get_advance_cash_journal(self):
        self.ensure_one()
        journal = self.env['account.journal'].search([
            ('company_id', '=', self.company_id.id),
            ('type', '=', 'cash'),
        ], order='sequence, id', limit=1)
        if not journal:
            raise UserError(_("Aucun journal de type Espèces n'est configuré pour cette société."))
        return journal

    def action_open_advance_payment_wizard(self):
        self.ensure_one()
        if not self._is_sg_eat_depot_company():
            raise UserError(_(ADVANCE_COMPANY_ERROR))
        if self.etat != 'ouvert':
            raise UserError(_("Le journal est clôturé. Impossible d'ajouter une avance."))
        journal = self._get_advance_cash_journal()
        return {
            'type': 'ir.actions.act_window',
            'name': _("AVANCE SUR PAYMENT"),
            'res_model': 'custom.paid.advance.payment.journal.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_cash_balance_id': self.id,
                'default_company_id': self.company_id.id,
                'default_journal_id': journal.id,
                'default_payment_date': self.date,
            },
        }


class AccountDailyBalanceMobile(models.Model):
    _inherit = 'account.daily.balance.mobile'

    show_advance_payment_button = fields.Boolean(
        compute='_compute_show_advance_payment_button',
        string="Afficher le bouton Avance sur Payment",
    )

    def _is_sg_eat_depot_company(self):
        self.ensure_one()
        return self.company_id.name == SG_EAT_DEPOT_COMPANY_NAME

    @api.depends('company_id')
    def _compute_show_advance_payment_button(self):
        for balance in self:
            balance.show_advance_payment_button = balance.company_id.name == SG_EAT_DEPOT_COMPANY_NAME

    def action_open_advance_payment_wizard(self):
        self.ensure_one()
        if not self._is_sg_eat_depot_company():
            raise UserError(_(ADVANCE_COMPANY_ERROR))
        if self.etats != 'ouvert':
            raise UserError(_("Le journal est clôturé. Impossible d'ajouter une avance."))
        if not self.operator_id.journal_id or self.operator_id.journal_id.type != 'bank':
            raise UserError(_(
                "Le journal de trésorerie %(journal)s doit être configuré avec un journal comptable de type Banque.",
                journal=self.operator_id.display_name,
            ))
        return {
            'type': 'ir.actions.act_window',
            'name': _("AVANCE SUR PAYMENT"),
            'res_model': 'custom.paid.advance.payment.journal.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_bank_balance_id': self.id,
                'default_company_id': self.company_id.id,
                'default_journal_id': self.operator_id.journal_id.id,
                'default_payment_date': self.date,
            },
        }


class AccountDailyBalanceLine(models.Model):
    _inherit = 'account.daily.balance.line'

    advance_payment_id = fields.Many2one(
        'custom.paid.advance.payment',
        string='Avance sur Payment',
        readonly=True,
        index=True,
        check_company=True,
    )

    @api.model
    def _upsert_advance_payment(self, balance, advance):
        existing = self.search([('advance_payment_id', '=', advance.id)], limit=1)
        label = advance._get_advance_label()
        vals = {
            'balance_id': balance.id,
            'reference': advance.name,
            'categorie': ADVANCE_LABEL,
            'libelle': label,
            'payment': advance.journal_id.type,
            'debit': 0.0,
            'credit': advance.amount,
            'move_id': advance.move_id.id,
            'journal_id': advance.journal_id.id,
            'payment_date': advance.payment_date,
            'advance_payment_id': advance.id,
        }
        if existing:
            if existing.balance_id.etat == 'ouvert':
                existing.write(vals)
            return existing
        return self.create(vals)


class AccountDailyBalanceMobileLine(models.Model):
    _inherit = 'account.daily.balance.mobile.line'

    advance_payment_id = fields.Many2one(
        'custom.paid.advance.payment',
        string='Avance sur Payment',
        readonly=True,
        index=True,
        check_company=True,
    )

    @api.model
    def _upsert_advance_payment(self, balance, advance):
        existing = self.search([('advance_payment_id', '=', advance.id)], limit=1)
        label = advance._get_advance_label()
        vals = {
            'balance_id': balance.id,
            'company_id': advance.company_id.id,
            'reference': advance.name,
            'categorie': ADVANCE_LABEL,
            'libelle': label,
            'payment': advance.journal_id.type,
            'debit': 0.0,
            'credit': advance.amount,
            'move_id': advance.move_id.id,
            'journal_id': advance.journal_id.id,
            'payment_date': advance.payment_date,
            'advance_payment_id': advance.id,
        }
        if existing:
            if existing.balance_id.etats == 'ouvert':
                existing.write(vals)
            return existing
        return self.create(vals)
