/** @odoo-module **/

import { Component } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/store/pos_hook";
import { PosComboProductItem } from "@wt_pos_combo/apps/popup/PosComboConfigurePopup/combocategory/PosComboProductItem/PosComboProductItem";

export class ComboCatProducts extends Component {
	static template = "wt_pos_combo.ComboCatProducts";
	static components = { PosComboProductItem };
	setup() {
        super.setup();
        this.pos = usePos();
        this.products_ids = this.props.combo_cat_obj.product_ids || false;
        this.product_ids_sequence = this.props.combo_cat_obj.product_ids_sequence;
    }
    get combo_product_items(){
    	var self = this;
        var products = [];
        if (this.product_ids_sequence){   
        	var product_ids_sequence = ((this.product_ids_sequence.replace('[','')).replace(']','')).split(',')
        	var products_ids = []
        	var product_ids = this.products_ids;
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
            this.products_ids = products_ids
        }
        for (const product of this.products_ids){
        	const combo_product = self.pos.db.get_product_by_id(product)
        	if(combo_product){
        		products.push(combo_product)
        	}
        }

        return products;
    }
}