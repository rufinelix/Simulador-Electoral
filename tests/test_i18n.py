import unittest
from core.i18n import t, set_lang, get_current_lang, SUPPORTED_LANGUAGES, MESSAGES
import streamlit as st


class TestI18n(unittest.TestCase):
    def setUp(self):
        # Reset session_state
        if "app_language" in st.session_state:
            del st.session_state["app_language"]

    def test_default_language_is_spanish(self):
        self.assertEqual(get_current_lang(), "es")
        self.assertIn("Simulador", t("app_title"))

    def test_switch_to_english(self):
        set_lang("en")
        self.assertEqual(get_current_lang(), "en")
        self.assertIn("Simulator", t("app_title"))
        self.assertIn("Seats", t("seats"))

    def test_formatting_parameters(self):
        set_lang("es")
        formatted_es = t("poll_candidates_expander", poll="GAD3", count=15)
        self.assertIn("GAD3", formatted_es)
        self.assertIn("15", formatted_es)

        set_lang("en")
        formatted_en = t("poll_candidates_expander", poll="GAD3", count=15)
        self.assertIn("GAD3", formatted_en)
        self.assertIn("15", formatted_en)

    def test_fallback_for_missing_key(self):
        set_lang("en")
        # Non-existent key should return fallback or key itself
        self.assertEqual(t("non_existent_key_xyz"), "non_existent_key_xyz")
        self.assertEqual(t("non_existent_key_xyz", default="Custom Default"), "Custom Default")


if __name__ == "__main__":
    unittest.main()
