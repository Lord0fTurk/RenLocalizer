# -*- coding: utf-8 -*-
"""Tests for safe language activation (zzz_<lang>_language.rpy generation).

Locks the single-source-of-truth implementation in
`src.core.pipeline.saving.create_language_init_file`, which forces the game
into the target language regardless of how it was launched or last saved.
"""

from src.core.pipeline.saving import create_language_init_file
from src.utils.config import ConfigManager


def test_create_language_init_file_forces_target_language(tmp_path):
    """Generated init file must force the target language in 3 phases."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)

    config = ConfigManager()
    logs = []
    create_language_init_file(
        str(game_dir), "turkish", config, lambda level, msg: logs.append(msg)
    )

    init_file = game_dir / "zzz_turkish_language.rpy"
    assert init_file.exists(), "language init file should be created"

    content = init_file.read_text(encoding="utf-8-sig")

    # Phase 1: highest-priority override (config.language beats user choice,
    # autodetect, and default_language).
    assert 'define config.language = "turkish"' in content

    # Phase 2: runtime enforcement on every game start.
    assert 'renpy.change_language("turkish")' in content

    # Phase 3: persistent (save file) protection against games that re-apply
    # their own language on load.
    assert 'persistent.language = "turkish"' in content

    # Phase 4: late-binding boot enforcement (init 999) to override developer init -1 hardcoded scripts
    assert 'init 999 python:' in content
    assert 'config.language = "turkish"' in content

    # ...but never switch languages during init: style/store backups do not
    # exist yet, so change_language() may only run from start callbacks.
    init_999 = content.split("init 999 python:", 1)[1]
    assert "change_language" not in init_999.split("# ====", 1)[0]

    # Hotkey overlay is intentionally omitted to avoid key collisions with game UI (log/load/input)
    assert 'screen _rl_hotkey_overlay' not in content
    assert 'screen _rl_toast_overlay' not in content


def test_language_activation_can_be_turned_off(tmp_path):
    """Off = only tl/<lang> is written, and an earlier run's file is removed."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)
    (game_dir / "zzz_turkish_language.rpy").write_text("# old\n", encoding="utf-8-sig")
    (game_dir / "zzz_turkish_language.rpyc").write_bytes(b"compiled")
    (game_dir / "zzz_ending.rpy").write_text("# the game's own file\n", encoding="utf-8")

    config = ConfigManager()
    config.translation_settings.activate_language_on_launch = False
    create_language_init_file(str(game_dir), "turkish", config, lambda level, msg: None)

    assert sorted(p.name for p in game_dir.iterdir()) == ["zzz_ending.rpy"]

    config.translation_settings.activate_language_on_launch = True
    create_language_init_file(str(game_dir), "turkish", config, lambda level, msg: None)
    assert (game_dir / "zzz_turkish_language.rpy").exists()


def test_create_language_init_file_cleans_stale_init_files(tmp_path):
    """A previous language init file for a different language is removed."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)

    # Pre-existing init file for another language (should be cleaned up).
    stale = game_dir / "zzz_english_language.rpy"
    stale.write_text("# stale\n", encoding="utf-8-sig")

    config = ConfigManager()
    create_language_init_file(
        str(game_dir), "turkish", config, lambda level, msg: None
    )

    assert not stale.exists(), "stale language init file should be removed"
    assert (game_dir / "zzz_turkish_language.rpy").exists()


def test_generated_file_only_uses_names_the_game_has(tmp_path):
    """
    The init file runs inside the game, not inside RenLocalizer.

    Its defensive `except` handlers used to call `logger.debug(...)`, a name the
    Ren'Py runtime does not have — so any failure inside the try block raised
    "NameError: name 'logger' is not defined" on top of it, during init.
    """
    import ast
    import re

    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)
    create_language_init_file(
        str(game_dir), "turkish", ConfigManager(), lambda level, msg: None
    )
    content = (game_dir / "zzz_turkish_language.rpy").read_text(encoding="utf-8-sig")

    code_only = "\n".join(
        line for line in content.splitlines() if not line.strip().startswith("#")
    )
    assert "logger" not in code_only, "RenLocalizer's logger does not exist in the game"

    # Every python block must at least parse on its own.
    blocks = re.findall(r"^init(?:\s+\d+)?\s+python:\n((?:(?: {4}.*)?\n)+)", content, re.MULTILINE)
    assert blocks, "the file should contain init python blocks"
    for block in blocks:
        dedented = "\n".join(line[4:] if line.startswith("    ") else line
                             for line in block.splitlines())
        ast.parse(dedented)


def test_generated_file_declares_no_game_variables(tmp_path):
    """It may set the language; it must never define or assign game state."""
    game_dir = tmp_path / "game"
    game_dir.mkdir(parents=True)
    create_language_init_file(
        str(game_dir), "turkish", ConfigManager(), lambda level, msg: None
    )
    content = (game_dir / "zzz_turkish_language.rpy").read_text(encoding="utf-8-sig")

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(("label ", "jump ", "call ", "$ ", "default ")):
            raise AssertionError(f"unexpected game statement: {stripped}")
