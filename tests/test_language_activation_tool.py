# -*- coding: utf-8 -*-
"""Toolbox / CLI "language activation" tool.

Ren'Py does not list the languages in game/tl by itself, so a translation made
with activation turned off (or by another tool) never shows up unless the game
has a language menu. The tool writes or removes game/zzz_<lang>_language.rpy.
"""
import sys
from unittest import mock

from src.core.pipeline.saving import (
    create_language_init_file,
    list_tl_languages,
    remove_language_init_files,
)
from src.utils.config import ConfigManager


def _game(tmp_path, *languages):
    game = tmp_path / "game"
    for lang in languages:
        (game / "tl" / lang).mkdir(parents=True)
        (game / "tl" / lang / "script.rpy").write_text(f"translate {lang} strings:\n", encoding="utf-8")
    (game / "tl" / ".diagnostics").mkdir(parents=True, exist_ok=True)
    (game / "tl" / "None").mkdir(parents=True, exist_ok=True)
    # Font Injector output lives in tl/ but is not a language.
    (game / "tl" / "renlocalizer_fonts").mkdir(parents=True, exist_ok=True)
    (game / "tl" / "renlocalizer_fonts" / "NotoSans-Regular.ttf").write_bytes(b"\0")
    return game


def test_lists_only_real_language_folders(tmp_path):
    game = _game(tmp_path, "russian", "Spanish")
    assert list_tl_languages(str(game)) == ["Spanish", "russian"]


def test_forced_activation_keeps_the_folder_name_exactly(tmp_path):
    """Ren'Py matches config.language case-sensitively; "ru" must not become "russian"."""
    game = _game(tmp_path, "ru")
    config = ConfigManager()
    config.translation_settings.activate_language_on_launch = False  # tool ignores the setting

    create_language_init_file(str(game), "ru", config, lambda *a: None, force=True)

    init = game / "zzz_ru_language.rpy"
    assert init.exists()
    assert 'define config.language = "ru"' in init.read_text(encoding="utf-8-sig")


def test_switching_language_drops_the_old_compiled_file(tmp_path):
    """A stale zzz_<old>_language.rpyc still runs and forces the old language."""
    game = _game(tmp_path, "russian", "german")
    config = ConfigManager()
    create_language_init_file(str(game), "russian", config, lambda *a: None, force=True)
    (game / "zzz_russian_language.rpyc").write_bytes(b"compiled")

    create_language_init_file(str(game), "german", config, lambda *a: None, force=True)

    names = sorted(p.name for p in game.iterdir() if p.is_file())
    assert names == ["zzz_german_language.rpy"]


def test_remove_only_touches_our_files(tmp_path):
    game = _game(tmp_path, "russian")
    create_language_init_file(str(game), "russian", ConfigManager(), lambda *a: None, force=True)
    (game / "zzz_russian_language.rpyc").write_bytes(b"compiled")
    (game / "zzz_credits.rpy").write_text("# the game's own file\n", encoding="utf-8")

    assert remove_language_init_files(str(game)) == 2
    assert [p.name for p in game.iterdir() if p.is_file()] == ["zzz_credits.rpy"]


def test_gui_tool_finds_game_dir_from_any_selected_path(tmp_path):
    from types import SimpleNamespace
    from src.backend.app_backend import AppBackend

    game = _game(tmp_path, "russian")
    exe = tmp_path / "Game.exe"
    exe.write_bytes(b"")
    for selected in (tmp_path, game, game / "tl" / "russian", exe):
        stub = SimpleNamespace(_project_path=str(selected))
        assert AppBackend._tool_game_dir(stub) == str(game), selected
    assert AppBackend._tool_game_dir(SimpleNamespace(_project_path=str(tmp_path / "nowhere"))) is None


def test_cli_activate_language_command(tmp_path):
    import src.cli_main as cli

    game = _game(tmp_path, "russian", "german")

    def run(*argv):
        with mock.patch.object(sys, "argv", ["cli", *argv]):
            return cli.main()

    # Two translations and no --lang: refuse instead of guessing.
    assert run("activate-language", str(tmp_path)) == 1
    assert run("activate-language", str(tmp_path), "--lang", "de") == 0  # "de" -> german folder
    assert (game / "zzz_german_language.rpy").exists()
    assert run("activate-language", str(game / "tl" / "russian"), "--lang", "russian") == 0
    assert not (game / "zzz_german_language.rpy").exists()
    assert run("activate-language", str(tmp_path), "--remove") == 0
    assert not list(game.glob("zzz_*"))
