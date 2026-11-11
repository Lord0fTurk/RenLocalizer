# -*- coding: utf-8 -*-
"""NvidiaTranslator (Riva-Translate): adaptive batching, limits and recovery. No network."""
from __future__ import annotations

import asyncio
import re

import pytest

from src.core.translators.base import TranslationEngine, TranslationRequest, TranslationResult
from src.core.translators.nvidia import (
    AdaptiveBatchSizer,
    NvidiaTranslator,
    RateLimiter,
    riva_language_code,
)


def run(coro):
    return asyncio.run(coro)


# ── language codes ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("tr", "tr"), ("TR", "tr"), ("en", "en"), ("es", "es-ES"), ("pt", "pt-BR"),
    ("pt-br", "pt-BR"), ("zh", "zh-CN"), ("zh-Hant", "zh-TW"), ("nb", "no"), ("fr_FR", "fr"),
])
def test_riva_language_codes(raw, expected):
    assert riva_language_code(raw) == expected


def test_riva_unsupported_and_auto():
    assert riva_language_code("sw") is None
    assert riva_language_code("auto") is None
    assert riva_language_code("auto", default="en") == "en"


# ── adaptive sizer ───────────────────────────────────────────────────────────

def test_sizer_grows_only_after_clean_full_requests():
    s = AdaptiveBatchSizer(start=15, maximum=30, grow_after=3, grow_step=3)
    s.record(15, True, 0)
    s.record(15, True, 0)
    assert s.size == 15
    s.record(15, True, 0)
    assert s.size == 18


def test_sizer_ignores_small_requests_for_growth():
    s = AdaptiveBatchSizer(start=15, grow_after=1)
    for _ in range(5):
        s.record(4, True, 0)  # a tail, tells nothing about 15
    assert s.size == 15


def test_sizer_holds_on_one_bad_request_and_shrinks_on_the_second():
    s = AdaptiveBatchSizer(start=20)
    s.record(20, False)          # one odd line can spoil any group; the translator splits it
    assert s.size == 20
    s.record(20, False)          # a second one within the window is a pattern
    assert s.size == 14


def test_sizer_never_leaves_its_bounds():
    s = AdaptiveBatchSizer(start=3, minimum=2, maximum=6, grow_after=1, grow_step=10)
    s.record(3, True, 0)
    assert s.size == 6
    for _ in range(20):
        s.record(6, False)
    assert s.size == 2


def test_sizer_token_loss_shrinks_only_when_repeated_above_tolerance():
    s = AdaptiveBatchSizer(start=20, tolerated_bad_ratio=0.10)
    s.record(20, True, 1)   # 5 %: tolerated, only resets growth
    assert s.size == 20
    s.record(20, True, 4)   # 20 %: first problem, held
    assert s.size == 20
    s.record(20, True, 4)   # second problem: shrinks
    assert s.size == 14


def test_sizer_single_line_requests_carry_no_signal():
    s = AdaptiveBatchSizer(start=10)
    for _ in range(5):
        s.record(1, False)
    assert s.size == 10


# ── rate limiter ─────────────────────────────────────────────────────────────

def _limiter(rpm, floor=10):
    now = [0.0]
    slept = []

    async def fake_sleep(d):
        slept.append(d)
        now[0] += d

    return RateLimiter(rpm=rpm, floor=floor, clock=lambda: now[0], sleep=fake_sleep), slept


def test_rate_limiter_spaces_requests_evenly_without_bursts():
    rl, slept = _limiter(60)

    async def go():
        for _ in range(3):
            await rl.acquire()

    run(go())
    assert slept == pytest.approx([1.0, 1.0])  # first goes at once, then one per second


def test_rate_limiter_gives_concurrent_callers_separate_slots():
    rl, slept = _limiter(60)

    async def go():
        await asyncio.gather(*(rl.acquire() for _ in range(4)))

    run(go())
    assert len(slept) == 3 and max(slept) <= 3.0 + 1e-6


def test_rate_limiter_back_off_pauses_the_next_caller():
    rl, slept = _limiter(60)

    async def go():
        await rl.acquire()
        rl.back_off(7.0)
        await rl.acquire()

    run(go())
    assert slept and slept[-1] == pytest.approx(7.0, abs=0.01)


def test_rate_limiter_slow_down_widens_spacing_and_keeps_a_floor():
    rl, _ = _limiter(12, floor=10)
    for _ in range(5):
        rl.slow_down()
    assert rl.rpm == 10
    rl2, _ = _limiter(3, floor=1)
    rl2.slow_down()
    assert rl2.rpm == 2


# ── translator with a fake endpoint ──────────────────────────────────────────

_FAKE_TAG = re.compile(r"<s(\d+)>(.*?)</s\1>", re.S)


class FakeNvidia(NvidiaTranslator):
    """Replaces the HTTP call with a deterministic fake 'model'."""

    def __init__(self, behaviour="ok", **kw):
        super().__init__(api_key="nvapi-test", **kw)
        self.behaviour = behaviour
        self.calls = []

    @staticmethod
    def _t(s):  # fake Turkish: keeps tokens, wraps text
        return "TR(" + s + ")"

    async def _call(self, system, text):
        self.calls.append((system, text))
        items = [(int(k), v) for k, v in _FAKE_TAG.findall(text)]
        if not items:                               # a single, untagged request
            return self._t(text), "", False
        if self.behaviour == "drop_one" and len(items) > 3:
            items = items[:-1]                      # the model loses the last line
        if self.behaviour == "merge_all" and len(items) > 1:
            return " ".join(self._t(v) for _, v in items), "", False   # tags gone
        out = []
        for i, (k, v) in enumerate(items):
            v = self._t(v)
            if self.behaviour == "lose_token" and i == 1:
                v = re.sub(r"⟦[^⟧]*⟧", "", v)
            out.append(f"<s{k}>{v}</s{k}>")
        return " ".join(out), "", False


def reqs(texts, tgt="tr", src="en"):
    return [TranslationRequest(t, src, tgt, TranslationEngine.NVIDIA) for t in texts]


def test_batch_uses_language_pair_and_numbered_tags():
    t = FakeNvidia()
    out = run(t.translate_batch(reqs(["Hello", "World", "Yes"])))
    assert all(r.success for r in out)
    assert [r.translated_text for r in out] == ["TR(Hello)", "TR(World)", "TR(Yes)"]
    assert len(t.calls) == 1
    assert t.calls[0][0] == "en-tr"
    assert t.calls[0][1] == "<s0>Hello</s0> <s1>World</s1> <s2>Yes</s2>"
    assert all(r.engine == TranslationEngine.NVIDIA for r in out)


def test_auto_source_language_is_english():
    t = FakeNvidia()
    run(t.translate_batch(reqs(["Hello", "World"], src="auto")))
    assert t.calls[0][0] == "en-tr"


def test_placeholders_round_trip():
    t = FakeNvidia()
    out = run(t.translate_batch(reqs(["Hello, [player_name]! {i}Wait{/i} %d left"])))
    assert out[0].success
    for needle in ("[player_name]", "{i}", "{/i}", "%d"):
        assert needle in out[0].translated_text


def test_a_missing_line_is_asked_again_alone_without_splitting_the_group():
    t = FakeNvidia(behaviour="drop_one")
    texts = [f"line {i}" for i in range(12)]
    out = run(t.translate_batch(reqs(texts)))
    assert [r.translated_text for r in out] == [f"TR({x})" for x in texts]
    group_calls = [c for c in t.calls if "<s" in c[1]]
    singles = [c for c in t.calls if "<s" not in c[1]]
    assert len(group_calls) == 1                  # no bisecting
    assert [c[1] for c in singles] == ["line 11"]  # only the lost line is re-asked


def test_reply_without_tags_degrades_to_smaller_groups_and_singles():
    t = FakeNvidia(behaviour="merge_all")
    texts = [f"line {i}" for i in range(6)]
    out = run(t.translate_batch(reqs(texts)))
    assert [r.translated_text for r in out] == [f"TR({x})" for x in texts]
    assert t.sizer.size < 15


def test_line_that_loses_a_token_is_asked_again_alone():
    t = FakeNvidia(behaviour="lose_token")
    texts = ["Hello", "Hi [name], welcome", "Bye"]
    out = run(t.translate_batch(reqs(texts)))
    # the single re-ask goes through the same fake and drops the token again, so the
    # pipeline's own guard (inject_missing_placeholders / fallback) decides; what we
    # assert here is that a lone request for that line was made.
    singles = [c for c in t.calls if "<s" not in c[1]]
    assert any("welcome" in c[1] for c in singles)
    assert len(out) == 3


def test_multiline_text_is_translated_per_line_and_rejoined():
    t = FakeNvidia()
    out = run(t.translate_batch(reqs(["one\ntwo\n\nfour", "x"])))
    assert out[0].translated_text == "TR(one)\nTR(two)\n\nTR(four)"
    assert out[1].translated_text == "TR(x)"
    # no request may contain a raw newline: Riva would merge the lines
    assert all("\n" not in c[1] for c in t.calls)


def test_text_containing_our_tag_markers_goes_alone():
    t = FakeNvidia()
    out = run(t.translate_batch(reqs(["a <s1> b", "c", "d"])))
    assert all(r.success for r in out)
    assert any(c[1] == "a <s1> b" for c in t.calls)
    assert not any("a <s1> b" in c[1] and c[1] != "a <s1> b" for c in t.calls)


def test_no_whitespace_is_invented_around_a_reply():
    # The syntax guard trims the source (same as Bing); Riva sometimes prefixes a space
    # (' Evet'), which must not reach the output.
    class Spacey(FakeNvidia):
        async def _call(self, system, text):
            out, err, quota = await super()._call(system, text)
            return " " + out + " ", err, quota

    out = run(Spacey().translate_batch(reqs(["Yes", "No"])))
    assert [r.translated_text for r in out] == ["TR(Yes)", "TR(No)"]


def test_unsupported_target_language_is_delegated():
    class FB:
        _engine = TranslationEngine.GOOGLE

        async def translate_batch(self, rs):
            return [TranslationResult(r.text, "G:" + r.text, r.source_lang, r.target_lang,
                                      TranslationEngine.GOOGLE, True) for r in rs]

    t = FakeNvidia()
    t.set_fallback_translator(FB())
    out = run(t.translate_batch(reqs(["Hi"], tgt="sw")))
    assert out[0].success and out[0].translated_text == "G:Hi"
    assert out[0].engine == TranslationEngine.NVIDIA
    assert out[0].metadata["fallback_engine"] == "google"
    assert t.calls == []


def test_http_failure_without_fallback_reports_error_not_success():
    class Down(FakeNvidia):
        async def _call(self, system, text):
            return None, "HTTP 401: bad key", False

    out = run(Down().translate_batch(reqs(["a", "b"])))
    assert [r.success for r in out] == [False, False]
    assert "401" in out[0].error


def test_missing_api_key_fails_cleanly_and_probe_says_why():
    t = NvidiaTranslator(api_key="")
    out = run(t.translate_batch(reqs(["Hi"])))
    assert not out[0].success and "API key" in out[0].error
    assert "API key" in run(t.probe_endpoint())


def test_long_lines_do_not_share_a_request_beyond_the_character_budget():
    t = FakeNvidia()
    long = "x" * 2000
    run(t.translate_batch(reqs([long, long, long, long])))
    assert all(len(c[1]) <= NvidiaTranslator.MAX_CHARS_PER_REQUEST + 60
               for c in t.calls)
    assert len(t.calls) >= 2


def test_stop_aborts_requests_in_flight_and_skips_the_fallback():
    import time

    class Slow(FakeNvidia):
        async def _call(self, system, text):
            await asyncio.sleep(30)          # a request that would take half a minute
            return None, "never", False

    class FB:
        _engine = TranslationEngine.GOOGLE
        used = False

        async def translate_batch(self, rs):
            FB.used = True
            return []

    t = Slow()
    t.STOP_POLL_SECONDS = 0.02
    t.set_fallback_translator(FB())
    flag = {"stop": False}
    t.should_stop_callback = lambda: flag["stop"]

    async def go():
        task = asyncio.ensure_future(t.translate_batch(reqs(["a", "b", "c"])))
        await asyncio.sleep(0.1)
        flag["stop"] = True
        return await asyncio.wait_for(task, timeout=3)

    started = time.monotonic()
    out = run(go())
    assert time.monotonic() - started < 3
    assert [r.success for r in out] == [False, False, False]
    assert not FB.used


def test_manager_cancels_any_engine_when_stopped():
    from src.core.translators.manager import TranslationManager

    class SlowGoogle:
        async def translate_batch(self, rs):
            await asyncio.sleep(30)

    m = TranslationManager.__new__(TranslationManager)
    m.STOP_POLL_SECONDS = 0.02
    flag = {"stop": False}
    m.should_stop_callback = lambda: flag["stop"]

    async def go():
        task = asyncio.ensure_future(m._await_unless_stopped(SlowGoogle().translate_batch([])))
        await asyncio.sleep(0.1)
        flag["stop"] = True
        return await asyncio.wait_for(task, timeout=3)

    assert run(go()) is None


# ── key check and Stop through the manager ───────────────────────────────────

class _Resp:
    def __init__(self, status, payload=None):
        self.status, self._payload, self.headers = status, payload or {}, {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, content_type=None):
        return self._payload

    async def text(self):
        return "detail"


class _Session:
    def __init__(self, status):
        self.status, self.posts, self.gets = status, [], []

    def post(self, url, **kw):
        self.posts.append(url)
        return _Resp(self.status, {"choices": [{"message": {"content": "Hallo"}}]})

    def get(self, url, **kw):
        self.gets.append(url)
        return _Resp(200)  # /models answers 200 whatever the key is


def _with_session(status):
    t = NvidiaTranslator(api_key="nvapi-made-up", rpm=100000)
    session = _Session(status)

    async def get_session():
        return session

    t._get_session = get_session
    return t, session


@pytest.mark.parametrize("status,expected", [
    (200, None), (429, None), (503, None), (401, "rejected"), (403, "rejected"), (404, "not found"),
])
def test_probe_checks_the_key_with_a_real_completion(status, expected):
    t, session = _with_session(status)
    reason = run(t.probe_endpoint())
    # /models accepts any key, so the probe must not rely on it.
    assert session.gets == [] and session.posts and session.posts[0].endswith("/chat/completions")
    if expected is None:
        assert reason is None
    else:
        assert expected in reason


def test_rejected_key_during_a_run_is_an_error_not_a_google_translation():
    class FB:
        _engine = TranslationEngine.GOOGLE
        used = False

        async def translate_batch(self, rs):
            FB.used = True
            return [TranslationResult(r.text, "G:" + r.text, r.source_lang, r.target_lang,
                                      TranslationEngine.GOOGLE, True) for r in rs]

    t, session = _with_session(401)
    t.set_fallback_translator(FB())
    out = run(t.translate_batch(reqs(["Hello there", "Good morning"])))
    assert [r.success for r in out] == [False, False]
    assert "rejected" in out[0].error
    assert not FB.used
    sent = len(session.posts)
    run(t.translate_batch(reqs(["One more line"])))
    assert len(session.posts) == sent  # a rejected key is not asked again


def test_stop_through_the_manager_cancels_the_open_requests():
    from src.core.translators.manager import TranslationManager

    state = {"started": 0, "finished": 0, "cancelled": 0}

    class Slow(FakeNvidia):
        async def _call(self, system, text):
            state["started"] += 1
            try:
                await asyncio.sleep(0.6)
                state["finished"] += 1
                return text, "", False
            except asyncio.CancelledError:
                state["cancelled"] += 1
                raise

    flag = {"stop": False}
    m = TranslationManager.__new__(TranslationManager)
    m.STOP_POLL_SECONDS = 0.01          # the manager notices first, as in a real run
    m.should_stop_callback = lambda: flag["stop"]
    t = Slow()
    t.STOP_POLL_SECONDS = 5
    t.should_stop_callback = m.should_stop_callback

    async def go():
        task = asyncio.ensure_future(m._await_unless_stopped(t.translate_batch(reqs(["a", "b", "c"]))))
        await asyncio.sleep(0.1)
        flag["stop"] = True
        result = await asyncio.wait_for(task, timeout=3)
        await asyncio.sleep(0.8)        # an orphaned request would finish here
        return result

    assert run(go()) is None
    assert state["started"] >= 1
    assert state["finished"] == 0 and state["cancelled"] == state["started"]
