# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2023-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions(<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU LESSER
#    GENERAL PUBLIC LICENSE (LGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU LESSER GENERAL PUBLIC LICENSE (LGPL v3) for more details.
#
#    You should have received a copy of the GNU LESSER GENERAL PUBLIC LICENSE
#    (LGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################

import time

from odoo import api, models, _
from odoo.exceptions import UserError


class ReportFinancial(models.AbstractModel):
    _name = 'report.base_accounting_kit.report_cash_flow'
    _description = 'Cash Flow Report'

    def _compute_account_balance(self, accounts):
        mapping = {
            'balance': "COALESCE(SUM(debit),0)"
                       " - COALESCE(SUM(credit), 0) as balance",
            'debit': "COALESCE(SUM(debit), 0) as debit",
            'credit': "COALESCE(SUM(credit), 0) as credit",
        }
        res = {}
        for account in accounts:
            res[account.id] = dict.fromkeys(mapping, 0.0)
        if accounts:
            tables, where_clause, where_params = self.env[
                'account.move.line']._query_get()
            tables = tables.replace('"', '') if tables else "account_move_line"
            wheres = [""]
            if where_clause.strip():
                wheres.append(where_clause.strip())
            filters = " AND ".join(wheres)
            request = "SELECT account_id as id, " + ', '.join(
                mapping.values()) + \
                      " FROM " + tables + \
                      " WHERE account_id IN %s " \
                      + filters + \
                      " GROUP BY account_id"
            params = (tuple(accounts._ids),) + tuple(where_params)
            self.env.cr.execute(request, params)
            for row in self.env.cr.dictfetchall():
                res[row['id']] = row
        return res

    def _compute_report_balance(self, reports):
        res = {}
        fields = ['credit', 'debit', 'balance']
        for report in reports:
            if report.id in res:
                continue
            res[report.id] = dict((fn, 0.0) for fn in fields)
            if report.type == 'accounts':
                accounts = self._get_cash_flow_accounts(report)
                res[report.id]['account'] = self._compute_account_balance(
                    accounts)
                for value in res[report.id]['account'].values():
                    res[report.id]['debit'] += value.get('debit')
                    res[report.id]['credit'] += value.get('credit')
                    res[report.id]['balance'] += self._get_cash_flow_account_line_balance(
                        report, value)
            elif report.type == 'account_type':
                # it's the sum the leaf accounts with such an account type
                accounts = self.env['account.account'].search(
                    [('account_type', 'in', report.account_type_ids)])
                res[report.id]['account'] = self._compute_account_balance(
                    accounts)
                for value in res[report.id]['account'].values():
                    for field in fields:
                        res[report.id][field] += value.get(field)
            elif report.type == 'account_report' and report.account_report_id:
                # it's the amount of the linked
                res[report.id]['account'] = self._compute_account_balance(
                    report.account_ids)
                for value in res[report.id]['account'].values():
                    for field in fields:
                        res[report.id][field] += value.get(field)
            elif report.type == 'sum':
                res2 = self._compute_report_balance(report.children_ids)
                for values in res2.values():
                    for field in fields:
                        res[report.id][field] += values.get(field)
        return res

    def _get_cash_flow_accounts(self, report):
        accounts = report.account_ids
        if report.parent_id:
            accounts |= report.parent_id.account_ids
        if 'cash_flow_type' in self.env['account.account']._fields:
            accounts |= self.env['account.account'].search([
                ('cash_flow_type', 'in', [report.id, report.parent_id.id]),
            ])
        if not accounts and self._use_account_type_fallback():
            accounts = self._get_cash_flow_fallback_accounts(report)
        return accounts

    def _use_account_type_fallback(self):
        if 'cash_flow_type' not in self.env['account.account']._fields:
            return True
        configured_accounts = self.env['account.account'].search_count([
            ('cash_flow_type', '!=', False),
        ])
        cash_flow_root = self.env.ref(
            'base_accounting_kit.account_financial_report_cash_flow0')
        configured_report_accounts = self.env['account.financial.report'].search_count([
            ('parent_id', '=', cash_flow_root.id),
            ('account_ids', '!=', False),
        ])
        return not configured_accounts and not configured_report_accounts

    def _get_cash_flow_fallback_accounts(self, report):
        account_types = []
        if self._is_operation_cash_in_report(report):
            account_types = ['income', 'income_other']
        elif self._is_operation_cash_out_report(report):
            account_types = ['expense', 'expense_depreciation', 'expense_direct_cost']
        elif self._is_investing_cash_report(report):
            account_types = ['asset_fixed', 'asset_non_current']
        elif self._is_financing_cash_report(report):
            account_types = [
                'equity', 'liability_payable', 'liability_current',
                'liability_non_current', 'liability_credit_card',
            ]
        if not account_types:
            return self.env['account.account']
        return self.env['account.account'].search([
            ('account_type', 'in', account_types),
        ])

    def _uses_fallback_balance_sign(self, report):
        return self._use_account_type_fallback() and (
            self._is_cash_in_report(report) or self._is_cash_out_report(report))

    def _is_operation_cash_in_report(self, report):
        return report == self.env.ref('base_accounting_kit.cash_in_from_operation0')

    def _is_operation_cash_out_report(self, report):
        return report == self.env.ref('base_accounting_kit.cash_out_operation1')

    def _is_investing_cash_report(self, report):
        return report in self.env['account.financial.report'].browse([
            self.env.ref('base_accounting_kit.cash_in_investing0').id,
            self.env.ref('base_accounting_kit.cash_out_investing1').id,
        ])

    def _is_financing_cash_report(self, report):
        return report in self.env['account.financial.report'].browse([
            self.env.ref('base_accounting_kit.cash_in_financial0').id,
            self.env.ref('base_accounting_kit.cash_out_financial1').id,
        ])

    def _is_cash_in_report(self, report):
        cash_in_reports = self.env['account.financial.report'].browse([
            self.env.ref('base_accounting_kit.cash_in_from_operation0').id,
            self.env.ref('base_accounting_kit.cash_in_financial0').id,
            self.env.ref('base_accounting_kit.cash_in_investing0').id,
        ])
        return report in cash_in_reports

    def _is_cash_out_report(self, report):
        cash_out_reports = self.env['account.financial.report'].browse([
            self.env.ref('base_accounting_kit.cash_out_operation1').id,
            self.env.ref('base_accounting_kit.cash_out_financial1').id,
            self.env.ref('base_accounting_kit.cash_out_investing1').id,
        ])
        return report in cash_out_reports

    def get_account_lines(self, data):
        lines = []
        account_report = self.env['account.financial.report'].search(
            [('id', '=', data['account_report_id'][0])])
        child_reports = account_report._get_children_by_order()
        res = self.with_context(
            data.get('used_context'))._compute_report_balance(child_reports)
        if data['enable_filter']:
            comparison_res = self.with_context(
                data.get('comparison_context'))._compute_report_balance(
                child_reports)
            for report_id, value in comparison_res.items():
                res[report_id]['comp_bal'] = value['balance']
                report_acc = res[report_id].get('account')
                if report_acc:
                    for account_id, val in comparison_res[report_id].get(
                            'account').items():
                        report_acc[account_id]['comp_bal'] = val['balance']
        for report in child_reports:
            vals = {
                'id': report.id,
                'r_id': report.id,
                'parent': report.parent_id.id or False,
                'name': report.name,
                'balance': res[report.id]['balance'] * int(report.sign),
                'type': 'report',
                'level': bool(report.style_overwrite) and int(
                    report.style_overwrite) or report.level,
                'account_type': report.type or False,
                # used to underline the financial report balances
            }
            if data['debit_credit']:
                vals['debit'] = res[report.id]['debit']
                vals['credit'] = res[report.id]['credit']
            if data['enable_filter']:
                vals['balance_cmp'] = res[report.id]['comp_bal'] * int(
                    report.sign)
            lines.append(vals)
            if report.display_detail == 'no_detail':
                # the rest of the loop is used to display the details of the
                # financial report, so it's not needed here.
                continue
            if res[report.id].get('account'):
                # if res[report.id].get('debit'):
                sub_lines = []
                for account_id, value in res[report.id]['account'].items():
                    # if there are accounts to display, we add them to the
                    # lines with a level equals to their level in
                    # the COA + 1 (to avoid having them with a too low level
                    # that would conflicts with the level of data
                    # financial reports for Assets, liabilities...)
                    flag = False
                    account = self.env['account.account'].browse(account_id)
                    vals = {
                        'id': '%s_%s' % (report.id, account.id),
                        'r_id': report.id,
                        'a_id': account.id,
                        'parent': report.id,
                        'name': account.code + ' ' + account.name,
                        'balance': self._get_cash_flow_account_line_balance(
                            report, value) * int(report.sign) or 0.0,
                        'type': 'account',
                        'level': report.display_detail ==
                                 'detail_with_hierarchy' and 4,
                        'account_type': account.account_type,
                    }
                    if data['debit_credit']:
                        vals['debit'] = value['debit']
                        vals['credit'] = value['credit']
                        if (not account.company_id.currency_id.is_zero(
                                vals[
                                    'debit']) or not account.company_id.
                                currency_id.is_zero(vals['credit'])):
                            flag = True
                    if not account.company_id.currency_id.is_zero(
                            vals['balance']):
                        flag = True
                    if data['enable_filter']:
                        vals['balance_cmp'] = value['comp_bal'] * int(
                            report.sign)
                        if not account.company_id.currency_id.is_zero(
                                vals['balance_cmp']):
                            flag = True
                    if flag:
                        sub_lines.append(vals)
                lines += sorted(sub_lines,
                                key=lambda sub_line: sub_line['name'])
        return lines

    def _get_cash_flow_account_line_balance(self, report, value):
        if self._is_cash_in_report(report):
            return value.get('credit') if self._uses_fallback_balance_sign(report) else value.get('debit')
        if self._is_cash_out_report(report):
            amount = value.get('debit') if self._uses_fallback_balance_sign(report) else value.get('credit')
            return -amount
        return value.get('balance')

    @api.model
    def _get_report_values(self, docids, data=None):
        if not data.get('form') or not self.env.context.get(
                'active_model') or not self.env.context.get('active_id'):
            raise UserError(
                _("Form content is missing, this report cannot be printed."))

        model = self.env.context.get('active_model')
        docs = self.env[model].browse(self.env.context.get('active_id'))
        report_lines = self.get_account_lines(data.get('form'))
        return {
            'doc_ids': self.ids,
            'doc_model': model,
            'data': data['form'],
            'docs': docs,
            'time': time,
            'get_account_lines': report_lines,
        }
