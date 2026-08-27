/** @odoo-module **/

import { Component } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/store/pos_hook";

export class PosComboProductItem extends Component {
	static template = "wt_pos_combo.PosComboProductItem";
	setup() {
		super.setup();
		this.pos = usePos();
	}
	get imageUrl() {
        const product = this.props.product;
        return `/web/image?model=product.product&field=image_128&id=${product.id}&write_date=${product.write_date}&unique=1`;
    }

    get combo_product_attribute(){
        var db = this.pos.db
        var combo_product_attribute_ids = [];
        var products = [];
        if (this.props.product.combo_product_attribute_ids_sequence){   
            var product_ids_sequence = ((this.props.product.combo_product_attribute_ids_sequence.replace('[','')).replace(']','')).split(',')
            
            var products_ids = []
            var product_ids = this.props.product.combo_product_attribute_ids
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
    get select_product_name(){
        var name = '';
        var self = this;
        var prod_id = this.props.product.id;
        var cate_id = this.props.combo_cat_obj.category_id[0];
        if(this.props.combo_lines != undefined){
            for (const key of Object.keys(self.props.combo_lines)){
                for (const item of self.props.combo_lines[key]){
                    if(item.category_id == cate_id && item.product_for_find_id == prod_id){
                        name = item.product.display_name
                    }
                }
            }
        }
        return name;
    }

    get select_qty(){
        var qty_selected = 0;
        var self = this;
        var prod_id = this.props.product.id;
        var cate_id = this.props.combo_cat_obj.category_id[0];
        if(this.props.combo_lines != undefined){
            for (const key of Object.keys(self.props.combo_lines)){
                for (const item of self.props.combo_lines[key]){
                    if(item.category_id == cate_id && item.product_id == prod_id){
                        qty_selected = item.qty;
                    }
                }
            }
        }
        return qty_selected;
    }

    get select_item(){
        var selected = '';
        var self = this;
        var prod_id = this.props.product.id;
        var cate_id = this.props.combo_cat_obj.category_id[0];
        if(this.props.combo_lines != undefined){
            for (const key of Object.keys(self.props.combo_lines)){
                for (const item of self.props.combo_lines[key]){
                    if(item.category_id == cate_id && item.product_id == prod_id){
                        selected = 'selected';
                    }
                    if(item.category_id == cate_id && item.product_for_find_id == prod_id){
                        selected = 'selected';
                    }
                }
            }
        }
        return selected;
    }

}