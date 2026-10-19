import unittest
from pathlib import Path
from arknights_unpacker.extraction.engine import validate_output_root, safe_component
from arknights_unpacker.extraction.decoder import normalize_flatbuffer

class EngineBoundaryTests(unittest.TestCase):
    def test_output_cannot_be_inside_game(self):
        with self.assertRaises(ValueError):
            validate_output_root(Path('D:/game/out'), [Path('D:/game')])
    def test_names_cannot_escape(self):
        self.assertNotIn('/', safe_component('../../a'))
        self.assertNotIn('\\', safe_component('..\\a'))
    def test_empty_dictionary_vector_preserved(self):
        class Fake:
            def Entries(self, i):
                return None
            def EntriesLength(self):
                return 0
            def EntriesIsNone(self):
                return False
        value, evidence = normalize_flatbuffer(Fake())
        self.assertEqual(value['entries'], [])
        self.assertEqual(evidence['/entries']['state'], 'empty_vector')
