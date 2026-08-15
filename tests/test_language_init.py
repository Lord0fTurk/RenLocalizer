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
