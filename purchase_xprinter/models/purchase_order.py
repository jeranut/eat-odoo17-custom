from odoo import models, fields, api
from odoo.exceptions import UserError
import requests

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def action_print_xprinter(self):
        """Envoi du bon de commande sélectionné vers le microservice Flask"""
        url = "https://xprinter.sysadaptpro.com/print_purchase"  # <-- endpoint corrigé
        headers = {
            'X-API-KEY': 'odoo1234',
            'Content-Type': 'application/json',
        }

        for order in self:
            # Vérifier que le bon de commande est confirmé
            if order.state != 'purchase':
                raise UserError("⚠️ Le bon de commande n'est pas encore confirmé. Veuillez le confirmer avant d'imprimer.")

            # Préparer les lignes de produits
            products = []
            for line in order.order_line:
                products.append({
                    'product_name': line.product_id.display_name,
                    'qty': line.product_qty,
                    'uom': line.product_uom.name,
                    'price_unit': line.price_unit,
                    'subtotal': line.price_subtotal,
                    'stock_real': line.product_id.qty_available,  # <-- stock réel ajouté
                })

            # Préparer les données à envoyer
            payload = {
                'type': 'purchase_order',
                'order_name': order.name,
                'supplier': order.partner_id.name or '',
                'date_order': str(order.date_order),
                'amount_total': order.amount_total,
                'products': products,
            }

            try:
                response = requests.post(url, json=payload, headers=headers, timeout=15)
                if response.status_code != 200:
                    raise UserError(f"Erreur Flask ({response.status_code}): {response.text}")
            except Exception as e:
                raise UserError(f"Erreur de connexion au serveur d'impression : {e}")

        return True
