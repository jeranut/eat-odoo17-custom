# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class VendorUnpaidSupplierReportWizard(models.TransientModel):
    _name = "vendor.unpaid.supplier.report.wizard"
    _description = "Wizard état des factures impayées"

    report_scope = fields.Selection(
        selection=[
            ("supplier", "Fournisseurs"),
            ("customer", "Clients"),
        ],
        string="Type de rapport",
        required=True,
        default="supplier",
    )
    print_mode = fields.Selection(
        selection=[
            ("range", "Intervalle de dates"),
            ("date", "Date unique"),
        ],
        string="Choix d'impression",
        required=True,
        default="range",
    )
    date_from = fields.Date(string="Date de facturation début")
    date_to = fields.Date(string="Date de facturation fin")
    report_date = fields.Date(string="Date de facturation")
    available_partner_ids = fields.Many2many(
        comodel_name="res.partner",
        relation="vendor_unpaid_available_partner_rel",
        column1="wizard_id",
        column2="partner_id",
        compute="_compute_available_partner_ids",
        string="Fournisseurs disponibles",
    )
    partner_ids = fields.Many2many(
        comodel_name="res.partner",
        relation="vendor_unpaid_selected_partner_rel",
        column1="wizard_id",
        column2="partner_id",
        string="Fournisseurs",
        domain="[('id', 'in', available_partner_ids)]",
        help="Seuls les partenaires ayant des factures non payées sont proposés.",
    )
    # Compatibility with wizard forms opened before partner_id became partner_ids.
    partner_id = fields.Many2one(comodel_name="res.partner", string="Partenaire précédent")

    @api.depends("report_scope", "print_mode", "date_from", "date_to", "report_date")
    def _compute_available_partner_ids(self):
        for wizard in self:
            domain = wizard._get_base_move_domain(apply_partner=False, validate_dates=False)
            grouped = self.env["account.move"].read_group(
                domain,
                ["partner_id"],
                ["partner_id"],
            )
            partner_ids = [group["partner_id"][0] for group in grouped if group.get("partner_id")]
            wizard.available_partner_ids = [(6, 0, partner_ids)]

    @api.onchange("print_mode")
    def _onchange_print_mode(self):
        if self.print_mode == "date":
            self.date_from = False
            self.date_to = False
        else:
            self.report_date = False

    @api.onchange("report_scope", "print_mode", "date_from", "date_to", "report_date")
    def _onchange_filters(self):
        self.partner_ids &= self.available_partner_ids

    def _get_base_move_domain(self, apply_partner=True, validate_dates=True):
        self.ensure_one()
        move_type = "out_invoice" if self.report_scope == "customer" else "in_invoice"
        domain = [
            ("move_type", "=", move_type),
            ("state", "=", "posted"),
            ("company_id", "=", self.env.company.id),
            ("payment_state", "in", ["not_paid", "partial"]),
            ("amount_residual", ">", 0),
        ]

        if self.print_mode == "range":
            if validate_dates and (not self.date_from or not self.date_to):
                raise UserError(_("Veuillez renseigner la date de début et la date de fin."))
            if self.date_from and self.date_to:
                if validate_dates and self.date_from > self.date_to:
                    raise UserError(_("La date de début ne peut pas être supérieure à la date de fin."))
                domain += [
                    ("invoice_date", ">=", self.date_from),
                    ("invoice_date", "<=", self.date_to),
                ]
        else:
            if validate_dates and not self.report_date:
                raise UserError(_("Veuillez renseigner la date."))
            if self.report_date:
                domain.append(("invoice_date", "=", self.report_date))

        if apply_partner and self.partner_ids:
            domain.append(("partner_id", "in", self.partner_ids.ids))

        return domain

    def action_print_pdf(self):
        self.ensure_one()
        moves = self.env["account.move"].search(
            self._get_base_move_domain(),
            order="invoice_date asc, invoice_date_due asc, name asc",
        )
        if not moves:
            raise UserError(_("Aucune facture impayée trouvée pour ce filtre."))

        data = {
            "wizard_id": self.id,
            "move_ids": moves.ids,
        }
        return self.env.ref(
            "vendor_unpaid_supplier_report.action_report_vendor_unpaid_supplier"
        ).report_action(self, data=data)
