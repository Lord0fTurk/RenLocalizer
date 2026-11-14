# -*- coding: utf-8 -*-
"""
Regression tests for Ren'Py's global `old "..."` uniqueness rule (v2.8.17).

Ren'Py keys string translations globally, not per file:

    Exception: A translation for "KYAHHHHHHHHHH!!" already exists at
    game/tl/turkish/SCRIPTS/MC/Hatake Yurika/hayu gallery.rpy:1156.

Reported against FunTanariZ 1.12. The same shouted line appeared in two
scripts; both were spoken by a multi-speaker/engine-code speaker, so native
TLID generation demoted each of them to a string entry — and that demotion ran
per file, after the pipeline's global dedup, which lets dialogue through by
location on purpose (multi-branch support).
"""

import re


from src.core.pipeline.extraction import generate_native_tlid_content


def _entry(text, character="", file_path="game/a.rpy", line=10, text_type="dialogue"):
    return {
        "text": text,
        "character": character,
        "file_path": file_path,
        "line_number": line,
        "text_type": text_type,
    }


def _old_strings(content):
    return re.findall(r'^\s*old\s+"(.*)"\s*$', content, re.MULTILINE)


def _generate(entries, shared=None, lang="turkish"):
    return generate_native_tlid_content(
        entries,
        game_dir="game",
        target_language=lang,
        source_language="english",
        engine=None,
        translation_manager=None,
        config=None,
        lang_name=lang,
        seen_string_texts=shared,
    )


class TestDemotedDialogueIsGloballyUnique:
    # Speakers that make native generation emit a string entry instead of a
    # TLID block: multi-speaker names and engine/keyword speakers.
    MULTI_SPEAKER = "Yurika and Hayu"

    def test_same_line_in_two_files_emits_old_once(self):
        """The exact FunTanariZ crash: one shared set must span both files."""
        shout = "KYAHHHHHHHHHH!!"
        shared = set()

        first = _generate(
            [_entry(shout, self.MULTI_SPEAKER, "game/yurikagreet.rpy", 2029)], shared
        )
        second = _generate(
            [_entry(shout, self.MULTI_SPEAKER, "game/hayu gallery.rpy", 1156)], shared
        )

        assert _old_strings(first) == [shout]
        assert _old_strings(second) == [], "the second file must not repeat the old entry"

    def test_without_the_shared_set_each_file_is_still_self_consistent(self):
        """Per-file dedup still applies when no shared set is handed in."""
        shout = "KYAHHHHHHHHHH!!"
        content = _generate([
            _entry(shout, self.MULTI_SPEAKER, "game/a.rpy", 1),
            _entry(shout, self.MULTI_SPEAKER, "game/a.rpy", 2),
        ])
        assert _old_strings(content) == [shout]

    def test_ui_string_and_demoted_dialogue_do_not_collide(self):
        """A UI string in one file and the same text demoted in another."""
        text = "Continue"
        shared = set()

        ui_file = _generate([_entry(text, "", "game/screens.rpy", 5, text_type="ui")], shared)
        dialogue_file = _generate(
            [_entry(text, self.MULTI_SPEAKER, "game/script.rpy", 40)], shared
        )

        assert _old_strings(ui_file) == [text]
        assert _old_strings(dialogue_file) == []

    def test_strings_already_on_disk_are_not_re_emitted(self):
        """The set is seeded with previous runs' entries, so re-runs stay valid."""
        text = "Save game"
        shared = {text}  # already present in tl/<lang>/ from an earlier run
        content = _generate([_entry(text, "", "game/screens.rpy", 5, text_type="ui")], shared)
        assert _old_strings(content) == []

    def test_ordinary_dialogue_still_repeats_across_files(self):
        """Normal speakers keep per-location TLID blocks (multi-branch support)."""
        line = "I knew you would come."
        shared = set()

        first = _generate([_entry(line, "Yurika", "game/a.rpy", 10)], shared)
        second = _generate([_entry(line, "Yurika", "game/b.rpy", 99)], shared)

        assert _old_strings(first) == [] and _old_strings(second) == []
        for content in (first, second):
            assert "translate turkish " in content
            assert line in content


class TestOrchestratorWiring:
    def test_generator_is_called_with_one_shared_set(self):
        """Every file of a run must receive the same set object."""
        import inspect

        from src.core.pipeline import orchestrator

        source = inspect.getsource(orchestrator.TranslationPipeline)
        assert "shared_string_texts = set(existing_global_strings)" in source
        assert "seen_string_texts=shared_string_texts" in source
