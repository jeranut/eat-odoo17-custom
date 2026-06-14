# -*- coding: utf-8 -*-
import requests
from odoo import fields, models, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    def action_print_invoice_xprinter(self):
        endpoint = "https://xprinter.sysadaptpro.com/print_invoice"
        headers = {'X-API-KEY': 'odoo1234', 'Content-Type': 'application/json'}

        for move in self:
            # Vérifications
            if move.move_type not in ("out_invoice", "out_refund"):
                raise UserError(_("L'impression Xprinter est réservée aux factures client."))
            if move.state != "posted":
                raise UserError(_("Veuillez valider la facture avant impression."))

            partner = move.partner_id
            company = move.company_id

            # Préparer les lignes (on prend tout, même sections/notes)
            lines = []
            for l in move.invoice_line_ids:
                lines.append({
                    "product": l.product_id.display_name if l.product_id else (l.name or "Article"),
                    "product_name": l.name or "",
                    "quantity": float(l.quantity or 0.0),
                    "qty": float(l.quantity or 0.0),
                    "price_unit": float(l.price_unit or 0.0),
                    "discount": float(l.discount or 0.0),
                    "subtotal": float(l.price_subtotal or 0.0),
                    "subtotal_incl": float(l.price_total or 0.0),
                    "uom": l.product_uom_id.name if l.product_uom_id else 'u',
                })

            if not lines:
                raise UserError(_("Aucune ligne à imprimer sur cette facture."))

            # Payload pour Flask
            payload = {
                "invoice": {
                    "name": move.name or move.ref or "",
                    "date": fields.Date.to_string(
                        move.invoice_date or move.date or fields.Date.context_today(self)
                    ),
                },
                "company": {"name": company.display_name or company.name or ""},
                "partner": {"name": partner.display_name or partner.name or ""},
                "amounts": {
                    "untaxed": float(move.amount_untaxed or 0.0),
                    "tax": float(move.amount_tax or 0.0),
                    "total": float(move.amount_total or 0.0),
                    "residual": float(move.amount_residual or 0.0),
                },
                "lines": lines,
            }

            # Envoi vers Flask
            try:
                r = requests.post(endpoint, json=payload, headers=headers, timeout=15)
            except Exception as e:
                raise UserError(_("Impossible de contacter le service d'impression: %s") % e)

            if not (200 <= r.status_code < 300):
                try:
                    msg = r.json()
                except Exception:
                    msg = r.text
                raise UserError(_("Erreur d'impression (HTTP %s): %s") % (r.status_code, msg))

            move.message_post(
                body=_("Facture envoyée à Xprinter via Flask. Réponse: %s") % r.text
            )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Impression Xprinter"),
                "message": _("Facture(s) envoyée(s) à l'imprimante."),
                "sticky": False,
            },
        }
