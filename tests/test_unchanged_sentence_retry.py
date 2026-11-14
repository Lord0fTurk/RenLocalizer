# -*- coding: utf-8 -*-
"""
Tests for v2.8.17 sentence-shaped unchanged classification and 1-shot retry candidate selection.

Covers:
  - Natural language sentences are recognized as retry candidates (e.g. 'She strokes your cock.')
  - Dialogue with quotes and terminal punctuation are recognized
  - Short names (Eileen, John Doe), interjections (Ah!, Oh!), and UI buttons (Cancel, OK) are NOT retried
  - Technical identifiers (snake_case, camelCase), file paths, URLs, and code constructs are NOT retried
  - Ren'Py keywords at start without punctuation are rejected
  - should_retry_unchanged correctly classifies 'core_ui' vs 'sentence' vs ''
"""

import pytest
from src.core.pipeline.translating import (
    is_sentence_shaped_natural_language,
    should_retry_unchanged,
)


class TestSentenceShapedClassification:
    @pytest.mark.parametrize("sentence", [
        "She strokes your cock.",
        "She strokes your cock",
        "He looked at her with a gentle smile.",
        "What are you doing here?",
        "I don't know what to say about this.",
        "Please, don't leave me alone.",
        "\"Are you sure about that?\"",
        "‘Wait for me!’",
        "I understand.",
        "Stop that!",
        "Why not?",
        "It was a dark and stormy night when they arrived.",
        "{b}She strokes your cock.{/b}",
        "{color=#ff0000}Look at that sunset!{/color}",
        "[hero_name] looked at the strange artifact.",
        "彼女は優しく微笑みかけた。",
        "どこへ行くの？",
    ])
    def test_natural_language_sentences_recognized(self, sentence):
        assert is_sentence_shaped_natural_language(sentence) is True, (
            f"Expected {sentence!r} to be recognized as a sentence-shaped retry candidate."
        )

    @pytest.mark.parametrize("non_sentence", [
        # Single names / words
        "Eileen",
        "John",
        "Sylvan",
        "Bob",
        "Cancel",
        "OK",
        "Yes",
        "No",
        "Next",
        # Short interjections
        "Ah!",
        "Oh!",
        "Ugh...",
        "Huh?",
        "Mm...",
        # Two-word non-sentence names or titles without terminal punctuation
        "John Doe",
        "Eileen Vance",
        "Dr. Smith",
        "Chapter One",
        # Code identifiers and snake_case
        "config_version",
        "button_idle_hover",
        "player_gold_count",
        "persistent_save_flag",
        # File paths and assets
        "gui/main_menu.png",
        "audio/music_bg.ogg",
        "scripts/intro.rpy",
        # Technical syntax / format strings
        "Value: %s",
        "Count: %d",
        "x == y",
        "x += 1",
        # All-caps short headers
        "MAIN MENU",
        "LOAD GAME",
        "HTTP ERROR",
        # Empty / whitespace
        "",
        "   ",
        "...",
        "---",
    ])
    def test_non_sentences_strictly_rejected(self, non_sentence):
        assert is_sentence_shaped_natural_language(non_sentence) is False, (
            f"Expected {non_sentence!r} to NOT be recognized as a sentence-shaped candidate."
        )


class TestShouldRetryUnchangedClassification:
    @pytest.mark.parametrize("core_ui_text", [
        "Save",
        "Load",
        "Preferences",
        "History",
        "Skip",
        "Auto",
        "Q.Save",
        "Q.Load",
        "Quit",
        "Return",
        "Gallery",
        "Music",
        "Sound",
        "Voice",
        "Fullscreen",
        "Auto-Forward Time",
    ])
    def test_core_ui_classification(self, core_ui_text):
        should_retry, kind = should_retry_unchanged(core_ui_text)
        assert should_retry is True
        assert kind == "core_ui"

    @pytest.mark.parametrize("sentence_text", [
        "She strokes your cock.",
        "Could you please help me with this?",
        "They walked silently into the shadows.",
    ])
    def test_sentence_classification(self, sentence_text):
        should_retry, kind = should_retry_unchanged(sentence_text)
        assert should_retry is True
        assert kind == "sentence"

    @pytest.mark.parametrize("ignored_text", [
        "Eileen",
        "John Doe",
        "Ah!",
        "button_idle_state",
        "bg_sunset_lake",
    ])
    def test_ignored_classification(self, ignored_text):
        should_retry, kind = should_retry_unchanged(ignored_text)
        assert should_retry is False
        assert kind == ""


class TestFallbackCooldownGuard:
    """Unchanged second-opinion retry must skip a fallback engine that is in 429 cooldown."""

    def _run(self, cooldown_until):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock
        from src.core.pipeline.translating import retry_unchanged_candidate
        from src.core.translator import TranslationEngine, TranslationRequest, TranslationResult

        req = TranslationRequest("Return", "en", "tr", TranslationEngine.BING, metadata={"original_text": "Return"})
        unchanged = TranslationResult("Return", "Return", "en", "tr", TranslationEngine.BING, True)

        primary = MagicMock()
        primary.translate_single = AsyncMock(return_value=unchanged)
        fallback = MagicMock()
        fallback._global_cooldown_until = cooldown_until
        fallback.translate_single = AsyncMock(return_value=TranslationResult(
            "Return", "Geri Dön", "en", "tr", TranslationEngine.GOOGLE, True))
        primary.fallback_translator = fallback

        manager = SimpleNamespace(translators={TranslationEngine.BING: primary})
        loop = asyncio.new_event_loop()
        try:
            text, recovered = retry_unchanged_candidate(
                loop, req, SimpleNamespace(original_text="Return"), "Return", manager, retry_kind="core_ui")
        finally:
            loop.close()
        return text, recovered, fallback.translate_single.await_count

    def test_fallback_used_when_not_cooling_down(self):
        text, recovered, calls = self._run(cooldown_until=0)
        assert (text, recovered, calls) == ("Geri Dön", True, 1)

    def test_fallback_skipped_during_cooldown(self):
        import time
        text, recovered, calls = self._run(cooldown_until=time.time() + 30)
        assert (text, recovered, calls) == ("Return", False, 0)

    def test_bing_opts_out_of_second_opinion_fallback(self):
        """Plain MT engines must not send unchanged strings to the Google fallback."""
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock
        from src.core.pipeline.translating import retry_unchanged_candidate
        from src.core.translator import BingTranslator, TranslationEngine, TranslationRequest, TranslationResult

        bing = BingTranslator()
        bing.translate_single = AsyncMock(return_value=TranslationResult(
            "Return", "Return", "en", "tr", TranslationEngine.BING, True))
        google = MagicMock()
        google.translate_single = AsyncMock()
        bing.set_fallback_translator(google)

        req = TranslationRequest("Return", "en", "tr", TranslationEngine.BING, metadata={"original_text": "Return"})
        manager = SimpleNamespace(translators={TranslationEngine.BING: bing})
        loop = asyncio.new_event_loop()
        try:
            text, recovered = retry_unchanged_candidate(
                loop, req, SimpleNamespace(original_text="Return"), "Return", manager, retry_kind="core_ui")
        finally:
            loop.close()
        assert (text, recovered) == ("Return", False)
        assert bing.translate_single.await_count == 1      # own retry still happens
        assert google.translate_single.await_count == 0    # no Google traffic
