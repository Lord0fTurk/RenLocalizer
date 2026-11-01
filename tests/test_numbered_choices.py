import zlib
from pathlib import Path

from src.core.numbered_choices import HOOK_FILENAME, game_builds_numbered_choices, render_hook
from src.core.pipeline.saving import manage_numbered_choice_hook
from src.core.constants import is_renlocalizer_generated_script


def _game(tmp_path, body):
    game = tmp_path / "game"
    game.mkdir()
    (game / "screens.rpy").write_text(body, encoding="utf-8")
    return game


def _rpyc(path: Path, source: str):
    blob = zlib.compress(source.encode("utf-8"))
    # one slot entry (slot, start, length) plus the all-zero terminator; data starts after both
    header = b"RENPY RPC2" + (1).to_bytes(4, "little") + (34).to_bytes(4, "little") + len(blob).to_bytes(4, "little")
    header += (0).to_bytes(4, "little") * 3
    path.write_bytes(header + blob)


def test_detects_concatenated_number_and_caption(tmp_path):
    game = _game(tmp_path, 'screen choice(items):\n    for num, item in enumerate(items, 1):\n        text str(num) + ". " + item.caption\n')
    assert game_builds_numbered_choices(game)


def test_detects_format_and_fstring_variants(tmp_path):
    for index, expr in enumerate(('"%d. %s" % (n, i.caption)', '"{}. {}".format(n, i.caption)', 'f"{n}. {i.caption}"')):
        root = tmp_path / f"g{index}"
        root.mkdir()
        assert game_builds_numbered_choices(_game(root, f"screen c():\n    text {expr}\n"))


def test_plain_caption_screen_is_not_flagged(tmp_path):
    game = _game(tmp_path, "screen choice(items):\n    for i in items:\n        textbutton i.caption action i.action\n")
    assert not game_builds_numbered_choices(game)


def test_detects_inside_compiled_rpyc(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    _rpyc(game / "screens.rpyc", 'text str(num) + ". " + item.caption')
    assert game_builds_numbered_choices(game)


def test_hook_written_only_when_needed_and_removed_otherwise(tmp_path):
    game = _game(tmp_path, 'text str(n) + ". " + i.caption\n')
    manage_numbered_choice_hook(game, True, lambda *a: None)
    assert (game / HOOK_FILENAME).exists()

    # Output mode switched away from native: the file must not linger.
    manage_numbered_choice_hook(game, False, lambda *a: None)
    assert not (game / HOOK_FILENAME).exists()


def test_hook_not_written_for_a_game_without_the_pattern(tmp_path):
    game = _game(tmp_path, "screen x():\n    text 'hi'\n")
    manage_numbered_choice_hook(game, True, lambda *a: None)
    assert not (game / HOOK_FILENAME).exists()


def test_generated_file_is_valid_python_and_ignored_by_scanners():
    compile(render_hook().split("init 998 python:\n", 1)[1].replace("\n    ", "\n").lstrip(), "hook", "exec")
    assert is_renlocalizer_generated_script(HOOK_FILENAME)
