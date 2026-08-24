import logging
from types import SimpleNamespace

import pytest

from src.core.constants import (
    RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD,
    RATE_LIMIT_LONG_COOLDOWN,
)
from src.core.translator import GoogleTranslator


def _make_translator() -> GoogleTranslator:
    cfg = SimpleNamespace(
        translation_settings=SimpleNamespace(
            use_multi_endpoint=True,
            enable_lingva_fallback=True,
            max_concurrent_threads=4,
            max_chars_per_request=1000,
            max_batch_size=50,
            aggressive_retry_translation=False,
            use_html_protection=False,
            request_delay=0.1,
        )
    )
    return GoogleTranslator(config_manager=cfg)


@pytest.mark.parametrize(
    "count,expected",
    [
        (1, 3.0),
        (2, 6.0),
        (3, 12.0),
        (4, 24.0),
        (5, 48.0),
    ],
)
def test_cooldown_escalates_exponentially(count, expected):
    translator = _make_translator()
    translator._consecutive_429_count = count
    assert translator._compute_global_cooldown() == expected


def test_circuit_breaker_caps_at_long_cooldown():
    translator = _make_translator()
    translator._consecutive_429_count = (
        RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD - 1
    )
    assert translator._compute_global_cooldown() == 48.0

    translator._consecutive_429_count = RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD
    assert translator._compute_global_cooldown() == float(RATE_LIMIT_LONG_COOLDOWN)

    translator._consecutive_429_count = RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD + 4
    assert translator._compute_global_cooldown() == float(RATE_LIMIT_LONG_COOLDOWN)


def test_apply_global_cooldown_increments_and_schedules():
    translator = _make_translator()
    before = translator._consecutive_429_count

    wait = translator._apply_global_cooldown()

    assert translator._consecutive_429_count == before + 1
    assert wait == 3.0
    assert translator._global_cooldown_until > 0.0


def test_circuit_breaker_warning_emitted_once_per_episode(caplog):
    translator = _make_translator()

    with caplog.at_level(logging.WARNING, logger="src.core.translator"):
        for _ in range(RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD + 2):
            translator._apply_global_cooldown()

    breaker_warnings = [
        r
        for r in caplog.records
        if "switching to alternate endpoint family" in r.getMessage()
    ]
    assert len(breaker_warnings) == 1
    # Trip must also arm the probe window so primaries stay silent afterwards.
    assert translator._primary_probe_at > 0.0


def test_success_decays_counter_without_full_reset():
    translator = _make_translator()
    translator._consecutive_429_count = 3

    translator._consecutive_429_count = max(0, translator._consecutive_429_count - 1)

    assert translator._consecutive_429_count == 2
