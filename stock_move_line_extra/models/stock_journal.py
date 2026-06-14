# -*- coding: utf-8 -*-
from odoo import models, fields, api

# ==========================================================
# Modèle stock.journal : Stockage des valeurs historiques
# ==========================================================
class StockJournal(models.Model):
    _name = 'stock.journal'
    _description = 'Stock History Journal (SI/SF)'

    move_line_id = fields.Many2one(
        'stock.move.line',
        string='Ligne de Mouvement',
        required=True,
        ondelete='cascade'
    )

    stock_initial = fields.Float(
        string='Stock Initial (SI)',
        digits='Product Unit of Measure'
    )
    stock_final = fields.Float(
        string='Stock Final (SF)',
        digits='Product Unit of Measure'
    )

    product_id = fields.Many2one(
        'product.product',
        string='Produit',
        related='move_line_id.product_id',
        store=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Société',
        related='move_line_id.company_id',
        store=True
    )
    product_categ_id = fields.Many2one(
        'product.category',
        string='Catégorie produit',
        related='move_line_id.product_id.categ_id',
        store=True
    )


# ==========================================================
# Héritage stock.move.line
# ==========================================================
class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    stock_journal_ids = fields.One2many(
        'stock.journal',
        'move_line_id',
        string='Historique SI / SF'
    )

    stock_initial = fields.Float(
        string='Stock Initial (SI)',
        compute='_compute_journal_values',
        digits='Product Unit of Measure'
    )
    stock_final = fields.Float(
        string='Stock Final (SF)',
        compute='_compute_journal_values',
        digits='Product Unit of Measure'
    )

    uom_ratio = fields.Float(
        string='Ratio UoM',
        compute='_compute_uom_ratio',
        store=False
    )

    product_uom_category_id = fields.Many2one(
        'uom.category',
        string='Catégorie UoM',
        related='product_uom_id.category_id',
        store=False,
        readonly=True
    )
    picking_id = fields.Many2one(
        'stock.picking',
        string='Document d’origine',
        related='move_id.picking_id',
        store=True,
        readonly=True
    )
    move_id = fields.Many2one(
        'stock.move',
        string="Mouvement associé",
        readonly=True
    )
    product_categ_id = fields.Many2one(
        comodel_name="product.category",
        string="Catégorie produit",
        compute="_compute_product_categ",
        store=True
    )
    date_month = fields.Char(string='Mois', compute='_compute_date_parts', store=True)
    date_day = fields.Char(string='Jour', compute='_compute_date_parts', store=True)

    # ----------------------------------------------------------
    # Découpage de la date
    # ----------------------------------------------------------
    @api.depends('date')
    def _compute_date_parts(self):
        for line in self:
            if line.date:
                line.date_month = line.date.strftime('%Y-%m')
                line.date_day = line.date.strftime('%Y-%m-%d')
            else:
                line.date_month = False
                line.date_day = False

    # ----------------------------------------------------------
    # Calcul product_categ_id optimisé
    # ----------------------------------------------------------
    @api.depends('stock_journal_ids')
    def _compute_product_categ(self):
        for line in self:
            if line.stock_journal_ids:
                # Prend la catégorie du premier journal
                line.product_categ_id = line.stock_journal_ids[0].product_categ_id
            else:
                # Sinon fallback sur le produit
                line.product_categ_id = line.product_id.categ_id

    # ----------------------------------------------------------
    # Calcul du ratio exact UoM / produit
    # ----------------------------------------------------------
    @api.depends('product_id', 'product_uom_id')
    def _compute_uom_ratio(self):
        for line in self:
            ratio = 1.0
            if line.product_id and line.product_uom_id:
                if line.product_uom_id.category_id == line.product_id.uom_id.category_id:
                    ratio = line.product_uom_id.factor / line.product_id.uom_id.factor
            line.uom_ratio = ratio

    # ----------------------------------------------------------
    # Calcul SI/SF depuis stock.journal
    # ----------------------------------------------------------
    @api.depends('stock_journal_ids')
    def _compute_journal_values(self):
        for line in self:
            journal = line.stock_journal_ids[:1]
            line.stock_initial = journal.stock_initial if journal else 0.0
            line.stock_final = journal.stock_final if journal else 0.0

    # ----------------------------------------------------------
    # _action_done multi-entreprise et batch
    # ----------------------------------------------------------
    def _action_done(self):
        journal_buffer = {}

        # 1️⃣ Préparer le stock initial et assigner la catégorie
        for line in self:
            if line.state not in ('done', 'cancel') and not line.stock_journal_ids:
                location_for_si = line.location_id if line.location_id.usage == 'internal' else line.location_dest_id

                # Filtre par company_id pour multi-entreprise
                qty_initial = sum(self.env['stock.quant'].search([
                    ('product_id', '=', line.product_id.id),
                    ('location_id', '=', location_for_si.id),
                    ('company_id', '=', line.company_id.id),
                ]).mapped('quantity'))

                journal_buffer[line.id] = qty_initial
                # Assignation directe pour le group_by
                line.product_categ_id = line.product_id.categ_id

        # 2️⃣ Appel du comportement standard
        result = super(StockMoveLine, self)._action_done()

        # 3️⃣ Préparer la création des journaux en batch
        journal_vals = []
        for line in self:
            if line.id in journal_buffer and not line.stock_journal_ids:
                location_for_sf = (
                    line.location_dest_id if line.location_dest_id.usage == 'internal'
                    else line.location_id if line.location_id.usage == 'internal'
                    else False
                )
                qty_final = 0.0
                if location_for_sf:
                    qty_final = sum(self.env['stock.quant'].search([
                        ('product_id', '=', line.product_id.id),
                        ('location_id', '=', location_for_sf.id),
                        ('company_id', '=', line.company_id.id),
                    ]).mapped('quantity'))

                journal_vals.append({
                    'move_line_id': line.id,
                    'stock_initial': journal_buffer[line.id],
                    'stock_final': qty_final,
                    'product_categ_id': line.product_categ_id.id,
                })

        # 4️⃣ Création batch
        if journal_vals:
            self.env['stock.journal'].create(journal_vals)

        return result


# ==========================================================
# Wizard pour filtrer les mouvements
# ==========================================================
class StockMoveLineFilterWizard(models.TransientModel):
    _name = 'stock.move.line.filter.wizard'
    _description = 'Filtrer les mouvements de stock'

    product_id = fields.Many2one('product.product', string='Produit')
    date_from = fields.Date(string='Date depuis', default=fields.Date.context_today)
    date_to = fields.Date(string='Date jusqu\'à', default=fields.Date.context_today)

    def apply_filter(self):
        domain = []
        context = dict(self.env.context)

        if self.product_id:
            domain.append(('product_id', '=', self.product_id.id))
            context['filter_product_name'] = self.product_id.display_name
        if self.date_from:
            domain.append(('date', '>=', self.date_from))
            context['filter_date_from'] = str(self.date_from)
        if self.date_to:
            domain.append(('date', '<=', self.date_to))
            context['filter_date_to'] = str(self.date_to)

        action = self.env.ref('stock_move_line_extra.action_stock_move_line_kanban_filtered').read()[0]
        action['domain'] = domain
        action['context'] = context
        return action
