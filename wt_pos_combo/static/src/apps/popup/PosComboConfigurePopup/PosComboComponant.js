/** @odoo-module */

import { useRef, useState, onWillStart, Component } from "@odoo/owl";
import { ComboCatProducts } from "@wt_pos_combo/apps/popup/PosComboConfigurePopup/combocategory/ComboCatProducts";

export class PosComboItemDetails extends Component {
	static template = "wt_pos_combo.PosComboItemDetails";
	static components = { ComboCatProducts };
	select_categories(event){
		var cat_id = $(event.currentTarget).data('pos_combo_cate_id');
        $(".combo_pack_box li").removeClass('active');
        $(".combo_pack_box li[data-pos_combo_cate_id='"+cat_id+"']").addClass('active');
        $(".product_display_block_combo").removeClass('active');
        $(".product_display_block_combo[data-pos_combo_cate_id='"+cat_id+"']").addClass('active');
		// this.trigger('updateComboCart');
	}
}


