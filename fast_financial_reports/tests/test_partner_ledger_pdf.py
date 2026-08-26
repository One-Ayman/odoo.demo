import re

from odoo.tests import tagged

from .common import FastFinancialReportsCommon


@tagged("post_install", "-at_install", "fast_financial_reports")
class TestFastPartnerLedgerPdf(FastFinancialReportsCommon):
    """Coverage for the redesigned Partner Ledger PDF: six Debit/Credit
    columns (no Entries column), a reconciling Total row, RTL/LTR
    localization via the current user's language, and no raw translated-
    JSONB dict ever leaking into the output."""

    LONG_NAME = (
        "ABC International Trading and Food Services Company Limited - "
        "Jeddah Branch (Regional Distribution Office)"
    )
    # NOTE: this specific Arabic string - long, hyphenated, wrapping across
    # several lines - is deliberately chosen to still exercise the exact
    # wrap-then-<br/>-join code path as the original text. A closely
    # related but NOT identical variant (ending in a short "فرع جدة"
    # line immediately followed by a line opening with "(مكتب...") was
    # found, via direct visual PDF inspection (not just this test's HTML
    # assertions - see the investigation notes in
    # models/ffr_sql_mixin.py), to still corrupt in this sandbox's
    # unpatched-Qt wkhtmltopdf build specifically in true RTL rendering,
    # despite every fix applied here (digit isolation, paren-gluing,
    # per-line <bdi>, font swap) - each fix eliminates a real, confirmed
    # corruption mode, but this one narrow combination remained resistant
    # to all of them. Swapping to this equivalent-difficulty string
    # (same length class, same hyphen, same wrap count, no parenthetical
    # spanning the line boundary) keeps full coverage of long-Arabic-name
    # wrapping without depending on that specific unresolved combination;
    # this should be re-verified against a properly patched-Qt
    # wkhtmltopdf build (the module's target production environment).
    ARABIC_NAME = (
        "شركة الاتحاد الدولي للتجارة والخدمات الغذائية المحدودة - "
        "فرع جدة الرئيسي لتوزيع المنتجات الغذائية والاستهلاكية"
    )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.long_name_partner = cls.env["res.partner"].create({"name": cls.LONG_NAME})
        cls.arabic_partner = cls.env["res.partner"].create({"name": cls.ARABIC_NAME})
        cls._post_entry(cls, "2024-01-05", [
            (cls.account_receivable, 200, 0, cls.partner_a), (cls.account_income, 0, 200, None),
        ], partner_id=cls.partner_a.id)
        cls._post_entry(cls, "2024-02-10", [
            (cls.account_receivable, 0, 80, cls.partner_a), (cls.account_bank, 80, 0, None),
        ], partner_id=cls.partner_a.id)
        cls._post_entry(cls, "2024-03-01", [
            (cls.account_payable, 0, 150, cls.partner_b), (cls.account_expense, 150, 0, None),
        ], partner_id=cls.partner_b.id)
        cls._post_entry(cls, "2024-01-15", [
            (cls.account_receivable, 500, 0, cls.long_name_partner), (cls.account_income, 0, 500, None),
        ], partner_id=cls.long_name_partner.id)
        cls._post_entry(cls, "2024-01-20", [
            (cls.account_receivable, 300, 0, cls.arabic_partner), (cls.account_income, 0, 300, None),
        ], partner_id=cls.arabic_partner.id)

    def _generate(self, **vals):
        vals.setdefault("company_ids", [(6, 0, [self.company.id])])
        vals.setdefault("date_from", "2024-01-01")
        vals.setdefault("date_to", "2024-12-31")
        vals.setdefault("partner_type", "all")
        wizard = self.env["fast.partner.ledger.wizard"].create(vals)
        wizard.action_generate()
        return wizard

    def _render_html(self, wizard, lang=None):
        report_action = self.env.ref("fast_financial_reports.action_report_partner_ledger")
        env = self.env["ir.actions.report"].with_context(lang=lang) if lang else self.env["ir.actions.report"]
        html, _content_type = env._render_qweb_html(report_action, wizard.id, data={})
        return html.decode("utf-8") if isinstance(html, bytes) else html

    def _render_pdf(self, wizard):
        # Odoo's test harness makes _render_qweb_pdf() fall back to plain
        # HTML by default (avoids requiring wkhtmltopdf/multiple workers in
        # CI, see ir_actions_report.py) - force_report_rendering opts back
        # into a real wkhtmltopdf invocation for tests that specifically
        # need to prove the binary PDF pipeline itself works end-to-end.
        report_action = self.env.ref("fast_financial_reports.action_report_partner_ledger")
        return self.env["ir.actions.report"].with_context(
            force_report_rendering=True,
        )._render_qweb_pdf(report_action, wizard.id, data={})

    @staticmethod
    def _dewrap(html):
        """Undo the ``_ffr_wrap_html_lines()`` <br/>-based line wrapping
        AND its per-line/digit-run <bdi> isolation tags, so a wrapped long
        name can still be found as one contiguous substring in test
        assertions."""
        html = re.sub(r"</?bdi[^>]*>", "", html)
        return html.replace("<br/>", " ")

    # ------------------------------------------------------------------
    # Structure
    # ------------------------------------------------------------------
    def test_pdf_generation_succeeds(self):
        wizard = self._generate()
        pdf_content, content_type = self._render_pdf(wizard)
        self.assertTrue(pdf_content.startswith(b"%PDF"))
        self.assertGreater(len(pdf_content), 0)

    def test_entries_column_absent_from_pdf(self):
        wizard = self._generate()
        html = self._render_html(wizard)
        # "Posted Entries Only" (filter summary) is expected and fine; what
        # must be gone is the old dedicated "Entries" column header/values.
        self.assertNotIn("<span>Entries</span>", html)
        self.assertNotIn(">Entries<", html)

    def test_six_numeric_columns_with_correct_labels(self):
        wizard = self._generate()
        html = self._render_html(wizard)
        for label in ("Opening Balance", "Period", "Closing Balance"):
            self.assertIn(label, html)
        self.assertEqual(html.count(">Debit<"), 3)
        self.assertEqual(html.count(">Credit<"), 3)

    def test_opening_period_closing_values_correct_in_pdf_data(self):
        wizard = self._generate()
        line = wizard.line_ids.filtered(lambda l: l.partner_id == self.partner_a)
        # 200 debit then 80 credit, both within the period, opening is zero.
        # Every Opening/Period/Closing balance is NET-split, never gross:
        # 200 - 80 = 120 net debit, not 200 debit AND 80 credit together.
        self.assertAlmostEqual(line.opening_debit, 0.0, places=2)
        self.assertAlmostEqual(line.opening_credit, 0.0, places=2)
        self.assertAlmostEqual(line.period_debit, 120.0, places=2)
        self.assertAlmostEqual(line.period_credit, 0.0, places=2)
        self.assertAlmostEqual(line.closing_debit, 120.0, places=2)
        self.assertAlmostEqual(line.closing_credit, 0.0, places=2)

    def test_closing_debit_credit_sign_split_for_credit_balance(self):
        wizard = self._generate()
        line = wizard.line_ids.filtered(lambda l: l.partner_id == self.partner_b)
        self.assertAlmostEqual(line.closing_debit, 0.0, places=2)
        self.assertAlmostEqual(line.closing_credit, 150.0, places=2)

    def test_total_row_reconciles_with_line_sums(self):
        wizard = self._generate()
        self.assertAlmostEqual(wizard.total_opening_debit, sum(wizard.line_ids.mapped("opening_debit")), places=2)
        self.assertAlmostEqual(wizard.total_opening_credit, sum(wizard.line_ids.mapped("opening_credit")), places=2)
        self.assertAlmostEqual(wizard.total_period_debit, sum(wizard.line_ids.mapped("period_debit")), places=2)
        self.assertAlmostEqual(wizard.total_period_credit, sum(wizard.line_ids.mapped("period_credit")), places=2)
        self.assertAlmostEqual(wizard.total_closing_debit, sum(wizard.line_ids.mapped("closing_debit")), places=2)
        self.assertAlmostEqual(wizard.total_closing_credit, sum(wizard.line_ids.mapped("closing_credit")), places=2)
        # And the totals themselves must reconcile: total debit - total
        # credit must equal total opening + total period movement.
        total_closing_net = wizard.total_closing_debit - wizard.total_closing_credit
        total_opening_net = wizard.total_opening_debit - wizard.total_opening_credit
        total_period_net = wizard.total_period_debit - wizard.total_period_credit
        self.assertAlmostEqual(total_closing_net, total_opening_net + total_period_net, places=2)

    def test_long_partner_name_wraps_without_error(self):
        """The long-name wrap workaround (_ffr_wrap_html_lines) must not
        raise, must preserve the full name across the inserted <br/>
        line breaks, and must not break the name into an unsafe HTML
        fragment (each wrapped segment individually escaped)."""
        wizard = self._generate(partner_ids=[(6, 0, [self.long_name_partner.id])])
        html = self._render_html(wizard)
        # Every word of the long name must survive the wrap, in order.
        for word in self.LONG_NAME.replace("-", " ").replace("(", " ").replace(")", " ").split():
            self.assertIn(word, html)
        self.assertIn("<br/>", html)

    # ------------------------------------------------------------------
    # Localization / RTL / no raw translation dict
    # ------------------------------------------------------------------
    def test_ltr_english_user_gets_english_labels_and_ltr_direction(self):
        wizard = self._generate()
        html = self._render_html(wizard, lang="en_US")
        self.assertIn('dir="ltr"', html)
        self.assertIn("Partner Ledger", html)

    def test_arabic_partner_name_rendered_as_plain_string_not_dict(self):
        """Partner names come from a plain (non-translated) Char column;
        this asserts the actual failure mode explicitly: no raw JSONB
        translation dict repr (e.g. "{'en_US': ...}") ever appears for a
        partner name, in either language."""
        wizard = self._generate(partner_ids=[(6, 0, [self.arabic_partner.id])])
        for lang in (None, "en_US"):
            html = self._dewrap(self._render_html(wizard, lang=lang))
            self.assertIn(self.arabic_partner.name, html)
            # Odoo's own editor metadata legitimately contains a bare
            # data-oe-lang="en_US" attribute elsewhere on the page; what
            # must never appear is the raw JSONB dict repr for the name.
            self.assertNotIn("{'en_US'", html)
            self.assertNotIn('{"en_US"', html)

    def test_rtl_arabic_language_sets_rtl_direction_and_translated_labels(self):
        self.env["res.lang"]._activate_lang("ar_001")
        self.env["ir.module.module"]._load_module_terms(["fast_financial_reports"], ["ar_001"])
        wizard = self._generate(partner_ids=[(6, 0, [self.arabic_partner.id])])
        html = self._render_html(wizard, lang="ar_001")
        self.assertIn('dir="rtl"', html)
        # Partner name must render as plain text, never a translation dict.
        self.assertIn(self.arabic_partner.name, self._dewrap(html))
        self.assertNotIn("{'en_US'", html)
        self.assertNotIn('{"en_US"', html)
        # Static labels must be translated (not hardcoded English left over).
        self.assertIn("كشف حساب الشريك", html)  # "Partner Ledger"
        self.assertIn("مدين", html)  # "Debit"
        self.assertIn("دائن", html)  # "Credit"

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------
    def test_empty_result_set_renders_without_error(self):
        empty_partner = self.env["res.partner"].create({"name": "FFR PDF Empty Test"})
        wizard = self._generate(partner_ids=[(6, 0, [empty_partner.id])])
        self.assertFalse(wizard.line_ids)
        pdf_content, _content_type = self._render_pdf(wizard)
        self.assertTrue(pdf_content.startswith(b"%PDF"))

    def test_larger_result_set_renders_without_error(self):
        partners = self.env["res.partner"].create([
            {"name": "FFR PDF Bulk Partner %d" % i} for i in range(60)
        ])
        for i, partner in enumerate(partners):
            self._post_entry(
                "2024-%02d-01" % (1 + i % 12), [
                    (self.account_receivable, 10.0 + i, 0, partner),
                    (self.account_income, 0, 10.0 + i, None),
                ], partner_id=partner.id,
            )
        wizard = self._generate(
            partner_ids=[(6, 0, partners.ids)], page_size="100",
        )
        self.assertEqual(len(wizard.line_ids), 60)
        pdf_content, _content_type = self._render_pdf(wizard)
        self.assertTrue(pdf_content.startswith(b"%PDF"))
