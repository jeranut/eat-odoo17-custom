from odoo import models


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _action_done(self, cancel_backorder=False):
        # Appel du comportement standard d’Odoo
        res = super()._action_done(cancel_backorder=cancel_backorder)

        # Filtrer uniquement les mouvements liés à un achat reçu en stock interne
        for move in self.filtered(lambda m:
            m.purchase_line_id
            and m.state == 'done'
            and m.location_dest_id.usage == 'internal'
        ):
            product = move.product_id
            supplier = move.purchase_line_id.partner_id
            new_cost = move.purchase_line_id.price_unit
            product_template = product.product_tmpl_id

            # ✅ Liste des fournisseurs spéciaux (pas de marge)
            special_suppliers = ['GLP DEPOT', 'GLP PRODUCTION', 'PIETRA ANALAKELY']

            # ✅ Détermination du prix de vente selon le fournisseur
            if supplier.name.upper() in [s.upper() for s in special_suppliers]:
                new_sale_price = new_cost  # même prix que le coût
            else:
                new_sale_price = new_cost * 1.10  # +10%

            # ✅ Mise à jour du coût et du prix de vente
            product.sudo().write({
                'standard_price': new_cost,
                'list_price': new_sale_price
            })

            # ✅ Recherche ou création de la fiche fournisseur (supplierinfo)
            supplierinfo = self.env['product.supplierinfo'].search([
                ('partner_id', '=', supplier.id),
                ('product_tmpl_id', '=', product_template.id),
                ('min_qty', '=', 1.0),
            ], limit=1)

            if supplierinfo:
                supplierinfo.sudo().write({
                    'price': new_cost
                })
            else:
                self.env['product.supplierinfo'].sudo().create({
                    'partner_id': supplier.id,
                    'product_tmpl_id': product_template.id,
                    'price': new_cost,
                    'currency_id': move.company_id.currency_id.id,
                    'min_qty': 1.0,
                })

        return res
