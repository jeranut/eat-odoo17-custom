from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    intercompany_sale_id = fields.Many2one(
        "sale.order",
        string="Intercompany Sale Order",
        copy=False,
        readonly=True,
    )
    is_reverse_intercompany_purchase = fields.Boolean(
        string="Reverse Intercompany Purchase",
        copy=False,
        readonly=True,
    )


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    intercompany_sale_line_id = fields.Many2one(
        "sale.order.line",
        string="Intercompany Sale Line",
        copy=False,
        readonly=True,
    )
