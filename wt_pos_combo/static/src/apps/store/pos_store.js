/** @odoo-module */

import { PosStore } from "@point_of_sale/app/store/pos_store";
import { patch } from "@web/core/utils/patch";
import { PosDB } from "@point_of_sale/app/store/db";
import { WtPosComboConfigurePopup } from "@wt_pos_combo/apps/popup/PosComboConfigurePopup/PosComboConfigurePopup";
	
patch(PosStore.prototype, {
	async _processData(loadedData) {
		await super._processData(...arguments);
		this.db.pos_combos_by_id = {};
		this.db.pos_combos_items_by_id = {};
		this.db.add_pos_combo(loadedData['wt.pos.combo']);
		this.db.add_pos_combo_items(loadedData['pos.combo.item']);
	},

	async addProductToCurrentOrder(product, options = {}) {
		super.addProductToCurrentOrder(...arguments);
		if(product.is_required){
			let { confirmed, payload } = this.env.services.popup.add(WtPosComboConfigurePopup, {
				product: product,
				pos_combo_id: product.pos_combo_id[0],
				selected_lines: null,
			});
		}
    },
});


patch(PosDB.prototype, {
	add_pos_combo(combos){
		if(combos){
			combos.forEach((combo) => {
				this.pos_combos_by_id[combo.id] = combo;
			});
		}
	},
	add_pos_combo_items: function(combo_items){
		if(combo_items){
			combo_items.forEach((combo_item) => {
				this.pos_combos_items_by_id[combo_item.id] = combo_item;
			});
		}
	},
	get_pos_combos_by_id(combo_id){
		if (combo_id instanceof Array) {
			var list = [];
			for (var i = 0, len = combo_id.length; i < len; i++) {
				var combo = this.pos_combos_by_id[combo_id[i]];
				if (combo) {
					list.push(combo);
				} else {
					console.error("get_pos_combos_by_id: no combo has id:", combo_id[i]);
				}
			}
			return list;
		} else {
			return this.pos_combos_by_id[combo_id];
		}
	},
	get_pos_combos_items_by_id(combo_item_id){
		if (combo_item_id instanceof Array) {
			var list = [];
			for (var i = 0, len = combo_item_id.length; i < len; i++) {
				var combo_item = this.pos_combos_items_by_id[combo_item_id[i]];
				if (combo_item) {
					list.push(combo_item);
				} else {
					console.error("get_pos_combos_items_by_id: no combo item has id:", combo_item_id[i]);
				}
			}
			return list;
		} else {
			return this.pos_combos_items_by_id[combo_item_id];
		}
	},
});