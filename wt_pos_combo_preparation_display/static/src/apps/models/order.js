/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Order } from "@pos_preparation_display/app/models/order";

patch(Order.prototype, {
    setup(order) {
        super.setup(...arguments);
        this.combo_lines = order.combo_lines
    }
});