/** @odoo-module */

import { WtPosComboConfigurePopup } from "@wt_pos_combo/apps/popup/PosComboConfigurePopup/PosComboConfigurePopup";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";

patch(ProductScreen.prototype,{
	selectLine(orderline) {
        super.selectLine(...arguments);
        const product = orderline.product;
        if(product && product.is_combo_product && product.pos_combo_id){
	        let { confirmed, payload } = this.env.services.popup.add(WtPosComboConfigurePopup, {
	            product: product,
	            pos_combo_id: product.pos_combo_id[0],
	            selected_lines: orderline.combo_lines,
	        });
        }
    },
});