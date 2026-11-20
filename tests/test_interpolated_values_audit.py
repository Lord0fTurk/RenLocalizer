# -*- coding: utf-8 -*-
"""define/default text shown inside other text with [name] is reported (see audit_interpolated_text_values)."""
from pathlib import Path

from src.core.pipeline.extraction import audit_interpolated_text_values


def _game(tmp_path: Path, script: str) -> str:
    game = tmp_path / "game"
    game.mkdir()
    (game / "script.rpy").write_text(script, encoding="utf-8")
    return str(game)


def _vars(result):
    return {s["variable"]: s for s in (result or {}).get("samples", [])}


def test_value_shown_inside_a_sentence_is_reported(tmp_path):
    game = _game(tmp_path, (
        'define mood = "Happy"\n'
        'default status = "Alive"\n'
        'define place = _("Castle")\n'
        'label start:\n'
        '    e "I feel [mood] today."\n'
        '    e "Your status is [status]."\n'
        '    e "Welcome to [place]!"\n'
    ))
    result = audit_interpolated_text_values(game, None)
    assert result["code"] == "interpolated_define_values" and result["count"] == 3
    assert set(_vars(result)) == {"mood", "status", "place"}
    assert _vars(result)["mood"]["line_number"] == 1 and _vars(result)["mood"]["uses"] == 1


def test_translatable_field_is_not_reported(tmp_path):
    game = _game(tmp_path, (
        'define mood = "Happy"\n'
        'label start:\n'
        '    e "I feel [mood!t] today."\n'
    ))
    assert audit_interpolated_text_values(game, None) is None


def test_unused_numbers_names_and_code_are_not_reported(tmp_path):
    game = _game(tmp_path, (
        'define mood = "Happy"\n'              # never shown
        'define score = "100"\n'               # no letters
        'default hero = "Neo"\n'               # used only in code below
        'define quotes = ["Hello", "Bye"]\n'   # not a plain string
        'define gui.text_font = "Font.ttf"\n'  # dotted names are config, not text
        'label start:\n'
        '    $ x = items[hero]\n'
        '    e "Total [score]."\n'
        '    e "[quotes[0]]"\n'
    ))
    assert audit_interpolated_text_values(game, None) is None


def test_attribute_and_index_uses_do_not_count(tmp_path):
    game = _game(tmp_path, (
        'define hero = "Neo"\n'
        'label start:\n'
        '    e "[hero.name] [hero[0]]"\n'
    ))
    assert audit_interpolated_text_values(game, None) is None


def test_format_specs_still_count(tmp_path):
    game = _game(tmp_path, (
        'define mood = "Happy"\n'
        'label start:\n'
        '    e "I feel [mood!u] today."\n'
    ))
    assert _vars(audit_interpolated_text_values(game, None)) .keys() == {"mood"}


def test_generated_and_tl_files_are_skipped(tmp_path):
    game = Path(_game(tmp_path, 'label start:\n    e "Hi"\n'))
    tl = game / "tl" / "turkish"
    tl.mkdir(parents=True)
    (tl / "x.rpy").write_text('define mood = "Happy"\nlabel a:\n    e "[mood]"\n', encoding="utf-8")
    assert audit_interpolated_text_values(str(game), None) is None


def test_warning_is_registered_localised_and_formats():
    import json
    from src.core.pipeline.constants import COVERAGE_WARNING_UI_KEYS

    key = COVERAGE_WARNING_UI_KEYS["interpolated_define_values"]
    for lang in ("en", "tr", "de", "es", "fr", "ru", "fa", "zh-CN", "ja", "ko"):
        text = json.loads(Path(f"locales/{lang}.json").read_text(encoding="utf-8"))[key]
        assert "{count}" in text
        assert text.format(count=3)
        assert "3" in text.format(count=3)


def test_names_are_never_suggested(tmp_path):
    """[name!t] would send a person's or place's name to the translator."""
    game = _game(tmp_path, (
        'define mc_name = "Alex"\n'
        'default hero = "Rose"\n'
        'default player_nickname = "Neo"\n'
        'define boss = "Viktor"\n'
        'define e = Character(boss)\n'
        'define mood = "Happy"\n'
        'label start:\n'
        '    e "Hi [mc_name], [hero] and [player_nickname]. [boss] is here. I feel [mood]."\n'
    ))
    result = audit_interpolated_text_values(game, None)
    assert set(_vars(result)) == {"mood"}


def test_interpolations_inside_define_strings_are_counted(tmp_path):
    game = _game(tmp_path, (
        'define mood = "Happy"\n'
        'define greeting = _("I feel [mood] today.")\n'
        'define self_ref = "Keep [self_ref]"\n'
    ))
    result = audit_interpolated_text_values(game, None)
    assert set(_vars(result)) == {"mood"}
    assert _vars(result)["mood"]["uses"] == 1
