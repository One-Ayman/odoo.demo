/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";

/**
 * Field widget for fleet.sales.visit's check_in_latitude field.
 *
 * Renders a "Capture My Location" button instead of an editable number
 * input. On click it reads the device's real GPS position and writes both
 * check_in_latitude and check_in_longitude onto the record -- there is no
 * way to type coordinates by hand through this widget, which is the whole
 * point: the geofence check on the server is only meaningful if the
 * coordinates it checks actually came from the device's own GPS.
 */
export class FleetSalesGpsCaptureField extends Component {
    static template = "fleet_sales_field_ops.GpsCaptureField";
    static props = { ...standardFieldProps };

    setup() {
        this.notification = useService("notification");
    }

    get isCaptured() {
        const data = this.props.record.data;
        return Boolean(data.check_in_latitude && data.check_in_longitude);
    }

    get latitude() {
        return this.props.record.data.check_in_latitude;
    }

    get longitude() {
        return this.props.record.data.check_in_longitude;
    }

    captureLocation() {
        if (!("geolocation" in navigator)) {
            this.notification.add(
                "This device/browser doesn't support location capture.",
                { type: "danger" }
            );
            return;
        }
        navigator.geolocation.getCurrentPosition(
            (position) => {
                this.props.record.update({
                    check_in_latitude: position.coords.latitude,
                    check_in_longitude: position.coords.longitude,
                });
                this.notification.add("Location captured.", { type: "success" });
            },
            (error) => {
                this.notification.add(
                    "Couldn't get your location: " + error.message,
                    { type: "danger" }
                );
            },
            { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
        );
    }
}

export const fleetSalesGpsCaptureField = {
    component: FleetSalesGpsCaptureField,
    supportedTypes: ["float"],
};

registry.category("fields").add("fleet_sales_gps_capture", fleetSalesGpsCaptureField);
