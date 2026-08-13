from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    fleet_sales_mada_journal_id = fields.Many2one(
        "account.journal",
        string="Mada / Card Collections Journal",
        domain=[("type", "=", "bank")],
        help="Bank journal used for Mada (card) collections registered "
        "from Fleet Sales visits. Payments booked to this journal from a "
        "visit are always created as draft receipt vouchers -- Finance "
        "must review and post them; the salesman's action never posts a "
        "bank payment directly.",
    )

    def _fleet_sales_set_default_mada_journal_demo(self):
        """Demo-data helper only. Points Mada collections at whatever bank
        journal the company already has, instead of creating a brand new
        one -- a fresh bank journal's automatically-created outstanding
        account can end up unlinked from any company in some setups, and
        reusing an existing, already-correctly-configured journal avoids
        that entirely.
        """
        for company in self:
            if company.fleet_sales_mada_journal_id:
                continue
            bank_journal = self.env["account.journal"].search(
                [("type", "=", "bank"), ("company_id", "=", company.id)],
                limit=1,
            )
            if bank_journal:
                company.fleet_sales_mada_journal_id = bank_journal.id
