# -*- coding: utf-8 -*-
from odoo import fields, models, Command, api
from collections import defaultdict

import logging

_logger = logging.getLogger(__name__)

class PosPreparationDisplayOrder(models.Model):
    _inherit = 'pos_preparation_display.order'

    def _export_for_ui(self, preparation_display):
        res = super(PosPreparationDisplayOrder, self)._export_for_ui(preparation_display)
        try:

            if res and res.get('orderlines'):
                for orderline in res.get('orderlines'):
                    line_display_id = self.env['pos_preparation_display.orderline'].browse(orderline.get('id'))
                    if line_display_id:
                        orderline['pos_order_line_id'] = line_display_id.pos_order_line_id.id if line_display_id.pos_order_line_id else False

                res['combo_lines'] = self.get_order_combo_display_data()

        except Exception as e:
            _logger.warning(e)

        return res

    def get_order_combo_display_data(self):
        data = {}
        try:
            if self.preparation_display_order_line_ids:
                for line in self.preparation_display_order_line_ids:
                    data[line.id] = {}
                    if line.pos_order_line_id:
                        for c_line in line.pos_order_line_id.combo_items_ids:
                            if not data[line.id].get(c_line.category_id.name):
                                data[line.id][c_line.category_id.name] = []
                            data[line.id][c_line.category_id.name].append(c_line.name)
                            
                return data
        except Exception as e:
            _logger.warning(e)
            
        return data
    
class PosPreparationDisplayOrderline(models.Model):
    _inherit = 'pos_preparation_display.orderline'

    pos_order_line_id = fields.Many2one('pos.order.line', string="POS Order Line")