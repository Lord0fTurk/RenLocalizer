# -*- coding: utf-8 -*-
"""Dashboard project card: what inspect_project() reads from a game folder."""
from pathlib import Path

from src.core.project_info import find_launcher, inspect_project, renpy_version


def _game(tmp_path: Path, name: str = "MyGame", *, scripts=("script.rpy", "script.rpyc"), rpa=(),
          options: str | None = None, vc: str | None = "8.5.2.26010301") -> Path:
    root = tmp_path / f"{name}-1.0-pc"
    game = root / "game"
    game.mkdir(parents=True)
    (root / "renpy").mkdir()
    if vc:
        (root / "renpy" / "vc_version.py").write_text(f"branch = 'fix'\nversion = '{vc}'\n", encoding="utf-8")
    for f in (f"{name}.py", f"{name}.exe", f"{name}-32.exe", f"{name}.sh", "python.exe"):
        (root / f).write_text("", encoding="utf-8")
    for s in scripts:
        (game / s).write_text("", encoding="utf-8")
    for a in rpa:
        (game / a).write_text("", encoding="utf-8")
    if options is not None:
        (game / "options.rpy").write_text(options, encoding="utf-8")
    return root


def test_reads_name_version_and_counts_only_the_games_own_scripts(tmp_path):
    root = _game(tmp_path, options='define config.name = _("My Game")\ndefine config.version = "1.0"\n')
    game = root / "game"
    (game / "tl" / "turkish").mkdir(parents=True)
    (game / "tl" / "turkish" / "script.rpy").write_text("", encoding="utf-8")
    (game / "zzz_turkish_language.rpy").write_text("", encoding="utf-8")   # ours, not the game's
    (game / "zzz_renlocalizer_runtime.rpy").write_text("", encoding="utf-8")
    (game / "images.rpa").write_text("", encoding="utf-8")

    info = inspect_project(str(root), platform="win32")
    assert info["ok"] and info["name"] == "My Game" and info["game_version"] == "1.0"
    assert info["renpy_version"] == "8.5.2"
    assert (info["rpy"], info["rpyc"], info["rpa"]) == (2, 1, 1)  # script.rpy + options.rpy
    assert info["tl_languages"] == ["turkish"]
    assert info["launcher"].endswith("MyGame.exe")
    assert info["notices"] == []


def test_launcher_follows_the_platform_and_the_users_pick(tmp_path):
    root = _game(tmp_path)
    assert find_launcher(root, platform="win32").endswith("MyGame.exe")      # not -32, not python.exe
    assert find_launcher(root, platform="linux").endswith("MyGame.sh")
    picked = root / "MyGame-32.exe"
    assert find_launcher(root, picked, platform="win32") == str(picked)
    info = inspect_project(str(picked), platform="win32")
    assert info["launcher"] == str(picked) and info["name"] == "MyGame"     # name from the launcher


def test_renpy7_version_tuple(tmp_path):
    root = _game(tmp_path, vc=None)
    (root / "renpy" / "__init__.py").write_text("version_tuple = (7, 4, 11, vc_version)\n", encoding="utf-8")
    assert renpy_version(root) == "7.4.11"


def test_scripts_only_in_archives(tmp_path):
    root = _game(tmp_path, scripts=(), rpa=("scripts.rpa", "images.rpa"))
    keys = lambda **kw: [n["key"] for n in inspect_project(str(root), **kw)["notices"]]
    assert keys(rpa_extraction=True) == ["project_scripts_in_rpa"]
    assert keys(rpa_extraction=False) == ["pipeline_rpa_extraction_disabled"]


def test_nothing_to_translate_and_rpyc_only(tmp_path):
    empty = _game(tmp_path, "Empty", scripts=())
    assert [n["key"] for n in inspect_project(str(empty))["notices"]] == ["pipeline_no_game_scripts"]
    compiled = _game(tmp_path, "Compiled", scripts=("script.rpyc",))
    assert inspect_project(str(compiled), rpyc_reader=True)["notices"] == []
    assert [n["key"] for n in inspect_project(str(compiled), rpyc_reader=False)["notices"]] == ["project_rpyc_reader_off"]


def test_game_folder_tl_folder_and_wrong_folder(tmp_path):
    root = _game(tmp_path)
    picked_game = inspect_project(str(root / "game"))
    assert picked_game["ok"] and picked_game["project_dir"] == str(root)

    (root / "game" / "tl" / "turkish").mkdir(parents=True)
    tl = inspect_project(str(root / "game" / "tl" / "turkish"))
    assert tl["tl_mode"] and [n["key"] for n in tl["notices"]] == ["log_tl_folder_detected"]

    wrong = tmp_path / "Documents"
    wrong.mkdir()
    info = inspect_project(str(wrong))
    assert not info["ok"] and [n["key"] for n in info["notices"]] == ["log_game_folder_missing"]
    assert inspect_project("")["ok"] is False
