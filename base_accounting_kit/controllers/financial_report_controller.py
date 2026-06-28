# -*- coding: utf-8 -*-
import logging

from odoo import http, fields
from odoo.http import request


_logger = logging.getLogger(__name__)


class FinancialReportController(http.Controller):
    """JSON controller for interactive financial report HTML views."""

    @http.route('/base_accounting_kit/financial_report/data', type='json', auth='user')
    def financial_report_data(self, report_name='Balance Sheet', report_xml_id=None,
                              date_from=None, date_to=None, target_move='posted', journal_ids=None,
                              **kwargs):
        company = request.env.company
        date_to = date_to or fields.Date.context_today(request.env.user)
        date_from = date_from or False
        journal_ids = self._sanitize_journal_ids(journal_ids, company)
        journals = self._get_company_journals(company)

        report_config = self._get_report_config(report_name, report_xml_id)
        account_report = report_config and report_config.get('record')

        if not account_report:
            return {
                'success': False,
                'error': 'Rapport financier introuvable.',
                'lines': [],
            }

        wizard_model = report_config.get('wizard_model', 'financial.report')
        wizard_env = request.env[wizard_model].sudo()
        wizard_values = {
            'account_report_id': account_report.id,
            'date_from': date_from,
            'date_to': date_to,
            'target_move': target_move,
            'debit_credit': False,
            'company_id': company.id,
        }
        if 'view_format' in wizard_env._fields:
            wizard_values['view_format'] = 'vertical'
        wizard = wizard_env.create(wizard_values)

        data = {
            'date_from': date_from,
            'date_to': date_to,
            'enable_filter': False,
            'debit_credit': False,
            'account_report_id': [account_report.id, account_report.name],
            'target_move': target_move,
            'journal_ids': journal_ids,
            'view_format': 'vertical',
            'company_id': [company.id, company.name],
            'filter_cmp': 'filter_no',
            'date_from_cmp': False,
            'date_to_cmp': False,
        }

        used_context = wizard._build_contexts({'form': data})
        data['used_context'] = dict(
            used_context,
            lang=request.env.context.get('lang') or 'fr_FR',
        )

        raw_lines = wizard.get_account_lines(data)
        self._log_cash_flow_raw_lines(report_config, report_name, report_xml_id, raw_lines)
        lines = self._build_report_lines(raw_lines, report_config)
        custom_cash_data = self._get_custom_paid_totals_cash_data(
            company.id, date_from, date_to, journal_ids,
        ) if report_config.get('custom_cash_summary') else False

        return {
            'success': True,
            'report_name': account_report.name,
            'report_title': report_config['title'],
            'report_xml_id': report_config['xml_id'],
            'pdf_action_xml_id': report_config['pdf_action_xml_id'],
            'xlsx_action_xml_id': report_config.get('xlsx_action_xml_id'),
            'date_from': str(date_from) if date_from else False,
            'date_to': str(date_to),
            'currency': company.currency_id.symbol or '',
            'company_name': company.name,
            'target_move': target_move,
            'target_move_label': (
                'Toutes les écritures'
                if target_move == 'all'
                else 'Pièces comptabilisées'
            ),
            'journals_label': self._journal_label(journal_ids, journals),
            'journals': [
                {'id': journal.id, 'name': journal.display_name or journal.name}
                for journal in journals
            ],
            'selected_journal_ids': journal_ids,
            'custom_cash_data': custom_cash_data,
            'lines': lines,
        }

    def _get_report_config(self, report_name=None, report_xml_id=None):
        reports = {
            'base_accounting_kit.account_financial_report_balancesheet0': {
                'aliases': {'Balance Sheet', 'Bilan'},
                'title': 'Bilan',
                'pdf_action_xml_id': 'base_accounting_kit.action_balance_sheet_report',
                'xlsx_action_xml_id': False,
                'root_labels': {
                    'Assets': 'ACTIF',
                    'Asset': 'ACTIF',
                    'Les Atouts': 'ACTIF',
                    'LES ATOUTS': 'ACTIF',
                    'Immobilisations': 'ACTIF',
                    'Liability': 'PASSIF',
                    'Passif': 'PASSIF',
                    'PASSIF': 'PASSIF',
                },
                'line_builder': 'balance_sheet',
                'section_rank': {'ACTIF': 0, 'PASSIF': 1},
            },
            'base_accounting_kit.account_financial_report_profitandloss0': {
                'aliases': {'Profit and Loss', 'Compte de résultat'},
                'title': 'Compte de résultat',
                'pdf_action_xml_id': 'base_accounting_kit.action_profit_and_loss_report',
                'xlsx_action_xml_id': False,
                'root_labels': {},
                'line_builder': 'generic',
                'section_rank': {},
            },
            'base_accounting_kit.account_financial_report_cash_flow0': {
                'aliases': {'Cash Flow Statement', 'Tableau des flux de trésorerie'},
                'title': 'Tableau des flux de trésorerie',
                'pdf_action_xml_id': 'base_accounting_kit.action_cash_flow_report',
                'xlsx_action_xml_id': False,
                'wizard_model': 'cash.flow.report',
                'line_builder': 'cash_flow',
                'custom_cash_summary': True,
                'root_labels': {},
                'section_rank': {},
            },
        }

        requested_xml_id = report_xml_id
        if requested_xml_id and not requested_xml_id.startswith('base_accounting_kit.'):
            requested_xml_id = 'base_accounting_kit.%s' % requested_xml_id

        config = reports.get(requested_xml_id)
        if not config:
            report_name = (report_name or '').strip()
            for xml_id, candidate in reports.items():
                if report_name in candidate['aliases']:
                    requested_xml_id = xml_id
                    config = candidate
                    break

        if not config:
            requested_xml_id = 'base_accounting_kit.account_financial_report_balancesheet0'
            config = reports[requested_xml_id]

        record = request.env.ref(requested_xml_id, raise_if_not_found=False)
        if not record:
            return None

        return dict(config, xml_id=requested_xml_id, record=record)

    def _get_company_journals(self, company):
        return request.env['account.journal'].sudo().search([
            ('company_id', '=', company.id),
            ('active', '=', True),
        ], order='type, code, name')

    def _sanitize_journal_ids(self, journal_ids, company):
        if not journal_ids:
            return []
        if isinstance(journal_ids, str):
            journal_ids = [journal_ids]
        try:
            journal_ids = [int(journal_id) for journal_id in journal_ids if journal_id]
        except (TypeError, ValueError):
            return []
        valid_ids = request.env['account.journal'].sudo().search([
            ('id', 'in', journal_ids),
            ('company_id', '=', company.id),
            ('active', '=', True),
        ]).ids
        return valid_ids

    def _journal_label(self, journal_ids, journals):
        if not journal_ids:
            return 'Tous les journaux'
        selected = journals.filtered(lambda journal: journal.id in journal_ids)
        if len(selected) == 1:
            return selected.display_name or selected.name
        return '%s journaux' % len(selected)

    def _log_cash_flow_raw_lines(self, report_config, report_name, report_xml_id, raw_lines):
        if report_config.get('xml_id') != 'base_accounting_kit.account_financial_report_cash_flow0':
            return
        _logger.info(
            'Cash Flow HTML raw_lines diagnostic: report_name=%s report_xml_id=%s count=%s',
            report_name, report_xml_id, len(raw_lines),
        )
        for line in raw_lines:
            _logger.info(
                'Cash Flow raw line: name=%s type=%s balance=%s r_id=%s a_id=%s parent=%s',
                line.get('name'), line.get('type'), line.get('balance'),
                line.get('r_id'), line.get('a_id'), line.get('parent'),
            )

    def _get_custom_paid_totals_cash_data(self, company_id, date_from, date_to, journal_ids):
        if not self._is_model_available('account.daily.balance'):
            return False

        date_to = fields.Date.to_date(date_to)
        date_from = fields.Date.to_date(date_from) if date_from else date_to
        journal_ids = journal_ids or []

        result = {
            'available': True,
            'title': 'Trésorerie opérationnelle',
            'total_cash_in': 0.0,
            'total_cash_out': 0.0,
            'net_cash_flow': 0.0,
            'opening_balance': 0.0,
            'closing_balance': 0.0,
            'adjustments': 0.0,
            'details': [],
        }

        sources = [
            {
                'balance_model': 'account.daily.balance',
                'line_model': 'account.daily.balance.line',
                'source': 'Caisse',
            },
            {
                'balance_model': 'account.daily.balance.mobile',
                'line_model': 'account.daily.balance.mobile.line',
                'source': 'Mobile Money',
            },
        ]

        for source in sources:
            if not self._is_model_available(source['balance_model']):
                continue
            balances = self._get_daily_balances(
                source['balance_model'], company_id, date_from, date_to, journal_ids,
            )
            if not balances:
                continue

            result['opening_balance'] += self._sum_edge_balance(
                balances, ['ancien_solde', 'old_balance', 'opening_balance'], first=True,
            )
            result['closing_balance'] += self._sum_edge_balance(
                balances, ['nouveau_solde', 'new_balance', 'closing_balance'], first=False,
            )

            details = self._get_daily_balance_details(source, balances, journal_ids)
            detail_cash_in = sum(detail['cash_in'] for detail in details)
            detail_cash_out = sum(detail['cash_out'] for detail in details)
            balance_cash_in = self._sum_field(
                balances,
                ['total_credit', 'total_encaissement', 'total_encaissements', 'total_cash_in'],
            )
            balance_cash_out = self._sum_field(
                balances,
                ['total_debit', 'total_decaissement', 'total_decaissements', 'total_cash_out'],
            )
            result['total_cash_in'] += balance_cash_in or detail_cash_in
            result['total_cash_out'] += balance_cash_out or detail_cash_out

            for detail in details:
                result['details'].append(detail)
                if detail.get('is_adjustment'):
                    result['adjustments'] += detail['balance']

        result['net_cash_flow'] = result['total_cash_in'] - result['total_cash_out']
        return result if result['details'] or result['total_cash_in'] or result['total_cash_out'] else False

    def _is_model_available(self, model_name):
        try:
            request.env[model_name]
        except KeyError:
            return False
        return bool(request.env['ir.model'].sudo().search([('model', '=', model_name)], limit=1))

    def _get_daily_balances(self, model_name, company_id, date_from, date_to, journal_ids):
        model = request.env[model_name].sudo()
        fields_map = model._fields
        date_field = self._first_existing_field(fields_map, ['date', 'balance_date', 'payment_date'])
        if not date_field:
            return model.browse()

        domain = [(date_field, '>=', date_from), (date_field, '<=', date_to)]
        if 'company_id' in fields_map:
            domain.append(('company_id', '=', company_id))
        balances = model.search(domain, order='%s, id' % date_field)
        if journal_ids:
            balances = balances.filtered(
                lambda balance: self._record_journal_id(balance) in journal_ids
            )
        return balances

    def _get_daily_balance_details(self, source, balances, journal_ids):
        line_model = source['line_model']
        if not balances or not self._is_model_available(line_model):
            return []

        model = request.env[line_model].sudo()
        balance_field = self._first_existing_field(
            model._fields, ['balance_id', 'daily_balance_id', 'daily_balance_mobile_id'],
        )
        if not balance_field:
            return []

        order_field = self._first_existing_field(model._fields, ['payment_date', 'date']) or 'id'
        lines = model.search([(balance_field, 'in', balances.ids)], order='%s, id' % order_field)
        if journal_ids:
            lines = lines.filtered(lambda line: self._record_journal_id(line) in journal_ids)

        grouped = {}
        for line in lines:
            journal_name = self._record_journal_name(line) or source['source']
            payment_type = self._string_field_value(
                line, ['payment', 'payment_type', 'payment_method', 'name', 'libelle'],
            )
            key = (source['source'], journal_name, payment_type or '')
            grouped.setdefault(key, {
                'key': '%s-%s-%s' % key,
                'source': source['source'],
                'journal': journal_name,
                'payment_type': payment_type,
                'cash_in': 0.0,
                'cash_out': 0.0,
                'balance': 0.0,
                'is_adjustment': False,
            })
            grouped[key]['cash_in'] += self._numeric_field_value(
                line, ['credit', 'amount_in', 'encaissement', 'montant_encaissement'],
            )
            grouped[key]['cash_out'] += self._numeric_field_value(
                line, ['debit', 'amount_out', 'decaissement', 'decaissements', 'montant_decaissement'],
            )
            grouped[key]['balance'] = grouped[key]['cash_in'] - grouped[key]['cash_out']
            if self._is_adjustment_line(line):
                grouped[key]['is_adjustment'] = True
        return list(grouped.values())

    def _first_existing_field(self, fields_map, names):
        for name in names:
            if name in fields_map:
                return name
        return False

    def _numeric_field_value(self, record, names):
        for name in names:
            if name in record._fields:
                value = record[name]
                return value or 0.0
        return 0.0

    def _string_field_value(self, record, names):
        for name in names:
            if name in record._fields:
                value = record[name]
                if not value:
                    return ''
                return value.display_name if hasattr(value, 'display_name') else str(value)
        return ''

    def _sum_field(self, records, names):
        return sum(self._numeric_field_value(record, names) for record in records)

    def _sum_edge_balance(self, records, names, first=True):
        grouped = {}
        for record in records:
            journal_id = self._record_journal_id(record) or False
            grouped.setdefault(journal_id, record)
            if not first:
                grouped[journal_id] = record
        return sum(self._numeric_field_value(record, names) for record in grouped.values())

    def _record_journal_id(self, record):
        for field_name in ['journal_id', 'cash_journal_id']:
            if field_name in record._fields and record[field_name]:
                return record[field_name].id
        if 'operator_id' in record._fields and record.operator_id:
            operator = record.operator_id
            if 'journal_id' in operator._fields and operator.journal_id:
                return operator.journal_id.id
        return False

    def _record_journal_name(self, record):
        for field_name in ['journal_id', 'cash_journal_id']:
            if field_name in record._fields and record[field_name]:
                return record[field_name].display_name
        if 'operator_id' in record._fields and record.operator_id:
            operator = record.operator_id
            if 'journal_id' in operator._fields and operator.journal_id:
                return operator.journal_id.display_name
            return operator.display_name
        return False

    def _is_adjustment_line(self, line):
        values = [
            self._string_field_value(line, ['regule_badge', 'state', 'etat', 'etats']),
            self._string_field_value(line, ['payment', 'payment_type', 'name', 'libelle']),
        ]
        needle = ' '.join(values).lower()
        return 'regule' in needle or 'régul' in needle or 'regul' in needle

    def _build_report_lines(self, raw_lines, report_config):
        builder = report_config.get('line_builder')
        if builder == 'balance_sheet':
            return self._build_balance_sheet_lines(raw_lines, report_config)
        if builder == 'cash_flow':
            return self._build_cash_flow_lines(raw_lines, report_config)
        return self._build_generic_financial_lines(raw_lines, report_config)

    def _build_balance_sheet_lines(self, raw_lines, report_config):
        return self._build_generic_financial_lines(raw_lines, report_config)

    def _build_cash_flow_lines(self, raw_lines, report_config):
        return self._build_generic_financial_lines(raw_lines, report_config)

    def _build_generic_financial_lines(self, raw_lines, report_config):
        """Normalize get_account_lines output for the interactive HTML view."""
        root_report = report_config['record']
        root_line = next(
            (
                line for line in raw_lines
                if line.get('type') == 'report'
                and line.get('r_id') == root_report.id
            ),
            None,
        )
        root_id = root_line and root_line.get('id')
        skipped_ids = {root_id} if root_id else set()

        normalized = []
        by_id = {}
        for order, raw_line in enumerate(raw_lines):
            if raw_line.get('type') == 'account':
                line_id = raw_line.get('id') or raw_line.get('a_id')
            else:
                line_id = raw_line.get('id')
            line_id = line_id or '%s_line_%s' % (report_config['xml_id'], order)
            if not line_id or line_id in skipped_ids:
                continue

            parent = raw_line.get('parent')
            if parent in skipped_ids:
                parent = False

            line = {
                'id': line_id,
                'parent': parent,
                'name': self._financial_report_display_name(raw_line, report_config),
                'balance': round(raw_line.get('balance') or 0.0, 2),
                'level': 0,
                'type': raw_line.get('type') or 'report',
                'total': raw_line.get('type') == 'report',
                'account_type': raw_line.get('account_type'),
                'r_id': raw_line.get('r_id'),
                'a_id': raw_line.get('a_id'),
                '_order': order,
                'unique_key': '%s-%s-%s' % (report_config['xml_id'], line_id, order),
            }
            normalized.append(line)
            by_id[line_id] = line

        for line in normalized:
            if line.get('parent') not in by_id:
                line['parent'] = False

        def compute_level(line, seen=None):
            seen = seen or set()
            parent_id = line.get('parent')
            if not parent_id or parent_id not in by_id or line['id'] in seen:
                return 0
            seen.add(line['id'])
            return compute_level(by_id[parent_id], seen) + 1

        for line in normalized:
            line['level'] = compute_level(line)

        return self._order_financial_report_lines(normalized, report_config)

    def _order_financial_report_lines(self, lines, report_config):
        by_parent = {}
        for line in lines:
            by_parent.setdefault(line.get('parent') or False, []).append(line)

        section_rank = report_config.get('section_rank') or {}

        def sort_key(line):
            if not line.get('parent'):
                return (section_rank.get(line.get('name'), 99), line.get('_order', 0))
            return (line.get('_order', 0),)

        ordered = []

        def append_children(parent_id=False):
            for child in sorted(by_parent.get(parent_id, []), key=sort_key):
                ordered.append(child)
                append_children(child['id'])

        append_children(False)
        for line in ordered:
            line.pop('_order', None)
        return ordered

    def _financial_report_display_name(self, line, report_config):
        if line.get('type') == 'account':
            return line.get('name') or ''

        name = (line.get('name') or '').strip()
        labels = {
            **(report_config.get('root_labels') or {}),
            'Fixed Assets': 'Immobilisations',
            'Non-current Assets': 'Actifs non courants',
            'Current Assets': 'Actif circulant',
            'Receivable Accounts': 'Créances clients',
            'Prepayments': "Charges constatées d’avance",
            'Bank and Cash': 'Trésorerie',
            'Equity': 'Capitaux propres',
            'Current Year Earnings': "Résultat non affecté",
            'Liabilities': 'Dettes',
            'Payable Accounts': 'Dettes fournisseurs',
            'Current Liabilities': 'Dettes à court terme',
            'Credit Card': 'Cartes de crédit',
            'Non-current Liabilities': 'Dettes à long terme',
            'Operations': 'Activités opérationnelles',
            'Investing Activities': 'Activités d’investissement',
            'Financing Activities': 'Activités de financement',
            'Cash In': 'Flux entrants',
            'Cash Out': 'Flux sortants',
            'Operating Income': 'Produits d’exploitation',
            'Other Income': 'Autres produits',
            'Cost of Revenue': 'Coût des ventes',
            'Gross Profit': 'Marge brute',
            'Income': 'Produits',
            'Expense': 'Charges',
            'Expenses': 'Charges d’exploitation',
            'Depreciation': 'Dotations aux amortissements',
            'Profit (Loss) to report': "Résultat de l’exercice",
            'Profit/Loss to report': "Résultat de l’exercice",
            'Bénéfice (perte) à déclarer': "Résultat de l’exercice",
            'BÉNÉFICE (PERTE) À DÉCLARER': "Résultat de l’exercice",
        }
        return labels.get(name, name)
