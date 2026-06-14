from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    intercompany_source_delivery_id = fields.Many2one(
        "stock.picking",
        string="Source Intercompany Delivery",
        copy=False,
        readonly=True,
    )
    intercompany_receipt_prepared = fields.Boolean(
        string="Intercompany Receipt Prepared",
        copy=False,
        readonly=True,
    )

    def button_validate(self):
        res = super().button_validate()
        done_pickings = self.filtered(lambda p: p.state == "done")
        done_pickings._prepare_reverse_intercompany_receipts()
        return res

    def _prepare_reverse_intercompany_receipts(self):
        for picking in self.sudo():
            sale = picking.sale_id
            if not sale or not sale.intercompany_purchase_id:
                continue
            if picking.picking_type_code != "outgoing":
                continue
            if not sale.company_id.reverse_intercompany_auto_prepare_receipt:
                continue

            purchase = sale.intercompany_purchase_id.sudo()
            incoming_pickings = purchase.picking_ids.filtered(
                lambda p: p.picking_type_code == "incoming" and p.state not in ("done", "cancel")
            )
            if not incoming_pickings:
                continue
            receipt = incoming_pickings[0]
            receipt.action_assign()

            delivered_by_sale_line = {}
            for move in picking.move_ids_without_package.filtered(lambda m: m.state == "done"):
                sale_line = move.sale_line_id
                if not sale_line:
                    continue
                delivered_by_sale_line[sale_line.id] = delivered_by_sale_line.get(sale_line.id, 0.0) + move.product_uom_qty

            for po_line in purchase.order_line.filtered("intercompany_sale_line_id"):
                qty = delivered_by_sale_line.get(po_line.intercompany_sale_line_id.id, 0.0)
                if not qty:
                    continue
                receipt_moves = receipt.move_ids_without_package.filtered(
                    lambda m: m.purchase_line_id.id == po_line.id and m.state not in ("done", "cancel")
                )
                for move in receipt_moves:
                    qty_to_set = min(qty, move.product_uom_qty)
                    qty -= qty_to_set
                    move._set_intercompany_done_quantity(qty_to_set)
                    if qty <= 0:
                        break

            receipt.write({
                "intercompany_source_delivery_id": picking.id,
                "intercompany_receipt_prepared": True,
            })


class StockMove(models.Model):
    _inherit = "stock.move"

    def _set_intercompany_done_quantity(self, qty):
        """Compatible helper for Odoo 16/17 quantity done differences."""
        self.ensure_one()
        if "quantity_done" in self._fields:
            self.quantity_done = qty
            return
        if "quantity" in self._fields:
            self.quantity = qty
            return
        move_lines = self.move_line_ids
        if move_lines:
            field_name = "qty_done" if "qty_done" in move_lines._fields else "quantity"
            move_lines[0][field_name] = qty
