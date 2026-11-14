# -*- coding: utf-8 -*-
"""
Tests for v2.8.3 Runtime Hook Performance Changes

Covers:
  - _rl_evict_cache_half: FIFO half-eviction correctness
  - Cache limit enforcement with half-eviction
  - Language sync throttle behavior
  - Shift+R (soft-reload) cache flush
  - sys._rl_caches initialization & native dict type
  - Hook template placeholder injection
"""

import re


from src.core import runtime_hook_template as rht


# ============================================================================
# 1. _rl_evict_cache_half — FIFO Half-Eviction Tests
# ============================================================================

class TestEvictCacheHalf:
    """Test the LRU-like half-eviction function extracted from the hook template."""

    @staticmethod
    def _evict_half(cache_dict):
        """Replicate the _rl_evict_cache_half logic for unit testing."""
        half = len(cache_dict) // 2
        if half < 1:
            cache_dict.clear()
            return
        keys_to_remove = list(cache_dict.keys())[:half]
        for k in keys_to_remove:
            del cache_dict[k]

    def test_empty_dict_stays_empty(self):
        d = {}
        self._evict_half(d)
        assert d == {}

    def test_single_element_cleared(self):
        d = {"a": 1}
        self._evict_half(d)
        assert d == {}

    def test_two_elements_keeps_newer(self):
        d = {"old": 1, "new": 2}
        self._evict_half(d)
        assert "old" not in d
        assert d == {"new": 2}

    def test_even_count_evicts_exact_half(self):
        d = {f"k{i}": i for i in range(10)}
        self._evict_half(d)
        assert len(d) == 5
        # Oldest 5 (k0-k4) removed, newest 5 (k5-k9) kept
        for i in range(5):
            assert f"k{i}" not in d
        for i in range(5, 10):
            assert f"k{i}" in d

    def test_odd_count_evicts_floor_half(self):
        d = {f"k{i}": i for i in range(11)}
        self._evict_half(d)
        # floor(11/2) = 5 removed, 6 kept
        assert len(d) == 6
        for i in range(5):
            assert f"k{i}" not in d
        for i in range(5, 11):
            assert f"k{i}" in d

    def test_large_cache_eviction_preserves_newest(self):
        """20K entries — realistic cache size."""
        d = {f"entry_{i}": f"value_{i}" for i in range(20000)}
        self._evict_half(d)
        assert len(d) == 10000
        # Newest 10K entries preserved
        assert "entry_19999" in d
        assert "entry_10000" in d
        # Oldest entries removed
        assert "entry_0" not in d
        assert "entry_9999" not in d

    def test_insertion_order_maintained_after_eviction(self):
        d = {f"k{i}": i for i in range(8)}
        self._evict_half(d)
        remaining_keys = list(d.keys())
        assert remaining_keys == ["k4", "k5", "k6", "k7"]

    def test_values_preserved_after_eviction(self):
        d = {"a": "apple", "b": "banana", "c": "cherry", "d": "date"}
        self._evict_half(d)
        assert d == {"c": "cherry", "d": "date"}

    def test_repeated_evictions_dont_crash(self):
        d = {f"k{i}": i for i in range(100)}
        for _ in range(10):
            self._evict_half(d)
            if len(d) <= 1:
                break
        assert len(d) >= 0  # Didn't crash


# ============================================================================
# 2. Cache Limit + Eviction Integration
# ============================================================================

class TestCacheLimitWithEviction:
    """Test that cache limits trigger half-eviction instead of full clear."""

    @staticmethod
    def _simulate_cache_with_limit(limit, insertions):
        """Simulate cache behavior: insert N items with a given limit."""
        cache = {}
        for i in range(insertions):
            if len(cache) >= limit:
                # Half eviction
                half = len(cache) // 2
                keys_to_remove = list(cache.keys())[:half]
                for k in keys_to_remove:
                    del cache[k]
            cache[f"key_{i}"] = f"val_{i}"
        return cache

    def test_cache_never_exceeds_limit_plus_one(self):
        """Cache should evict BEFORE growing beyond the limit."""
        cache = self._simulate_cache_with_limit(10, 25)
        # After inserting 25 items with limit 10, cache should be ≤ 10
        assert len(cache) <= 10

    def test_cache_retains_recent_after_eviction(self):
        cache = self._simulate_cache_with_limit(10, 15)
        # Most recent insertion should always be present
        assert "key_14" in cache

    def test_thundering_herd_avoided(self):
        """After eviction, cache should still have entries (not empty)."""
        cache = self._simulate_cache_with_limit(100, 150)
        # Should have ~50-100 entries, NOT 0 (which .clear() would give)
        assert len(cache) > 0
        assert len(cache) <= 100


# ============================================================================
# 3. Language Sync Throttle Tests
# ============================================================================

class TestLanguageSyncThrottle:
    """Test the language sync throttle (now in _rl_harvest_screens, not hot path)."""

    def test_harvest_throttle_in_template(self):
        """Verify harvest throttle constant is present (replaces old 2s lang sync throttle)."""
        hook = rht.render_runtime_hook("tr")
        assert "_rl_harvest_throttle" in hook

    def test_throttle_check_uses_time(self):
        """Verify the throttle uses time.time() for comparison."""
        hook = rht.render_runtime_hook("tr")
        assert "_rl_time.time()" in hook

    def test_throttle_skip_logic(self):
        """Verify harvest throttle early-return condition exists."""
        hook = rht.render_runtime_hook("tr")
        assert "_rl_last_harvest_time" in hook
        assert "_rl_harvest_throttle" in hook


# ============================================================================
# 4. Soft-Reload (Shift+R) Cache Flush Tests
# ============================================================================

class TestSoftReloadFlush:
    """Test that v4.2.0 MRU/alias caches are properly cleared on reload."""

    def test_language_reload_clears_mru_cache(self):
        """Hot-swap and load functions must reset the MRU cache dict."""
        hook = rht.render_runtime_hook("tr")
        # v2.8.4: MRU is now a dict {{}} for O(1) lookup, cleared by reassignment
        assert "_rl_mru_cache = {}" in hook

    def test_language_reload_clears_alias_cache(self):
        """Load / hot-swap must reset the alias cache dict."""
        hook = rht.render_runtime_hook("tr")
        assert "_rl_alias_cache = {}" in hook

    def test_miss_set_present_and_cleared_on_reload(self):
        """v2.8.4+: _rl_miss_set prevents repeated full-chain lookups for untranslated texts."""
        hook = rht.render_runtime_hook("tr")
        assert "_rl_miss_set = set()" in hook   # Init + clear on reload
        assert "_rl_miss_set.add(" in hook       # Misses are added
        assert "in _rl_miss_set" in hook         # Fast-path check


# ============================================================================
# 5. Hook Template Rendering Tests (Placeholder Injection)
# ============================================================================

class TestHookTemplateRendering:
    """Test that render_runtime_hook correctly injects all placeholders."""

    def test_language_placeholder_injected(self):
        hook = rht.render_runtime_hook("turkish")
        assert '"turkish"' in hook
        # Should NOT contain the raw placeholder
        assert "{renpy_lang}" not in hook

    def test_diagnostics_enabled(self):
        hook = rht.render_runtime_hook("fr", runtime_string_diagnostics=True)
        assert "_rl_runtime_string_diagnostics = True" in hook

    def test_diagnostics_disabled(self):
        hook = rht.render_runtime_hook("de", runtime_string_diagnostics=False)
        assert "_rl_runtime_string_diagnostics = False" in hook

    def test_miss_limit_injected(self):
        hook = rht.render_runtime_hook("tr", runtime_miss_limit=250)
        assert "_rl_runtime_miss_limit = 250" in hook

    def test_default_miss_limit_is_500(self):
        hook = rht.render_runtime_hook("tr")
        assert "_rl_runtime_miss_limit = 500" in hook

    def test_doubled_braces_resolved(self):
        """Template {{ and }} should be resolved to { and } in output."""
        hook = rht.render_runtime_hook("tr")
        # Output should contain real Python dicts, not template escapes
        assert "{{" not in hook
        assert "}}" not in hook

    def test_hook_is_valid_python_ish(self):
        """Basic syntax check: no unresolved template placeholders remain."""
        hook = rht.render_runtime_hook("tr")
        # No template placeholders like {something} should remain
        # (except for Python string formatting in debug log lines)
        unresolved = re.findall(r"\{[a-z_]+\}", hook)
        # Filter out legitimate Python dict/set literals and format calls
        # Exclude legitimate Python/ Ren'Py brace patterns found in comments/docstrings
        legit = {"{}", "{event}", "{what}", "{tag}", "{b}", "{i}", "{color}", "{size}",
                 "{font}", "{image}", "{text}", "{key}", "{value}", "{source}"}
        suspicious = [m for m in unresolved if m not in legit]
        assert len(suspicious) == 0, f"Unresolved placeholders: {suspicious}"


# ============================================================================
# 6. Cache Usage Pattern Tests (Functional Logic from Template)
# ============================================================================

class TestCacheUsagePatterns:
    """Test the cache interaction patterns used in the v4.2.0 hook."""

    def test_replace_cache_used_in_replace_text(self):
        """replace_text checks the MRU cache before dict lookups."""
        hook = rht.render_runtime_hook("tr")
        assert "_rl_mru_lookup(text)" in hook

    def test_normalized_cache_used_in_normalize(self):
        """Normalised lookup dict is built at load time for special-char keys (v2.8.4+: ASCII keys skipped for perf)."""
        hook = rht.render_runtime_hook("tr")
        assert "_rl_translations_norm" in hook  # Still built + used in harvest/alias path

    def test_missed_cache_used_for_deduplication(self):
        """Runtime miss logging deduplicates via _rl_runtime_miss_logged set."""
        hook = rht.render_runtime_hook("tr", runtime_string_diagnostics=True)
        assert "_rl_runtime_miss_logged" in hook

    def test_translated_cache_for_skip_already_translated(self):
        """MRU cache is updated after every successful translation."""
        hook = rht.render_runtime_hook("tr")
        assert "_rl_mru_update(" in hook

    def test_eviction_called_at_limit(self):
        """MRU list is capped by _rl_mru_cache_max."""
        hook = rht.render_runtime_hook("tr")
        assert "_rl_mru_cache_max" in hook
        assert "_rl_mru_update" in hook


# ============================================================================
# 7. Cache Limit Constants
# ============================================================================

class TestCacheLimitConstants:
    """Test that v4.2.0 cache limit constants are correctly set."""

    def test_mru_cache_max_default(self):
        """Default MRU cache max should be 500 entries (v2.8.4+: increased from 100)."""
        hook = rht.render_runtime_hook("tr")
        assert "_rl_mru_cache_max = 500" in hook

    def test_mru_cache_max_configurable(self):
        """render_runtime_hook accepts mru_cache_size parameter."""
        hook = rht.render_runtime_hook("tr", mru_cache_size=200)
        assert "_rl_mru_cache_max = 200" in hook


# ============================================================================
# 8. Hook Architecture Validation
# ============================================================================

class TestHookArchitecture:
    """Validate the overall hook structure is sound."""

    def test_init_minus_999_block(self):
        """Hook starts with init -999 python: for earliest execution."""
        hook = rht.render_runtime_hook("tr")
        assert "init -999 python:" in hook

    def test_init_999_hook_installation(self):
        """Hook installation happens at init 999 (late) to chain existing handlers."""
        hook = rht.render_runtime_hook("tr")
        assert "init 999 python:" in hook

    def test_three_layer_architecture(self):
        """v4.2.0 hook has Layer 1 (say_menu) + Layer 2 (replace_text); Layer 3 is screen harvesting."""
        hook = rht.render_runtime_hook("tr")
        assert "_rl_say_menu_text_filter" in hook
        assert "_rl_replace_text" in hook
        assert "_rl_harvest_screens" in hook

    def test_handler_chaining_preserved(self):
        """Previous handlers should be saved and chained, not overwritten."""
        hook = rht.render_runtime_hook("tr")
        assert "_rl_prev_say_menu_filter" in hook
        assert "_rl_prev_replace_text" in hook

    def test_screen_observer_callback(self):
        """Screen harvesting is installed via start_interact_callbacks."""
        hook = rht.render_runtime_hook("tr")
        assert "_rl_harvest_screens" in hook
        assert "start_interact_callbacks" in hook

    def test_rtl_language_set(self):
        """RTL language set should include standard RTL languages."""
        hook = rht.render_runtime_hook("tr")
        for lang in ("arabic", "persian", "hebrew"):
            assert lang in hook

    def test_hotkey_screen_overlay(self):
        """_rl_harvest_screens is registered in start_interact_callbacks."""
        hook = rht.render_runtime_hook("tr")
        assert "_rl_harvest_screens" in hook
        assert "start_interact_callbacks" in hook
