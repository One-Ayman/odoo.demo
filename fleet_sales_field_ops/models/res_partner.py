from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    enforce_visit_geofence = fields.Boolean(
        string="Enforce Visit Location Check",
        default=True,
        help="If enabled, a salesman can only check in to a visit for this "
        "customer while within Visit Geofence Radius of the customer's "
        "registered location. Turn off for a specific customer if their "
        "GPS coordinates aren't reliable (e.g. no location captured yet, "
        "or a customer that is visited from multiple legitimate sites).",
    )
    visit_geofence_radius = fields.Integer(
        string="Visit Geofence Radius (m)",
        default=150,
        help="Maximum distance, in meters, allowed between the salesman's "
        "device and this customer's location for a visit check-in to "
        "succeed. Only enforced when Enforce Visit Location Check is on.",
    )
