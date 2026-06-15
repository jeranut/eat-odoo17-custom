from odoo import api, fields, models, tools


class TreasuryAnalysisReport(models.Model):
    _name = 'treasury.analysis.report'
    _description = 'Analyse des encaissements et décaissements'
    _auto = False
    _order = 'date desc, id desc'

    date = fields.Date(string='Date', readonly=True)
    period_label = fields.Char(string='Période', readonly=True)
    company_id = fields.Many2one('res.company', string='Société', readonly=True)
    source_type = fields.Selection(
        [
            ('cash', 'Caisse'),
            ('mobile_money', 'Journaux configurés'),
        ],
        string='Type',
        readonly=True,
    )
    journal_id = fields.Many2one('account.journal', string='Journal comptable', readonly=True)
    operator_id = fields.Many2one('mobile.money.operator', string='Journal de trésorerie', readonly=True)
    total_income = fields.Float(string='Encaissements', readonly=True)
    total_expense = fields.Float(string='Décaissements', readonly=True)
    balance_amount = fields.Float(string='Solde net', readonly=True)

    @api.model
    def get_apex_analysis_data(self, filters=None):
        filters = filters or {}
        period = filters.get('period', 'day')
        if period not in ('day', 'week', 'month'):
            period = 'day'

        allowed_company_ids = self.env.companies.ids
        company_id = int(filters.get('company_id') or 0)
        if company_id not in allowed_company_ids:
            company_id = False

        domain = [('company_id', 'in', allowed_company_ids)]
        if company_id:
            domain.append(('company_id', '=', company_id))
        if filters.get('date_from'):
            domain.append(('date', '>=', filters['date_from']))
        if filters.get('date_to'):
            domain.append(('date', '<=', filters['date_to']))
        if filters.get('source_type') in ('cash', 'mobile_money'):
            domain.append(('source_type', '=', filters['source_type']))
        operator_id = int(filters.get('operator_id') or 0)
        if operator_id:
            domain.append(('operator_id', '=', operator_id))

        grouped = self.read_group(
            domain,
            ['total_income:sum', 'total_expense:sum', 'balance_amount:sum'],
            [f'date:{period}'],
            orderby=f'date:{period}',
            lazy=False,
        )
        labels = []
        incomes = []
        expenses = []
        for row in grouped:
            labels.append(row.get(f'date:{period}') or '')
            incomes.append(row.get('total_income', 0.0))
            expenses.append(row.get('total_expense', 0.0))

        companies = self.env['res.company'].browse(allowed_company_ids)
        operators = self.env['mobile.money.operator'].search([
            ('company_id', 'in', allowed_company_ids),
        ])
        if company_id:
            operators = operators.filtered(lambda operator: operator.company_id.id == company_id)

        selected_companies = companies.filtered(lambda company: company.id == company_id) if company_id else companies
        currency = selected_companies.currency_id if len(selected_companies.currency_id) == 1 else False
        return {
            'labels': labels,
            'income': incomes,
            'expense': expenses,
            'totals': {
                'income': sum(incomes),
                'expense': sum(expenses),
                'balance': sum(incomes) - sum(expenses),
            },
            'companies': [{'id': company.id, 'name': company.name} for company in companies],
            'operators': [{'id': operator.id, 'name': operator.name} for operator in operators],
            'currency': {
                'symbol': currency.symbol if currency else '',
                'position': currency.position if currency else 'after',
            },
        }

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW treasury_analysis_report AS (
                SELECT
                    cash_line.id * 2 AS id,
                    COALESCE(cash_line.payment_date, cash_balance.date) AS date,
                    TO_CHAR(
                        COALESCE(cash_line.payment_date, cash_balance.date),
                        'YYYY-MM-DD'
                    ) AS period_label,
                    cash_balance.company_id AS company_id,
                    'cash'::varchar AS source_type,
                    cash_line.journal_id AS journal_id,
                    NULL::integer AS operator_id,
                    COALESCE(cash_line.credit, 0.0) AS total_income,
                    COALESCE(cash_line.debit, 0.0) AS total_expense,
                    COALESCE(cash_line.credit, 0.0) - COALESCE(cash_line.debit, 0.0)
                        AS balance_amount
                FROM account_daily_balance_line cash_line
                JOIN account_daily_balance cash_balance
                    ON cash_balance.id = cash_line.balance_id

                UNION ALL

                SELECT
                    mobile_line.id * 2 + 1 AS id,
                    COALESCE(mobile_line.payment_date, mobile_balance.date) AS date,
                    TO_CHAR(
                        COALESCE(mobile_line.payment_date, mobile_balance.date),
                        'YYYY-MM-DD'
                    ) AS period_label,
                    mobile_balance.company_id AS company_id,
                    'mobile_money'::varchar AS source_type,
                    mobile_line.journal_id AS journal_id,
                    mobile_balance.operator_id AS operator_id,
                    COALESCE(mobile_line.credit, 0.0) AS total_income,
                    COALESCE(mobile_line.debit, 0.0) AS total_expense,
                    COALESCE(mobile_line.credit, 0.0) - COALESCE(mobile_line.debit, 0.0)
                        AS balance_amount
                FROM account_daily_balance_mobile_line mobile_line
                JOIN account_daily_balance_mobile mobile_balance
                    ON mobile_balance.id = mobile_line.balance_id
            )
        """)
