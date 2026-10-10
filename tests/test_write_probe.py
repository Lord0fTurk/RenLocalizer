# -*- coding: utf-8 -*-
"""Pre-flight writability probe for the game folder (validating stage)."""
from src.core.pipeline.validating import probe_directory_writable


def test_probe_accepts_writable_dir_and_leaves_no_trace(tmp_path):
    assert probe_directory_writable(str(tmp_path)) is True
    assert list(tmp_path.iterdir()) == []


def test_generated_scripts_are_not_rescanned(tmp_path):
    """Our own zzz_<lang>_language.rpy docstrings were re-extracted on the next run."""
    from src.core.constants import is_renlocalizer_generated_script
    from src.core.parser import RenPyParser
    from src.utils.config import ConfigManager
    from src.core.pipeline.saving import create_language_init_file

    game = tmp_path / "game"
    game.mkdir()
    (game / "script.rpy").write_text(
        'label start:\n    "A perfectly normal line of dialogue here."\n    return\n', encoding="utf-8"
    )
    create_language_init_file(str(game), "turkish", ConfigManager(), lambda *a: None)
    assert (game / "zzz_turkish_language.rpy").exists()

    results = RenPyParser(ConfigManager()).extract_from_directory_with_deep_scan(game, include_deep_scan=False)
    assert [p.name for p in results] == ["script.rpy"]

    for name in ("zzz_renlocalizer_runtime.rpy", "zzz_turkish_language.rpyc", "zz_rl_exported_ui.rpy"):
        assert is_renlocalizer_generated_script(name)
    for name in ("script.rpy", "zzz_ending.rpy", "language.rpy"):
        assert not is_renlocalizer_generated_script(name)


def test_probe_rejects_missing_or_non_directory(tmp_path):
    assert probe_directory_writable(str(tmp_path / "missing")) is False
    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    assert probe_directory_writable(str(file_path)) is False
