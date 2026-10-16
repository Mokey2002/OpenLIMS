from django.test import SimpleTestCase

from assistant.registration_input import parse_registration_fields


class RegistrationInputTests(SimpleTestCase):
    def test_duplicate_json_keys_are_rejected_at_every_depth(self):
        for value in ['{"x": 1, "x": 2}', '[{"x": 1, "x": 2}]']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_registration_fields("source=" + value)

    def test_unsafe_json_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_registration_fields('source={"\\u0000": "bad"}')

    def test_valid_unicode_and_json_values_are_preserved(self):
        self.assertEqual(parse_registration_fields('source="café 🧪", data={"ok": [true, 1, null]}'),
                         {"source": "café 🧪", "data": {"ok": [True, 1, None]}})
