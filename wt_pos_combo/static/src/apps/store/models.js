/** @odoo-module */

import { Order, Orderline, Product } from "@point_of_sale/app/store/models";
const { DateTime } = luxon;
import { patch } from "@web/core/utils/patch";
import { Component } from "@odoo/owl";
import { groupBy } from "@web/core/utils/arrays";

patch(Order.prototype, {
    getOrderChanges(skipped = false) {
        const changes = super.getOrderChanges(...arguments);
        for (const orderlineIdx in this.orderlines) {
            const orderline = this.orderlines[orderlineIdx];
            const note = orderline.getNote();
            const lineKey = `${orderline.uuid} - ${note}`;
            if(changes.orderlines[lineKey]){
                changes.orderlines[lineKey]['combo_items'] = orderline.combo_customer_data
            }
        }
        return changes
    },
});


patch(Orderline.prototype, {
    // components: { ...Orderline.components, ComboOrderLine },
    setup(_defaultObj, options) {
        super.setup(...arguments);
        if(options.json && options.json.combo_lines){
            this.combo_lines = options.json.combo_lines;
        }else{
            this.combo_lines = this.combo_lines || {};          
        }
        this.combo_customer_data = [];
        this.set_combo_customer_data();
    },
    set_combo_lines(combo_lines){
        this.combo_lines = combo_lines;
        this.update_unit_price();
        this.set_combo_customer_data();
        this.order._updateRewards()
        // if (this.pos.config.iface_customer_facing_display) this.pos.send_current_order_to_customer_facing_display();
    },
    update_unit_price(){
        var self = this;
        var total = 0;
        var combo_lines = this.get_combo_lines() || {};
        if(combo_lines != undefined){
            for(const combo_line of Object.values(combo_lines)){
                for(const item of Object.values(combo_line)){
                    total += item.product.get_price() * item.qty
                }
            }
        }
        var cprice = total;
        this.set_price_extra(cprice);
        this.set_unit_price(this.product.get_price(this.order.pricelist, this.get_quantity(), this.get_price_extra()));
        this.set_quantity(this.get_quantity())
        this.order.fix_tax_included_price(this);
    },

    set_combo_customer_data(){
        var self = this;
        var combo = [];
        var combo_lines = this.get_combo_lines() || {};
        if(combo_lines != undefined){
            for(const key of Object.keys(combo_lines)){
                var products = [];
                for(const item of Object.values(combo_lines[key])){
                    products.push({
                        'item_name': item.product_name,
                        'item_qty': item.qty,
                        'item_price': item.price,
                        'item_total_price': item.total_price
                    });
                }
                var value = {
                    'category': self.pos.db.get_category_by_id(key).name,
                    'items': products
                }
                combo.push(value);
            }
        }
        this.combo_customer_data = combo;
    },
    get_combo_customer_data(){
        return this.combo_customer_data;
    },
    get_combo_lines(){
        return this.combo_lines;
    },
    export_as_JSON() {
        const json = super.export_as_JSON(...arguments);
        json['combo_items_ids'] = this.product.is_combo_product ? this.export_combo_items_lines() : [];
        json['is_combo'] = this.product.is_combo_product && this.combo_lines ? true : false;
        return json;
    },
    export_combo_items_lines(){
        var lines = [];
        var combo_lines = this.get_combo_lines() || {};
        if(combo_lines != undefined){
            for(const clines of Object.values(combo_lines)){
                for(const item of Object.values(clines)){
                    lines.push([0, 0, {
                        'product_id': item.product_id,
                        'category_id': item.category_id,
                        'price': item.unit_price,
                        'qty': parseInt(item.qty)
                    }]);
                }
            }
        }
        return lines;
    },
    init_from_JSON(json) {
        super.init_from_JSON(...arguments);
        var self = this;
        this.combo_lines = json.combo_lines;
        if(this.combo_lines == undefined && json.combo_items_ids && json.combo_items_ids.length){
            var com_products = [];
            for(const cline of json.combo_items_ids){
                if(cline[0] == 0 && cline[1] == 0){
                    var co_line = cline[2];
                    var pricelist = self.order.pricelist;
                    var product = self.pos.db.get_product_by_id(co_line.product_id);
                    var category = self.pos.db.get_category_by_id(co_line.category_id);
                    com_products.push({
                        category_id: co_line.category_id,
                        product_id: co_line.product_id,
                        product: product,
                        product_name: product.display_name,
                        category: category,
                        qty: co_line.qty,
                        // price: elf.getComboFormatCurrency(co_line.price),
                        // total_price: self.getComboFormatCurrency(co_line.total_price),
                        price: co_line.price,
                        total_price: co_line.price * co_line.qty,
                        unit_price: co_line.price,
                        decimal_total_price: co_line.price * co_line.qty,
                    });
                }
            }
            if(com_products.length){
                this.set_combo_lines(groupBy(com_products, (product) => product.category_id))
            }
        }
    },
    can_be_merged_with(orderline){
        if(this.combo_lines && this.combo_lines.length){
            return false
        }
        return super.can_be_merged_with(...arguments)
    },
    get_category_data(id){
        var category_by_ids = {}
        var combo_lines = this.get_combo_lines()
        var category_data = this.pos.db.get_category_by_id(Object.keys(combo_lines))
        for(const category_id of category_data){
            category_by_ids[category_id.id] = category_id
        }
        return category_by_ids;
    },
    getDisplayData() {
        return {
            ...super.getDisplayData(),
            is_combo_product: this.product.is_combo_product,
            combo_lines: this.get_combo_lines(),
            combo_category_data: this.get_category_data(),
        };
    },
});

patch(Product.prototype, {
    get_price(pricelist, quantity, price_extra = 0, recurring = false) {
        if(this.is_combo_product){
            const date = DateTime.now();
            if (recurring && !pricelist) {
                alert(
                    _t(
                        "An error occurred when loading product prices. " +
                            "Make sure all pricelists are available in the POS."
                    )
                );
            }

            const rules = !pricelist
                ? []
                : (this.applicablePricelistItems[pricelist.id] || []).filter((item) =>
                      this.isPricelistItemUsable(item, date)
                  );

            let price = this.lst_price + (price_extra || 0);
            const rule = rules.find((rule) => !rule.min_quantity || quantity >= rule.min_quantity);
            if (!rule) {
                return price;
            }

            if (rule.base === "pricelist") {
                const base_pricelist = this.pos.pricelists.find(
                    (pricelist) => pricelist.id === rule.base_pricelist_id[0]
                );
                if (base_pricelist) {
                    price = this.get_price(base_pricelist, quantity, 0, true);
                    if(price_extra){
                        price += price_extra
                    }
                }
            } else if (rule.base === "standard_price") {
                price = this.standard_price;
                if(price_extra){
                    price += price_extra
                }
            }

            if (rule.compute_price === "fixed") {
                price = rule.fixed_price;
                if(price_extra){
                    price += price_extra
                }
            } else if (rule.compute_price === "percentage") {
                price = price - price * (rule.percent_price / 100);
            } else {
                var price_limit = price;
                price -= price * (rule.price_discount / 100);
                if (rule.price_round) {
                    price = round_pr(price, rule.price_round);
                }
                if (rule.price_surcharge) {
                    price += rule.price_surcharge;
                }
                if (rule.price_min_margin) {
                    price = Math.max(price, price_limit + rule.price_min_margin);
                }
                if (rule.price_max_margin) {
                    price = Math.min(price, price_limit + rule.price_max_margin);
                }
            }

            // This return value has to be rounded with round_di before
            // being used further. Note that this cannot happen here,
            // because it would cause inconsistencies with the backend for
            // pricelist that have base == 'pricelist'.
            return price;
        }
        return super.get_price(...arguments);
    },
});

