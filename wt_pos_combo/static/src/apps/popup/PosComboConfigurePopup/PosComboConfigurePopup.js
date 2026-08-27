/** @odoo-module */

import { AbstractAwaitablePopup } from "@point_of_sale/app/popup/abstract_awaitable_popup";
import { _t } from "@web/core/l10n/translation";
import { useRef, useState, onWillStart, Component, useExternalListener, onMounted } from "@odoo/owl";
import { useBus, useService } from "@web/core/utils/hooks";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { PosComboItemDetails } from "@wt_pos_combo/apps/popup/PosComboConfigurePopup/PosComboComponant"
import { PosComboProductItem } from "@wt_pos_combo/apps/popup/PosComboConfigurePopup/combocategory/PosComboProductItem/PosComboProductItem";
import { ComboCatProducts } from "@wt_pos_combo/apps/popup/PosComboConfigurePopup/combocategory/ComboCatProducts";
import { groupBy } from "@web/core/utils/arrays";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
// import { PosBus } from "@point_of_sale/app/bus/pos_bus_service";

export class WtPosComboConfigurePopup extends AbstractAwaitablePopup {
	static template = "wt_pos_combo.WtPosComboConfigurePopup";
	static components = { PosComboItemDetails, ComboCatProducts, PosComboProductItem };
	setup() {
		super.setup();
		this.orm = useService("orm");
		this.pos = usePos();
		this.product = this.props.product || false;
		this.pos_combo_id = this.props.pos_combo_id || false;
		this.is_editable_pp = this.props.selected_lines ? true : false;
		this.selected_lines = this.props.selected_lines || [];
		this.total_combo_items = 0;
		this.line_combo_items = 0;
		this.state = useState({
			selected_lines: this.selected_lines
		});
		this._updateComboCart();
		useExternalListener(window, "mouseup", this.onOutsideClick);
	}
	get is_required(){
		return this.product.is_required;
	}
	get combo_info(){
		return this.pos.db.get_pos_combos_by_id(this.pos_combo_id);
	}
	get combo_cat_items(){
		var self = this;
		var combo_items = self.pos.db.get_pos_combos_items_by_id(this.combo_info.pos_combo_items_ids)
		return combo_items.sort(function(a,b){
			return a.sequence - b.sequence;
		});
	}
	get combo_lines(){
		return this.selected_lines;
	}

	get check_is_max(){
		var self = this;
		var category_data = {};
		for (const item of this.combo_cat_items){
			var qtys_total = 0
			for (const combo_key of Object.keys(self.combo_lines)){
				if(combo_key == item.category_id[0]){
					qtys_total += self.combo_lines[combo_key].map((item) => item.qty).reduce((a, b) => a + b, 0)
				}
			}
			category_data[item.category_id[0]] = qtys_total;
		}
		return category_data;
	}

	get combo_items_totals(){
		return this.env.utils.formatCurrency(this.total_combo_items);
	}
	get total_main_plus_item(){
		return this.env.utils.formatCurrency(this.total_combo_items + this.product.get_display_price())
	}
	get pricelist() {
		const current_order = this.pos.get_order();
		let current_pricelist = this.pos.default_pricelist;
		if (current_order) {
			current_pricelist = current_order.pricelist;
		}
		return current_pricelist;
	}
	price(product, qty) {
        const formattedUnitPrice = this.env.utils.formatCurrency(product.get_display_price(this.pricelist, qty));
        if (product.to_weight) {
            return `${formattedUnitPrice}/${
                this.pos.units_by_id[product.uom_id[0]].name
            }`;
        } else {
            return formattedUnitPrice;
        }
    }
	render_selected_products(){
		var self = this;
		var items = $('.pos_combo_item_details').find('.product.selected');
		this.selected_lines = [];
		this.total_combo_items = 0;
		var products = [];
		if(items && items.length){
			for( const el of items){
				var data = $(el).data();
				var category = self.pos.db.get_category_by_id(data.category_id);
				var product = self.pos.db.get_product_by_id(data.product_id);
				var price = self.price(product, data.qty);
				var total_price = product.get_display_price() * data.qty;
				var unit_price = product.get_display_price();
				products.push({
					'category_id': data.category_id,
					'product_id': data.product_id,
					'product': product,
					'product_name': product.display_name,
					'category': category,
					'qty': data.qty,
					'price': price,
					'total_price': this.env.utils.formatCurrency(total_price),
					'unit_price': unit_price,
					'decimal_total_price': total_price,
					'product_for_find_id' : data.product_for_find_id,
				});
				self.total_combo_items += total_price;
			}
		}
		if(products.length){
			this.selected_lines = groupBy(products, (product) => product.category_id);
		}
		this.render();
	}

	render_editable_value(){
		var self = this;
		if(this.selected_lines != undefined){
			var products = [];
			for(const lines of Object.values(this.selected_lines)){
				for(const item of Object.values(lines)){
					var product = self.pos.db.get_product_by_id(item.product_id);
					var price = self.price(product, item.qty);
					var total_price = product.get_display_price() * item.qty;
					var unit_price = product.get_display_price();
			        products.push({
			            'category_id': item.category_id,
			            'product_id': item.product_id,
			            'product': product,
			            'product_name': item.product_name,
			            'category': item.category,
			            'qty': item.qty,
			            'price': price,
			            'total_price': self.env.utils.formatCurrency(total_price),
			            'unit_price': unit_price,
			            'decimal_total_price': total_price,
			            'product_for_find_id' : item.product_for_find_id,
			        });
			        self.total_combo_items += total_price;
				}
			}
			if(products.length){
			    this.selected_lines = groupBy(products, (product) => product.category_id);
			}
		}
		this.is_editable_pp = false;
		this.render();
	}

	async _updateComboCart(){
		if(!this.is_editable_pp){
			this.render_selected_products();
		}else{
			this.render_editable_value();
		}
	}

	check_max_limit_in_category(cate_id, combo_cat_obj_id){
		var check_is_max = this.check_is_max;
		var qtys = check_is_max[cate_id];
		if(combo_cat_obj_id.is_min_max_config && combo_cat_obj_id.max_qty && qtys >= combo_cat_obj_id.max_qty){
			return true;
		}
		return false;
	}

	onProductRemoveClick(combo_item){
		var currentTarget = $("article[data-combo_item_key='"+ combo_item +"']");
		if(currentTarget && currentTarget.length){
			currentTarget.data().qty = 0;
			currentTarget.find('.qty_text').text(0);
			currentTarget.removeClass('selected');
			this._updateComboCart()
		}
	}

	OnSelectComboProduct(combo_item){
		var currentTarget = $("article[data-combo_item_key='"+ combo_item +"']");
		if(currentTarget && currentTarget.length){
			var cat_id = parseInt(currentTarget.data('category_id'), 10);
			var combo_cat_obj = parseInt(currentTarget.data('combo_cat_obj'), 10);
			var combo_cat_obj_id = this.pos.db.get_pos_combos_items_by_id(combo_cat_obj)
			var is_valid = this.check_max_limit_in_category(cat_id, combo_cat_obj_id);

			var qty = parseInt(currentTarget.find('.qty_text').text(), 10);
			var prodict_id = parseInt(currentTarget[0].dataset.product_id, 10);
			var prodict = this.pos.db.get_product_by_id(prodict_id)
			if(is_valid){
				var error = "You can only select "+ combo_cat_obj_id.max_qty + " items from " + combo_cat_obj_id.category_id[1];
				return this.pos.popup.add(ErrorPopup, {
					title: _t("Quantity Validation"),
					body: _t(error),
				});
			}else if(qty && prodict.is_only_single){
				var error = "You can only add one quantity of "+ prodict.display_name;
				// Gui.showNotification(error)
				return this.pos.popup.add(ErrorPopup, {
					title: _t("Quantity Validation"),
					body: _t(error),
				});
			}else{
				currentTarget.addClass('selected');
				var qty = parseInt(currentTarget.find('.qty_text').text(), 10);
				var qty = qty + 1;
				currentTarget.data().qty = qty;
				currentTarget.find('.qty_text').text(qty);
				this._updateComboCart()
			}
		}
	}

	onProductMinusClick(combo_item){
		var currentTarget = $("article[data-combo_item_key='"+ combo_item +"']")
		if(currentTarget && currentTarget.length){
			var qty = parseInt(currentTarget.find('.qty_text').text(), 10);
			if(qty){
				qty = qty - 1;
				currentTarget.data().qty = qty;
				currentTarget.find('.qty_text').text(qty);
			}
			if(!qty){
				currentTarget.removeClass('selected');
			}
			this._updateComboCart()
		}
	}

	onchangeProductAttr(combo_item){
		var currentTarget = $("article[data-combo_item_key='"+ combo_item +"']")
		if(currentTarget && currentTarget.length){
			var product = parseInt(currentTarget[0].dataset.product_id, 10);
			var product_id = this.pos.db.get_product_by_id(product);
			var target = currentTarget.find('select[data-product_id='+product+']');
			var value = target.val();
			currentTarget.data().qty = 1;
			if(value){
				currentTarget.data().product_id = parseInt(value, 10);
				currentTarget.addClass('selected');
			}else{
				currentTarget.data().product_id = product_id.id;
				currentTarget.removeClass('selected');
			}
			this._updateComboCart()
		}
	}

	add_selection_items(combo_item) {
		var self = this;
		var currentTarget = $("article[data-combo_item_key='"+ combo_item +"']");
		if(currentTarget && currentTarget.length){
			var cat_id = parseInt(currentTarget.data('category_id'), 10);
			var combo_cat_obj = parseInt(currentTarget.data('combo_cat_obj'), 10);
			var combo_cat_obj_id = this.pos.db.get_pos_combos_items_by_id(combo_cat_obj)
			var product = parseInt(currentTarget[0].dataset.product_id, 10);
			var product_id = this.pos.db.get_product_by_id(product);
			var category_qty = 0
			for (const key of Object.keys(self.combo_lines).filter((line) => line == cat_id)){
				for (const line of self.combo_lines[key]){
					category_qty += line.qty
				}
			}
			var target = currentTarget.find('.product_plus_button');
			if(target.data().prods != "" && target.data().prods != '0'){
				category_qty -= 1
			}
			if(combo_cat_obj_id.is_min_max_config && combo_cat_obj_id.max_qty && category_qty >= combo_cat_obj_id.max_qty){
				var error = "You can only select "+ combo_cat_obj_id.max_qty + " items from " + combo_cat_obj_id.category_id[1];
				return this.pos.popup.add(ErrorPopup, {
					title: _t("Quantity Validation"),
					body: _t(error),
				});
			}else{
				var combo_product_attribute = this.combo_product_attribute(product_id);
				var count = 0
				var prod_length = combo_product_attribute.length
				var product_id = parseInt(target.data().product_id, 10)
				product_id = this.pos.db.get_product_by_id(product_id)
				if (target.data().prods == "") {
					var value = combo_product_attribute[count].id.toString()
					target.data().prods = count + 1
				} else {
					if (parseInt(target.data().prods) < prod_length) {
						var value = combo_product_attribute[parseInt(target.data().prods)].id.toString()
						target.data().prods = parseInt(target.data().prods) + 1
					}
				}
				currentTarget.data().qty = 1;

				if(value){
					currentTarget.data().product_id = parseInt(value, 10);
					currentTarget.addClass('selected');
				}else{
					currentTarget.data().product_id = product_id.id;
					// currentTarget.removeClass('selected');
				}
				this._updateComboCart()
			}
		}
	}

	remove_selection_items(combo_item){
		var currentTarget = $("article[data-combo_item_key='"+ combo_item +"']");
		if(currentTarget && currentTarget.length){
			var cat_id = parseInt(currentTarget.data('category_id'), 10);
			var product = parseInt(currentTarget[0].dataset.product_id, 10);
			var product_id = this.pos.db.get_product_by_id(product);
			var combo_product_attribute = this.combo_product_attribute(product_id);
			var count = 0
			// var prod_length = combo_product_attribute.length
			var previousElementtarget = currentTarget.find('.product_plus_button');
			var value = null
			if(previousElementtarget.data().prods != "0"){
				if(parseInt(previousElementtarget.data().prods) <= combo_product_attribute.length){
					previousElementtarget.data().prods = parseInt(previousElementtarget.data().prods) - 1
					value = combo_product_attribute[parseInt(previousElementtarget.data().prods)].id.toString()
				}

			}else {
				var qty = parseInt(currentTarget.find('.qty_text').text(), 10);
				if(qty){
					qty = qty - 1;
					currentTarget.data('qty', qty);
					currentTarget.find('.qty_text').text(qty);
				}
				if(!qty){
					currentTarget.removeClass('selected');
				}
				previousElementtarget.data().prods = 0;
				this._updateComboCart();
			}
			currentTarget.data().qty = 1;

			if(value){
				currentTarget.data().product_id = parseInt(value, 10);
				currentTarget.addClass('selected');
			}else{
				currentTarget.data().product_id = product_id.id;
				// currentTarget.removeClass('selected');
			}
			this._updateComboCart();
		}

	}

	combo_product_attribute(product){
		var db = this.pos.db
		var combo_product_attribute_ids = [];

		var products = [];
		if (product.combo_product_attribute_ids_sequence){   
			var product_ids_sequence = ((product.combo_product_attribute_ids_sequence.replace('[','')).replace(']','')).split(',')
			
			var products_ids = []
			var product_ids = product.combo_product_attribute_ids
			for (const i of product_ids_sequence){
				if(product_ids.includes(parseInt(i))){
					products_ids.push(parseInt(i))
				}
			}
			for (const p of product_ids){
				if(!products_ids.includes(p)){
					products_ids.push(p)
				}   
			}

			for (const product of products_ids){
				const obj_product = db.get_product_by_id(product);
				if(obj_product){
					combo_product_attribute_ids.push(obj_product)
				}	
			}
			
		}else{
			for (const attribute_id of this.props.product.combo_product_attribute_ids){
				const obj_product = db.get_product_by_id(attribute_id);
				if(obj_product){
					combo_product_attribute_ids.push(obj_product)
				}
			}
		}
		
		return combo_product_attribute_ids
	}

	check_is_valid_or_not(){
        var self = this;
        var flag = true;
        var error = '';
        for (const item of this.combo_cat_items){
			var qtys_total = 0
			for (const combo_key of Object.keys(self.combo_lines)){
				if(combo_key == item.category_id[0]){
					qtys_total += self.combo_lines[combo_key].map((item) => item.qty).reduce((a, b) => a + b, 0)
				}
			}
			if(item.is_min_max_config && item.min_qty && qtys_total < item.min_qty){
                error = "You must have to select " + item.min_qty +" item from "+ item.category_id[1];
                flag = false;
                break;
            }
		}
        if(error){
            this.pos.popup.add(ErrorPopup, {
				title: _t("Quantity Validation"),
				body: _t(error),
			});
        }
        return flag;
    }
    async confirm() {
        this._updateComboCart();
        var s_orderline = this.pos.get_order().get_selected_orderline();
        var is_valid = this.check_is_valid_or_not();
        if(is_valid){
            s_orderline.set_combo_lines(this.combo_lines);
            this.cancel();
        }
    }
    onOutsideClick(ev){
		if(this.product.is_required){
			return;
		}
    	if($(ev.target).find('.pos_combo_configure_popup').length){
    		this.cancel();
    	}
    }
}