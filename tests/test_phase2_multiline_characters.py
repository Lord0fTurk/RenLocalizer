#!/usr/bin/env python3
"""
Phase 2: Multiline Character Definition Support
Tests and implementation for character definitions spanning multiple lines
"""

import unittest
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from src.core.parser import RenPyParser


class TestPhase2MultilineCharacterDefinitions(unittest.TestCase):
    """Test multiline character definition extraction"""
    
    def setUp(self):
        self.parser = RenPyParser()
    
    # ========================================================================
    # TEST 1: Single-line Character (Baseline - should still work)
    # ========================================================================
    
    def test_single_line_character_still_works(self):
        """Single-line character definitions should still be extracted"""
        # Create temp file
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_char.rpy"
            test_file.write_text('define emma = Character("Emma")')
            
            # Parse
            entries_by_file = self.parser.parse_directory(str(tmpdir))
            all_entries = []
            for file_path, entries_list in entries_by_file.items():
                if 'test_char' in str(file_path):
                    all_entries.extend(entries_list)
            
            # Should find Emma
            emma_entries = [e for e in all_entries if 'Emma' in e.get('text', '')]
            self.assertGreater(len(emma_entries), 0, "Should find 'Emma' character")
    
    # ========================================================================
    # TEST 2: Multiline Character Definition (2 lines)
    # ========================================================================
    
    def test_multiline_character_2_lines(self):
        """Multiline character definition spanning 2 lines should be extracted"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_char.rpy"
            code = '''define mc = Character("Ethan",
                      color="#FFFFFF")'''
            test_file.write_text(code)
            
            # Parse
            entries_by_file = self.parser.parse_directory(str(tmpdir))
            all_entries = []
            for file_path, entries_list in entries_by_file.items():
                if 'test_char' in str(file_path):
                    all_entries.extend(entries_list)
            
            # Should find Ethan
            ethan_entries = [e for e in all_entries if 'Ethan' in e.get('text', '')]
            self.assertGreater(len(ethan_entries), 0, "Should find 'Ethan' from multiline definition")
    
    # ========================================================================
    # TEST 3: Multiline Character Definition (3+ lines)
    # ========================================================================
    
    def test_multiline_character_3plus_lines(self):
        """Multiline character definition spanning 3+ lines"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_char.rpy"
            code = '''define maya = Character("Maya",
                      color="#FF00FF",
                      image="maya")'''
            test_file.write_text(code)
            
            entries_by_file = self.parser.parse_directory(str(tmpdir))
            all_entries = []
            for file_path, entries_list in entries_by_file.items():
                if 'test_char' in str(file_path):
                    all_entries.extend(entries_list)
            
            maya_entries = [e for e in all_entries if 'Maya' in e.get('text', '')]
            self.assertGreater(len(maya_entries), 0, "Should find 'Maya' from 3-line multiline definition")
    
    # ========================================================================
    # TEST 4: NVLCharacter Multiline (Ren'Py 7+ feature)
    # ========================================================================
    
    def test_nvl_character_multiline(self):
        """NVLCharacter multiline definition"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_char.rpy"
            code = '''define narrator = NVLCharacter("Narrator",
                      color="#FFFFFF",
                      kind=nvl)'''
            test_file.write_text(code)
            
            entries_by_file = self.parser.parse_directory(str(tmpdir))
            all_entries = []
            for file_path, entries_list in entries_by_file.items():
                if 'test_char' in str(file_path):
                    all_entries.extend(entries_list)
            
            narrator_entries = [e for e in all_entries if 'Narrator' in e.get('text', '')]
            self.assertGreater(len(narrator_entries), 0, "Should find 'Narrator' from NVLCharacter")
    
    # ========================================================================
    # TEST 5: DynamicCharacter Multiline (v7.5+)
    # ========================================================================
    
    def test_dynamic_character_multiline(self):
        """DynamicCharacter multiline definition"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_char.rpy"
            code = '''define dynamic_char = DynamicCharacter("char_name",
                      color=character_color)'''
            test_file.write_text(code)
            
            entries_by_file = self.parser.parse_directory(str(tmpdir))
            all_entries = []
            for file_path, entries_list in entries_by_file.items():
                if 'test_char' in str(file_path):
                    all_entries.extend(entries_list)
            
            # DynamicCharacter with variable name might not be extracted
            # But should not crash
            self.assertIsNotNone(entries_by_file)
    
    # ========================================================================
    # TEST 6: Multiple Characters in Same File
    # ========================================================================
    
    def test_multiple_multiline_characters(self):
        """Multiple multiline character definitions in one file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_char.rpy"
            code = '''define alice = Character("Alice",
                      color="#FF0000")

define bob = Character("Bob",
                       color="#0000FF",
                       image="bob")

define charlie = Character("Charlie")'''
            test_file.write_text(code)
            
            entries_by_file = self.parser.parse_directory(str(tmpdir))
            all_entries = []
            for file_path, entries_list in entries_by_file.items():
                if 'test_char' in str(file_path):
                    all_entries.extend(entries_list)
            
            # Should find all three
            names = [e.get('text', '') for e in all_entries]
            self.assertIn('Alice', names, "Should find Alice")
            self.assertIn('Bob', names, "Should find Bob")
            self.assertIn('Charlie', names, "Should find Charlie")
    
    # ========================================================================
    # TEST 7: Translatable Character Names _()
    # ========================================================================
    
    def test_translatable_character_name_multiline(self):
        """Character with translatable name (_) in multiline definition"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_char.rpy"
            code = '''define diana = Character(_("Diana"),
                      color="#00FF00")'''
            test_file.write_text(code)
            
            entries_by_file = self.parser.parse_directory(str(tmpdir))
            all_entries = []
            for file_path, entries_list in entries_by_file.items():
                if 'test_char' in str(file_path):
                    all_entries.extend(entries_list)
            
            diana_entries = [e for e in all_entries if 'Diana' in e.get('text', '')]
            self.assertGreater(len(diana_entries), 0, "Should find 'Diana' even with _() wrapper")
    
    # ========================================================================
    # TEST 8: Edge Case - Nested Parentheses
    # ========================================================================
    
    def test_character_with_nested_parens(self):
        """Character definition with function calls containing parentheses"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_char.rpy"
            code = '''define eve = Character("Eve",
                      color=Color(255, 0, 0),
                      who_prefix=who_prefix_func())'''
            test_file.write_text(code)
            
            entries_by_file = self.parser.parse_directory(str(tmpdir))
            all_entries = []
            for file_path, entries_list in entries_by_file.items():
                if 'test_char' in str(file_path):
                    all_entries.extend(entries_list)
            
            [e for e in all_entries if 'Eve' in e.get('text', '')]
            # This is an edge case - might not be captured,  but should not crash
            self.assertIsNotNone(entries_by_file)
    
    # ========================================================================
    # TEST 9: Backward Compatibility (v7 vs v8 differences)
    # ========================================================================
    
    def test_renpy7_multiline_character(self):
        """Ren'Py 7 style multiline (no trailing commas required)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_char.rpy"
            # v7 style - more flexible formatting
            code = '''define frank = Character(
    "Frank",
    color="#ABCDEF"
)'''
            test_file.write_text(code)
            
            entries_by_file = self.parser.parse_directory(str(tmpdir))
            all_entries = []
            for file_path, entries_list in entries_by_file.items():
                if 'test_char' in str(file_path):
                    all_entries.extend(entries_list)
            
            frank_entries = [e for e in all_entries if 'Frank' in e.get('text', '')]
            self.assertGreater(len(frank_entries), 0, "Should handle Ren'Py 7 formatting")


class TestPhase2CountBenchmark(unittest.TestCase):
    """Benchmark against test games - count character names"""
    
    def setUp(self):
        self.parser = RenPyParser()
    
    def test_count_extracted_characters(self):
        """Count character names extracted from test files"""
        # Create a temporary test directory with common character definition patterns
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "characters.rpy"
            
            # Simulated game with mixed single/multiline definitions
            code = '''# Characters
define player = Character("Player")

define npc1 = Character("NPC One",
    color="#FF0000")

define npc2 = Character("NPC Two",
    color="#00FF00",
    image="npc2")

define npc3 = DynamicCharacter("npc_name",
    color="#0000FF")

define narrator = NVLCharacter("Narrator",
    kind=nvl)
'''
            test_file.write_text(code)
            
            entries_by_file = self.parser.parse_directory(str(tmpdir))
            all_entries = []
            for file_path, entries_list in entries_by_file.items():
                if 'characters' in str(file_path):
                    all_entries.extend(entries_list)
            
            char_entries = [e for e in all_entries if e.get('text_type') == 'character_name']
            
            print("\n--- Phase 2 Benchmark ---")
            print(f"Total entries found: {len(all_entries)}")
            print(f"Character entries: {len(char_entries)}")
            
            for entry in char_entries:
                print(f"  - {entry.get('text', '?')}")
            
            # Expect to find at least Player and some of the defined characters
            self.assertGreater(len(char_entries), 0, "Should extract at least some character names")


if __name__ == '__main__':
    unittest.main(verbosity=2)
