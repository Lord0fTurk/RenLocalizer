# -*- coding: utf-8 -*-
"""
Tests for Syntax Guard corruption survival and token recovery engine.
Verifies that corrupted tokens (mutated hex, altered brackets, OCR-like typos,
transliterations, and space injections) introduced during machine translation
are faithfully recovered by restore_renpy_syntax.
"""
from pathlib import Path
import random
from src.core.parser import RenPyParser
from src.core.syntax_guard import (
    protect_renpy_syntax,
    restore_renpy_syntax,
    validate_translation_integrity,
)

# Robust synthetic Ren'Py strings covering tags, variables, escapes, formatting
SYNTHETIC_CORPUS = [
    "{b}Welcome, [player_name]!{/b}",
    "Your score is {color=#00ff00}[score]{/color} out of 100.",
    "{i}Thinking: [thoughts]{/i}",
    "Hello [player.name], you found [item_count] gold!",
    "{size=+4}Chapter [chap_num]: The Beginning{/size}",
    "{cps=25}Text appears slowly...{/cps}{w=1.0}{fast} and then resumes.",
    "Health: [hp]/[max_hp] ({color=#f00}[hp_pct]% remaining{/color})",
    "{font=gui/font.ttf}Custom font text with [hero_name] here.{/font}",
    "Item received: [[Ancient Relic]] - Value: [item.val]G",
    "{alpha=0.5}Ghostly presence: [ghost_name]{/alpha}",
    "Progress: %d%% complete for user %(user)s",
    "{b}{i}Nested bold italic with [param]{/i}{/b}",
    "{#disambig_id}Start New Adventure with [companion]",
]


def test_syntax_guard_corruption_recovery():
    """Verify that syntax guard successfully recovers from realistic translation corruptions."""
    # Collect corpus from synthetic cases + any repository .rpy samples
    test_strings = list(SYNTHETIC_CORPUS)

    repo_rpy = list(Path("examples").glob("*.rpy")) if Path("examples").exists() else []
    if repo_rpy:
        parser = RenPyParser()
        for rpy in repo_rpy:
            entries = parser.extract_text_entries(str(rpy))
            for entry in entries:
                txt = entry.get("text", "")
                if txt and ("{" in txt or "[" in txt) and txt not in test_strings:
                    test_strings.append(txt)

    assert len(test_strings) >= len(SYNTHETIC_CORPUS)

    total_strings = 0
    corrupted_count = 0
    recovered_count = 0
    failed_count = 0

    random.seed(42)

    for text in test_strings:
        protected_text, placeholders = protect_renpy_syntax(text)
        if not placeholders:
            continue

        total_strings += 1

        # Test 1: Uncorrupted round-trip baseline
        restored_clean = restore_renpy_syntax(protected_text, placeholders)
        missing_clean = validate_translation_integrity(restored_clean, placeholders)
        assert not missing_clean, f"Clean round-trip failed for: {text!r} -> {restored_clean!r}"

        # Test 2: Deliberate token corruptions
        corrupted_text = protected_text
        has_corruptions = False

        for key in list(placeholders.keys()):
            if key.startswith("__WRAPPER_PAIR") or key.startswith("__TAG_"):
                continue

            if "RLPH" in key:
                inner = key.strip("\u27e6\u27e7")
                parts = inner.split("_")
                if len(parts) >= 2:
                    hex_part = parts[0]
                    suff_part = parts[1]

                    # Select a corruption strategy deterministically/pseudorandomly
                    strategy = random.choice(["typo_rlph", "hex_ocr", "spaces", "brackets"])

                    if strategy == "typo_rlph":
                        # Typo in prefix: RLPH -> RLLPH
                        new_hex = hex_part.replace("RLPH", "RLLPH", 1)
                        new_token = f"\u27e6{new_hex}_{suff_part}\u27e7"
                    elif strategy == "hex_ocr":
                        # OCR error: 0 -> O, 1 -> I
                        new_hex = hex_part.replace("0", "O").replace("1", "I")
                        new_token = f"\u27e6{new_hex}_{suff_part}\u27e7"
                    elif strategy == "spaces":
                        # Space insertion inside token: ⟦ RLPH... ⟧
                        new_token = f"\u27e6 {inner} \u27e7"
                    elif strategy == "brackets":
                        # Bracket stripped or converted to square bracket: [RLPH...]
                        new_token = f"[{inner}]"
                    else:
                        new_token = key

                    if new_token != key and key in corrupted_text:
                        corrupted_text = corrupted_text.replace(key, new_token, 1)
                        corrupted_count += 1
                        has_corruptions = True

        if has_corruptions:
            try:
                restored_corrupted = restore_renpy_syntax(corrupted_text, placeholders)
                missing_vars = validate_translation_integrity(restored_corrupted, placeholders)
                if not missing_vars:
                    recovered_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1

    # Assertions guaranteeing test effectiveness
    assert total_strings > 0, "No syntax-containing strings were processed"
    assert corrupted_count > 0, "No corruptions were applied to test recovery"
    assert failed_count == 0, f"Recovery failed for {failed_count} strings (recovered: {recovered_count})"
    assert recovered_count > 0, "No corrupted tokens were recovered"


def test_syntax_guard_transliteration_recovery():
    """Verify recovery when legacy format tokens are transliterated or spaced."""
    # Test spaced legacy token
    placeholders = {"VAR0": "[player_name]", "TAG1": "{b}"}
    spaced_input = "Hello VAR 0 and TAG 1 Welcome"
    restored = restore_renpy_syntax(spaced_input, placeholders)
    assert "[player_name]" in restored
    assert "{b}" in restored
