
import os
import sys
from pathlib import Path

# Add src to path
sys.path.append(os.getcwd())

from src.core.parser import RenPyParser

def verify_false_positives():
    parser = RenPyParser()
    
    # Cases that SHOULD be extracted
    positive_cases = [
        ('define MC_NAME = "Rhiannon"', "Rhiannon"),
        ('$ gallery.button("Unlockable Gallery Item")', "Unlockable Gallery Item"),
        ('$ gallery_gup.button("Special Item")', "Special Item"),
        ('default QUEST_DESC = "Kill the dragon"', "Kill the dragon"),
        ('$ my_ui.notify("Something happened!")', ""), # Not in TIER1 unless I added it? Wait.
        ('$ renpy.notify("Alert")', "Alert"), # Standard Tier 1
    ]
    
    # Cases that SHOULD NOT be extracted (False Positives)
    negative_cases = [
        'define VERSION = "1.2.3"',
        'define IMAGE_PATH = "images/bg/forest.png"',
        '$ renpy.play("audio/music.ogg")',
        '$ gallery.image("images/gallery/pic1.webp")',
        'define GAME_STATE = "playing"', # Should this be skipped? Probably intercepted by snake_case check if it was raw, but here it's inside quotes.
        '$ config.developer = "auto"',
        'define _INTERNAL = "hidden"',
    ]

    print("--- Running False Positive & Verification Test ---")
    
    # Test file content
    content = "\n".join([c[0] for c in positive_cases] + negative_cases)
    test_file = Path("tests/fp_test.rpy")
    test_file.write_text(content, encoding='utf-8')
    
    entries = parser.extract_text_entries(test_file)
    extracted_texts = [e['text'] for e in entries]
    
    print("\n[POSITIVE CASES]")
    for code, expected in positive_cases:
        if not expected: continue
        found = expected in extracted_texts
        status = "PASS" if found else "FAIL"
        print(f"Code: {code:40} | Expected: {expected:25} | Result: {status}")

    print("\n[NEGATIVE CASES (Should be EMPTY)]")
    for code in negative_cases:
        any(text in code for text in extracted_texts if text and text in code)
        # Check specifically for the string value
        found_val = False
        parts = code.split('"')
        if len(parts) >= 2:
            val = parts[1]
            found_val = val in extracted_texts
        
        status = "PASS (Skipped)" if not found_val else "FAIL (Extracted)"
        val_str = parts[1] if len(parts) >= 2 else "N/A"
        print(f"Code: {code:40} | Value: {val_str:25} | Result: {status}")

    # Special check for "playing"
    if "playing" in extracted_texts:
         print("\nNOTE: 'playing' was extracted. This is an edge case. If it's a game state, it might be a false positive.")

if __name__ == "__main__":
    verify_false_positives()
