from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    fleet_sales_mada_journal_id = fields.Many2one(
        related="company_id.fleet_sales_mada_journal_id",
        readonly=False,
        string="Mada / Card Collections Journal",
    )
