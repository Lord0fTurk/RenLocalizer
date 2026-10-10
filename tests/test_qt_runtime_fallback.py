"""Windows graphics fallback chain and persistent failure state (qt_runtime)."""

from src.utils.qt_runtime import (
    WINDOWS_FALLBACK_CHAIN,
    build_qt_safe_relaunch_env,
    configure_qt_graphics_environment,
    load_failed_graphics_modes,
    next_windows_render_mode,
    parse_failed_modes_env,
    remember_failed_graphics_mode,
    select_qt_render_mode,
    should_attempt_qt_safe_relaunch,
)


def _configure(env, **kwargs):
    kwargs.setdefault("platform_name", "win32")
    kwargs.setdefault("scale_percent", 100)
    kwargs.setdefault("frozen", True)
    kwargs.setdefault("software_gl_available", True)
    return configure_qt_graphics_environment(env=env, **kwargs)


def test_windows_default_is_desktop_opengl():
    env = {}
    result = _configure(env)
    assert result.mode == "opengl"
    assert env["QSG_RHI_BACKEND"] == "opengl"
    assert "QT_OPENGL" not in env


def test_windows_hidpi_starts_at_software_gl():
    env = {}
    result = _configure(env, scale_percent=150)
    assert result.mode == "software"
    assert env["QT_OPENGL"] == "software"


def test_failed_opengl_steps_down_to_software_gl():
    env = {}
    result = _configure(env, failed_modes={"opengl"})
    assert result.mode == "software"
    assert env["QT_OPENGL"] == "software"
    assert env["QT_DISABLE_SHADER_DISK_CACHE"] == "1"


def test_missing_opengl32sw_skips_to_raster():
    env = {}
    result = _configure(env, failed_modes={"opengl"}, software_gl_available=False)
    assert result.mode == "raster"
    assert result.graphics_api == "software"
    assert env["QT_QUICK_BACKEND"] == "software"
    assert "QSG_RHI_BACKEND" not in env


def test_chain_end_is_sticky():
    assert next_windows_render_mode("opengl", set(WINDOWS_FALLBACK_CHAIN)) == "raster"


def test_explicit_mode_wins_over_failure_state():
    assert select_qt_render_mode("win32", 100, requested_mode="opengl", failed_modes={"opengl"}) == "opengl"


def test_failed_modes_from_env_are_honoured():
    env = {"RENLOCALIZER_QT_FAILED_MODES": "opengl,software"}
    result = _configure(env)
    assert result.mode == "raster"


def test_state_roundtrip_and_version_reset(tmp_path):
    state = tmp_path / "graphics_state.json"
    assert remember_failed_graphics_mode(state, "opengl", "2.8.19")
    assert load_failed_graphics_modes(state, "2.8.19") == {"opengl"}
    # An app update retries the whole chain.
    assert load_failed_graphics_modes(state, "2.8.20") == set()


def test_state_ignores_garbage(tmp_path):
    state = tmp_path / "graphics_state.json"
    state.write_text("{not json", encoding="utf-8")
    assert load_failed_graphics_modes(state, "2.8.19") == set()
    assert remember_failed_graphics_mode(None, "opengl") is False


def test_windows_relaunch_walks_the_chain():
    env = {}
    first = _configure(env)
    assert should_attempt_qt_safe_relaunch(env, "win32", first)

    child_env = build_qt_safe_relaunch_env(env, "win32", failed_mode=first.mode)
    assert child_env["RENLOCALIZER_QT_RECOVERY_ATTEMPT"] == "1"
    assert "QSG_RHI_BACKEND" not in child_env
    assert parse_failed_modes_env(child_env) == {"opengl"}

    second = _configure(child_env)
    assert second.mode == "software"
    assert should_attempt_qt_safe_relaunch(child_env, "win32", second)

    grandchild_env = build_qt_safe_relaunch_env(child_env, "win32", failed_mode=second.mode)
    assert parse_failed_modes_env(grandchild_env) == {"opengl", "software"}
    third = _configure(grandchild_env)
    assert third.mode == "raster"
    # Two attempts used and the GL-free path is the end of the chain.
    assert not should_attempt_qt_safe_relaunch(grandchild_env, "win32", third)


def test_windows_relaunch_respects_explicit_user_mode():
    env = {"RENLOCALIZER_QT_RENDER_MODE": "opengl"}
    result = _configure(env)
    assert not should_attempt_qt_safe_relaunch(env, "win32", result)


def test_linux_relaunch_still_single_shot():
    env = {"DISPLAY": ":0"}
    result = configure_qt_graphics_environment(env=env, platform_name="linux", scale_percent=100, frozen=False)
    assert should_attempt_qt_safe_relaunch(env, "linux", result)
    child_env = build_qt_safe_relaunch_env(env, "linux")
    assert child_env["RENLOCALIZER_QT_RENDER_MODE"] == "software"
    assert child_env["QT_QPA_PLATFORM"] == "xcb"
    assert not should_attempt_qt_safe_relaunch(child_env, "linux", result)
