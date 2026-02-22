import unittest

from music_key import extract_key_from_name_tokens, normalize_key_query


class MusicKeyTests(unittest.TestCase):
    def test_normalize_major_and_minor_variants(self):
        self.assertEqual(normalize_key_query("A"), "A")
        self.assertEqual(normalize_key_query("Am"), "Am")
        self.assertEqual(normalize_key_query("Amin"), "Am")
        self.assertEqual(normalize_key_query("Aminor"), "Am")
        self.assertEqual(normalize_key_query("A major"), "A")
        self.assertEqual(normalize_key_query("A maj"), "A")

    def test_normalize_flat_keys_without_b_note_confusion(self):
        self.assertEqual(normalize_key_query("B"), "B")
        self.assertEqual(normalize_key_query("Bb"), "Bb")
        self.assertEqual(normalize_key_query("Bbm"), "Bbm")
        self.assertNotEqual(normalize_key_query("B"), normalize_key_query("Bb"))

    def test_invalid_key_returns_none(self):
        self.assertIsNone(normalize_key_query(""))
        self.assertIsNone(normalize_key_query("Alydian"))
        self.assertIsNone(normalize_key_query("random"))

    def test_extract_key_from_tokens(self):
        self.assertEqual(extract_key_from_name_tokens(["kick", "120", "Bb", "loop"]), "Bb")
        self.assertEqual(extract_key_from_name_tokens(["pad", "A", "minor", "124"]), "Am")
        self.assertEqual(extract_key_from_name_tokens(["bass", "B", "loop"]), "B")
        self.assertIsNone(extract_key_from_name_tokens(["hat", "b", "loop"]))
        self.assertIsNone(extract_key_from_name_tokens(["bass", "drum", "loop"]))


if __name__ == "__main__":
    unittest.main()
