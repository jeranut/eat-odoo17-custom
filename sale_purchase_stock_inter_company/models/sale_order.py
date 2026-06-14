from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    intercompany_purchase_id = fields.Many2one(
        "purchase.order",
        string="Intercompany Purchase Order",
        copy=False,
        readonly=True,
    )
    intercompany_buyer_company_id = fields.Many2one(
        "res.company",
        string="Intercompany Buyer Company",
        copy=False,
        readonly=True,
    )

    def action_confirm(self):
        res = super().action_confirm()
        if not self.env.context.get("skip_reverse_intercompany"):
            self._create_reverse_intercompany_purchase_orders()
        return res

    def _get_intercompany_buyer_company(self):
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        companies = self.env["res.company"].sudo().search([])
        return companies.filtered(
            lambda c: c.id != self.company_id.id
            and c.partner_id.commercial_partner_id.id == partner.id
        )[:1]

    def _prepare_reverse_intercompany_purchase_vals(self, buyer_company):
        self.ensure_one()
        seller_partner = self.company_id.partner_id
        if not seller_partner:
            raise UserError(_("The seller company has no related partner."))
        return {
            "partner_id": seller_partner.id,
            "company_id": buyer_company.id,
            "currency_id": self.currency_id.id,
            "origin": self.name,
            "date_order": fields.Datetime.now(),
            "intercompany_sale_id": self.id,
            "is_reverse_intercompany_purchase": True,
        }

    def _prepare_reverse_intercompany_purchase_line_vals(self, line, purchase):
        taxes = line.product_id.supplier_taxes_id.filtered(
            lambda t: not t.company_id or t.company_id == purchase.company_id
        )
        return {
            "order_id": purchase.id,
            "product_id": line.product_id.id,
            "name": line.name or line.product_id.display_name,
            "product_qty": line.product_uom_qty,
            "product_uom": line.product_uom.id,
            "price_unit": line.price_unit,
            "date_planned": fields.Datetime.now(),
            "taxes_id": [(6, 0, taxes.ids)],
            "intercompany_sale_line_id": line.id,
        }

    def _create_reverse_intercompany_purchase_orders(self):
        Purchase = self.env["purchase.order"].sudo()
        PurchaseLine = self.env["purchase.order.line"].sudo()
        ctx = dict(
            self.env.context,
            skip_reverse_intercompany=True,
            skip_intercompany=True,
            no_intercompany_sync=True,
            skip_intercompany_sale=True,
            intercompany_skip=True,
        )
        for order in self:
            if order.intercompany_purchase_id:
                continue
            if not order.company_id.reverse_intercompany_sale_purchase:
                continue
            buyer_company = order._get_intercompany_buyer_company()
            if not buyer_company:
                continue
            lines = order.order_line.filtered(
                lambda l: not l.display_type and l.product_id and l.product_uom_qty > 0
            )
            if not lines:
                continue
            purchase_vals = order._prepare_reverse_intercompany_purchase_vals(buyer_company)
            purchase = Purchase.with_company(buyer_company).with_context(ctx).create(purchase_vals)
            for line in lines:
                PurchaseLine.with_company(buyer_company).with_context(ctx).create(
                    order._prepare_reverse_intercompany_purchase_line_vals(line, purchase)
                )
            purchase.with_company(buyer_company).with_context(ctx).button_confirm()
            order.sudo().write({
                "intercompany_purchase_id": purchase.id,
                "intercompany_buyer_company_id": buyer_company.id,
            })
