{
    'name': 'Stock Move Line Extra',
    'version': '1.0',
    'category': 'Inventory',
    'summary': 'Ajoute colonnes S.I et RESTE à stock.move.line',
    'description': 'Module qui ajoute la quantité en stock (S.I) et le reste (RESTE) sur chaque mouvement de stock.',
    'author': 'Votre Nom',
    'depends': ['stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/stock_move_line_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'stock_move_line_extra/static/src/css/stock_move_line.css',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
