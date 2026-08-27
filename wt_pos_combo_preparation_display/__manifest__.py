# -*- coding: utf-8 -*-
{
    'name':'WT Pos Combo Preparation Display',
    'version':'17.0.0.1',
    'summary':'Pos Combo Preparation Display',
    'description':'Pos Combo Preparation Display.',
    'category':'Sales/Point of Sale',
    'website': 'https://www.warlocktechnologies.com',
    'depends':['web','point_of_sale','pos_preparation_display','wt_pos_combo'],
    'data':[
    ],
    'assets':{
        'pos_preparation_display.assets': [
            "/wt_pos_combo_preparation_display/static/src/apps/models/order.js",
            "/wt_pos_combo_preparation_display/static/src/apps/components/orderline/orderline.js",
            "/wt_pos_combo_preparation_display/static/src/apps/components/orderline/orderline.xml",
        ],
    },
    'external_dependencies': {
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3'
}