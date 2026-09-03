# -*- coding: utf-8 -*-
"""
Tests for EndpointRouter — smart endpoint routing between Google families.
"""
import asyncio
import time
import pytest
from src.core.translator import _FamilyHealth, EndpointRouter

# ── _FamilyHealth ──────────────────────────────────────────────────────────

def test_family_health_initial_state():
    h = _FamilyHealth()
    assert h.success == 0
    assert h.failure == 0
    assert h.success_rate == 1.0
    assert not h.is_blocked()

def test_family_health_success_rate():
    h = _FamilyHealth()
    h.record_success(); h.record_success(); h.record_failure()
    assert abs(h.success_rate - 2/3) < 1e-9

def test_family_health_block_and_unblock():
    h = _FamilyHealth()
    h.record_failure(block_for=100.0)
    assert h.is_blocked()
    h.reset_block()
    assert not h.is_blocked()

# ── EndpointRouter ─────────────────────────────────────────────────────────

def test_router_initial_state():
    r = EndpointRouter()
    assert not r.primary_blocked
    assert r.best_family_for_batch() == EndpointRouter.FAMILY_PRIMARY
    assert r.best_family_for_single() == EndpointRouter.FAMILY_PRIMARY

def test_router_blocks_after_threshold():
    from src.core.constants import RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD as T
    r = EndpointRouter()
    for _ in range(T): r.record_primary_429()
    assert r.primary_blocked

def test_router_batch_routes_to_batchexecute_when_primary_blocked():
    from src.core.constants import RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD as T
    r = EndpointRouter()
    for _ in range(T): r.record_primary_429()
    assert r.best_family_for_batch() == EndpointRouter.FAMILY_BATCHEXECUTE

def test_router_single_routes_to_clients5_when_primary_blocked():
    from src.core.constants import RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD as T
    r = EndpointRouter()
    for _ in range(T): r.record_primary_429()
    assert r.best_family_for_single() == EndpointRouter.FAMILY_CLIENTS5

def test_router_falls_to_clients5_when_batchexecute_blocked():
    from src.core.constants import RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD as T
    r = EndpointRouter()
    for _ in range(T): r.record_primary_429()
    r.record_family_failure(EndpointRouter.FAMILY_BATCHEXECUTE, block_for=120.0)
    r.record_family_failure(EndpointRouter.FAMILY_BATCHEXECUTE, block_for=120.0)
    assert r.best_family_for_batch() == EndpointRouter.FAMILY_CLIENTS5

def test_router_recovers_on_success():
    from src.core.constants import RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD as T
    r = EndpointRouter()
    for _ in range(T): r.record_primary_429()
    assert r.primary_blocked
    for _ in range(T): r.record_primary_success()
    assert not r.primary_blocked

def test_probe_task_singleton():
    import asyncio
    from src.core.constants import RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD as T
    async def run():
        r = EndpointRouter()
        async def slow(): await asyncio.sleep(999); return False
        r._do_probe = slow
        for _ in range(T): r.record_primary_429()
        r._schedule_probe(); t1 = r._probe_task
        r._schedule_probe(); t2 = r._probe_task
        assert t1 is t2
        if t1: t1.cancel()
        try: await t1
        except asyncio.CancelledError: pass
    asyncio.run(run())

if __name__ == "__main__":
    import subprocess, sys
    result = subprocess.run([sys.executable, "-m", "pytest", __file__, "-v"], capture_output=False)
    sys.exit(result.returncode)
