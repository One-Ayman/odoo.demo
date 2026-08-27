/** @odoo-module */

import { onWillStart } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { Orderline } from "@pos_preparation_display/app/components/orderline/orderline";

patch(Orderline.prototype, {
    getcombolines(){
    	debugger
    	return this.props.orderline.order.combo_lines[this.props.orderline.id] || {}
    }
});