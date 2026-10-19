# -*- coding: utf-8 -*-
"""Text tags an engine moved out of order.

Ren'Py raises "'/i' closes a text tag that isn't open." when it shows a line
whose close tag comes first (renpy/text/text.py). Turkish word order made
Google/Bing return "... gereken {/i} şeyi{i}yapıyoruz" for
"what we're {i}supposed{/i} to be doing", and the output guard only compared
which tags were present.
"""
from src.core.pipeline.translating import (
    classify_translation_corruption,
    renpy_tag_order_problem,
    repair_renpy_tag_order,
    sanitize_translation_for_output,
)
from src.core.syntax_guard import (
    inject_missing_placeholders,
    protect_renpy_syntax,
    restore_renpy_syntax,
    validate_translation_integrity,
)

SOURCE = "Like...like we're doing what we're {i}supposed{/i} to be doing, you know?"
SWAPPED = "Yani... Sanki yapmamız gereken {/i} şeyi{i}yapıyoruz, anlıyor musun?"
REPAIRED = "Yani... Sanki yapmamız gereken {i}şeyi{/i} yapıyoruz, anlıyor musun?"


def test_rule_matches_renpy():
    assert renpy_tag_order_problem("{i}a{/i}") is None
    assert renpy_tag_order_problem("a{/i} b{i}") == "unopened"
    assert renpy_tag_order_problem("{b}{i}a{/b}{/i}") == "misnested"
    # Self-closing and special tags are not on Ren'Py's style stack.
    assert renpy_tag_order_problem("Wait{w} {p}and {nw}{#id}{fast}see.") is None
    # '{{' is an escaped brace, not a tag.
    assert renpy_tag_order_problem("Use {{/i} to close.") is None


def test_guard_blocks_a_swapped_pair():
    assert classify_translation_corruption(SOURCE, SWAPPED) == "renpy_tag_order_mismatch"
    assert classify_translation_corruption(SOURCE, REPAIRED) is None


def test_guard_accepts_what_the_source_already_does():
    sloppy = "{b}{i}Hey{/b}{/i} you"
    assert classify_translation_corruption(sloppy, "{b}{i}Hey{/b}{/i} sen") is None
    # ...but never a line that makes Ren'Py raise.
    assert classify_translation_corruption(sloppy, "{/b}{b}{i}Hey{/i} sen") == "renpy_tag_order_mismatch"


def test_repair_swaps_the_pair_and_follows_the_source_spacing():
    assert repair_renpy_tag_order(SOURCE, SWAPPED) == REPAIRED


def test_repair_keeps_tag_values():
    source = "It was {color=#ff0000}red{/color} and cold."
    swapped = "Soğuktu ve {/color}kırmızıydı{color=#ff0000}."
    repaired = repair_renpy_tag_order(source, swapped)
    assert repaired == "Soğuktu ve {color=#ff0000}kırmızıydı{/color}."
    assert classify_translation_corruption(source, repaired) is None


def test_repair_leaves_other_problems_to_the_guard():
    source = "{b}Bold {i}both{/i}{/b} end"
    crossed = "{b}Kalın {i}ikisi{/b}{/i} son"
    assert repair_renpy_tag_order(source, crossed) == crossed
    assert classify_translation_corruption(source, crossed) == "renpy_tag_order_mismatch"
    # Nothing to do on a correct or tag-less line.
    assert repair_renpy_tag_order(SOURCE, REPAIRED) == REPAIRED
    assert repair_renpy_tag_order("Hello.", "Merhaba.") == "Merhaba."


def test_engine_output_through_the_real_restore_chain_is_repaired():
    protected, placeholders = protect_renpy_syntax(SOURCE)
    opener = next(k for k, v in placeholders.items() if v == "{i}")
    closer = next(k for k, v in placeholders.items() if v == "{/i}")
    engine = f"Yani... Sanki yapmamız gereken {closer} şeyi{opener}yapıyoruz, anlıyor musun?"

    restored = restore_renpy_syntax(engine, placeholders)
    missing = validate_translation_integrity(restored, placeholders)
    if missing:
        restored = inject_missing_placeholders(restored, protected, placeholders, missing)

    events = []
    text, reason = sanitize_translation_for_output(
        original=SOURCE, translated=restored, file_path="script.rpy", translation_id="x",
        diagnostic_report=None, log_emit=lambda *a: None, config=None,
        record_guard_event_fn=lambda **kw: events.append(kw),
    )
    assert reason is None and not events
    assert text == REPAIRED
