/** @odoo-module */

import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";
import { patch } from "@web/core/utils/patch";

patch(TicketScreen.prototype,{
    async addAdditionalRefundInfo(order, destinationOrder) {
        // used by L10N, e.g: add a refund reason using a specific L10N field
        for (const line of destinationOrder.get_orderlines()) {
            const refund_line = order.get_orderlines().filter((refund_line) => refund_line.id == line.refunded_orderline_id)
            if(refund_line.length){
                const combo_lines = refund_line[0].combo_lines
                line.set_combo_lines(combo_lines)
            }            
        }
        debugger
        return await super.addAdditionalRefundInfo(...arguments);
    }
});