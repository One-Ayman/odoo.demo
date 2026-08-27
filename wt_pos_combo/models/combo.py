# Part of Warlock Technolab
from odoo import fields, models, api, _
import json

class PosSession(models.Model):
    _inherit = 'pos.session'

    def _pos_ui_models_to_load(self):
        result = super()._pos_ui_models_to_load()
        result.append('wt.pos.combo')
        result.append('pos.combo.item')
        return result

    def _get_pos_ui_wt_pos_combo(self, params):
        return self.env['wt.pos.combo'].search_read(**params['search_params'])

    def _get_pos_ui_pos_combo_item(self, params):
        return self.env['pos.combo.item'].search_read(**params['search_params'])

    def _loader_params_product_template(self):
        result = super()._loader_params_product_template()
        for field_key in ['is_combo_product', 'pos_combo_id','is_only_single','combo_product_attribute_ids','menu_type_selection','combo_product_attribute_ids_sequence','is_required']:
            result['search_params']['fields'].append(field_key)
        return result

    def _loader_params_product_product(self):
        result = super()._loader_params_product_product()
        for field_key in ['is_combo_product', 'pos_combo_id','is_only_single','combo_product_attribute_ids','menu_type_selection','combo_product_attribute_ids_sequence','is_required']:
            result['search_params']['fields'].append(field_key)
        return result

    def _loader_params_wt_pos_combo(self):
        return {
            'search_params': {
                'domain': [],
                'fields': ['name','pos_combo_items_ids'],
            },
        }

    def _loader_params_pos_combo_item(self):
        return {
            'search_params': {
                'domain': [],
                'fields': ['sequence','pos_combo_id','category_id','product_ids','is_min_max_config', 'max_qty', 'min_qty','product_ids_sequence'],
            },
        }

class WtPosCombo(models.Model):
    _name = 'wt.pos.combo'
    _description = 'name'
    _rec_name = 'name'

    name = fields.Char(string="Name", required=True)
    pos_combo_items_ids = fields.One2many('pos.combo.item', 'pos_combo_id', string="Products", required=True)

    
class PosComboItems(models.Model):
    _name = 'pos.combo.item'
    _description = 'product_id'

    sequence = fields.Integer(default="10")
    product_sequence = fields.Char()
    product_ids_sequence = fields.Char()
    pos_combo_id = fields.Many2one('wt.pos.combo', string="Combo", ondelete='cascade')
    category_id = fields.Many2one('pos.category', string="Category", required=True)
    product_ids = fields.Many2many('product.product', string="Item", required=True)
    is_min_max_config = fields.Boolean(string="Is Set Min-Max Quantity")
    max_qty = fields.Integer(string="Max Qty")
    min_qty = fields.Integer(string="Min Qty")

    @api.onchange('product_ids')
    def on_chanage_product_ids(self):
        product_ids = self.product_ids.ids
        product_names = self.product_ids.mapped('name')
        if self.product_ids_sequence:
            if not self.product_sequence:
                self.product_sequence = self.product_ids_sequence
            product_ids_sequence = json.loads(self.product_ids_sequence)
            product_sequence = json.loads(self.product_sequence)
        else:
            product_ids_sequence = []
            product_sequence = []

        for pis in product_ids:
            if pis not in product_ids_sequence:
                product_ids_sequence.append(pis)

        for piss in product_ids_sequence:
            if piss not in product_ids:
                product_ids_sequence.remove(piss)

        for pis in product_names:
            if pis not in product_sequence:
                product_sequence.append(pis)

        for piss in product_sequence:
            if piss not in product_names:
                product_sequence.remove(piss)

        self.product_ids_sequence = json.dumps(product_ids_sequence)
        self.product_sequence = json.dumps(product_sequence)

class ProductsTemplate(models.Model):
    _inherit = 'product.template'

    is_combo_product = fields.Boolean(string="Is Combo")
    pos_combo_id = fields.Many2one('wt.pos.combo', string="POS Combo")
    is_required = fields.Boolean(string="Is Required", default=False)
    is_only_single = fields.Boolean(string="Is Only Single")
    combo_product_attribute_ids = fields.Many2many("product.product", "combo_product_attribute_rel", "combo_product_id", "combo_attribute_id", string="Combo Product Attributes", domain="[('available_in_pos', '=', True)]")
    combo_product_attribute_sequence = fields.Char()
    combo_product_attribute_ids_sequence = fields.Char()
    menu_type_selection = fields.Selection(
            selection=[
                ("drop_down", "Drop Down"),
                ("plus_minus", "Plus Minus"),
            ], default='drop_down'
        )

    @api.onchange('combo_product_attribute_ids')
    def on_chanage_product_ids(self):
        combo_product_attribute_ids = self.combo_product_attribute_ids.ids
        product_names = self.combo_product_attribute_ids.mapped('name')
        if self.combo_product_attribute_ids_sequence:
            if not self.combo_product_attribute_sequence:
                self.combo_product_attribute_sequence = self.combo_product_attribute_ids_sequence
            combo_product_attribute_ids_sequence = json.loads(self.combo_product_attribute_ids_sequence)
            combo_product_attribute_sequence = json.loads(self.combo_product_attribute_sequence)
        else:
            combo_product_attribute_ids_sequence = []
            combo_product_attribute_sequence = []

        for pis in combo_product_attribute_ids:
            if pis not in combo_product_attribute_ids_sequence:
                combo_product_attribute_ids_sequence.append(pis)

        for piss in combo_product_attribute_ids_sequence:
            if piss not in combo_product_attribute_ids:
                combo_product_attribute_ids_sequence.remove(piss)

        for pis in product_names:
            if pis not in combo_product_attribute_sequence:
                combo_product_attribute_sequence.append(pis)

        for piss in combo_product_attribute_sequence:
            if piss not in product_names:
                combo_product_attribute_sequence.remove(piss)
        self.combo_product_attribute_ids_sequence = json.dumps(combo_product_attribute_ids_sequence)
        self.combo_product_attribute_sequence = json.dumps(combo_product_attribute_sequence)

class PosOrder(models.Model):
    _inherit = "pos.order"

    def _prepare_order_line(self, order_line):
        order_line = super()._prepare_order_line(order_line)
        combo_items_ids = []
        if order_line['combo_items_ids']:
            for combo in order_line["combo_items_ids"]:
                cline = self.env['pos.order.line.combo.items'].search_read([('id', '=', combo)])[0]
                combo_items_ids.append([0, 0, cline])
        order_line["combo_items_ids"] = combo_items_ids
        return order_line

    def _get_fields_for_order_line(self):
        fields = super(PosOrder, self)._get_fields_for_order_line()
        fields.append('combo_items_ids')
        return fields

    # breck new coupon genrate functionality
    def confirm_coupon_programs(self, coupon_data):
        coupon_data_dic = {}
        for k, v in coupon_data.items():
            if int(k) > 0:
                coupon_data_dic[k] = v
        return super(PosOrder, self).confirm_coupon_programs(coupon_data_dic)

class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    is_combo = fields.Boolean("Is Combo")
    combo_items_ids = fields.One2many("pos.order.line.combo.items", 'orderline_id', "Combo Items")

    def open_combo_items(self):
        self.ensure_one()
        view_id = self.env.ref('wt_pos_combo.combo_email_compose_message_wizard_form').id
        return  {'type': 'ir.actions.act_window',
                'name': _('Extra Toppings'),
                'res_model': 'combo.items.wizard',
                'target': 'new',
                'view_mode': 'form',
                'views': [[view_id, 'form']],
            }

    def _export_for_ui(self, orderline):
        res = super(PosOrderLine, self)._export_for_ui(orderline)
        res['combo_items_ids'] = [[0, 0, combo] for combo in orderline.combo_items_ids.export_for_ui()] if orderline.combo_items_ids else []
        res['is_combo'] = orderline.is_combo
        return res

class pos_order_line_combo_items(models.Model):
    _name = "pos.order.line.combo.items"
    _description = 'name'
    _rec_name = 'name'

    name = fields.Char(string="Name", compute="_compute_combo_item")
    orderline_id = fields.Many2one('pos.order.line', 'POS Line')
    product_id = fields.Many2one('product.product', 'Product')
    category_id = fields.Many2one('pos.category', string="Category")
    price = fields.Float('Item Price', required=True)
    qty = fields.Float('Quantity', default=1)
    total_price = fields.Float(string="Total", compute="_compute_combo_item")

    def _export_for_ui(self, combo):
        return {
            'product_id': combo.product_id.id,
            'category_id': combo.category_id.id,
            'price': combo.price,
            'qty': combo.qty,
            'total_price': combo.total_price
        }

    def export_for_ui(self):
        return self.mapped(self._export_for_ui) if self else []

    def _compute_combo_item(self):
        for rec in self:
            if rec.product_id :
                rec.name = rec.product_id.display_name +' X '+ str(rec.qty)
            else:
                rec.name = '/'
            if rec.price and rec.qty:
                rec.total_price = rec.price * rec.qty
            else:
                rec.total_price = 0

class pos_order_line_combo_items_wizard(models.TransientModel):
    _name = 'combo.items.wizard'
    _description = 'Extra Toppings'

    combo_ids = fields.Many2many('pos.order.line.combo.items', string="Combo")

    @api.model
    def default_get(self, fields):
        line = False
        if self.env.context and self.env.context.get('active_id'):
            line = self.env['pos.order.line'].sudo().browse(self.env.context.get('active_id'))
        result = super(pos_order_line_combo_items_wizard, self).default_get(fields)
        if line:
            result['combo_ids'] = line.combo_items_ids
        return result