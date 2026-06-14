from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    reverse_intercompany_sale_purchase = fields.Boolean(
        string="Create Purchase from Intercompany Sale",
        help=(
            "When this company sells to another internal company, automatically "
            "create and confirm a purchase order in the buying company."
        ),
    )
    reverse_intercompany_auto_prepare_receipt = fields.Boolean(
        string="Prepare Receipt from Delivery",
        default=True,
        help=(
            "When the seller validates the delivery, automatically fill the related "
            "incoming receipt in the buyer company. The receipt is not validated."
        ),
    )
