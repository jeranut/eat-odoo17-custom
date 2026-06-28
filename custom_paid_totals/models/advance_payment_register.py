from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

from .advance_payment import ADVANCE_LABEL, SG_EAT_DEPOT_COMPANY_NAME, ADVANCE_COMPANY_ERROR


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    use_advance_payment = fields.Boolean(string="Utiliser l'avance disponible")
    advance_payment_ids = fields.Many2many(
        'custom.paid.advance.payment',
        string='Avances disponibles',
        compute='_compute_available_advances',
    )
    available_advance_amount = fields.Monetary(
        string='Avance disponible',
        compute='_compute_available_advances',
        currency_field='currency_id',
    )
    advance_amount_to_use = fields.Monetary(
        string='Montant avance utilisé',
        currency_field='currency_id',
    )
    original_payment_amount = fields.Monetary(
        string='Montant facture',
        currency_field='currency_id',
        readonly=True,
    )
    residual_after_advance = fields.Monetary(
        string='Reste à payer',
        compute='_compute_residual_after_advance',
        currency_field='currency_id',
    )

    def _is_sg_eat_depot_company(self, company=None):
        company = company or self.company_id or self.env.company
        return company.name == SG_EAT_DEPOT_COMPANY_NAME

    def _get_advance_label(self, partner):
        return "%s - %s" % (ADVANCE_LABEL, partner.display_name or "")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        wizard = self.new(values)
        advances = wizard._get_available_advances()
        if advances:
            available_amount = sum(advances.mapped('residual_amount'))
            amount = wizard._get_invoice_residual_amount() or values.get('amount') or wizard.amount
            amount_to_use = min(available_amount, amount)
            values['original_payment_amount'] = amount
            values['use_advance_payment'] = True
            values['advance_amount_to_use'] = amount_to_use
            if amount_to_use and amount_to_use < amount:
                values['amount'] = amount - amount_to_use
        return values

    @api.depends('partner_id', 'company_id', 'currency_id')
    def _compute_available_advances(self):
        for wizard in self:
            advances = wizard._get_available_advances()
            wizard.advance_payment_ids = advances
            wizard.available_advance_amount = sum(advances.mapped('residual_amount'))
            if (
                wizard.use_advance_payment
                and not wizard.advance_amount_to_use
                and wizard.available_advance_amount
            ):
                amount = wizard.original_payment_amount or wizard.amount
                wizard.advance_amount_to_use = min(wizard.available_advance_amount, amount)

    @api.depends('amount', 'advance_amount_to_use', 'use_advance_payment', 'original_payment_amount')
    def _compute_residual_after_advance(self):
        for wizard in self:
            amount = wizard.original_payment_amount or wizard.amount
            wizard.residual_after_advance = (
                max(amount - wizard.advance_amount_to_use, 0.0)
                if wizard.use_advance_payment
                else amount
            )

    @api.onchange('use_advance_payment', 'available_advance_amount', 'amount')
    def _onchange_use_advance_payment(self):
        for wizard in self:
            amount = wizard.original_payment_amount or wizard.amount
            if not wizard.use_advance_payment:
                wizard.advance_amount_to_use = 0.0
                if wizard.original_payment_amount:
                    wizard.amount = wizard.original_payment_amount
                continue
            wizard.advance_amount_to_use = min(wizard.available_advance_amount, amount)
            if wizard.original_payment_amount and wizard.advance_amount_to_use < wizard.original_payment_amount:
                wizard.amount = wizard.original_payment_amount - wizard.advance_amount_to_use

    def _get_invoice_moves(self):
        self.ensure_one()
        moves = self.line_ids.move_id
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids') or []
        if active_model == 'account.move':
            moves |= self.env['account.move'].browse(active_ids)
        elif active_model == 'account.move.line':
            moves |= self.env['account.move.line'].browse(active_ids).move_id
        return moves.exists().filtered(
            lambda move: move.move_type == 'out_invoice'
            and move.payment_state != 'paid'
            and (not self.company_id or move.company_id == self.company_id)
        )

    def _get_available_advances(self):
        self.ensure_one()
        invoices = self._get_invoice_moves()
        partner = invoices[:1].partner_id or self.partner_id
        company = invoices[:1].company_id or self.company_id
        if not partner or not company:
            return self.env['custom.paid.advance.payment']
        if not self._is_sg_eat_depot_company(company):
            return self.env['custom.paid.advance.payment']
        commercial_partner = partner.commercial_partner_id
        advances = self.env['custom.paid.advance.payment'].search([
            ('company_id', '=', company.id),
            ('company_id.name', '=', SG_EAT_DEPOT_COMPANY_NAME),
            ('state', 'in', ('paid', 'partial')),
            ('residual_amount', '>', 0),
        ], order='payment_date asc, id asc')
        return advances.filtered(
            lambda advance: advance.partner_id == partner
            or advance.partner_id.commercial_partner_id == commercial_partner
        )

    def _get_advance_partner(self):
        self.ensure_one()
        invoices = self._get_invoice_moves()
        return invoices[:1].partner_id or self.partner_id

    def _get_receivable_account(self):
        self.ensure_one()
        partner = self._get_advance_partner()
        company = self._get_invoice_moves()[:1].company_id or self.company_id
        account = partner.with_company(company).property_account_receivable_id
        if not account:
            raise UserError(_("Veuillez configurer le compte client de %(partner)s.",
                              partner=partner.display_name))
        return account

    def _get_receivable_lines_to_pay(self):
        self.ensure_one()
        invoices = self._get_invoice_moves()
        lines = self.line_ids.filtered(
            lambda line: line.move_id in invoices
            and line.account_id.account_type == 'asset_receivable'
            and not line.reconciled
        )
        if not lines and self.env.context.get('active_model') == 'account.move.line':
            lines = self.env['account.move.line'].browse(
                self.env.context.get('active_ids') or []
            ).exists().filtered(
                lambda line: line.move_id in invoices
                and line.account_id.account_type == 'asset_receivable'
                and not line.reconciled
            )
        if not lines:
            lines = invoices.line_ids.filtered(
                lambda line: line.account_id.account_type == 'asset_receivable'
                and not line.reconciled
            )
        return lines

    def _get_invoice_residual_amount(self):
        self.ensure_one()
        invoices = self._get_invoice_moves()
        if not invoices:
            return 0.0
        return sum(invoices.mapped('amount_residual'))

    def _prepare_advance_allocation_move(self, amount):
        self.ensure_one()
        invoices = self._get_invoice_moves()
        company = invoices[:1].company_id or self.company_id
        if not self._is_sg_eat_depot_company(company):
            raise UserError(_(ADVANCE_COMPANY_ERROR))
        advance_account = company.advance_payment_account_id
        if not advance_account:
            raise UserError(_("Veuillez configurer le compte d'attente des avances sur payment pour cette société."))
        receivable_lines = self._get_receivable_lines_to_pay()
        receivable_account = receivable_lines[:1].account_id or self._get_receivable_account()
        partner = self._get_advance_partner()
        label = self._get_advance_label(partner)
        return {
            'move_type': 'entry',
            'date': self.payment_date or fields.Date.context_today(self),
            'journal_id': self.journal_id.id,
            'company_id': company.id,
            'ref': label,
            'line_ids': [
                (0, 0, {
                    'name': label,
                    'account_id': advance_account.id,
                    'partner_id': partner.id,
                    'debit': amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'name': label,
                    'account_id': receivable_account.id,
                    'partner_id': partner.id,
                    'debit': 0.0,
                    'credit': amount,
                }),
            ],
        }

    def _apply_advance_payment(self, amount):
        self.ensure_one()
        invoices = self._get_invoice_moves()
        if not invoices:
            raise UserError(_("Aucune facture client n'a été trouvée pour imputer l'avance."))
        if not self._is_sg_eat_depot_company(invoices[:1].company_id or self.company_id):
            raise UserError(_(ADVANCE_COMPANY_ERROR))

        advances = self._get_available_advances()
        available_amount = sum(advances.mapped('residual_amount'))
        amount = min(amount, available_amount, self._get_invoice_residual_amount())
        if float_is_zero(amount, precision_rounding=self.currency_id.rounding):
            return 0.0

        allocation_move = self.env['account.move'].with_company(self.company_id).create(
            self._prepare_advance_allocation_move(amount)
        )
        allocation_move.action_post()

        remaining = amount
        for advance in advances:
            consumed = advance._consume_amount(remaining, invoices)
            remaining -= consumed
            if float_is_zero(remaining, precision_rounding=self.currency_id.rounding):
                break

        receivable_account = self._get_receivable_lines_to_pay()[:1].account_id or self._get_receivable_account()
        lines_to_reconcile = (
            self._get_receivable_lines_to_pay()
            | allocation_move.line_ids.filtered(
                lambda line: line.account_id == receivable_account and not line.reconciled
            )
        )
        if lines_to_reconcile:
            lines_to_reconcile.reconcile()
        for invoice in invoices:
            invoice.message_post(body=_("Facture réglée par avance sur payment."))
        return amount

    def _prepare_advance_payment_action(self, allow_confirmation=True):
        self.ensure_one()
        if self.env.context.get('skip_advance_payment_check'):
            return False
        invoices = self._get_invoice_moves()
        advances = self._get_available_advances()
        available_amount = sum(advances.mapped('residual_amount'))
        invoice_residual = self._get_invoice_residual_amount()

        if (
            invoices
            and self.payment_type == 'inbound'
            and self.partner_type == 'customer'
            and available_amount
            and not float_is_zero(invoice_residual, precision_rounding=self.currency_id.rounding)
        ):
            amount_to_use = min(available_amount, invoice_residual)
            remaining_amount = invoice_residual - amount_to_use
            if (
                float_compare(available_amount, invoice_residual, precision_rounding=self.currency_id.rounding) < 0
                and not self.env.context.get('advance_payment_confirmed')
            ):
                if not allow_confirmation:
                    raise UserError(_(
                        "Ce client possède une avance disponible de %(advance).2f %(currency)s. "
                        "Veuillez utiliser l'avance ou confirmer le paiement de la différence uniquement.",
                        advance=amount_to_use,
                        currency=self.currency_id.symbol or self.currency_id.name,
                    ))
                return {
                    'type': 'ir.actions.act_window',
                    'name': _("Confirmation utilisation avance"),
                    'res_model': 'custom.paid.advance.payment.use.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {
                        'payment_register_id': self.id,
                        'default_available_amount': amount_to_use,
                        'default_remaining_amount': remaining_amount,
                    },
                }

            used_amount = self._apply_advance_payment(amount_to_use)
            remaining_amount = invoice_residual - used_amount
            if float_is_zero(remaining_amount, precision_rounding=self.currency_id.rounding):
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("Avance sur Payment"),
                        'message': _("Facture réglée par avance sur payment."),
                        'type': 'success',
                        'sticky': False,
                        'next': {'type': 'ir.actions.act_window_close'},
                    },
                }
            self.amount = remaining_amount

        return False

    def action_create_payments(self):
        self.ensure_one()
        advance_action = self._prepare_advance_payment_action(allow_confirmation=True)
        if advance_action:
            return advance_action
        return super(AccountPaymentRegister, self.with_context(skip_advance_payment_check=True)).action_create_payments()

    def _create_payments(self):
        self.ensure_one()
        advance_action = self._prepare_advance_payment_action(allow_confirmation=False)
        if advance_action:
            return self.env['account.payment']
        return super()._create_payments()


class CustomPaidAdvancePaymentUseWizard(models.TransientModel):
    _name = 'custom.paid.advance.payment.use.wizard'
    _description = "Confirmation d'utilisation d'avance"

    available_amount = fields.Monetary(string='Avance disponible', readonly=True)
    remaining_amount = fields.Monetary(string='Reste à payer', readonly=True)
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
        readonly=True,
    )
    message = fields.Text(compute='_compute_message')

    @api.depends('available_amount', 'remaining_amount')
    def _compute_message(self):
        for wizard in self:
            wizard.message = _(
                "Le client dispose d'une avance de %(advance).2f %(currency)s.\n"
                "Le reste à payer est %(remaining).2f %(currency)s.\n\n"
                "Voulez-vous utiliser l'avance et encaisser uniquement la différence ?",
                advance=wizard.available_amount,
                remaining=wizard.remaining_amount,
                currency=wizard.currency_id.symbol or wizard.currency_id.name,
            )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        register = self.env['account.payment.register'].browse(
            self.env.context.get('payment_register_id')
        ).exists()
        if register:
            values['currency_id'] = register.currency_id.id
        return values

    def action_confirm(self):
        self.ensure_one()
        register = self.env['account.payment.register'].browse(
            self.env.context.get('payment_register_id')
        ).exists()
        if not register:
            return {'type': 'ir.actions.act_window_close'}
        return register.with_context(advance_payment_confirmed=True).action_create_payments()
