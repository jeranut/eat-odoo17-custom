# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.tools import format_date
from odoo.tools.misc import formatLang


class ReportVendorUnpaidSupplier(models.AbstractModel):
    _name = "report.vendor_unpaid_supplier_report.unpaid_vendor"
    _description = "Rapport état des impayés fournisseurs"

    def _get_due_label(self, move):
        due_date = move.invoice_date_due
        if not due_date:
            return "-"
        current_date = fields.Date.context_today(move)
        delta = (due_date - current_date).days
        if delta == -1:
            return "Hier"
        if delta == 0:
            return "Aujourd'hui"
        if delta == 1:
            return "Demain"
        if delta > 1:
            return "Dans %s jours" % delta
        return "Il y a %s jours" % abs(delta)

    def _is_overdue(self, move):
        return bool(
            move.invoice_date_due
            and move.invoice_date_due < fields.Date.context_today(move)
        )

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        wizard = self.env["vendor.unpaid.supplier.report.wizard"].browse(
            data.get("wizard_id")
        ).exists()
        moves = self.env["account.move"].browse(data.get("move_ids", [])).exists()
        company = moves[:1].company_id or self.env.company
        document = moves[:1]
        return {
            "doc_ids": moves.ids,
            "doc_model": "account.move",
            "docs": moves,
            "doc": document,
            "wizard": wizard,
            "company_id": company,
            "company": company,
            "total_amount": sum(moves.mapped("amount_total_signed")),
            "get_due_label": self._get_due_label,
            "is_overdue": self._is_overdue,
            "format_date": lambda value: format_date(self.env, value) if value else "",
            "format_amount": lambda amount: formatLang(
                self.env,
                amount,
                currency_obj=company.currency_id,
            ),
        }
