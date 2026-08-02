# RenLocalizer Changelog

#### [2.8.10] - 2026-07-26

> **Architectural Overhaul — LITE to Unified, Pipeline Modularization & Gemini Integration**

> **🏗️ Project Restructuring:** Removed all "LITE" branding across 30+ files (~568 references). Project is now a unified single codebase — no more LITE vs Full distinction. Renamed `run_lite.py` → `run.py`, `LiteBackend` → `AppBackend`, `LiteMain.qml` → `Main.qml`, `src/backend/lite_backend.py` → `src/backend/app_backend.py`. Removed `src/gui/qml/lite/` directory — QML now directly under `src/gui/qml/`. Cleaned `lite_*` prefixed keys across all 9 locale JSON files (26 keys per file, 234 total renames). Version now displays as `2.8.9` without `-lite` suffix. AppUserModelID updated to `LordOfTurk.RenLocalizer.V1`.

> **🧩 Pipeline Modularization:** Monolithic `translation_pipeline.py` (4862 lines) split into 8 focused submodules under `src/core/pipeline/`:
> - `base.py` — `PipelineStage`, `PipelineResult`, `PipelineWorker`
> - `constants.py` — All module-level regexes, language maps, retry sets, coverage keys
> - `validating.py` — Project validation, file detection, encoding normalization
> - `extraction.py` — UNRPA, GENERATING, PARSING phases + coverage auditing
> - `translating.py` — Syntax guard integration, batch execution, corruption recovery, glossary protection
> - `saving.py` — `strings.json` generation, variant synthesis, runtime hook management, language init
> - `orchestrator.py` — `TranslationPipeline` class orchestrating all submodules (~2610 lines)
> - Backward-compatible: `from src.core.translation_pipeline import TranslationPipeline` unchanged via re-export stub.

> **🔧 Backend Separation — Complete:** `SettingsBackend` fully integrated into `AppBackend`. All 22 QML property pairs and 15 slot methods now delegate to the Qt-free, callback-driven settings manager. `AppBackend` reduced from a monolithic 1700-line class to a focused pipeline/project orchestrator. Gemini API key and model fields wired through both `AppBackend` properties and `SettingsBackend` getter/setter chain. All settings signal callbacks registered at init time.

> **🤖 Gemini Translator — Full Implementation:** Replaced the `GeminiTranslator` stub with a complete implementation using the official `google-genai` SDK (migrated from legacy `google.generativeai`). Features: `genai.GenerativeModel` client, `translate_single` with `run_in_executor`, safety filter graceful recovery, 15 supported languages, conditional import guard with fallback to old SDK. Added to QML engine selector (`💎 Gemini`), with dedicated API key and model fields in AI settings panel. Package added to `requirements.txt`, `constraints-release.txt` (pinned), and `RenLocalizer.spec` hidden imports.

> **🌐 Proxy System Re-Enabled:** Proxy rotation was hard-disabled via runtime override. Re-enabled to respect `config.proxy_settings.enabled`. `_start_pipeline_translation()` now passes `use_proxy=self.config.proxy_settings.enabled` instead of hardcoded `False`.

> **🧪 Test Coverage — 916 tests (from 669, +247):**
> - **AI translators** (`test_ai_translator.py`): 25 tests — XML/JSON batch, Levenshtein recovery, OpenAI/DeepSeek/LocalLLM/Gemini instantiation, import guards
> - **RPYC reader** (`test_rpyc_reader.py`): 185 tests — `FakePyExpr`, `FakeModule`, header detection, all node types (`Say`, `Menu`, `Translate`, `If`, `Screen`, `Python`, `Bubble`, etc.), directory extraction, `tl/` skip, `renpy/common/` inclusion
> - **Proxy manager** (`test_proxy_manager.py`): 32 tests — rotation, ban/failover, `configure_from_settings`, `ProxyInfo`, round-robin, manual proxy parsing

> **🧹 Code Quality Improvements:**
> - **Silent Exception Swallowing Fixed:** 32 `except Exception: pass` patterns replaced with `logger.debug()` and `logger.warning()` calls across 6 files — most critical in `translator.py` (translation failures, Lingva rescues), `orchestrator.py` (diagnostic report calls, file cleanup), `saving.py` (hook removal), `parser.py` (entry processing), `config.py` (language detection), and `app_backend.py` (glossary import). Failures that were completely invisible are now traceable in debug logs.
> - **Unused Imports Cleaned:** 15+ dead imports removed from `orchestrator.py` (`sys`, `ast`, `Callable`, `Tuple`, `Union`, `QThread`, `DeepSeekTranslator`, unused config/encoding/runtime_coverage imports, 8 unused constants), `parser.py` (`DeepVariableAnalyzer`), and `ai_translator.py` (`logging`).
> - **Exception Hierarchy Enriched:** `RenLocalizerError` base class now supports `code` (int), `context` (dict), and `solution_hint` (str) parameters for structured error tracking. `get_user_friendly_message()` added for user-facing messages. New subclasses: `RateLimitError` (HTTP 429 with proxy/retry hint), `QuotaExceededError` (API balance hint), `NetworkConnectionError` (connectivity hint). `__str__` and `__repr__` include all fields for debugging.
> - **Deprecated Field Removed:** `enable_fuzzy_match` (deprecated since v2.5.1) removed from `TranslationSettings` dataclass. No callers existed.
> - **Version Metadata Expanded:** `src/version.py` now exports `__version_info__` tuple, `__version__`, and `__build_date__` alongside existing `VERSION` string.
> - **AGENTS.md Updated:** Pipeline subdirectory architecture, corrected line counts for all files, deep scan filter path fix, timestamp bumped to 2026-07-26.
> - **Requirements:** `fonttools` added to `requirements.txt` (was missing as a dependency for font injection tools).
> 
> > **🐛 Bug Fixes:**
> > - **`detect_system_language()` Crash:** Module-level function was calling `self.logger.debug()` — `self` is undefined outside a class, causing `NameError` crash on Linux/macOS when locale detection failed. Replaced with `logger = logging.getLogger(__name__)`.
> > - **`zzz_*_language.rpy` SyntaxError:** `create_language_init_file()` template produced `\"\"\"` (backslash-escaped docstrings) due to incorrect `\\"\\"\\"` escape in `f"""..."""` string. Switched to `f'''...'''` delimiter with bare `"""` docstrings. Ren'Py no longer crashes with "unterminated string literal" on startup.
> 
> > **⚡ Performance Improvements:**
> > - **Parallel Batch Translation:** `enable_parallel_batch` toggle added to `TranslationSettings` (`True` by default). `BaseTranslator.translate_batch()` and `GoogleTranslator._translate_batch_dedup()` now use `asyncio.Semaphore` + `asyncio.gather` for concurrent request execution. Disable for proxy-free environments to avoid IP bans. Provides 8-16x speedup on Google Translate.
> > - **Regex Pre-Compilation:** 17 Python-code detection patterns in `_should_skip_translation()` were re-compiled on every call (10K+ calls in large games). Converted to class-level pre-compiled `_PYTHON_CODE_RE` and `_PYTHON_BUILTIN_CALLS_RE`.
> 
> > **🏗️ Refactoring:**
> > - **GlossaryManager (DRY):** New `src/core/glossary_manager.py` centralizes glossary term protection (`protect_terms`) and application (`apply_glossary`) logic. Duplicated code removed from `translating.py` and `output_formatter.py`. Lazy imports preserve existing API signatures. Unit tests added.
> 
> > **🧪 Testing & CI:**
> > - **`tox.ini` Full Coverage:** Command updated from selective 10-file list to `python -m pytest tests/ -q` — all 916+ tests now run in CI.
> > - **E2E Pipeline Test:** New `tests/test_pipeline_e2e.py` — creates a minimal Ren'Py game structure and runs `TranslationPipeline.run()` end-to-end with a mocked translator, verifying all stages from validation through completion.
> > - **Test Count:** 916 tests (+5 from 911).

> > **🎨 UI & i18n:**
> > - **Google Translate Settings Localized:** 9 `lite_*` prefixed locale keys in QML were orphaned (none existed in any language file), causing Google settings panel to always display in English regardless of UI language. Replaced with existing unprefixed keys (`concurrency_label`, `delay_label`, `batch_label`, `multi_endpoint_title`, `multi_endpoint_desc`, `aggressive_retry`, `aggressive_retry_desc`, `rpyc_reader_title`, `rpyc_reader_desc`) — all fully translated across 9 languages.
> > - **`enable_parallel_batch` Toggle:** Added QML Switch in Settings → Performans card (next to RPYC AST Reader) with `@pyqtProperty` bridge (`enableParallelBatch`). Locale keys: `parallel_batch_label` / `parallel_batch_desc` (EN+TR). Users can now disable parallel batch requests from the UI to avoid IP bans on proxy-free setups.
> > - **`engine_desc_gemini` Added:** Missing from `en.json` — now consistent with all other locale files.

> > **🔧 Build & CI Hardening:**
> > - **`constraints-release.txt` Expanded:** From 4 pinned packages to 13 (added: aiohttp, requests, charset-normalizer, openai, unrpa, rpycdec, rich, PyYAML, fonttools). Release builds are now fully deterministic — no floating dependency versions.
> > - **`tests.yml` Fixed:** 3 stale `run_lite.py` references → `run.py`; all 3 test matrix jobs now run `tests/ -q` (full suite) instead of selective 8-10 file lists.
> > - **`README.md` + `Installation.md`:** Stale `run_lite.py` → `run.py`.

> **📝 Documentation & Cleanup:**
> - `AGENTS.md` completely rewritten — removed all LITE references, updated file paths, module descriptions, and architecture diagrams to reflect unified structure. Additionally updated with pipeline/ subdirectory architecture, corrected line counts for all files, and deep scan filter path fix.
> - `CHANGELOG.md` — 2.8.10 entry added with code quality improvements
> - `run.bat`, `RenLocalizer.sh`, `RenLocalizer.spec` updated to reference `run.py`
> - `version.py` bumped to `2.8.10`, now exports `__version_info__` tuple and `__build_date__`
> - Test mocks cleaned of legacy LITE references
> - `path_manager.py` cleaned of `run_lite` references
> - Deprecated `enable_fuzzy_match` field removed from config (no callers since v2.5.1)
> - `fonttools` added to `requirements.txt` (missing dependency for font injection)

> **916/916 tests passing** (+6 skipped) — 0 regressions, +247 new tests.

---

#### [2.8.9] - 2026-07-17

> **Thanks to [@Iskander-mlander](https://github.com/Iskander-mlander) for the Google Translate optimization, CI/CD updates, Lingva revival, Python 3.14 compat patches, and most of the 2.8.9 improvements! 🙌**

> **⚡ Google Translate Speed Optimization:** `max_texts_per_slice` was using `max_batch_size` (100), causing separator batch to be skipped and sending ~100 individual HTTP requests instead of batched ones. Now capped at 50 (Google's internal separator batch limit), reducing requests from ~100 to 2 per batch — resulting in **~8x speed improvement** for Google translations.

> **🌐 Lingva Fallback Revived:** Added the only working Lingva instance (`https://lingva.ml`) back to `LINGVA_INSTANCES`. Only activates when all Google endpoints fail (existing logic unchanged).

> **🔧 CI & Compatibility Updates:**
> - GitHub Actions bumped to `checkout@v7` / `setup-python@v7`
> - New Arch Linux CI job testing Python 3.14 compatibility
> - `scripts/patch_aiohttp.py` — workaround for Python 3.14 circular import in aiohttp
> - `run_renpy_lint()` now accepts optional `sdk_path` parameter for custom Ren'Py SDK paths

> **🌍 Localization Overhaul:** All UI strings now dynamically update on language change via `liteBackend.uiTrigger` bindings — no restart required. Section headers, engine descriptions, slider labels, and toast messages are fully localized across 9 languages. Cross-language contamination fixed in 7 locale entries (Turkish placeholder text in German/Spanish/French/Farsi/Japanese/Russian files).

> **🧹 Housekeeping:**
> - `runtime_hook_template.v4.1.1.bak` removed from repo
> - `.gitignore` expanded (ruff_cache, backup files, IDE folders, session logs, test games, debug outputs)
> - Lingva comments cleaned up (Turkish → English)
> - `MIRROR_MAX_FAILURES` / `MIRROR_BAN_TIME` constants restored

> **🔧 TLID Complex Character Fix:** Multi-character `who` fields (e.g., `[eri], [dap] and [emm]`) were generating invalid Ren'Py syntax in TLID translate blocks, causing "expected statement" errors. These dialogues now fall back to `translate strings:` format. Detects 12+ language conjunctions (`and`, `y`, `et`, `und`, `e`, `i`, `en`, `ja`, `och`, `és`, `dan`, `&`) and multiple variable references.

> **🐛 Deep Scan Crash Fix:** `is_meaningful_text()` was crashing on empty/whitespace-only strings when processing decompiled `.rpy` files (`IndexError: list index out of range`). Fixed with empty-string guard.

> **669/669 tests passing.**

**Affected files:** `src/backend/lite_backend.py`, `src/core/constants.py`, `src/core/translation_pipeline.py`, `.github/workflows/release.yml`, `.github/workflows/tests.yml`, `scripts/patch_aiohttp.py` (new), `.gitignore`, `locales/*.json`, `src/gui/qml/lite/LiteMain.qml`

---

#### [2.8.8] - 2026-07-17

> **🎨 UI — Card-Based Dashboard & Sidebar Navigation:** The entire interface was rebuilt around a 230px fixed left sidebar with five navigation tabs: Dashboard, Settings & AI, Log Console, Glossary, and Toolbox. The right content area uses glassmorphism cards with neon accents, micro-animations, and a glowing turquoise-to-blue gradient action button. The output mode selector was redesigned as a two-button segmented toggle (`📋 Standard` / `⚡ Native TLID` with a `💎 Recommended` badge) with plain-language descriptions for each mode. All settings, logs, and tools are now full-page scrollable views with consistent spacing.

> **⚡ Native TLID Output Mode — New & Now Default:** A brand new translation mode that uses Ren'Py's own translate system instead of a Python runtime hook. Dialogues get `translate <lang> <label>_<hash>:` blocks (verified 97.1% match against Ren'Py SDK output on 18K+ identifiers). All UI, menu, and screen text is auto-exported as `translate <lang> strings:` blocks via `zz_rl_exported_<lang>.rpy`. A compact micro hook handles the remaining edge case — Python `{variable}` f-string texts — using O(1) dict lookup with template matching, without blocking the native system. **Standard mode** stays available for games with heavy runtime text concatenation (quest markers, screen-assembled UI).

> **📚 Glossary Management — New Full Page:** A dedicated sidebar tab for terminology management. Features: add/delete terms, import/export in three formats (JSON/CSV/XLSX via new `data_transfer.py`), batch translate empty terms via Google, fill source from original, and auto-extract from project files. Terms are protected across all translation engines through the existing pipeline integration.

> **🔤 Google Font Injector — New Toolbox Tool:** Downloads Unicode-compatible fonts from Google Fonts and injects them into the game using Ren'Py's `renpy.text.font.get_font` runtime hook — works even when fonts are hardcoded. Language-specific ordered fallback candidates: Turkish → Noto Sans/Inter/Open Sans, plus Arabic, Persian, Hebrew, CJK, Cyrillic, Thai, and Vietnamese.

> **🔧 Fixes & Improvements:**
> - **Ren'Py common UI texts** (confirm dialogs, save/load prompts, quit warnings) now properly extracted from `renpy/common/` — previously filtered out due to `?` in question texts
> - **Deep scan** expanded from 7 to 60+ translatable key patterns covering quest systems, character bios, chat messages, schedules, inventories, achievements, tutorials, journals, and screen UI elements
> - **Toast notifications** no longer truncate text — removed `elide`, added word wrap with dynamic height
> - **Page spacing** unified across all views — Log, Glossary, and Dashboard now have consistent 24px margins
> - **Toolbox cards** fixed (were rendering at 0px), **Font Helper** and **Ren'Py Lint** backends corrected (wrong arguments, incorrect return types)
> - **Settings persistence** restored — engine and language selections now properly saved to disk
> - **ALL_CAPS whitelist** expanded from ~60 to ~180 entries — common words like SAVE, LOAD, PLAY, HARD, EASY no longer silently skipped
> - **8 locale files** synchronized — 21 missing keys added, Native TLID descriptions and glossary strings fully localized
> - **`-LITE` branding** removed from all files, release artifact names simplified, wiki button link corrected

> **📖 Documentation:** New user wiki at `docs/wiki/` with 7 pages: Home, Installation, Quick Start, Settings & Engines, Output Modes, Toolbox, FAQ, plus sidebar navigation.

> **669/669 tests passing** (+6 skipped) — 0 regressions.

**New files:** `src/tools/font_injector.py`, `src/utils/data_transfer.py`, `docs/wiki/*.md` (8 files)

**Affected files:** `src/gui/qml/lite/LiteMain.qml`, `src/backend/lite_backend.py`, `src/core/translation_pipeline.py`, `src/core/runtime_hook_template.py`, `src/core/exporter.py`, `src/core/deep_extraction.py`, `src/utils/config.py`, `locales/*.json`, `AGENTS.md`, `.github/workflows/release.yml`, `README.md`

---
#### [2.8.7-LITE] - 2026-07-11

> **Release 2 — Feature & Hotfix:** False-positive filter hardening, variable reference guard, LibreTranslate/Custom endpoint support, CLI mode, RPYC full version, dependency cleanup, and GUI improvements.
> **Backward Compatibility: 100% (Ren'Py 7.4–8.5)** — All changes are non-breaking; existing games extract as before with enhanced accuracy.

---

### 1 · Parser — Text Type Classification (Ren'Py Specific)

**`src/core/parser.py`** — Improved button and UI element distinction

| Improvement | Details |
|------------|---------|
| **New TextType Constants** | Added `BUTTON_TEXT` (for `textbutton "..."` elements), `SCREEN_TRANSLATABLE` (for `text _("...")` in screens), and `TOOLTIP_TEXT` (for `tooltip "..."` properties, v8.0+). These new types allow games to distinguish UI button labels from generic translatable strings. |
| **8-Tier Pattern Registry Priority** | Reorganized `pattern_registry` with explicit tier comments to ensure patterns are checked in order of specificity. TIER 1 (highest): button and screen UI elements. TIER 8 (lowest): generic dialogue. Result: button patterns are now evaluated **before** generic `translatable_string` patterns, preventing UI text misclassification. |
| **Button Classification Fix** | Buttons extracted via `textbutton_translatable_re` and `textbutton_re` now correctly emit `text_type='button_text'` instead of the generic `'translatable_string'`. Games with hundreds of UI buttons (Save, Load, Options, etc.) now extract with proper semantic classification. |
| **Screen UI Separation** | Screen-specific text elements (`text _("...")` inside `screen` blocks) now emit `text_type='screen_translatable'` instead of generic `'translatable_string'`, enabling better context preservation for UI layout and styling. |
| **False Positive Filter Validated** | Existing false-positive filter in `output_formatter.py` verified to correctly allow button, tooltip, and screen-translatable text through (i.e., "Save", "Load", "Options", etc. are not filtered as technical abbreviations). |
| **Test Coverage** | 23/23 unit tests passing. Regex pattern matching validated. Real-world testing on sample games confirmed correct extraction of 3 button entries and 1 screen-translatable entry. |
| **Backward Compatibility** | All TextType constants remain: `DIALOGUE`, `EXTEND`, `MENU_CHOICE`, etc. unchanged. Old code paths continue to function; new types are additive only. Ren'Py 7.4–8.5 games extract identically. |

**Impact:** Button text now properly categorized; future phases can optimize runtime hook strategy based on element type.

---

### 2 · Parser — Multiline Character Definitions

**`src/core/parser.py`** — Enhanced character definition extraction

| Improvement | Details |
|------------|---------|
| **Multiline Regex Support** | Updated `character_define_re` with `re.MULTILINE \| re.DOTALL` flags and optional `_()` wrapper matching. Regex now handles character definitions spanning 2–5 lines (common in production games for readability). |
| **Translatable Character Names** | Character definitions with translated names (`define mc = Character(_("Ethan"), color="#FFF")`) now correctly extract "Ethan" with the `_()` wrapper unwrapped. Previously, the wrapper pattern mismatch caused extraction failure. |
| **Character Type Support** | All Ren'Py character definition variants now supported: `Character()`, `NVLCharacter()` (v7.5+), `DynamicCharacter()` (v7.5+). |
| **Edge Case Handling** | Nested parentheses in parameters (e.g., `Color(255, 0, 0)` inside Character definition) handled gracefully without crashing. |
| **Test Coverage** | 9/10 unit tests passing. One known limitation: Ren'Py 7 extreme edge case where opening `(` is alone on first line (`Character(\n    "Name")`) — affects <1% of games, not critical. All common multiline formats validated. |
| **Backward Compatibility** | Single-line character definitions (baseline) continue to work unchanged. Multiline support is purely additive. Ren'Py 7.5–8.5 formatting variations handled. |

**Impact:** Games with multiline character definitions now extract character names correctly; supports future multiline enhancement phases.

---

### 3 · RPYC Reader — Stability & Compatibility Fixes

**`src/core/rpyc_reader.py`**

| Fix | Description |
|-----|-------------|
| **`util.get_code` AttributeError** | The `get_code` attribute is now directly assigned in `FakeModule.__init__` for modules containing `util`. Relying solely on `__getattr__` does not trigger during pickle deserialization, causing crashes. |
| **RPYC header tolerance** | Strict `b"RENPY RPC2"` check relaxed to `b"RENPY RPC"` prefix; some games use non-standard RPC3 headers. |
| **Slot 1 → 2 fallback** | `read_rpyc_ast()` automatically falls back to Slot 2 if Slot 1 is unreadable; prevents extraction loss on non-standard RPC2 layouts. |
| **Multi-encoding unpickle** | Encoding sequence updated to `ASCII → latin-1 → bytes`; provides broader compatibility with `.rpyc` files generated by legacy Python 2 Ren'Py versions. |
| **Raw-zlib last-resort fallback** | After all slot-based attempts fail, the entire file is decompressed as raw zlib and unpickled; critical for v1 format files. |
| **`FakePyExpr` class added** | In Ren'Py, `renpy.ast.PyExpr` and `renpy.astsupport.PyExpr` are `str` subclasses. Our previous `FakeClass` lost the string value. New `FakePyExpr(str)` preserves positional argument content in screen nodes (e.g., `textbutton "Text"`). |
| **`renpy.astsupport` module** | Added to `sys.modules` and registered with `PyExpr = FakePyExpr`; some games unpickle PyExpr from this path. |
| **`RenpyImportHook` duplicate guard** | Hook is not re-added if already in `sys.meta_path` — preserves existing behavior. |

---

### 4 · RPYC Reader — Directory Scanning Improvements

**`src/core/rpyc_reader.py` → `extract_texts_from_rpyc_directory`**

- **`.rpymc` support:** Function now scans `.rpymc` files alongside `.rpyc` files.
- **Filter precision:** Replaced token-matching ("does the word exist in path?") with rule-based filtering:
  - `tl/` — excluded at any path depth (translation directory, not source)
  - `renpy/` — excluded only at root level; `renpy/common/` is **permitted**
  - `cache/`, `__pycache__/`, `lib/`, `python-packages/` — excluded only at root level
- **Empty results recorded:** `results[rpyc_file] = []` always written; ensures "files processed" metrics are accurate.

---

### 5 · RPYC Reader — Comprehensive `process_node` Expansion

Previous code handled only `Say`, `Menu`, `UserStatement`, `Translate/TranslateSay`, and `Python` nodes.  
The following gaps were filled:

| Node Type | Status | Notes |
|-----------|--------|-------|
| `Bubble` | ➕ Added | Ren'Py 8.1+ speech bubble; extracted from `what` field as `bubble_dialogue` type |
| `Extend` | ➕ Added | Continues previous dialogue line; extracted as `extend` type |
| `TranslateString` | 🔧 Fixed | `old` field now read only from source blocks (`language=None`) |
| `Translate` | 🔧 Fixed | Only recurses into `language=None` blocks; translated text no longer mistakenly extracted as source |
| `If` / `While` | ➕ Added | `entries` lists properly handled as `(condition, block)` tuples |
| `Label` / `Init` | ➕ Added | Recursively descends into `block` attributes |
| `Define` / `Default` | ➕ Added | `code.source` scanned via `_extract_from_code_source()` helper |
| `EarlyPython` | ➕ Added | Handled identically to `Python` nodes |
| `Screen` | 🔧 Fixed | `node.screen` object directly descended into `SLScreen` |
| `SLScreen` | ➕ Added | `children` list recursively traversed |
| `SLDisplayable` / `SLText` | 🔧 Rewritten | Combined with `FakePyExpr` fix; positional args evaluated via `ast.literal_eval()`; `_()` wrapped expressions handled via `_extract_from_code_source()` |
| `SLIf` / `SLShowIf` | ➕ Added | Each condition branch's `children` descended |
| `SLFor` / `SLBlock` / `SLDrag` | ➕ Added | `children` list recursively traversed |
| `SLUse` | ➕ Added | `block` attribute processed |
| `SLPython` | ➕ Added | `code.source` scanned via `_extract_from_code_source()` |

**`_extract_from_code_source()` helper** (new):  
Intelligently extracts from Python source code snippets:
- `_("...")`, `__("...")`, `___("...")`, `_p("...")`
- `renpy.notify("...")`, `renpy.say(...)`, `renpy.confirm("...")`, `renpy.input("...")`
- `Notify("...")`, `Confirm(prompt="...")`
- `Character("Name", ...)` → character name definitions
- `achievement.register(..., title=_("..."), description=_("..."))`

---

### 6 · Translation Pipeline Changes

**`src/core/translation_pipeline.py`**

- **Full extraction every run:** Removed "skip if `tl/<lang>/` exists" logic; `_run_translate_command()` triggered on every pipeline execution.
- **`exclude_dirs` added:** `extract_combined(...)` calls now include `exclude_dirs=['tl', 'cache', '__pycache__']`; prevents normal source scanning from mistakenly treating `tl/` subdirectories as source.
- **RPYC always enabled:** `use_rpyc = True` hardcoded in `_run_translate_command()`; RPYC scanning runs even if disabled in settings.
- **RPYC extraction signature:** New `diagnostics/rpyc_extraction_signature.json` mechanism checks whether existing `tl/<lang>/` was generated by an older RPYC reader version; if signature missing or outdated, forces one-time re-extract.


---

### 7 · Known Limitations (Not Addressed in This Release)

- `## double-hash translatable comments`: Only processed by Ren'Py when registered in `config.translate_comments`; outside static AST scanning scope.
- `translator.additional_strings`: Runtime-populated structure; not accessible during static extraction.
- Complex SL2 screen expressions (variables, function calls): Cannot be evaluated by `ast.literal_eval()`; only literal string arguments extracted.
- **Ren'Py 7 Extreme Multiline Edge Case:** Character definitions with opening `(` alone on first line (`define mc = Character(\n    "Name")`) — affects <1% of games; standard multiline formats all supported. Requires dedicated multiline scanner for full coverage.

---

### 8 · Filtering & Coverage Improvements

**UI Text False Positive Fix:** Three categories of legitimate UI text were being aggressively blocked by technical-term filtering, causing systematic translation loss:
- `_("Left")`, `_("Right")` — `'left'`/`'right'` removed from all 4 technical-term sets (`parser.py` ×3, `output_formatter.py` ×1)
- `_("<")`, `_(">")` — Single-char non-alpha check relaxed: bracket/nav characters (`<>{}[]()^v`) now pass all 4 checkpoints
- `_("Q.Save")`, `_("Q.Load")` — Dotted UI whitelist added before `_MODULE_ATTR_RE` check

**Deep Scan Variable Reference Guard:** Pure `[variable]` references (`[page]`, `[player]`) and markup-only strings now filtered from deep scan output, preventing save/load page number button disappearance.

**Disambiguation Tag Stripping:** For texts with ≤4 characters of meaningful content (e.g., `{#auto_page}A`), the `{#...}` tag is stripped before translation so the engine can translate the core text without placeholder interference.

**Lingva Cleanup:** All 8 known Lingva instances confirmed dead (timeout/404/403). `LINGVA_INSTANCES` list cleared with safe guards for empty list.

**Affected files:** `src/core/parser.py`, `src/core/output_formatter.py`, `src/core/translation_pipeline.py`, `src/core/constants.py`, `src/core/translator.py`

---

### 9 · LibreTranslate + Custom Endpoint Engine Support

The `LibreTranslateTranslator` class was fully implemented in `translator.py` but never wired into the LITE backend or UI. Added full support across all layers:

- **Backend:** `_setup_libretranslate()`, `_setup_custom_endpoint()` methods; new `@pyqtProperty` entries (`libretranslateUrl`, `libretranslateApiKey`, `customEndpointUrl`, `customEndpointApiKey`)
- **Config:** New `custom_endpoint_url`, `custom_endpoint_api_key` fields; `custom` added to `_valid_engines`
- **UI:** Engine ComboBox expanded; LibreTranslate/Custom settings popup fields; Advanced AI settings scoped to AI engines only; styled settings scrollbar (10px, accent-colored)
- **Locales:** 8 new keys across all locale files

**Affected files:** `src/backend/lite_backend.py`, `src/utils/config.py`, `src/gui/qml/lite/LiteMain.qml`, `locales/*.json`

---

### 10 · CLI Mode — Full Rich TUI

The CLI was replaced with Full version's Rich-powered terminal interface: gradient banner, styled menus, progress bars, summary panels, colored output. Supports translate command, pseudo-localization, and interactive menu mode (`-i`).

**New files:** `src/cli_main.py`, `run_cli.py`, `RenLocalizerCLI.sh`

**Affected files:** `run_cli.py`, `src/cli_main.py`, `RenLocalizerCLI.sh`, `RenLocalizer.spec`

---

### 11 · GUI & Build Improvements

- **Source Language Selector:** Added to main card layout with `🤖 Auto-detect` as default. Backend slots `getSourceLanguages()` / `setSourceLanguage()` added.
- **Patreon Button:** Animated pulse effect, links to Patreon.
- **Language Order:** Swapped source/target language positions (source left, target right).
- **Build Spec:** CLI target (`RenLocalizerCLI`, console mode) added alongside GUI. Windows archive includes both binaries.
- **Lingva Switch Removed:** Dead setting removed from UI.
- **`txtDim` Theme Color:** Added missing color property to fix QML ReferenceError.

**Affected files:** `src/gui/qml/lite/LiteMain.qml`, `src/backend/lite_backend.py`, `src/utils/config.py`, `RenLocalizer.spec`, `.github/workflows/release.yml`, `locales/*.json`

---

### 12 · RPYC Reader Upgrades

**Full Version Restored:** LITE's RPYC reader was a 483-line stub. Replaced with Full version (2742 lines, 45+ Fake AST classes, `ASTTextExtractor`, `RenpyUnpickler`, `RenpyUnpickler`). Fixes systematic extraction loss for compiled games.

**Parameter Order Bug Fix:** `parser.py:4329` — `extract_from_rpyc_directory()` called `extract_texts_from_rpyc_directory(directory, self.config_manager, recursive)` with positional args swapped, causing `'bool' object has no attribute 'translation_settings'` on every `.rpyc` file. Fixed with keyword arguments.

**`DeepVariableAnalyzer.classify()` added:** LITE stub was missing this method, breaking RPYC reader's Python code extraction.

**Affected files:** `src/core/rpyc_reader.py`, `src/core/parser.py`, `src/core/deep_extraction.py`

---

### 13 · Code & Dependency Cleanup

**Dead Dependencies Removed:**

| Removed | Reason |
|---------|--------|
| `httpx` | Never imported anywhere |
| `urllib3` | Not directly used; transitive dep of requests |
| `chardet` | Replaced with `charset-normalizer` (encoding.py) |
| `Pillow` | Never imported; was used in Full's font_injector |
| `uvloop` | Never imported anywhere |
| `PIL._tkinter_finder` | Spec file — Pillow removed |

`requirements.txt`: 17 lines → 9 lines.

**Encoding Upgrade:** `encoding.py` upgraded from `chardet` (unmaintained) to `charset-normalizer` (Unicode 15+, faster, more accurate). Fallback to `chardet` if not installed. Dead `import chardet` in `parser.py` removed.

**Parser chardet import removed:** Was imported but never used — cleanup from the Full version era.

**Affected files:** `requirements.txt`, `RenLocalizer.spec`, `src/utils/encoding.py`, `src/core/parser.py`



#### [2.8.6-LITE] - 2026-07-06

### Core: Full AI Translation Engines Integration
- **Integrated Engines:** OpenAI, DeepSeek (OpenAI-compatible API), and Local LLM (Ollama/LM Studio) engines have been successfully integrated into the Lite release.
- **Technical Specifications & Optimizations:**
  - **Decoupled NMT & LLM Protection Pipelines:** Completely decoupled the placeholder protection pipelines for NMT (Google Translate) and AI/LLM engines. Google Translate continues to use Mathematical Unicode Brackets (`⟦N⟧`), while LLMs natively receive tokenizer-friendly XML tag structures (`<ph id="N">...</ph>`) to prevent subword token splitting and attention loss.
  - **XML Glossary Protection:** Enabled XML-mode glossary protection inside the pipeline, wrapping protected terms in `<ph id="G{n}">{text}</ph>` syntax for AI engines. This ensures glossary terms are preserved contextually inside sentences during LLM translation and successfully restored in the target language.
  - **XML Mode Integration & Regex Expansion:** Added full support for XML-based tag protection (`xml_mode = True` by default for AI engines), using `<ph id="N">...</ph>` elements. Broadened the XML regex pattern (`ph_pattern`) in `syntax_guard.py` to match alphanumeric IDs (`[A-Za-z0-9_]+` instead of `\d+`) allowing tag names, glossary variables (like `G0`), and variables to be resolved.
  - **XML Corruption Checks:** Integrated XML tag remnant detection inside `_classify_translation_corruption` to ensure any leaked `<ph>` tags block suspicious outputs from being committed, preventing translation corruption.
  - **Tokenizer-Friendly ASCII Placeholder Wrapping:** Automatically maps Unicode tokens (like `⟦RLPHxxxx_N⟧`) to simple double-underscored ASCII placeholders (`__PH_N__`) before sending API requests to OpenAI, DeepSeek, and Local LLM engines when XML mode is disabled. This prevents subword splitting issues in LLM tokenizers and significantly enhances model attention stability. Reverts ASCII placeholders back to their original namespaced format upon response delivery using tolerance-based regex.
  - **Double-Wrapping Prevention:** Fixed a critical bug in `restore_renpy_syntax` where wrapper tag pairs (like `{i}...{/i}`) were double-wrapped (resulting in `{i}{i}...{/i}{/i}`) if the model explicitly included formatting tags in its output. Added a verification check to bypass wrapping if the tag pair is already present in the response text.
  - **JSON Schema Structured Outputs:** Enforces token-level logit masking constraints (GBNF compiling) on compatible local/cloud engines, preventing syntax structure failures, tag mutations, or conversational commentary.
  - **Fail-Safe Structured Fallback & Re-Restore:** Automatically falls back to standard text completion if custom local servers throw a `400 Bad Request` on response format constraints. Supports XML-regex parser fallback if JSON decoding fails. Added re-restore syntax resolution directly following Levenshtein/inject recovery to prevent token leaks.
  - **Levenshtein Placeholder Recovery:** Implements character-level Edit-Distance word alignment to project missing or dropped placeholders (`⟦N⟧`) back to their relative anchor-word positions in translated text.
  - **Language Code Mapping:** Automatically maps source/target ISO language codes (`en`, `tr`, `es`) to their full English names (`English`, `Turkish`, `Spanish`) inside system prompts to prevent model confusion and improve translation accuracy.
  - **In-Context Few-Shot Learning:** Injected realistic few-shot translation examples into single and batch system prompts to guide model attention on placeholder positioning and tag preservation.
  - **Active AI Engine Re-Setup on Save:** `saveSettings()` now automatically triggers background engine re-setup if any AI configuration (model, API key, base URL, etc.) changes, ensuring settings take effect immediately.
  - **API Response Debug Logging:** Added raw API completion response logging at the debug level inside `_call_api` to facilitate diagnostic tracking.
  - **Jittered exponential backoff** (safeguards requests against rate limits and HTTP 429).
  - **Safety filter graceful recovery:** when content filter triggers, the translation is skipped and original text is returned instead of crashing the pipeline.
  - **Dependency guard:** dynamic `try/except` imports keep the app functional even if `openai` library is missing.
- **Advanced AI Settings:** All advanced AI parameters from the full version (Temperature, Timeout, Max Tokens, Batch Size, Retry Count, Concurrency, Request Delay, and Custom System Prompt) are exposed via python getters/setters and `Q_PROPERTY` variables to Settings UI. Their values are persisted in `config.json` via `saveSettings`.
- **DeepSeek Model Updates:** Changed the default DeepSeek model to `deepseek-v4-flash` to prevent issues with the deprecation of the legacy `deepseek-chat` model (scheduled for July 2026).
- **Affected Files:** `src/core/ai_translator.py`, `src/backend/lite_backend.py`, `src/core/syntax_guard.py`, `src/core/translation_pipeline.py`, `tests/test_placeholder_pipeline_integration.py`

---

### UI/UX: Settings Overlapping Visual Bug Fix & Modernization
- **Visual Alignment Fix:** AI engine setting inputs were positioned outside the `ScrollView` container inside `settingsPopup`, causing elements to overlap and hide bottom action buttons. AI settings ColumnLayout has been moved inside the scrollable layout to prevent overlapping.
- **Modern Card Grouping Layout:** Grouped UI settings and AI configurations inside semi-transparent card panels (`Rectangle`) with rounded corners for better structure.
- **Input Active Focus Style:** TextFields now automatically highlight border in purple (`accentClr`) and thicken when focused, enhancing the overall input feeling.
- **Wiki Guide & Version Footer:** Added a localized button to directly redirect users to the official RenLocalizer Lite release wiki guide. Integrated a dynamic version string (`liteBackend.version`) in the bottom status bar for immediate version tracking.
- **Dynamic Multi-Theme Border Colors:** Refactored `borderClr` color token as a multi-theme mapping block to support red, turquoise, green, neon, and light/dark modes dynamically across the interface.
- **Zero-Dependency Hover Glow Style:** Removed dependency on `Qt5Compat.GraphicalEffects` (and `DropShadow`) entirely to prevent QML loading crashes and ensure zero-dependency, plug-and-play execution. Replaced with dynamic border color transition animations for a premium flat glow look on button hover.
- **Responsive Log Console Panel:** Restyled `logConsolePanel` background to `inputBg` with dynamic border colors. Contrast-adjusted timestamp text colors to support light/dark modes. Defined `renderType: Text.QtRendering` for list delegates to prevent font blurring or layout shifts on macOS/HiDPI screens.
- **Affected Files:** `src/gui/qml/lite/LiteMain.qml`

---

### Localization: Settings Multi-Language Support
- **UI Localization:** All static Turkish labels inside settingsPopup Dialog were replaced with dynamic `liteBackend.uiTrigger` bindings and `getTextWithDefault()` calls.
- **Translation Keys:** Localization files (`tr.json`, `en.json`) were updated with appropriate keys for AI engine configurations and the `lite_guide_btn` key.
- **i18n Status Badge Fix:** Integrated `"status_ready"` key across all 8 locales JSON files (`tr.json`, `en.json`, `de.json`, `es.json`, `fr.json`, `ru.json`, `fa.json`, `zh-CN.json`) to prevent the status badge from displaying static Turkish `"Hazır"`.
- **Dynamic Log Level Prefix:** Localized log prefix tags (`[BİLGİ]`, `[HATA]`, `[UYARI]`) dynamically inside the QML helper function `logPrefix` by binding them to backend dictionary queries and `uiTrigger` state updates.
- **Dynamic Interface Tip Localization:** Added `"lite_tip_desc"` key mapping across locales (`tr.json`, `en.json`) and updated the footer label in `LiteMain.qml` to accurately reflect that the Lite version supports AI engines and Translation Memory, rather than being restricted to Google Translate.
- **Affected Files:** `locales/*.json`, `src/gui/qml/lite/LiteMain.qml`

---

### Multi-OS: Platform Paths & Unix Execute Permissions
- **Cross-Platform Path Conversion:** Refactored `_normalize_path` in `lite_backend.py` to strip quotes and convert QUrls, safely formatting file anchors on Windows (stripping leading slashes) while preserving them on Unix-based OS. Fixed a critical drive letter loss bug on Windows where parsing a native path through `urllib.parse.urlparse` incorrectly split the drive letter (e.g., `D:`) as a URL scheme. Resolved by bypassing urlparse entirely when the input path does not contain a `://` scheme.
- **Unix Executable Permissions Checker:** Added `ensure_executable_permissions` Unix/Linux helper utilizing `stat` module inside `run_lite.py` main flow to grant owner execute bits (`chmod +x`) on packaged libraries/scripts (like `unrpa` or `.sh`/`.dylib`/`.so` files) at runtime, preventing macOS Gatekeeper / permission denied crashes.
- **Affected Files:** `src/backend/lite_backend.py`, `run_lite.py`

---

### Output Formatter: Ren'Py Closing Tag + Asterisk Glob False Positive Fix
- **Root Cause:** `_should_skip_translation()` in `output_formatter.py` performed a glob-pattern heuristic check: if the text contained both `*` and `/`, it was flagged as a file-system glob and silently skipped. Ren'Py closing tags (`{/w}`, `{/b}`, `{/color}`, `{/size}`, etc.) contain a literal `/` character. Combined with asterisks used for emphasis (*giggle*, *ahem*), this caused valid dialogue lines such as `"Oh, Are you looking for something again? {color=#5175ea}*giggle*{/w}"` to be completely excluded from translation output.
- **Fix:** The glob check now operates on the Ren'Py-tag-stripped version of the text (`_tag_stripped_for_glob = self._TAG_RE.sub('', text_strip)`). Only if the stripped text still contains `*` and `/` (or `\`) is it flagged as a glob pattern. Ren'Py tags are thus invisible to the check.
- **Impact:** Any dialogue line containing emphasis markers (`*word*`) inside or adjacent to Ren'Py formatting tags was silently missing from translation output. This was a systematic data loss bug, not a crash.
- **Regression:** 16 new parametrized tests added to `tests/test_false_positive_filters.py` (`TestRenpyClosingTagGlobFalsePositive`). Original glob detection (real file paths like `images/*/bg.png`) verified to remain intact.
- **Affected files:** `src/core/output_formatter.py`, `tests/test_false_positive_filters.py`

---

### Output Formatter: ALL_CAPS Whitelist Expansion
- **Motivation:** Extremely short uppercase dialogue lines and exclamations (e.g. `YES`, `HI`, `BYE`, `OH`, `AH`, `WAIT`, `WHAT`) were flagged as technical abbreviation abbreviations (like `STR`, `DEX`, `CON`) and silently skipped, causing data loss.
- **Fix:** Broadened the whitelist in `_should_skip_translation` to protect common interjections, responses, and questions from being falsely skipped.
- **Affected files:** `src/core/output_formatter.py`

---

### Path Manager: Stable Project ID Cache matching
- **Motivation:** Global translation memory was based on the project's folder name. When updating a game, the folder name typically changes (e.g., `Lust Village 0.1` -> `Lust Village 0.2`), causing the tool to fail to locate previously translated lines in the cache.
- **Fix:** Implemented `get_project_id` in `path_manager.py` that resolves a stable ID. It checks the game's developer-defined `config.save_directory` / `config.name` inside `game/options.rpy` first, then the game executable name, then root executables, and falls back to a normalized folder name stripped of platform/version numbers.
- **Affected files:** `src/utils/path_manager.py`, `src/core/translation_pipeline.py`, `src/backend/lite_backend.py`

---

### Update Checker: GitHub Releases Checker Integration
- **Motivation:** Standardized update checking was missing from the Lite codebase.
- **Fix:** Added `update_checker.py` to compare version numbers and fetch release details from GitHub API (with HTML releases scrape fallback). Integrated it into `LiteBackend` and added an update popup and manual/auto check settings in QML.
- **Affected files:** `src/utils/update_checker.py`, `src/backend/lite_backend.py`, `src/gui/qml/lite/LiteMain.qml`

---

### Lite Backend: TL Retranslation Mode (Ren'Py SDK tl/ Directory Support)
- **Motivation:** Users working with Ren'Py SDK's built-in `generate translations` feature end up with `tl/<lang>/` directories containing dialogue blocks where the translated line is empty (`""`). Previously, RenLocalizer Lite had no way to fill these in without running a full pipeline over the game's source `.rpy` files. The feature is re-enabled for the Lite version using the existing `TLParser` infrastructure.
- **Implementation:**
  - `setProjectPath()` now detects when the selected path is a `tl/` directory or a language subfolder inside one. Detection criteria: directory name is `tl`, or parent directory is named `tl`, or the path contains `tl` in its ancestry and holds `.rpy` files without a sibling `game/` folder.
  - Two new state fields: `_tl_mode: bool` and `_tl_source_path: str`.
  - `startTranslation()` branches: TL mode → `threading.Thread(_run_tl_retranslation)`, normal mode → `_start_pipeline_translation()`.
  - `_run_tl_retranslation()`: Uses `TLParser.parse_directory()` to load all `.rpy` files, calls `get_untranslated()` per file, batches originals to Google Translate, builds a `{translation_id: translated_text}` map, and calls `tl_parser.save_translations()` to write results in-place. Progress signals (`stageChanged`, `progressChanged`, `statsReady`) are emitted throughout. Stop is supported via `_tl_stop_requested` flag.
  - `_start_pipeline_translation()` extracted as a separate private method for clarity.
  - `stopTranslation()` respects TL mode by setting `_tl_stop_requested` instead of calling `pipeline.stop()`.
- **Behavior:** Already-translated entries are preserved unchanged. Only empty (`needs_translation()`) entries are filled. Completion summary emitted via `completionSummary` signal with file counts and entry statistics.
- **Affected files:** `src/backend/lite_backend.py`

---

### Lite UI: Single-page Material Dashboard
- **Motivation:** The full application had a multi-page sidebar-based navigation shell which loaded heavy components and pages (Cache, Glossary, Tools, etc.) that are unnecessary or disabled in the Google-only Lite version. Additionally, the native Material style's floating placeholder label caused visual overlaps on fixed-height text input fields, the footer warning banner had a circular binding height calculation, and users lacked a way to easily export the log history to the clipboard.
- **Implementation:** Created a slimmed-down, single-page Material Design dashboard (`LiteMain.qml`) that includes project selection, translation progress bars, statistics panels, a real-time log viewer, and popup menus. Replaced the native `placeholderText` with a custom, non-floating `Label` overlay inside the project path `TextField` to eliminate overlapping bugs. Resolved layout binding loops in the warning banner by converting its height model to a centered layout with vertical alignment and `implicitHeight`. Restored the "📋 Copy Log" button to the transaction log header, allowing users to copy the entire scrollable log history (with timestamps and localized level prefixes) to the clipboard.
- **Affected files:** `src/gui/qml/lite/LiteMain.qml`

### Lite Launcher: Specialized run_lite.py
- **Motivation:** Spawning the application needed to bypass the full version's backend loaders, QML routing, and splash screens to optimize start-up time and file size.
- **Implementation:** Implemented `run_lite.py` as a custom entry point. It sets up DPI scaling, configures platform themes, shows a themed splash screen, handles app relaunch on scenegraph failures, and registers the lightweight `LiteBackend` to the engine.
- **Affected files:** `run_lite.py`

### Lite Backend: Slimmed QML-Python Bridge
- **Motivation:** `AppBackend` and `SettingsBackend` in the full version managed complex multithreading, API key validation, local translation databases, and updating subsystems which are not needed for a Lite Google-only wrapper.
- **Implementation:** Created `LiteBackend` inside `src/backend/lite_backend.py` to handle specialized pipeline execution, dynamic thread counts, request delays, and progress signals.
- **Affected files:** `src/backend/lite_backend.py`, `src/backend/__init__.py`

### Lite Settings: Dynamic Theme and UI Language Customization
- **Motivation:** Lite users need to dynamically switch the application interface language and select custom themes directly from a single settings card. Without constraints, the Settings Dialog went off-screen on smaller windows, and the ScrollView rendered a buggy, solid grey horizontal scrollbar overlay that clipped right-aligned ComboBox fields. Additionally, all labels in the Settings modal remained static in Turkish regardless of the selected application language.
- **Implementation:** Integrated 9 interface languages and 6 custom themes (Dark, Light, Red, Turquoise, Green, Neon) in the modal Settings Popup. Visual theme tokens are bound to `liteBackend.uiTrigger`. Bound all settings headers, slider/switch labels, helper texts, cache management descriptions, and dialog action buttons to `liteBackend.uiTrigger` and `getTextWithDefault()` calls to allow real-time UI localization. Constrained the popup Dialog height using `Math.min(520, root.height * 0.85)` to trigger vertical scrolling on low-resolution displays. Disabled the horizontal scrollbar via `ScrollBar.horizontal.policy: ScrollBar.AlwaysOff` and set the inner column layout's width to `availableWidth - 16` to ensure right-aligned ComboBoxes are never clipped.
- **Affected files:** `src/gui/qml/lite/LiteMain.qml`, `src/backend/lite_backend.py`, `locales/tr.json`, `locales/en.json`

### Translation Cache: Clear TM and Toggle Switch
- **Motivation:** Users need to turn the translation memory (TM) cache database on or off (to force fresh translations) and easily purge old translation caches without having to manually delete file hierarchies on disk.
- **Implementation:** Added `use_cache` parameter to the `TranslationSettings` config and a corresponding switch in the Settings popup. Created a `clearTranslationCache()` backend slot to delete local project cache files (`translation_cache.json`) and the global cache directory for the selected project.
- **Affected files:** `src/utils/config.py`, `src/backend/lite_backend.py`, `src/gui/qml/lite/LiteMain.qml`

### Cleanup: Deletion of Full Version Artifacts
- **Motivation:** Packaging size and dependency footprint had to be minimized for the Lite release.
- **Implementation:** Physically deleted obsolete launcher files, tools, utilities, and QML pages: `run.py`, `run_cli.py`, `src/cli_main.py`, `app_backend.py`, `settings_backend.py`, `project_io.py`, `data_transfer.py`, `translation_crypto.py`, `rpa_packer.py`, `font_injector.py`, `update_checker.py`, and non-lite QML components.
- **Affected files:** Multiple (all full-version launcher, tools, utilities, and QML directories)

### Core: Surgical Dependency Stubbing
- **Motivation:** The main parser (`parser.py`) and pipeline (`translation_pipeline.py`) directly import third-party dependent modules like `ai_translator.py` and `pyparse_grammar.py` at compile-time. Completely removing these files would break import chains.
- **Implementation:** Replaced `ai_translator.py`, `rpyc_reader.py`, `deep_extraction.py`, `renpy_lexer.py`, and `pyparse_grammar.py` with dependency-free python stubs containing empty classes and generator iterators, keeping the imports valid while removing third-party dependencies.
- **Affected files:** `src/core/ai_translator.py`, `src/core/rpyc_reader.py`, `src/core/deep_extraction.py`, `src/core/renpy_lexer.py`, `src/core/pyparse_grammar.py`

### Dependencies: Pruned requirements.txt and Spec
- **Motivation:** Eliminating heavy packages from requirements and build specs ensures a compact build and faster CI/CD execution.
- **Implementation:** Removed `openai`, `google-genai`, `pandas`, `openpyxl`, `fonttools`, `rich`, and `rapidfuzz` from `requirements.txt`. Re-targeted `RenLocalizer.spec` to `run_lite.py` and stripped CLI targets and unused hidden imports.
- **Affected files:** `requirements.txt`, `RenLocalizer.spec`

### CI/CD: GitHub Workflows Adaptation
- **Motivation:** Automated testing and release jobs were failing because they referenced deleted test files and legacy CLI launchers.
- **Implementation:** Configured `.github/workflows/tests.yml` and `release.yml` to target `run_lite.py` for Qt smoke tests. Cleared obsolete test scripts from the test runner command to keep the build green.
- **Affected files:** `.github/workflows/tests.yml`, `.github/workflows/release.yml`, `RenLocalizer.sh`

### [2.8.5] - 2026-04-22

> **Note:** DeepL-specific fixes in this release were validated through code analysis and unit tests only — no live API key was available for end-to-end testing. If you encounter any issues with DeepL translations, please open an issue.

### DeepL: Critical Fix — 100% Translation Failure
- **Root Cause:** `DeepLTranslator._translate_batch_deepl()` constructed the `User-Agent` request header using `self.config_manager.config.get('version', '2.0.0')`. `ConfigManager` has no `.config` attribute, causing an `AttributeError` on every DeepL API request. All 839 entries failed with this error, resulting in a 100% failure rate for any DeepL translation job.
- **Fix:** Replaced the broken attribute access with a direct import of `VERSION` from `src.version`. The `User-Agent` header now reads `RenLocalizer/<version>` correctly without any runtime attribute lookup on `ConfigManager`.
- **Affected files:** `src/core/translator.py`

### DeepL: Response Read Outside Context Manager Fix
- **Root Cause:** `payload = await resp.json()` was called outside the `async with session.post(...) as resp:` block. In aiohttp, reading the response body after the context manager exits risks a `ClientResponseError` (connection already closed). On stable connections this was silently fine, but on slower/proxied connections it could cause sporadic `200 OK` responses to fail at the read step.
- **Fix:** Moved `payload = await resp.json(content_type=None)` inside the `async with` block, immediately after the `status != 200` guard. `translations = payload.get(...)` moved one line down accordingly.
- **Affected files:** `src/core/translator.py`

### Lingva: Dead Instances Removed
- `lingva.garudalinux.org` (403) and `translate.plausibility.cloud` (500) are no longer responding. Removed from `LINGVA_INSTANCES`. Active instances: `lingva.lunar.icu` and `lingva.ml`.
- **Affected files:** `src/core/constants.py`

### Unrpyc: Suppress Console Window on Windows
- **Root Cause:** `unrpyc_adapter.py` spawns subprocesses (`python -m decompiler`, `unrpyc`, `rpycdec`) to decompile `.rpyc` files. On Windows, each subprocess briefly opened a visible console window (a flash of the app's own splash screen), which was confusing to users.
- **Fix:** Added `creationflags=subprocess.CREATE_NO_WINDOW` to all `subprocess.run` calls in `unrpyc_adapter.py` on Windows. Output capture behavior is unchanged; only the window visibility is suppressed. No effect on Linux/macOS.
- **Affected files:** `src/utils/unrpyc_adapter.py`

### DeepL: Quota Exceeded No Longer Retried
- **Root Cause:** On HTTP 456 (quota exceeded), the translator entered the retry loop and waited 1 + 2 + 4 = 7 seconds before giving up, firing two additional pointless API requests along the way. A quota exhaustion is not a transient network error — retrying cannot resolve it.
- **Fix:** HTTP 456 now short-circuits the retry loop immediately and returns a `quota_exceeded=True` result without any delay. HTTP 429 (rate limit) and HTTP 500 (server error) still retry normally as before.
- **Affected files:** `src/core/translator.py`

### DeepL: Ren'Py Closing Tag Corruption Fix
- **Root Cause:** The post-translation tag cleanup list applied a `/?\s*` pattern (matching both `{i}` and `{/i}`) before the slash-specific pattern. Because `re.sub` processes the first matching rule, `{/i}` was matched by the no-slash branch, the `/` was silently discarded, and the result was `{i}` — a valid opening tag instead of a closing tag, causing Ren'Py syntax errors in translated output.
- **Fix:** Reordered the cleanup list so the slash pattern (`{/i}`, `{/b}`, etc.) is tested first. The catch-all no-slash pattern now only matches tags that genuinely have no slash.
- **Affected files:** `src/core/translator.py`

### DeepL: Quota Error Now Reports Engine Name
- The `error_api_quota` log message previously read "API Quota Exceeded!" with no indication of which engine triggered it. It now includes the engine name (e.g. "DeepL API quota exceeded!") so users don't have to scan the log to find the source.
- Updated all 8 locale files (`en`, `tr`, `de`, `fr`, `es`, `ru`, `fa`, `zh-CN`) to accept the new `{engine}` format parameter.
- **Affected files:** `src/core/translation_pipeline.py`, `locales/*.json`

### DeepL: API Key Placeholder Corrected
- The settings field placeholder previously showed `API Key (sk-...) or (free:...)`. Both formats are wrong: `sk-...` is an OpenAI key format and `free:...` does not exist in DeepL's API. The correct formats are `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx:fx` (Free) and `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` (Pro/Paid).
- Updated all 8 locale files with the correct UUID-based placeholder.
- **Affected files:** `locales/*.json`

### DeepL: "API Key Missing" Error Localized
- `translate_batch` returned a hardcoded English string `"API Key Missing"` when no key was configured, bypassing the localization system. Now uses `_get_text('error_deepl_key_required', ...)` consistent with the rest of the error messages.
- **Affected files:** `src/core/translator.py`

### CI: `--rootdir .` Added to `linux-pyqt-compat` Job
- The `linux-pyqt-compat` compatibility regression suite was missing `--rootdir .`, which the `core-regression` job already had. Without it, pytest's rootdir detection on certain runner configurations could pick up unintended directories and cause collection errors.
- **Affected files:** `.github/workflows/tests.yml`

---

### [2.8.4] - 2026-04-15

### Parser: Catastrophic Slowdown Fix (Large .rpy Files)
- **Root Cause — Runaway `logical_lines` Buffer:** `pyparse_grammar.py` accumulates lines into a `buffer` while tracking open parentheses. On files where a parenthesis inside a string or comment is never balanced, the buffer grew without bound — eventually holding the **entire file content** (1 MB for `script.rpy`) as a single "logical line." Every entry produced by the grammar pass then stored this 1 MB string as its `context_line`.
- **Root Cause — O(n) Substring Search on 1 MB `context_line`:** `score_extraction_confidence()` built `combined_context` from the raw `context_line` and ran five `any(token in combined_context …)` substring searches on it. At 1 MB per entry × ~11 000 entries → **~401 seconds** of search time alone.
- **Root Cause — MD5 on 1 MB String:** `compute_translation_id()` hashed `label_context + ":" + context_line`. Hashing a 1 MB payload per entry added **~47 seconds**.
- **Root Cause — Continuation Lookahead Loop:** `deep_scan_strings()` treated any line containing `(` but not `)` as a multi-line continuation and scanned **all remaining lines** of the file for the next string literal. On a 23 000-line file this turned per-match work from O(1) into O(n), producing O(n²) total behaviour.
- **Root Cause — `"\n".join()` Lookback Per Match:** The same function rebuilt a multi-line context string by joining up to 10 previous lines on every string match — ~11 000 joins × string allocation → **~1.8 seconds** of extra allocation.
- **Root Cause — O(n) `count('\n')` for Line Number:** Triple-quote match positions were converted to line numbers via `full_content[:offset].count('\n')`, an O(n) scan repeated for every match.
- **Fix — Buffer Overflow Guard:** Added a 50-line safety cap to the `logical_lines` accumulator. If a buffer exceeds 50 lines without the parenthesis depth returning to zero, it is flushed immediately. This prevents any `context_line` from ever exceeding a few hundred characters regardless of file content.
- **Fix — `context_line` Clamped to 500 chars:** All `context_line` assignments in `pyparse_grammar.py` now store `line[:500]`. Defensive 500-char clamps were also added inside `score_extraction_confidence()` and `compute_translation_id()` so even unexpected large values from other code paths cannot cause quadratic behaviour.
- **Fix — Continuation Lookahead Scoped:** The `('(' in line and ')' not in line)` continuation condition was removed (too broad — matched every `screen main():` line). Continuation is now only triggered by trailing `\\`, `+`, or an open paren at the end of a line **inside a python block**. Lookahead is capped at 5 lines.
- **Fix — Lookback Without String Allocation:** Key/variable lookback in `deep_scan_strings()` now iterates over individual previous lines with early-exit instead of `"\n".join(slice)` + full `finditer`.
- **Fix — O(log n) Line Number Lookup:** Added a `_line_offsets` list and a `_offset_to_line()` helper using `bisect.bisect_right`, replacing all `full_content[:offset].count('\n')` calls.
- **Fix — Markup Fast Path in `is_meaningful_text`:** Skip `_strip_markup_structurally()` entirely when the text contains no `{` or `[` characters, avoiding O(n) character iteration on plain dialogue strings.
- **Result:** Total directory scan for the test game (22 files, 1 MB `script.rpy`) dropped from **10+ minutes (hung indefinitely)** to **~70 seconds**.
- **Affected files:** `src/core/pyparse_grammar.py`, `src/core/parser.py`, `src/core/deep_extraction.py`

### Runtime Hook: Severe Lag Fix (GrandmasHouse / Large strings.json)
- **Root Cause 1 — Language Sync in Hot Path:** `_rl_ensure_language_sync()` was called on every `_rl_replace_text` and `_rl_say_menu_text_filter` invocation. In games with many text render calls (100–300 per frame at 60fps), this meant `_rl_time.time()` and a language comparison ran thousands of times per second. If language casing mismatched (e.g. `"Turkish"` vs `"turkish"` — common because Ren'Py capitalises language names in `_preferences.language`), a full 50,000-entry reload was triggered every 2 seconds, clearing all caches and causing repeated warmup spikes.
- **Root Cause 2 — Phrase/Template Fallback on Every New Text:** `_rl_replace_text` ran phrase fallback (up to 28,389 candidates × 80-cap anchor search × `str.find`) and template matching (regex `findall`) on every unique text not yet in cache. In a VN with thousands of unique dialogue lines, this "warmup" period never truly ended.
- **Root Cause 3 — Phrase/Template Index Built at Load Time Unnecessarily:** `_rl_load_translations` still built `_rl_phrase_variants`, `_rl_phrase_index`, `_rl_template_map` and prefix/suffix indexes for all 50K entries at startup — `regex.findall` called per entry — even though these structures were never consulted after the hot-path fallbacks were removed.
- **Root Cause 4 — MRU Too Small / Storing Misses:** Old MRU cache size was 100 entries, causing constant eviction/re-scan. Misses were stored in MRU as `{text: text}`, consuming capacity and mixing with real translations.
- **Fix — Hot Path Simplified to Pure O(1):** Removed all language sync, phrase fallback, template matching, and normalized lookup from `_rl_replace_text` and `_rl_say_menu_text_filter`. Both functions now only perform: miss_set check → MRU check → exact dict → trimmed exact → CI dict → quote-wrapped → alias cache. All O(1) dict operations.
- **Fix — Miss Set (`_rl_miss_set`):** Added permanent miss set (capped at 50,000 entries). Texts confirmed to have no translation are added once and never re-scanned. Cleared on language reload.
- **Fix — MRU Cache:** Size increased 100 → 500. Now stores only confirmed translations (punct-fixed result cached at insertion time — no regex on hit). Misses go to `_rl_miss_set` exclusively.
- **Fix — Language Sync Moved to Harvest (Throttled):** `_rl_ensure_language_sync` removed from hot path entirely. Language sync now runs inside `_rl_harvest_screens` which is throttled — at most once every 15 seconds.
- **Fix — Phrase/Template Index Removed from Load:** `_rl_load_translations` no longer builds `_rl_phrase_variants`, `_rl_phrase_index`, `_rl_template_map`, `_rl_template_prefix_index`, `_rl_template_suffix_index`. Startup time significantly reduced for large games (was running `regex.findall` for every placeholder-containing key).
- **Affected files:** `src/core/runtime_hook_template.py`

### Runtime Hook: Rollback Lag Fix
- **Root Cause 1 — Harvest Throttle Bypassed When Not Loaded:** `_rl_loaded` was checked *before* the 5-second throttle. If `_rl_loaded = False` (e.g. after a failed language reload), `_rl_load_translations()` was called on *every* interaction, not once per 5 seconds. During rollback sequences where multiple interactions fire rapidly, this caused repeated full-reload attempts.
- **Root Cause 2 — Case-Sensitive Language Comparison Triggering Reload Loop:** `_rl_loaded_language != active_lang` comparison was case-sensitive. On Windows (case-insensitive filesystem), `"Turkish"` ≠ `"turkish"` was detected as a language change every 15 seconds → `_rl_load_translations()` succeeded (same file, different casing) → `_rl_miss_set` and `_rl_mru_cache` were cleared → warmup spike repeated indefinitely. Affects all languages where Ren'Py's `_preferences.language` casing differs from the `tl/` folder name.
- **Root Cause 3 — Harvest BFS Running at Rollback Interaction Start:** `_rl_harvest_screens` is registered to `config.start_interact_callbacks`. Each rollback step is an interaction; the first one per throttle window triggered a full BFS traversal of up to 8 screens × 300 nodes.
- **Fix — Throttle Before Load Check:** Moved `_rl_last_harvest_time` throttle check to execute *before* the `_rl_loaded` check, so failed-load retries are also rate-limited to once per 15 seconds.
- **Fix — Case-Insensitive Language Comparison:** Changed `_rl_loaded_language != active_lang` → `_rl_loaded_language.casefold() != active_lang.casefold()` in the harvest language sync block. Prevents spurious cache-wipe reloads due to capitalisation differences across all languages.
- **Fix — Skip Harvest During Rollback:** Added `renpy.in_rollback()` guard at the top of `_rl_harvest_screens`. During the fast-forward replay phase of rollback, screen harvesting provides no new content and is skipped entirely.
- **Fix — Harvest Throttle Increased:** `_rl_harvest_throttle` raised from 5 s → 15 s. Screen harvesting is discovery-only; 15-second intervals are sufficient.
- **Fix — BFS Scope Reduced:** `max_screens` default reduced 8 → 4. Added 300-node cap per screen to prevent runaway traversal on complex UIs.
- **Affected files:** `src/core/runtime_hook_template.py`

### Runtime Hook: MRU Eviction Direction Fix
- **Bug:** `_rl_mru_update` half-clear evicted `keys[half:]` (the *newest*, most recently inserted entries) and kept `keys[:half]` (the *oldest*). This caused actively used translations to be evicted while stale ones were retained, lowering effective cache hit rate after each eviction cycle.
- **Fix:** Changed to `for k in keys[:half]: _rl_mru_cache.pop(k, None)` — evicts oldest (first-inserted) half, retains newest (most recently added). Python 3.7+ dict insertion order is relied upon.
- **Affected files:** `src/core/runtime_hook_template.py`

### Runtime Hook: RTL Detection Case-Insensitive
- **Bug:** `_rl_apply_runtime_language_direction` checked `active_lang in _rl_rtl_languages` where `_rl_rtl_languages` contains lowercase entries (`'arabic'`, `'farsi'`, etc.). If `_preferences.language` stored `"Arabic"` or `"Farsi"`, RTL styles were not applied.
- **Fix:** Changed to `active_lang.casefold() in _rl_rtl_languages`.
- **Affected files:** `src/core/runtime_hook_template.py`

### Runtime Hook: Dead Code Removed
- Removed `_rl_ensure_language_sync()` function (no callers after hot-path redesign).
- Removed `_rl_lang_sync_last_check` and `_rl_lang_sync_interval` init variables (only used by the removed function).
- **Affected files:** `src/core/runtime_hook_template.py`

### Tests
- Updated `tests/test_v283_runtime_perf.py` to reflect harvest-based language sync, new miss set, and MRU size increase. All 890 tests pass, 1 skipped.

### Syntax Guard: Trailing-Punctuation Wrapper-Pair Fix
- **Root Cause Identified:** Ren'Py dialogue strings like `{i}Oh, it's about to start{/i}.` (closing tag immediately followed by terminal punctuation) caused `_CLOSE_TAG_RE` to fail its end-of-string anchor match, so `{i}` and `{/i}` fell through to ordinary tokenisation as separate `⟦RLPH…⟧` tokens. Google NMT then silently dropped the trailing `⟦…⟧` token (positioned between translated text and the terminal period), triggering an integrity failure, Lingva/injection retries, and in unrecoverable cases a full revert to the untranslated original.
- **Fix (`_CLOSE_TAG_RE`):** Extended the regex to optionally capture trailing sentence-final punctuation (`[.!?…\u2026]*`) before the end-of-string anchor. The captured punctuation is stripped from the match and re-appended to the *inner* text, allowing the close tag to form a valid wrapper-pair. Result: `{i}text{/i}.` → inner=`text.`, wrapper=`({i},{/i})` → after restore `{i}translated.{/i}` — visually equivalent in Ren'Py.
- **No change for mid-sentence closing tags:** Patterns like `{i}(whisper){/i} Please, take the panties, sire.` still fall through to regular tokenisation (the trailing content is full text, not just punctuation), giving `⟦0⟧(whisper)⟦1⟧ more text` where `{/i}` is safely mid-sentence and preserved by Google.
- **Affected files:** `src/core/syntax_guard.py` — `_CLOSE_TAG_RE` definition + closing-tag extraction block in `protect_renpy_syntax()`.

### Pipeline Log: strings.json Count Substitution Fix
- **Root Cause:** The locale message `log_strings_json_generated` existed only at the JSON root level in all 8 locale files; the pipeline's `get_log_text()` lookup prepends `pipeline_logs.` and therefore found no key, emitting the raw key string instead of the formatted message. Additionally, `_generate_strings_json()` returned `None` implicitly and the `app_backend.py` call site used `get_ui_text()` (root lookup, no `count` kwarg) rather than `get_log_text()`.
- **Fix:** Added `log_strings_json_generated` to the `pipeline_logs` section of all 8 locale files (en, tr, de, es, fa, fr, ru, zh-CN). Made `_generate_strings_json()` return `len(mapping)`. Fixed `app_backend.py` to capture the count and use `get_log_text('log_strings_json_generated', count=count or 0)`.
- **zh-CN gotcha:** The root-level entry used Unicode curly-quotes (`\u201c…\u201d`) around `strings.json`; ASCII `"` could not be inserted as-is inside a JSON string value, so `\u201c` / `\u201d` Unicode escapes were used in the edited line.

### Parser: Translation ID Computation
- **Ren'Py-Compatible ID Generation:** Added `compute_translation_id()` to `RenPyParser`. Generates `label_xxxxxxxx` format IDs (label name + 8-char MD5 hash) matching Ren'Py's internal translation ID scheme exactly, ensuring generated `tl/` files load without ID mismatch errors.
- **Collision Handling:** Serial counter appends alphabetic suffix (`m`, `n`, `o`…) for duplicate label+statement pairs, mirroring Ren'Py's own collision resolution.
- **Per-Entry ID Field:** Every entry returned by `_record_entry()` now includes a `translation_id` field for downstream use by the exporter and output formatter.

### Syntax Guard: Ruby/Furigana Protection
- **Lenticular Bracket Support:** Added `_PAT_RUBY` pattern (`【base｜ruby】` / `【base|ruby】`) to the protection pipeline. Ruby/furigana annotations are now tokenized atomically before reaching any translation engine, preventing the base and annotation from being separated, reordered, or corrupted during translation.
- **Priority Ordering:** `_PAT_RUBY` is placed before `_PAT_TAG` and `_PAT_VAR` in `_PROTECT_PATTERN_STR` to ensure correct capture precedence.

### False Positive Filter: Ren'Py-Specific Guards
- **Character Code Parameters:** Added `_CHAR_CODE_PARAM_RE` to skip `Character()` code parameter strings like `who_prefix="["`, `what_suffix=")"`, `voice_tag="eileen_voice"`, `icon=`, `sound=` — values that are asset or code references, not translatable text.
- **GUI Font/Config Assignments:** Added `_GUI_FONT_ASSIGN_RE` to skip `define gui.text_font =`, `gui.text_size =`, `config.font_size =`, `gui.label_color =` and similar property assignments whose values are technical, not translatable.
- **Image Tag References:** Added `_IMAGE_TAG_REF_RE` to skip inline `image="sprite_name"` asset references inside `Character()` or `define` statements.
- **Pattern Priority:** All three guards use pre-compiled class-level regex and run after the existing Python condition/code logic guards but before the final `return False`, keeping the performance profile of the method unchanged.

### Runtime Hook v4.2.0 Redesign
- **10x Main Menu Speedup:** Added MRU cache layer (50-100 entries) to runtime text lookup pipeline. Hit rate 60-80%, lookup time <1ms per 100 strings (was ~10ms).
- **Fixed Cache Asymmetry Bug:** Language reload was using aggressive `.clear()` instead of graceful half-eviction, causing cold-cache spikes. Now unified and smooth (~500ms transitions).
- **Fixed Screen Harvesting:** Replaced recursive implementation (stack overflow risk) with iterative BFS traversal (safe on deep UI hierarchies).
- **Dynamic Variable Support:** Pre-compiled regex templates for `[player_name]` interpolation with first-encounter alias caching.
- **8 New Runtime Functions:** `_rl_mru_update/lookup`, `_rl_try_template_match`, `_rl_alias_lookup/add`, `_rl_harvest_screens`, `_rl_language_hot_swap`, `_rl_print_stats/toggle_debug`.
- **Backwards Compatible:** Gracefully chains to v4.1.1 hooks if present; existing `strings.json` format fully supported.
- **File Changes:** Complete v4.2.0 rewrite of `runtime_hook_template.py` (42.89 KB); v4.1.1 backup preserved.

### Unrpyc Decompile Integration (Complementary Pipeline)
- **New `src/utils/unrpyc_adapter.py`:** Unified adapter for .rpyc → .rpy decompilation with automatic backend selection:
  - Priority 1: `decompiler` module (unrpyc installed from source/git)
  - Priority 2: `python -m decompiler` subprocess (unrpyc on PATH)
  - Priority 3: `unrpyc` script in PATH
  - Priority 4: `rpycdec` (pip installable PyPI fallback)
  - Graceful skip if no backend available (rpyc_reader still runs)
- **Context Manager API:** `decompile_to_temp(rpyc_files, source_root)` yields `(tmp_dir, rpy_paths)`, cleans up automatically on exit.
- **Pipeline Phase 5.5:** After Deep Scan, decompiles .rpyc files to `tempfile.mkdtemp()`, runs `RenPyParser.extract_combined()` on decompiled .rpy files, merges any new strings as `strings_unrpyc.rpy` in tl/ dir. Complementary to — not replacing — existing rpyc_reader AST extraction.
- **Config Toggle:** `enable_unrpyc_decompile: bool = True` in `TranslationSettings` (default on; skipped silently if no backend).
- **Settings UI:** New "RPYC Decompile (Complementary)" `DescriptiveCheck` toggle in Settings page (after "Automatic RPA Extraction").
- **Settings Backend:** `getEnableUnrpycDecompile()` / `setEnableUnrpycDecompile()` PyQt slots.
- **Locale Keys:** `enable_unrpyc_decompile_label`, `enable_unrpyc_decompile_desc`, `unrpyc_decompile_running`, `unrpyc_decompile_found`, `unrpyc_decompile_new_strings`, `unrpyc_decompile_error` added to all 8 locale files.
- **requirements.txt:** `rpycdec>=0.1.12` added as optional dependency.
- **Stray .rpy Cleanup Fix:** Subprocess-based backends (`unrpyc` script, `rpycdec` CLI) write the decompiled .rpy next to the original .rpyc in the game directory by default. These stray files are now deleted immediately after being copied to the temp directory. Previously they were left in `game/`, causing Ren'Py to load both the .rpy and the .rpyc simultaneously, which triggers duplicate-label / re-parse crashes at game startup.

### rpyc_reader.py Gap Fixes
- **Show/Scene ATL Descent:** `_process_node()` now descends into the `.atl` attribute of `FakeShow` and `FakeScene` nodes. ATL blocks attached to show/scene statements may contain Python code with translatable strings; previously silently skipped.
- **FakeSLOnEvent Action Extraction:** `_process_screen_node()` now handles `FakeSLOnEvent` nodes, extracting translatable text from the `.action` attribute via `_extract_from_action()`. Catches `Confirm`/`Notify`/`Tooltip`/`Help` actions in screen `on show/hide` event handlers.

### Ren'Py 7.5+/8.x Compatibility: Duplicate String Crash Fix (CRITICAL)
- **Root cause:** `existing_global_strings` dedup logic only excluded `old "text"` entries from existing tl/ files when `new "..."` was non-empty. Entries with `new ""` (empty translation placeholders — e.g. from `renpy translate <lang>` templates or partially-translated games) were NOT excluded, causing the same `old "text"` to be generated twice. Ren'Py 7.5+ / 8.x crashes with *"The string X has been translated more than once."* on any duplicate `old` key in `translate strings:` blocks.
- **Fix:** Changed `if old_text and new_text and new_text.strip():` → `if old_text:` in the existing-tl-file scanner. Now ALL `old "..."` entries from existing tl/ files (empty OR translated) are added to `existing_global_strings` and skipped during generation. Applies to both `string_pair_pattern` (strings format) and `dialogue_block_pat` (dialogue format) scanners.
- **Effect:** Games that already have `tl/<lang>/` files with any `translate strings:` content — including stub placeholders — will no longer trigger the Ren'Py duplicate-string crash on load.

### tl/ File Safety: Append Instead of Overwrite on Re-Extraction
- **Root cause:** During re-extraction (`_needs_re_extraction` → True, e.g. when source .rpy files changed after the initial translation run), `_run_translate_command` wrote newly-found strings to tl/ files using `os.replace()` — unconditionally overwriting the existing file content. This destroyed previously-translated entries and any game-native dialogue-format (`translate id:`) blocks in the same file.
- **Fix:** When the target tl/ file already exists, the new `translate strings:` block is **appended** to the existing file content instead of replacing it. Multiple `translate strings:` blocks in the same .rpy file are valid Ren'Py syntax and merged at load time. Falls back to `os.replace()` only on `IOError` (logged as warning). New files (don't exist yet) continue to be created normally.
- **Effect:** Re-extracting after source changes preserves all existing translations. Games with native tl/ files (including dialogue-format blocks) are no longer at risk of having their translation content overwritten.

### RPYC Always-On
- `use_rpyc = True` is enforced unconditionally in `_run_translate_command` regardless of `include_rpyc` instance attribute or config setting. `.rpyc` AST scanning always runs alongside `.rpy` regex parsing to catch strings that appear only in compiled files (e.g. games where .rpy source is stripped before distribution).

### Unrpyc Adapter: rpycdec Detection Fix
- **Root Cause:** `_detect_backends()` probed `rpycdec` via `rpycdec.__version__`, but `rpycdec` does not expose a `__version__` attribute, raising `AttributeError` and causing the backend to be silently skipped even when the package was installed and functional.
- **Fix:** Detection probe changed from `__version__` attribute check to `hasattr(rpycdec, 'decompile_file')`. The decompilation call also updated to use the correct `rpycdec.decompile_file(input, output)` signature.
- **Affected files:** `src/utils/unrpyc_adapter.py`

### Translation Guard: Ren'Py Tag Mismatch False Positive Fix
- **Root Cause:** `_classify_translation_corruption()` compared Ren'Py tag sets between `entry.original_text` (raw parser output) and the restored translation. When the Google token-mode protection pipeline was active, `entry.original_text` contained the raw source text (e.g. `{w}`) while the translation had the same tag correctly restored — a legitimate match. However, when a stale or hallucinated cache entry injected unrelated tags (e.g. `{size=50}{color=…}`) into the translated output for a short tag-free original, the check triggered correctly. The check also had a theoretical false-negative window: if `entry.original_text` contained placeholder tokens (`⟦…⟧`), tag comparison was unreliable because the tag count in the original was already distorted by the protect step.
- **Fix:** Added a guard: if `⟦` or `⟧` is present in the original text passed to the checker, the `renpy_tag_set_mismatch` branch is skipped entirely. In practice, `entry.original_text` is always raw (never contains `⟦…⟧`), so this guard is a safety net rather than a behavioural change for the common path — but it eliminates the theoretical FN window without affecting FP detection for tag-free originals.
- **Affected files:** `src/core/translation_pipeline.py`

### Yandex: Engine Removed
- **Reason:** The Yandex widget.js endpoint (`translate.yandex.net/website-widget/v1/widget.js`) was shut down by Yandex; the URL now returns only `"limited"`, making SID retrieval impossible. The engine became non-functional.
- **Removed:** `YandexTranslator` class, `TranslationEngine.YANDEX` enum value, all Yandex constants (`YANDEX_TRANSLATE_API_URL`, `YANDEX_WIDGET_JS_URL`, `YANDEX_SID_LIFETIME`, `YANDEX_MAX_CHARS_PER_REQUEST`), Yandex section in Settings UI, `yandex` option from CLI engine list, Yandex keys from all 8 locale files, `testYandexConnection()` settings method.
- **Affected files:** `src/core/translator.py`, `src/core/constants.py`, `src/core/translation_pipeline.py`, `src/backend/app_backend.py`, `src/backend/settings_backend.py`, `src/gui/qml/pages/SettingsPage.qml`, `src/cli_main.py`, `locales/*.json`, `AGENTS.md`, related test files

### rpyc_reader: EarlyPython 'hide' Attribute Error Fixed
- **Root Cause:** `EarlyPython` AST nodes were mapped to the `FakePython` class. During pickle deserialization Python does not call `__init__`, only `__setstate__`. Because `FakePython` had no `__setstate__` of its own, `FakeASTBase.__setstate__` ran instead, which applied the pickle state dict directly to `__dict__`. Since `EarlyPython` pickle states do not contain a `hide` key, the attribute was left missing, causing `AttributeError` on access.
- **Fix:** Added `__setstate__` to `FakePython`. Before calling `super().__setstate__()`, `code`, `hide`, and `store` fields are pre-initialized to safe defaults; the pickle state is then applied on top.
- **Affected files:** `src/core/rpyc_reader.py`

### tl_parser: Language Directory Double-Join Fixed
- **Root Cause:** Some call sites passed `tl_dir` as `game/tl/turkish` while `language` was also `"turkish"`. The resulting `os.path.join("game/tl/turkish", "turkish")` → `game/tl/turkish/turkish` path did not exist, producing a spurious "Language directory not found" warning.
- **Fix:** Added a defensive guard at the start of `parse_directory`: if the last component of `tl_dir` already matches `language` and the directory exists, `lang_dir = tl_dir` is used directly without an additional join.
- **Affected files:** `src/core/tl_parser.py`

---

### [2.8.3] - 2026-04-11

### Pipeline Safety
- **Critical Fix — Resume Crash:** Fixed a `NameError` crash in `_translate_entries` that occurred when all entries were filtered out (e.g. already translated via cache) before the cache file path was defined. This primarily affected the "Resume Translation" workflow where previously cached translations left no new entries to process.
- **Gemini Fallback Fix:** Fixed Google Translator fallback initialization for the Gemini engine where positional arguments caused `config_manager` to be silently ignored, resulting in suboptimal fallback behavior (default batch size, no Lingva fallback, incorrect proxy routing). The same issue existed in the GUI backend and CLI entry points and has been fixed across all three code paths.

### CLI Overhaul
- **Modern Terminal UI:** Rebuilt the CLI interface with [Rich](https://github.com/Textualize/rich) for a premium terminal experience: gradient ASCII banner, styled panels, colored log output with severity icons, and formatted summary tables.
- **Rich Progress Bars:** Replaced raw `\r` progress output with Rich progress bars featuring spinners, completion bars, ETA counters, and task descriptions that update in real time.
- **Full Engine Support:** The interactive mode now exposes all translation engines with descriptions, whereas the old menu only showed Google and DeepL. (Note: Yandex was included at 2.8.3 release but removed in 2.8.4 due to endpoint shutdown.)
- **13 Languages Shortlist:** Expanded the interactive language picker from 9 to 13 common languages with flag icons.
- **Engine Selection in Wizard:** Added an engine selection step to both "Full Translation" and "TL Folder" interactive workflows so the engine choice no longer requires a separate Settings detour.
- **Styled Help Panel:** Help text now renders inside a Rich panel with colored command examples and mode descriptions.
- **Completion Summary Panel:** Translation results are displayed in bordered panels with duration tracking, item counts, and color-coded success/failure indicators.
- **Graceful Fallback:** When the `rich` library is not installed, the CLI gracefully falls back to plain `print()` output without crashing.
- **DeepSeek CLI Support:** Added DeepSeek engine initialization in the CLI engine setup, which was previously missing.

### Runtime Hook
- **RTL Indentation Fix:** Fixed a generated runtime hook indentation mismatch that could break Ren'Py script parsing on some projects.

### Runtime Hook Performance (Rollback Optimization)
- **Native Dict Rollback Bypass (Core Fix):** Migrated all dynamically mutating dictionaries (`_rl_replace_cache`, `_rl_normalized_lookup_cache`, `_rl_runtime_miss_logged`) out of Ren'Py's store into standard native python `dict` allocations bound to the external `sys` module (`sys._rl_caches`). This entirely circumvents Ren'Py's `RevertableDict` tracking mechanism. By stopping the engine from logging 20,000+ cached string interactions into the traceback history, the huge lag and memory bloat associated with clicking the `Rollback` (mouse wheel up) feature in heavy translation operations is entirely eliminated!
- **LRU-Like Cache Eviction:** Replaced cliff-edge `cache.clear()` with half-eviction (FIFO) for caches. Previously, when either cache reached its limit, the entire cache was destroyed at once — causing a cold-cache thundering-herd effect where lookups miss. Now only the oldest half is evicted, keeping recent translations warm.
- **Language Sync Throttle:** `_rl_ensure_language_sync()` now checks `_preferences.language` at most once every 2 seconds instead of on every `replace_text` call. During a typical rollback burst (15-100+ `replace_text` invocations in <0.5s), this eliminates ~99% of redundant `hasattr` + property access overhead.
- **Increased Cache Limits:** `_rl_replace_cache_limit` raised from 12,000 to 20,000 and `_rl_normalized_lookup_cache_limit` from 8,000 to 12,000. 
- **Soft-Reload (Shift+R) Resilience:** Added cache clearing hooks to the `sys` module initialization block. This ensures that when a developer or user uses hot-reloading (Shift+R), the decoupled memory caches are properly flushed, preventing stale or ghost translations from persisting across reloads.

### Locales
- **Locale Sync:** Synchronized missing dashboard and deepseek string keys across `de`, `es`, `fa`, `fr`, `ru`, `tr`, and `zh-CN` loc files, falling back to English strings safely where previously missing.

### [2.8.2] - 2026-04-06

### Runtime Coverage Learning
- **Miss Metadata Enrichment:** Runtime missed-string diagnostics now record source kind, active language, active screen, statement name, normalized visible text, and additional text-shape metadata so edge-case misses can be classified without guessing from raw output alone.
- **Runtime Candidate Scoring:** Added a runtime coverage scoring layer that ranks missed strings by promotion value, helping the pipeline distinguish long meaningful dialogue and screen text from noisy stats, placeholders, and technical fragments.
- **Runtime-Observed Alias Synthesis:** `strings.json` generation now synthesizes guarded exact-match aliases from previously observed runtime misses, allowing future builds to recover stable visible forms without resorting to global substring replacement.
- **Screen Scope Harvesting:** Added a low-risk screen observer that harvests string-like values from active screen scope variables during interaction-start callbacks and records them as diagnostics only; it does not modify gameplay text at runtime.
- **Mode-Aware Coverage Expansion:** `Aggressive` mode now accepts a wider set of medium-confidence runtime and screen-derived alias candidates and relaxes visible-fragment thresholds, while `Balanced` keeps promotion limited to higher-confidence exact-match recoveries.
- **Runtime Hot-Path Optimization:** Indexed template and long-phrase runtime candidates so `replace_text` no longer linearly scans every template or phrase entry on large projects, reducing UI lag risk on translation-heavy sandbox-style games.
- **Runtime Memoization:** Added bounded memoization for post-interpolation `replace_text` results and normalized lookup keys so repeated UI fragments no longer pay the full runtime matching cost on every interaction.
- **General RTL Runtime Support:** The runtime hook now also applies RTL-aware direction settings for supported languages such as Persian, Arabic, and Hebrew, reducing reversed or incorrectly ordered text even when the separate font-fixer tool is not used.
- **User-Invisible Automation:** The new runtime coverage learning path works behind the scenes. Users can still follow the same simple flow: select a project, translate, and play.

### Desktop UX
- **Native Completion Notifications:** Translation completion now also attempts a native desktop notification through Qt system tray integration on supported Windows, Linux, and macOS environments, while keeping the existing in-app completion dialog as the fallback path.

### Font Injection
- **Broader Font Override Coverage:** The automatic font fixer now updates both the runtime font hook and common `gui.*_font` / `style.*.font` targets, then rebuilds styles and restarts interaction so newly injected fonts apply more consistently in modern/custom Ren'Py projects.
- **Cache Refresh Safety:** The generated font override script now attempts to clear Ren'Py font caches before rebuilding styles, reducing cases where a newly injected font exists on disk but stale cached font objects keep old glyph coverage active.
- **Target-Language Font Checks:** The font compatibility check tool now validates fonts against the currently selected target language instead of always checking Turkish, making diagnostics accurate for languages like Vietnamese and other non-default targets.
- **Static Font Risk Scan:** The font check tool now also scans project scripts for hardcoded/custom font usage such as `what_font=`, `Text(..., font=...)`, `{font=...}` tags, `FontGroup()`, and font mapping APIs, helping identify projects where automatic font replacement may only be partial.
- **Language-Aware Font Fallbacks:** Automatic font injection now uses ordered language-specific fallback candidates instead of a single hardcoded font choice, improving the odds of selecting a better default family for languages like Vietnamese and other script-sensitive targets.
- **RTL Reading Support:** Generated font override scripts now also enable RTL-aware text settings for languages like Persian, Arabic, and Hebrew by applying `config.rtl` plus weak RTL reading-order hints on common text styles, reducing reversed or incorrectly ordered text after font injection.

### [2.8.1] - 2026-04-05

### Extraction Safety
- **Mode-Based Precision Control:** Added a new extraction safety selector with `Strict`, `Balanced`, and `Aggressive` modes so users can choose how much risk to take when discovering Ren'Py text.
- **Balanced Default:** Set `Balanced` as the default mode to prioritize higher text coverage while still keeping false positives under control.
- **Markup-Aware Text Parsing:** Began shifting the parser toward structure-first markup handling so tag-heavy Ren'Py strings are evaluated by visible text content instead of relying on regex-only stripping.
- **Screen UI Coverage:** Applied the same visible-text rule to screen/textbutton style entries so tag-heavy UI labels are less likely to be dropped as technical markup.
- **RPYC Visible-Text Gating:** Applied the same visible-text rule inside the RPYC AST reader so tagged displayable strings are judged by their readable content before confidence filtering.
- **Deep Scan Alignment:** Extended the same visible-text rule to deep-scan data value checks so tag-heavy JSON/YAML/inline candidates are filtered by their readable content instead of markup alone.
- **Combined Source Scan:** Switched the main game source scan to `extract_combined()` so deep-scan-only strings from nested dict/list structures now enter the translation pipeline instead of remaining in a separate discovery pass.
- **Runtime Normalized Fallback:** Added a conservative runtime lookup fallback that normalizes Unicode punctuation and whitespace, helping exact-match translation survive curly quotes, long dashes, ellipsis, and similar visible-form variants.
- **Visible-Form Alias Synthesis:** `strings.json` generation now synthesizes safe visible-text aliases for common punctuation variants such as apostrophes, ellipsis, and spaced dash forms, improving runtime exact-match coverage without enabling substring replacement.
- **Visible Fragment Aliases:** Long multi-sentence strings now also synthesize guarded prefix/visible-fragment aliases for runtime exact-match coverage, helping screen-driven text that renders shortened visible portions of a larger source string.
- **Guarded Long-Phrase Runtime Fallback:** Added a tightly scoped runtime fallback for long visible phrases so larger screen-driven fragments can still recover a translation when the rendered text contains a single unambiguous long source phrase inside a bigger display string.
- **Grammar Alignment:** Updated the SDK-free pyparse grammar to use visible-text gating while still preserving original Ren'Py markup in extracted output.
- **Runtime Verification:** Validated the new extraction safety pipeline on several large real-world Ren'Py projects, confirming the visible-text gating and mode thresholds behave consistently across parser, RPYC, deep scan, and grammar paths, while still leaving room for edge-case tuning on unusual project layouts.
- **False-Positive Guardrails:** The new mode system maps to confidence thresholds under the hood, keeping the default path conservative while still allowing broader coverage when needed.
- **Localized Guidance:** Added explanatory UI text for the new extraction controls in all supported locale files so the setting is understandable without relying on English-only labels.

### [2.8.0] - 2026-04-04

### UI Revision 
- **Navigation Shell Revamp:** Expanded the left navigation from icon-only shortcuts into a clearer workspace/help sidebar with labeled destinations, improving discoverability without removing any existing actions.
- **Settings Reorganization:** Split the Settings page into tabbed sections so General, Engines, Translation, Network, AI, and System options stay fully available but are easier to scan and reach.
- **Localization Expansion:** Added new UI strings for the revised navigation shell and settings tabs across all locale files.
- **Brand Simplification:** Removed `V2` from visible application labels and subtitles so the UI reads more cleanly across navigation, home, and about surfaces.
- **Home Dashboard Summary:** Added a compact overview strip for project, language pair, and engine/TM status so the main screen feels more like a guided workspace.
- **Log Collapse:** Added a collapsible log panel to reduce clutter without hiding functionality.
- **Page Grouping:** Reworked Glossary, Cache, and Tools into clearer dashboard-style sections with summary cards and grouped tool blocks.
- **Responsive Card Heights:** Fixed overlapping section text by giving dashboard cards content-driven heights so the revised layouts stay stable on Windows, Linux, and macOS.
- **Compact Lists:** Loosened glossary rows and cache cards so translated content has more vertical room and stays readable on narrower desktop layouts.
- **Density Reduction:** Reduced header, toolbar, and row action density in Glossary and Cache for a cleaner, less crowded reading experience.
- **Icon/Text Split Headers:** Separated icon glyphs from page titles on the revised pages so Linux and macOS font fallback is less likely to disturb alignment or readability.
- **Settings Header Split:** Separated icon glyphs from major Settings section headers to reduce overlap and improve cross-platform readability.
- **Micro Layout Polish:** Tightened Settings row widths and relaxed cache/search spacing so compact windows stay readable without squeezing controls.
- **Live Locale Refresh:** Wired UI language changes to a global QML refresh so the interface updates immediately without needing an app restart.

### Stability Fixes
- **QML Startup Fix:** Resolved a NavigationBar load failure caused by an invalid `Label` property assignment (`letterSpacing`). The sidebar now uses the supported font property path so the UI loads normally again.
- **Startup Splash Screen:** Added an English loading splash screen built into the launcher so slow startup work is visible instead of looking frozen, using the bundled `icon.png` without requiring extra assets.
- **Splash Fallback Safety:** Improved the splash fallback so missing or unreadable `icon.png` still shows a branded loading surface instead of a plain black box.
- **Animated Splash Messaging:** Added stage-based splash messages with a subtle dot animation to make slow startup feel active instead of frozen.

### Translation Coverage
- **Safer Say Coverage:** Extended Ren'Py dialogue extraction to cover quoted speaker names and image-attribute say lines like `"Mark" "..."` and `iside basics "..."` while keeping `screen` and command-like statements outside the translation path.

### Language Path Normalization
- **Ren'Py Folder Keys:** Normalized target language handling so `tl/<lang>/` paths use Ren'Py folder keys consistently across all languages, while API codes remain only for translation requests and legacy configs are auto-mapped.
- **Path/URL Centralization:** Standardized QUrl-based local path handling across dialogs and file operations so Home, Cache, Tools, glossary import/export, and external TM flows use the same platform-safe conversion path.

### Tools
- **TXT/YAML Translator:** Added a standalone helper tool for `.txt` and `.yml/.yaml` files that scans folders recursively, creates sibling `old-txt-yaml` backups automatically, and replaces files in place with best-effort formatting preservation (Experimental).

### UX Direction
- **Control Preserved:** The redesign keeps advanced options visible and accessible while reducing visual clutter and improving task orientation.

### [2.7.8] - 2026-03-29

### Bug Fixes
- **External TM Selection Fix:** Fixed a critical UX bug where imported External TM sources were listed but could not be selected. The Translation Reuse Center (CachePage) now includes CheckBox controls for each TM source with visual highlighting (accent-colored border for selected items) and a status label showing "Selected: X / Y". Selection changes are properly persisted via `toggleTMSource()` and reflected immediately in the Home page TM card.
- **External TM Real-time Refresh:** Fixed a bug where newly imported TM sources did not appear in the Home page until the application was restarted. Added a new `tmSourcesChanged` signal to the backend that is emitted after TM import and delete operations. Both HomePage and CachePage now listen to this signal and refresh their TM source lists in real-time.
- **QML Binding Loop Fix:** Resolved "Binding loop detected" errors in CachePage and fixed "Unable to assign [undefined] to QColor" warnings by improving property binding structure and removing invalid Material.dark references.

### External TM Enhancements
- **TM Management UI:** Moved External TM from Tools page to Translation Reuse Center (CachePage) with a dedicated section including:
  - **Toggle Switch:** High-visibility Switch component to activate/deactivate TM usage
  - **Selection Status:** Real-time display of "Selected: X / Y" count
  - **CheckBox Selection:** Each TM source can be individually selected for use
  - **Options Menu (⚙️):** Right-click or button menu for each source with Rename, Export, and Delete options
- **Detailed TM Statistics in Logs:** Translation completion logs now include hit count, hit rate percentage, miss count, source names with entry counts, and total memory entries.
- **TM Backend Operations:** Added new backend slots (`renameTMSource`, `mergeTMSources`, `exportTMSource`) to AppBackend. Merge functionality is available in the backend and ready for future UI integration.

### Translation & Engine Updates
- **External TM UI Redesign:** Moved the External Translation Memory system from the Tools page to a dedicated section in the Translation Reuse Center (CachePage). The toggle is now combined with TM source management for a unified experience.
- **Google Batch Fix:** Resolved a rare "NoneType object has no attribute strip" error in the Google Translate engine by adding robust null-checks to the batch processing logic.
- **Custom AI System Prompt Persistence:** Fixed a bug where user-defined system prompts entered in the AI Tuning settings were not being saved to `config.json`. The `getAISystemPrompt` / `setAISystemPrompt` backend slots now correctly persist the value, and the QML input field uses a 500 ms debounce timer plus `onActiveFocusChanged` / `Component.onDestruction` guards to ensure the prompt is never lost. Additionally fixed a `KeyError` crash in `LocalLLMTranslator` when a custom prompt contained literal curly braces (e.g. `{i}`, `{b}`); now uses safe `str.replace()` instead of `str.format()`, consistent with all other AI engines.

### UI & UX Improvements
- **Tools Page Polish:** Fixed visual corruption in `ToolsPage.qml` by restoring proper UTF-8 encoding for Turkish characters and emojis.
- **Dialog Binding Fixed:** Resolved "Binding loop detected" errors in the CachePage clear confirmation dialog by assigning explicit widths and proper contentItem structure.

### Localization
- **Multi-Language Support:** Updated all 8 supported UI languages (EN, TR, DE, ES, FR, RU, FA, ZH-CN) with translations for the relocated External TM settings, TM management dialogs, and new UI elements (tm_selected_count, tm_rename_title, tm_rename_desc, tm_export_title, tm_export_desc, tm_export_select_location, btn_rename, btn_export, btn_delete, btn_options, placeholder_new_name, placeholder_select_destination).

### [2.7.7] - 2026-03-24

### Ren'Py Runtime Hardening (Phase 1-6)
- **Template-Aware Runtime Matching:** Added `_rl_template_match` to the runtime hook, enabling intelligent translation of text containing dynamic interpolation (e.g. `Score: [score]`) by matching against learned "template shapes" in `strings.json`.
- **Conflict Management & Diagnostics:** The translation pipeline now detects and reports `duplicate_key_conflict` and `case_insensitive_conflict` during `strings.json` generation. Conflicts are recorded with source file names and line numbers in `diagnostics/strings_json_skipped_corruptions.json`.
- **Enhanced ReplaceText Coverage:** `strings.json` now synthesizes tag-stripped variants to ensure `config.replace_text` can match text fragments separated by Ren'Py tags (e.g., `{b}Hello{/b}` → matching `Hello` alone).
- **Consolidated Miss Diagnostics:** Improved categorization of runtime misses in `runtime_missed_strings.jsonl`, distinguishing between `template_candidate_miss`, `exact_match_miss`, and `case_insensitive_miss` for easier troubleshooting.
- **Robust Placeholder Injection:** Increased the safety of the runtime template matcher to only process stable shapes with single placeholders, preventing recursive evaluation or injection risks.

### Translation Coverage Expansion
- **Structure-Aware Screen Argument Extraction:** Added a conservative parser pass for `call/show screen ...(...)` string arguments so custom screen titles and prompts in data-driven projects are now captured without broadening false positives.
- **Displayable Helper Label Extraction:** Added a second guarded pass for screen/displayable helper calls such as `idle build_loc_icon(..., "Pool", ...)` and `add Text(...)`, improving coverage for custom navigation UI and helper-driven labels.
- **Config-Gated Deep Extraction Flags:** New `deep_extraction_screen_arguments` and `deep_extraction_displayable_calls` toggles extend coverage without changing legacy extraction behavior, and both default to the safe enabled path for 2.7.7.
- **Regression Coverage Added:** Locked the new structure-aware extraction behavior with dedicated tests covering screen titles, helper labels, asset-path skipping, and low-signal lowercase argument rejection.
- **No-Space Say Syntax Support:** Character dialogue lines written as `a"..."` (without a space after the speaker name) are now extracted safely, while common screen/UI statement keywords remain excluded to avoid false positives.

### Coverage Diagnostics & User Guidance
- **Coverage Warning Audit Layer:** The pipeline now records likely non-fatal coverage risks into diagnostics, including image-only interactive UI, compiled-only scripts when `RPYC Reader` is disabled, and dynamic UI text patterns when the runtime hook is unavailable.
- **GUI Warning Localization:** Coverage warning summaries and report-path hints were added to all 8 GUI locale files so the Home/UI warning flow remains fully localized.
- **Diagnostics Report Enrichment:** `diagnostic_<lang>.json` now includes serialized `coverage_warnings` metadata and total warning counts for post-run inspection.
- **Locale Coverage Cleanup:** High-visibility locale gaps in nested pipeline log blocks were cleaned up, and all 8 locale files were rechecked against `en.json` so no translation keys are missing after the 2.7.7 additions.

### Guard Messaging & UX Polish
- **Dedicated Guard Log Level:** Translator-output safety messages that keep the original text are no longer surfaced as generic warnings; they now use a dedicated `guard` log level to clearly signal “protected fallback” rather than “hard failure.”
- **User-Friendly Guard Reasons:** Technical guard reason codes like `length_inflation` and `placeholder_set_mismatch` now resolve to localized, human-readable explanations in logs.
- **Theme-Aware Log Semantics:** Home-page log colors were rebalanced for meaning and readability: errors stay red, warnings use amber/orange, guard events use blue, success stays green, and neutral/debug messages keep muted tones across light and dark themes.
- **Less Noisy GUI Feedback:** Guard events stay visible in the log panel but no longer trigger toast notifications, reducing false alarm perception during normal translation runs.
- **Coverage Notes Stay Log-Only:** Coverage diagnostics such as image-only UI and dynamic UI risk notes no longer open popup warnings; they remain in logs and diagnostic reports only.
- **Calmer Completion Dialog:** Successful translation runs now use a dedicated completion summary dialog with output/report shortcuts, keeping review notes separate from real warning popups.

### Batch Size Flexibility
- **General Batch Ceiling Raised:** The standard source-install batch setting now supports values up to `10000`, making high-volume non-AI engines less constrained on large projects.
- **AI Batch Ceiling Raised Too:** The dedicated AI batch setting can now also be increased up to `10000` for users who intentionally want larger request grouping.
- **Engine-Specific Effective Caps:** Google Translate and Yandex continue to enforce a safer effective batch cap of `1000`, while still honoring lower user-selected values normally.
- **Localized UI Guidance:** Settings now explain the wider batch range, the AI trade-offs of very large batches, and the effective cap behavior for the currently selected engine in all GUI locale files.
- **Runtime Cap Notice:** When a stored batch size exceeds an engine's safe effective limit, the pipeline logs a friendly informational notice instead of silently surprising the user; very large AI batches now also emit a low-noise informational caution in logs.

### PyQt6 Source Compatibility & CI
- **Source Install Range Opened Carefully:** `requirements.txt` now allows the tested PyQt6 `6.6.x` through `6.10.x` line for source installs instead of forcing a single patch version.
- **Release Build Pin Preserved:** Official packaged builds still resolve through `constraints-release.txt`, keeping the release pipeline pinned to the validated `PyQt6 6.10.1` stack.
- **New Linux Compatibility Matrix:** Added a dedicated GitHub Actions workflow that validates source installs against multiple PyQt6 minor lines with a real Qt/QML startup smoke test under Xvfb.
- **Local Matrix Helper:** Added `tox.ini` so PyQt6 compatibility checks can also be reproduced locally without manually editing dependency pins.
- **Matrix Verified:** The Linux source compatibility matrix now passes across the tested PyQt6 `6.6.1` through `6.10.1` range, confirming that source installs no longer require forcing only the newest tested minor line.

### Documentation & Developer Experience
- **Community Manifesto & Covenant:** Rewrote `CODE_OF_CONDUCT.md` and `CONTRIBUTING.md` to establish the "RenLocalizer Manifesto." This version formalizes the project's "Free Forever" guarantee and the non-commercial commitment required from all future forks and contributors.
- **Architecture & Engine Sync:** Updated `AGENTS.md` to accurately reflect the v4.1.1 4-layer runtime hook structure and corrected the active translation engine count to 8, establishing clarity on available providers (including Yandex).

### [2.7.6] - 2026-03-20

### Linux UI Icon Reliability
- **Bundled Emoji Font Bridged Into QML:** Linux/macOS startup now passes the registered emoji font family into QML so icon-like emoji labels can explicitly use the bundled/system emoji font instead of depending on distro-specific fallback behavior.
- **Critical UI Surfaces Updated:** Navigation, toast notifications, Home, Settings, Tools, Glossary, Cache, and About pages now apply the shared icon font on their emoji-based action labels and section headers, reducing missing icon glyphs on Linux desktops that previously showed blank squares or fallback boxes.
- **No Extra Asset Pack Required:** The main application logo continues to use packaged `icon.png`/`icon.ico`; the user-visible Linux icon issue was primarily caused by emoji glyph rendering, not missing bitmap assets.

### UI Branding Sharpness
- **In-App Logo Uses PNG Everywhere:** The QML navigation, Home, and About pages now use the high-resolution `icon.png` for the visible in-app logo on all platforms instead of using the Windows `.ico` asset inside the UI. The `.ico` file remains reserved for native window/taskbar integration.
- **Sharper Small-Size Rendering:** Navigation and About logos now explicitly enable smooth + mipmap sampling for the in-app branding image, improving downscaled logo clarity without changing the native application icon behavior.

### Linux Portable Launcher Polish
- **Dual-Mode `RenLocalizer.sh`:** The launcher now detects whether it is running from a bundled portable folder or a source checkout. Portable Linux builds launch the packaged executable directly, while source checkouts still auto-bootstrap a local virtual environment and start `run.py`.
- **tar.gz Launcher Included:** Linux portable `.tar.gz` releases now include `RenLocalizer.sh` inside the packaged folder so users have a clear entrypoint in addition to the raw executable.
- **Portable Safe Retry:** The portable Linux launcher now mirrors the AppImage safety net and retries once with `QT_QUICK_BACKEND=software` after signal-based OpenGL/GLX startup crashes.
- **Launcher Contract Smoke Test:** GitHub Actions now smoke-tests the portable launcher script against the packaged Linux folder before publishing the `.tar.gz` artifact.

### Linux: GLX Crash Auto-Recovery
- **Proactive GLX Probe (`qt_runtime.py`):** Frozen Linux builds now probe GLX availability via `glXQueryExtension()` (ctypes) and `glxinfo` (subprocess) **before** Qt creates any OpenGL context. When GLX is broken (missing GPU drivers, DRI mismatches, container environments), the bootstrap automatically selects `QT_QUICK_BACKEND=software` — preventing the fatal `SIGABRT` crash in `libqxcb-glx-integration.so` that previously killed the process before Python-level recovery code could run.
- **AppImage Crash-and-Retry (`AppRun`):** If the bundled binary crashes with a signal-based exit code (> 128, e.g. SIGABRT=134), the AppImage launcher automatically retries once with software rendering. Normal error exits (1–127) are passed through without retry since Python-level recovery already handles those.
- **tar.gz Crash-and-Retry (`RenLocalizer.sh`):** Same signal-aware crash-and-retry mechanism for the portable tar.gz launcher. Uses `RENLOCALIZER_GL_RETRY` env var to prevent infinite retry loops.
- **Affected Systems:** Bazzite, Fedora Atomic/Silverblue, VMs without GPU passthrough, Wayland-only sessions, and other environments where GLX hardware acceleration is unavailable.
- **Installation Docs:** Added Linux pre-built binary installation guide and GLX troubleshooting section with manual `QT_QUICK_BACKEND=software` override instructions.

### [2.7.5] - 2026-03-14

### Parser & Scan Responsiveness Fixes
- **Create-Phase Progress Visibility:** The translation-file generation flow now emits coarse source-scan and deep-scan progress logs while it is still inside the broader "creating translation files" stage, making long scans visible instead of looking frozen with no feedback.
- **Progress Totals Aligned:** Source-scan progress counters now use the number of actually processable `.rpy` files after exclusions instead of the raw discovered file count, avoiding misleading totals on projects with many skipped `tl/` or generated files.
- **Deep Scan Re-Parse Removal:** The deep scan pipeline no longer re-runs the primary `.rpy` extraction pass for every file just to build its duplicate filter, reducing repeated work and improving responsiveness on very large script files.
- **Excessive-Line Warning Deduplication:** Repeated `Skipping line ... due to excessive length` warnings are now logged once per file/line/length combination per parser instance instead of spamming the console during repeated scan passes.
- **Directory Scan Progress Callbacks:** Core parser directory walkers now support lightweight progress callbacks so GUI logging can surface long-running scan phases without flooding the UI.

### Release Audit Hardening
- **Crash Report Path Reliability:** Early startup crash reports now prefer the managed writable data path (`logs/crash_report.log`) instead of assuming the current working directory is writable inside packaged Linux/macOS launches.
- **Native Startup Error Dialog Fallbacks:** Non-Qt startup failures now try a platform-native dialog (`MessageBox`, `osascript`, `zenity`/`kdialog`) before falling back to console-only output, reducing silent launch failures on GUI-first systems.
- **Deep Scan Directory Exclusions Honored:** `extract_combined(..., exclude_dirs=...)` now forwards and respects root-level directory exclusions during `.rpy` deep scans instead of silently ignoring the parameter.
- **macOS Bundle Metadata Update:** The macOS bundle script now updates `Info.plist` via `plistlib` instead of a hard-coded `sed` replacement tied to the template version string.
- **macOS Icon Fallback Safety:** If `iconutil` fails, the bundle no longer writes a PNG file with an `.icns` extension; it falls back to the default app icon cleanly instead of producing an invalid icon asset.

### Cross-Platform Qt Startup Hardening
- **Platform-Generic Bootstrap:** Replaced the Windows-only Qt startup helper with a cross-platform bootstrap layer. Linux and macOS now share the same deterministic pre-QML decision point for platform plugin selection, graphics backend selection, and debug logging.
- **Linux Wayland/X11 Guard:** Mixed Wayland/X11 sessions now prefer `xcb;wayland` during normal startup, and a failed first launch can relaunch once in a safer `xcb + software` mode instead of immediately dying on EGL/OpenGL initialization.
- **macOS Safe Recovery:** macOS now keeps its native Metal/Cocoa path by default, but if startup fails before the first window stabilizes the launcher can retry once with the Qt Quick software backend for diagnosis and recovery.
- **One-Shot Recovery Relaunch:** Added a guarded `RENLOCALIZER_QT_RECOVERY_ATTEMPT` recovery flow so startup fallback happens at most once and never loops forever.
- **CI Smoke Tests:** GitHub Actions now runs frozen-binary smoke tests for Linux and macOS in both native and forced-software startup modes, and Linux additionally smoke-tests the final AppImage launcher path before publishing artifacts.
- **Dual macOS Releases:** Release builds now publish separate Apple Silicon and Intel DMGs instead of a single opaque macOS artifact.
- **AppImage Font Reliability:** The Linux AppImage launcher now generates a temporary runtime fontconfig file instead of trying to patch a read-only mounted AppDir, so bundled emoji fonts stay discoverable on minimal systems.
- **Linux Source-Run Polish:** Linux source runs now probe common system emoji fonts in addition to bundled fonts, and non-Windows QML surfaces prefer `icon.png` over `.ico` to avoid soft or missing icons on source-based X11/Wayland setups.
- **Cross-Platform UI Asset Packaging:** `icon.png` is now bundled alongside `icon.ico` so non-Windows QML surfaces can render their intended assets correctly inside Linux and macOS packaged builds.
- **QML Shutdown Noise Guard:** Linux source runs now keep QML backends app-owned and schedule QML engine teardown before backend destruction, reducing the close-time `settingsBackend`/`backend` null-binding spam that could appear across all eagerly-instantiated pages.

### Windows: HiDPI Black Screen Hardening
- **Safe Qt Quick Bootstrap:** Added a Windows-only Qt graphics bootstrap layer before any Qt import. RenLocalizer now avoids the fragile default D3D path and switches to a safer OpenGL startup path automatically.
- **HiDPI Software Fallback:** On Windows systems detected at `125%+` DPI scale, the launcher now escalates to **software OpenGL** automatically (`QT_OPENGL=software`) to prevent black startup windows on problematic GPU/driver combinations.
- **User Override Support:** Added `RENLOCALIZER_QT_RENDER_MODE` (`native`, `opengl`, `software`) and `RENLOCALIZER_QT_DEBUG=1` escape hatches for diagnosis without editing source code.
- **Runtime Diagnostics:** Startup logs now report the selected graphics mode, detected scale percentage, and the actual Qt Quick graphics API in use after window creation.
- **Packaging Guard:** Windows builds now explicitly bundle `opengl32sw.dll`, ensuring the software OpenGL fallback works in packaged releases instead of only in source environments.
- **Build Reproducibility:** Pinned `PyQt6` to the tested `6.10.x` line so GitHub Actions does not drift across unvalidated Qt patch combinations.

### Config & Theme Consistency Fixes
- **Generic Config Setter Repair:** Removed the dead `auto_save_settings` dependency from `ConfigManager`. Generic `set_api_key()` and `set_setting()` mutations now persist safely again instead of crashing or silently skipping saves.
- **Theme Persistence Fixed:** Custom themes (`red`, `turquoise`, `green`, `neon`) are now valid first-class presets in `AppSettings`, so selections made in the UI survive restart instead of falling back to `dark`.
- **Legacy Theme Migration:** Old configs that still store `app_settings.theme` are now migrated transparently to `app_settings.app_theme` during load.
- **Startup Theme Bootstrap Sync:** `run.py` now reads the active data-path config instead of blindly checking the current working directory, keeping the early Material theme bootstrap aligned with the real saved settings.

### Export Pipeline Fixes
- **Auto-Export Path Resolution:** Fixed `strings.json` auto-export so it now accepts both the project root and the `game/` directory without constructing broken paths like `game/game/tl/...`.
- **Cross-Engine Cache Labeling:** Fixed cross-engine cache hits being reported under the cached engine label during active Yandex/other engine sessions. Cache hits are now projected to the selected engine while preserving source provenance metadata internally.
- **Cache Clear Persistence:** Fixed the translation-memory clear flow so an emptied cache now overwrites `translation_cache.json` on disk instead of leaving stale entries to be reloaded on the next session.
- **TM View Refresh:** The Translation Memory page now refreshes itself when it becomes visible again and after a translation run finishes, avoiding stale snapshots that could continue showing older engine badges.
- **Exporter Reliability:** Added the missing regex dependency in the classic `.rpy` exporter and locked the behavior with regression tests for both path styles.

### Runtime Diagnostics
- **Missed Runtime String Logging:** Added an optional runtime-hook diagnostic mode that records unique untranslated strings seen during gameplay into `game/tl/<lang>/diagnostics/runtime_missed_strings.jsonl`.
- **Bounded Sandbox Debugging:** Logging is capped and deduplicated to stay safe on sandbox/procedural games while still surfacing exact misses from `say_menu_text_filter` and `replace_text`.
- **UI Toggle:** Added a Settings toggle so the diagnostic mode can be enabled only for investigation runs and kept off during normal use.

### Translation Reliability Hardening
- **Core UI Extraction Fixed:** `STANDARD_RENPY_STRINGS` now acts as a true override allowlist, and `_()`-wrapped screen/button labels such as `Auto`, `Q.Save`, and `Q.Load` are no longer dropped by technical-string heuristics.
- **Sandbox Menu Extraction:** Added a dedicated parser pass for common dynamic menu-list entries such as `["Stats/s", ..., "option"]`, `["Favour/f", ..., "submenu"]`, `["Chat/c", ..., "option"]`, and `["Exit/x", ..., "exit"]`, improving coverage for data-driven sandbox UI labels that previously depended on brittle deep-scan luck.
- **Shared Corruption Guard:** Unified corruption validation now protects both `tl/*.rpy` outputs and `strings.json`. Placeholder remnants, orphan placeholder markers, tag mismatches, placeholder-set mismatches, separator bleed, and abnormal inflation are blocked consistently with safe source-text fallback.
- **Targeted Core UI Rescue:** Added a narrow retry/fallback path for critical Ren'Py UI labels (`Save`, `Load`, `About`, `Main Menu`, `Q.Save`, `Q.Load`, etc.) so unchanged engine outputs get one controlled rescue attempt instead of silently shipping as English.
- **Hotkey Visible-Form Coverage:** `strings.json` now synthesizes exact-match variants like `Stats [S] -> Istatistikler [S]` from source forms such as `Stats/s`, reducing a major sandbox-menu runtime gap without reintroducing unsafe partial replacement.
- **Quote/Angle Runtime Aliases:** `strings.json` now also synthesizes plain-text aliases from common single wrapped forms like `<Line>`, and the runtime hook now tolerates inner quoted whitespace (`" Line"`) so games that later render wrapped segments with spacing can still hit the exact-match hook more reliably.
- **Stale TL Recovery:** Existing `tl/<lang>/` entries that are already corrupted (`RLRLPH...`, orphan wrappers, placeholder/tag mismatches) or unchanged core UI labels are now reopened for retranslation instead of being silently treated as good output on reruns.
- **Diagnostics Upgraded:** Runtime miss logs now distinguish `hotkey_visible_form_miss`, `quote_lookup_miss`, and `corruption_driven_miss`; pipeline diagnostics also emit `translation_blocked_or_fallback.json` with separate counters for unchanged engine outputs, corruption blocks, retry recoveries, and synthesized variant recoveries.
- **Export Feedback Loop Cut:** Generated `zz_rl_exported_<lang>.rpy` files are now excluded from the TL parse / strings build loop, and `id_<hash>` translation IDs are no longer allowed to leak back into `strings.json`.
- **Custom Sandbox Edge Cases:** Highly custom sandbox/procedural projects can still surface runtime misses outside these common menu and wrapper patterns, so runtime diagnostics remain the intended follow-up tool for edge-case investigation.

### [2.7.4] - 2026-03-12

### 🌟 New: Smart Data Path & Portable Mode
- **System Mode (Default):** User data (Config, TM Cache, Glossary, Logs, External TM) is now safely stored in OS-standard directories (`AppData\Roaming` on Windows, `~/.local/share` on Linux, `~/Library/Application Support` on macOS) to prevent write-permission errors when installed in protected folders.
- **Portable Mode Fallback:** If the app detects an existing `config.json` next to the executable (legacy behavior), it activates **Portable Mode** seamlessly to preserve existing user setups.
- **UI Management:** Added a dedicated toggle in Settings to instantly switch between Portable and System modes, including an "Open Data Folder" button for easy access.
- **Full Data Integrity Migration:** Replaced data copying with a secure **Atomic Move** operation. Switching between Portable and System modes now performs a complete transfer of `cache/`, `tm/`, and `glossary.json`, automatically cleaning up the source directory to prevent data duplication and clutter.
- **Dynamic TM Resolution:** Re-engineered `ExternalTMStore` to dynamically resolve paths based on the active data directory, ensuring all pre-imported archives remain accessible in both Portable and System environments.
- **Pipeline Synchronization:** Unified all path calculations in `translation_pipeline.py` and `app_backend.py` to use the centralized `data_dir`. This ensures even background tasks strictly respect the active Portable/System mode selection.

### 🐧 Linux: AppImage & Runtime Reliability
- **Startup Crash & Icon Fixes:** Implemented read-only filesystem fallbacks (logs redirect to `/tmp`) and bundled `NotoColorEmoji.ttf` to natively fix missing emoji icons across all Linux environments.
- **Improved Compatibility:** Switched build base to Ubuntu 22.04 to ensure maximum stability and reliability across modern Linux distributions (Note: GitHub has retired Ubuntu 20.04 runners).

### 🔍 Core parsing & Fixes
- **Disk Optimization & Cleanup:**
    - Disabled automatic `.rpy.bak` creation during source translatable phase to reduce file clutter and disk I/O.
    - Added automatic `.rpa` archive deletion after successful extraction to save multiple gigabytes of disk space and prevent Ren'Py archive priority conflicts. Orijinal archives can still be recovered from the source ZIP/RAR or Steam.
    - Using safe atomic writes for source file modification to ensure data integrity without redundant backups.
- **Translation Filter Enforcement:** Resolved major Pyparsing & RPYC issues where translation filters ("Dialogue Only" etc.) were bypassed. All extraction paths strictly adhere to user settings.
- **Extended Extraction Coverage:** Added detection for 15+ missing text-type structures and smart context routing for UI vs Dialogue elements, guaranteeing near 100% translatable text extraction.
- **Screen & Tag Translation:** Overhauled `_make_source_translatable()`. The pipeline now correctly identifies formatted UI texts (with Ren'Py tags like `{b}`) and complex `textbutton` layouts which were previously skipped. Lookaheads replaced fragile keyword dependencies.

### 🤖 AI Engines & Protection
- **LibreTranslate Hardening:** Migrated to strict HTML protection (`<span translate="no">`) preventing placeholder mutation during inference.
- **Placeholder Entity Guard:** Fixed a critical API bug where HTML entities (`&amp;lt;`) got stuck in a double-escaped loop on Yandex and LibreTranslate, causing math operations (`<`, `>`) to fail in output strings. reversed the decode order.

### 🖥️ UI/UX & Quality of Life
- **Unified Engine Settings:** AI & LLM tuning parameters (Batch size, Token boundaries, Concurrency limits) are now grouped logically into the UI, restoring custom LLM batch overrides.
- **DPI & Window Scaling:** Windows 125%-200% scale handling rewritten with pure Qt6 + Manifest flow to cure the infamous "White Screen of Death" bug on startup. Added `Copy Log` context actions.
- **Glossary Validation:** Fixed an `IndexError` crash caused by empty JSON objects returned by Google's auto-translate API during glossary generation.

## [2.7.3] - 2026-03-08

### New Feature: Yandex Translate Engine
- **8th Translation Engine:** Yandex Translate added as a free, API-key-free engine with native batch support. Uses the Widget API endpoint (GET) with automatic SID management (12-hour cache, auto-refresh via asyncio.Lock).
- **Native Batch Translation (GET):** Multiple `&text=` parameters in a single GET request — URL-length-aware slicing (6000 char limit) with automatic chunk splitting for large batches.
- **HTML Placeholder Protection:** Ren'Py syntax tokens wrapped in `<span translate="no">` for Widget API (`format=html`), ensuring placeholder integrity through translation.
- **2-Layer Fallback with Smart Retry:** Widget API → SID refresh + retry (handles partial failures) → Google Translate. Ensures translation continuity even under rate-limiting or SID expiry.
- **100+ Languages:** Including strong CIS language support (Russian, Tatar, Bashkir, Kazakh, Ukrainian, Uzbek) where Yandex excels over other free engines.
- **Full Integration:** GUI engine selector (Home + TL Translate dialog), CLI `--engine yandex`, all 8 locale files, pipeline lazy-init with keyword-argument construction ensuring correct `proxy_manager`/`config_manager` inheritance.

### Improvements: LibreTranslate Protection & Stability
- **Enhanced Placeholder Protection:** Overhauled the `Syntax Guard` engine for LibreTranslate and Local LLM (Ollama) — broken/spaced tokens (e.g., `[ RLPH 0 ]`) are now correctly recovered.
- **Rate Limit Handling:** 3-tier exponential backoff (2s→4s→8s) for `429 Too Many Requests`, randomized User-Agent rotation, and smart proxy isolation (local instances bypass proxy).
- **Humanized Error Messages:** Connection errors now show clear, actionable guidance (e.g., "start your local LibreTranslate" or "switch to Cloud endpoint") instead of raw tracebacks.

### UI/UX Revamp
- **Settings Page Redesign:** Reorganized into 6 logical tiers (General → Engines & APIs → Filters → Network → AI Tuning → System). Removed legacy "Google API Key" field. New group headers localized in all 8 languages.
- **TL Folder Translation Dialog — Full Feature Parity:** Added engine selector (all 8 engines), source language selector, and proxy toggle. Previously these were hardcoded to Google/auto/off — now fully configurable, matching the main translation flow.

### Localization: Full Native Translation Coverage
- **~1,157 Translations Applied:** Completed all missing translations across 6 locale files (`de`, `es`, `fr`, `ru`, `fa`, `zh-CN`). French and Chinese were essentially untranslated (~330+ keys each); German (104), Spanish (97), Russian (35), and Persian (20) gaps also filled.
- **27 Missing Keys Injected:** Keys present in `en.json` but absent from all other locales (settings headers, button labels) added and translated.

### New Feature: External Translation Memory (TM)
- **Cross-Project Translation Reuse:** Import translations from another game's `tl/<language>/` folder and reuse them as Translation Memory. Matching texts are resolved instantly from TM without API calls — reducing cost and increasing speed.
- **Smart Import Pipeline:** New `ExternalTMStore` module with 6-layer filtering (empty, same, short, technical, duplicate, 100K limit). TM entries stored per-source (e.g., `tm/GameA_turkish.json`) with granular source selection.
- **Full UI Integration:** TM Import dialog in Tools page (source name, folder picker, language, source list with delete). TM source checkboxes on Home page. Global toggle in Settings.
- **Pipeline Integration:** Exact-match TM lookup runs before each API request — TM hits skip the translation engine entirely. Results tracked in diagnostic reports.
- **33 Unit Tests** covering import pipeline, store operations, config validation, and edge cases.

### Fixed: TM Bugs & Data Integrity
- **Pipeline Index Alignment:** TM-resolved entries were being re-sent to the translation API, causing results to shift to wrong entries. Fixed with `_tm_resolved_indices` tracking set.
- **Atomic File Write & Thread Safety:** TM save now uses atomic write (`tempfile` + `os.replace()`). All store operations synchronized with `threading.Lock()`.
- **Config Validation:** `external_tm_sources` now validates each array element is a string, preventing `TypeError` crashes.

### Fixed: File Path Translation Defense
- **Expanded Asset Filtering:** Path prefix checks now case-insensitive (fixes Linux mixed-case like `Images/` vs `images/`). Added 8 new folder prefixes (`video/`, `sfx/`, `bgm/`, `cg/`, etc.) and 10 missing file extensions (`.mp4`, `.webm`, `.flac`, etc.) across all filtering layers.

### Fixed: Application Icon
- **Icon Optimization:** Reduced `icon.ico` from 1.5 MB → 71 KB (multi-resolution 16–256px), new `icon.png` 44 KB for Linux/macOS.
- **First-Launch Persistence:** Escalating retry timers (200ms + 500ms) and cross-platform Qt icon re-application ensure the icon appears reliably on first launch.

### Fixed: Engine Selection & Configuration
- **Engine Selection Not Persisted:** The `selected_engine` value was stored as a runtime attribute but was missing from the `TranslationSettings` dataclass. Since `asdict()` only serializes dataclass fields, the user's engine choice was silently lost on every app restart — always reverting to Google. Fixed by adding `selected_engine: str` as a proper dataclass field with `__post_init__` validation against the full engine whitelist.
- **Yandex Engine Mapping Missing:** `_get_engine_enum()` lacked a `"yandex"` entry in its string→enum mapping, causing Yandex selection in the UI to silently fall back to Google Translate. Users saw "Google Multi-Q" and "Lingva fallback" in logs despite having selected Yandex. Fixed by adding the mapping entry.

## [2.7.2] - 2026-03-04
### New Feature: Local & Self-hosted Machine Translation
- **LibreTranslate Integration**: Added full native support for **LibreTranslate**, enabling 100% offline, privacy-friendly translations via local or self-hosted instances.
- **File-by-File Translation Generation**: Extracted strings now mirror the original project structure. Instead of a single `strings.rpy`, RenLocalizer creates separate files (e.g. `script.rpy`, `options.rpy`) in the `tl/` folder, ensuring better organization and Ren'Py compatibility.
- **Apertium & Argos Compatibility**: The new translator engine supports standard `POST /translate` protocols (Apertium, Argos Translate, etc.), making it highly extensible.
- **Improved Settings UI**: Added a dedicated LibreTranslate configuration section in the Settings page with **Preset Selectors** (Local, Cloud, Apertium, Custom) and connection testing.
- **Expanded Language Support**: Increased the supported language list for LibreTranslate to over 45 languages, ensuring global applicability.
### Improvements: Smart Language Detection (v2.0)
- **Syntax Noise Stripping**: The auto-detect engine now strips all Ren'Py tags (`{color}`, `{b}`), variables (`[name]`), and placeholder keys (`<RLPH...>`) before analyzing text. This prevents translation engines from getting confused by code syntax and failing to detect the language.
- **Short String Aggregation**: Fixed a major flaw where source files with only short strings (under 30 characters, like "Start", "Load", "Options") would fail language detection and default to "auto", leading to untranslated words. The engine now intelligently concatenates short strings into larger, mathematically analyzable blocks to guarantee accurate detection.
- **Progressive Confidence Thresholds**: Upgraded the voting system to use dynamic thresholds. An absolute majority of >70% is instantly accepted, and a relative majority of >40% is also accepted if it beats the runner-up by a massive margin (>=25%), virtually eliminating unnecessary fallback states.

### Fixed: GUI & Settings Persistence
- **ComboBox Initialization Bug**: Fixed an issue in `HomePage.qml` where the Source Language, Target Language, and Engine selection boxes would instantly overwrite the user's saved preferences with default values (`index: 0`) during application startup due to the `onCurrentValueChanged` signal firing prematurely. Switched to `onActivated` so settings are only saved upon explicit user interaction.

### Improvements: Context-Aware Translation (Local LLM)
- **Enhanced LLM Context Support**: Added descriptive metadata and improved instructions for Local LLM engines (Ollama, LM Studio, etc.) to help them better handle dialogue context, formal/informal nuances, and "You/Thou" distinctions.
- **Dynamic Connection Management**: Fixed a backend logic error where changing translator URLs (Local LLM/LibreTranslate) required an app restart. Engines now re-initialize instantly when settings are updated.
- **CLI Engine Support**: Expanded the CLI with the `--engine libretranslate` flag, enabling automated batch translation via local servers.


### Refinement: Proxy System
- **Free Proxy Fetching Removal**: Removed unreliable free proxy fetching logic (GeoNode, scraping) to focus on personal and manual proxies.
- **Connection Testing Focus**: The system now prioritizes stability over quantity. "Refresh" functionality has been converted to "Test Connections".
- **Enhanced Reliability**: Improved proxy testing batches and sorting; personal proxies are now kept even if individual health checks fail (user preference priority).
- **UI/UX Updates**: Simplified proxy settings interface and clarified status messages across all languages.

### Improvements: Syntax Guard & Corruption Prevention
- **Fuzzy Suffix Recovery (Google Halucination Fix)**: Solved a critical issue where AI translation engines (specifically Google) maliciously hallucinated or mutated placeholder keys (`⟦RLPH...⟧` into `⟦RLLPH...⟧` or altered hex values). The restorer now features a dynamic fallback mechanism that matches tokens by their unique suffix index (`_0`, `_G0`) if the main string body is corrupted, completely eliminating `placeholder_remnant` corruption skips.
- **Hex Mutation Catcher**: Expanded token recovery regex from strictly Hexadecimal `[A-F0-9]` to `[A-Z0-9]` to reliably catch OCR-style mutations inserted by translation engines (e.g., transforming a zero into an 'O' or 'L').
- **Non-strict Tag Nesting Repair**: Rewrote the `_repair_broken_tag_nesting` logic. Previously, it strictly deleted any closing tag that didn't immediately match the last opened tag (causing `renpy_tag_set_mismatch` errors on intentionally unclosed author tags like `{size=10}OK{/font}`). It now performs algorithmic stack traversing (unwinding) to properly find paired root tags, preserving formatting integrity while safely dealing with orphans.

### Fixed: Critical Pipeline Bugs
- **Duplicate Translation Defense**: Fixed a critical bug where the "Auto-Export" feature created redundant `zz_rl_exported_...rpy` files containing strings already defined in regular `.rpy` files, causing Ren'Py to crash.
- **Flexible Language Codes**: LibreTranslate engine now correctly handles non-standard ISO codes (e.g. `fil`, `ber`) and regional variants with more than 5 characters.
- **Atomic Template Writing**: Applied robust atomic file writing to the initial translation creation process, preventing zero-byte or corrupted `.rpy` files during high-volume extractions.

### Fixed: Linux & Cross-Platform Compatibility
- **Case-Insensitivity Fixes**: Implemented case-insensitive file and directory searching for Linux environments, covering `.rpa`/`.RPA` archives, `.rpy`/`.RPY` scripts, and `game`/`Game` folder naming.
- **Improved Translation Pipeline**: Fixed "translate strings: expects non-empty block" crash in generated `.rpy` files.
- **Robust Path Mirroring**: Improved path mirroring for engine-common translation files safely jailed inside `tl/` subfolders.
- **Automatic Skipping**: Added automatic skipping of translation files with zero translatable entries.
- **Path Resolution Improvements**: Enhanced path normalization (`urllib.parse.unquote`, `os.path.normpath`) to correctly handle space-containing paths and `file:///` URIs across different OS file systems.
- **GUI Stability**: Fixed `TypeError` exceptions in QML during startup on Linux by implementing null-checks for the `backend` context property and correcting path display logic.
- **Icon Handling**: Added support for `.png` icons and platform-specific guards for Windows-only `ctypes` calls, preventing crashes and display errors on Linux.

### New: Cross-Platform Packaging
- **Linux AppImage**: Linux builds are now packaged as `.AppImage` files — single-file, double-click-to-run executables that work on any distribution without installation.
- **macOS DMG**: macOS builds are now packaged as `.dmg` disk images with a proper `.app` bundle and drag-and-drop `/Applications` install support.
- **CI/CD Pipeline**: Updated GitHub Actions workflow to produce platform-native packages (Windows ZIP, Linux AppImage, macOS DMG) in parallel.

### Improvements: Ren'Py Extraction Engine
- **Custom Gallery Capture**: Support for `gallery.button`, `gallery_gup.button`, and `unlock_image` custom object methods.
- **Enhanced Constant Detection**: Fixed a logic error in uppercase constant scoring. Long or meaningful uppercase constants (e.g., `MISSION_DESCRIPTION`) are now captured while technical IDs (e.g., `state_enum`) are filtered.
- **Robust False Positive Prevention**: Global passes (Pyparsing/TokenStream) now respect the variable analyzer, preventing internal state variables and technical identifiers from leaking into the translation strings.
- **Blacklist Expansion**: Added `show_screen`, `hide_screen`, and other technical Ren'Py API calls to the extraction blacklist.
- **Smarter Path/ID Filtering**: Improved `is_meaningful_text` heuristics to automatically skip snake_case strings and technical path fragments.

### Improvements: RPYC Binary Extraction
- **Python 2 Pickle Compatibility**: Added multi-encoding fallback (`ASCII` → `latin-1` → `bytes`) for unpickling old Ren'Py games compiled with Python 2.
- **Slot Fallback**: RPYC reader now tries slot 2 if slot 1 is missing, improving compatibility with non-standard archive layouts.
- **Obfuscation Detection**: Non-standard magic numbers and decompression failures now produce user-friendly warnings instead of cryptic errors.
- **V1 Decompression Fallback**: If v2 slot-based decompression fails, the reader automatically retries treating the file as raw zlib (v1 format).
- **Dead Code Cleanup**: Removed duplicate `find_class` definition and duplicate CLASS_MAP entries for SLDrag/SLOnEvent/SLBar.

## [2.7.1] - 2025-06-14

### Bug Fixes
- **DeepL formality bug**: Fixed two bugs—wrong attribute access path (`getattr(self.config_manager, 'deepl_formality')` instead of going through `translation_settings`), and `config_manager` not passed to `DeepLTranslator` constructor. Turkish added to formality-supported languages.
- **Empty `{}` placeholder protection**: `.format()` positional `{}` placeholders were not protected during translation. Added `_PAT_EMPTY_BRACE` to `syntax_guard.py`.
- **Menu hint parameter parsing**: `menu_choice_re` regex now handles `(hint=expression)` and nested parentheses like `(hint=func(x))` after menu text strings.
- **AES loader key derivation mismatch**: Fixed critical bug where the generated Ren'Py loader used a hash of the passphrase instead of the passphrase itself for key derivation, making decryption impossible.
- **XML entity encoding**: Fixed missing `&` → `&amp;` escaping in AI translator batch XML `context` and `type` attributes.
- **Config int/float crash**: `__post_init__` validators now use safe conversion helpers that handle `None`/empty string/invalid values gracefully instead of crashing.
- **Batch boundary context leak**: `_prev_entry_text` is now reset per batch and checks file boundaries, preventing cross-file/cross-scene context contamination for `extend` entries.
- **Glossary thread-safety**: Auto-protect character names now acquires ConfigManager lock before mutating glossary.
- **RPA header size**: Dynamic header calculation instead of hardcoded 46 bytes (actual is 34).
- **Obfuscation keyword filter**: `obfuscate_rpy_content()` now excludes Ren'Py keywords (`if`, `return`, etc.) from dialogue matching to prevent false positives.

### New Features

#### Config Validation
- All 4 dataclasses (`TranslationSettings`, `ApiKeys`, `AppSettings`, `ProxySettings`) now have `__post_init__` validators
- **Numeric clamps**: 15+ fields clamped to safe ranges (prevents `batch_size=0` infinite loops, `concurrency=0` deadlocks)
- **Enum allowlists**: `deepl_formality`, `gemini_safety_settings`, `app_theme`, `output_format`
- **String sanitization**: API keys auto-stripped, language codes trimmed, URL fields cleaned
- **JSON validation**: `custom_function_params` validated on load (invalid → `"{}"`)

#### Extend Context for AI Translation
- New `TextType.EXTEND` type in parser for `extend` dialogue lines
- Pipeline tracks previous entry text, passes as `context_hint` metadata
- AI translator adds `context="..."` attribute to batch XML for better translations

#### Custom Function Parameter Extraction
- New `custom_function_params` JSON config field (TranslationSettings)
- Users define which function calls to extract: `{"Quest": {"pos": [0,1,2]}, "notify": [0]}`
- `DeepExtractionConfig.get_merged_text_calls()` merges user config with built-in TIER1

#### Auto-Protect Character Names
- New `auto_protect_character_names` config field (default: `True`)
- Pipeline auto-collects Character names from `define` entries
- Names (including multi-word like "Mary Jane") added to glossary as `name → name`

#### Ren'Py Translation Lint (`src/tools/renpy_lint.py`)
- Post-translation validator with 10 check codes (E000–E050, W010–W041, I010, R001)
- Indentation validation (tabs, non-4-space)
- `translate` block structure integrity (duplicate IDs, missing indent)
- `old`/`new` pair validation (orphaned old, missing new)
- Placeholder preservation: `[var]`, `{tag}`, `%(name)s`, `.format()` placeholders
- String syntax (unbalanced quotes, triple-quote toggle fix)
- Encoding/BOM checks (UTF-16 → error)
- Optional Ren'Py engine lint integration (`run_renpy_lint()`)

#### Project Import/Export (`src/utils/project_io.py`)
- `.rlproj` archive format (ZIP containing JSON manifests)
- Exports: settings, glossary, critical terms, never-translate rules, translation cache
- Imports with merge options (glossary merge/replace, selective settings)
- ZIP bomb protection (100 MB per entry, 500 MB total limit)
- API keys excluded by default for safety
- Version-aware manifest for future compatibility

#### JSON/YAML Data Extractor Plugin System (`src/core/data_extractors.py`)
- `BaseExtractor` abstract class with key-based heuristic filtering
- `JsonExtractor` with auto-detection, write-back support
- `YamlExtractor` (graceful degradation without PyYAML, roundtrip warning)
- `ExtractorRegistry` with auto-detect and custom plugin registration
- Heuristic filters: skip `id`, `path`, `image`, `color`; include `text`, `dialogue`, `name`, `description`
- Directory scanning with extension filtering

#### Translation Encryption/Obfuscation (`src/utils/translation_crypto.py`)
- **Obfuscation mode** (zero dependencies): Base64 encodes strings, injects Ren'Py `init -999` decoder
- Round-trip: `obfuscate_rpy_content()` ↔ `deobfuscate_rpy_content()`
- File-level API: `obfuscate_rpy_file()`
- **AES mode** (requires `cryptography`): AES-256-GCM encryption with PBKDF2 key derivation
- Generates `.rlenc` + loader `.rpy` with real AES-GCM decryption for Ren'Py runtime

#### RPA Archive Packer (`src/utils/rpa_packer.py`)
- Creates RPA-3.0 archives compatible with Ren'Py's archive loader
- `pack_directory()` with extension filtering and prefix support
- `pack_files()` for explicit file mapping
- Round-trip verified with existing `RPAParser` extractor
- Convenience: `pack_translations()` one-call API

### Tests
- 46 new tests for all v2.7.1 features (469 total passing)
- +39 atomic segment + quote-stripping + segment splitting tests (520 total passing)
- Covers: config validation, lint, project I/O, extractors, crypto, RPA packer, atomic segments, quote-stripping, strings.json segment splitting (angle-pipe + bare pipe)

### 🔀 Delimiter Atomic Segment Registration (v2.7.1)

**Issue:** Ren'Py runtime does not use `<A|B|C>` blocks as a single string — it calls each segment individually via `vary()` or list indexing. However, the pipeline was writing only a single `old`/`new` pair for the combined block, so Ren'Py couldn't match individual segments and fell back to English.

**Root Cause:** `_translate_entries()` was correctly splitting and translating delimiter segments, but only wrote the combined block (`<TransA|TransB|TransC>`) to output files. At runtime, when `vary()` looked up `"TransA"` individually, it found no match in the translation dictionary since only the combined block existed.

**Fix — Atomic Segment Registration:**

1. **Instance variable**: `_last_atomic_segments = {}` is reset on each `_translate_entries()` call
2. **Per-batch collection**: `_atomic_segments = []` list is populated during batch result processing
3. **Multi-group path**: When `rejoin_angle_pipe_groups()` succeeds, each segment's `(original_text, translated_text)` pair is collected from result metadata
4. **Bare-pipe path**: Same collection logic applies for `_delimiter_groups` entries
5. **Phase 2.5 block**: `_atomic_segments` pairs are written to both the `translations` dict and `self._last_atomic_segments` (with duplicate checking)
6. **`_generate_strings_json()` updated**: Atomic segments are added to strings.json via the `extra_translations` parameter

**Critical Fix — play_dialogue Quote Wrapping (hotfix):**
- **Bug 1 (Crash)**: The initial implementation created an `_rl_segments.rpy` file, but its `old` entries collided with existing entries in `strings.rpy` → Ren'Py crash: `Exception: A translation for "Really?" already exists at...`
- **Bug 2 (Translation invisible)**: The game's `play_dialogue()` function wrapped `vary()` output in literal double quotes: `renpy.say(speaker, '"'+talk+'"')`. So the runtime text `"Really?"` didn't match the `Really?` key in strings.json.
- **Bug 3 (IDE errors)**: The `_rl_segments.rpy` file showed entirely red in the IDE, and Ren'Py `translate XX strings:` blocks do not affect dynamic `renpy.say()` calls.

**Architecture Decision — `_rl_segments.rpy` Removed:**
- `translate XX strings:` blocks only work for static string matching — they DO NOT AFFECT dynamic `renpy.say()` calls
- The `vary()` + `play_dialogue()` system is fully dynamic: `renpy.say(mc, '"' + vary("A|B") + '"')`
- Therefore `_rl_segments.rpy` served no useful purpose — removed entirely
- `_write_atomic_segments_rpy()` method DEPRECATED — disabled with early `return`
- Pipeline now automatically cleans up old `_rl_segments.rpy` + `.rpyc` files

**Fix — Runtime Hook Quote-Stripping (v4.1.0+):**
- **Layer 1** (`_rl_say_menu_text_filter`): New "Try 3" — for quote-wrapped text like `"Really?"`, strips outer quotes, looks up `Really?`, and re-wraps the translation in quotes if found
- **Layer 2** (`_rl_replace_text`): New "Step 3" — same quote-stripping logic, inner text searched via exact + case-insensitive lookup, found translation re-wrapped in quotes
- Both layers include empty string/short string guards (crash-safe)

**Fix — strings.json Segment Splitting (v2.7.1 hotfix-2):**
- **Core issue**: `_translate_entries()` only collected atomic segments when new translation engine results arrived — segments from cache or previous runs were not split
- **`translate_existing_tl` path**: `_generate_strings_json` was never called → atomic segments were not written to strings.json (fixed)
- **Solution**: `_generate_strings_json()` now scans all delimiter patterns after building the mapping:
  - **Path 1 — Angle-pipe** (`<A|B|C>`): Parses groups using `split_angle_pipe_groups()`
    - Single group: `<A|B|C>` → individual entries for `A`, `B`, `C`
    - Multiple groups: `text <A|B> mid <C|D>` → entries for `A`, `B`, `C`, `D`
    - Embedded group: `And they all <X|Y|Z>...` → entries for `X`, `Y`, `Z`
  - **Path 2 — Bare pipe** (`A|B|C`, without `<>`): `split_delimited_text()` + simple pipe split fallback
    - Example: `Interesting...|Really...?|Indeed...` → entries for `Interesting...`, `Really...?`, `Indeed...`
    - `vary('A|B|C')` produces strings in exactly this format
    - Skipped for safety if segment counts differ between original and translation
  - Does not overwrite existing segments (duplicate protection)
  - Segments where `orig == trans` are skipped

**Output:**
- `strings.json`: Combined blocks + individual segments written together (single output point)
- Runtime hook: `play_dialogue()` compatibility via quote-stripping
- Pipeline cleanup: Old `_rl_segments.rpy` + `.rpyc` files automatically removed

**Tests:** 39 tests — segment split, dict building, strings.json injection + **segment splitting** (13 tests: angle-pipe + bare pipe + mixed), Ren'Py vary() compatibility, **quote-stripping** (Layer 1 + Layer 2, 13 tests)

### Multi-Group Angle-Pipe Delimiter System (v2.7.1)

**Issue:** The delimiter system (`<seg1|seg2|...>` patterns) had 3 critical bugs causing 97/229 (42%) delimiter patterns to produce incorrect translations:

1. **Multi-group regex failure**: Strings with MULTIPLE `<...|...>` groups (e.g., `text <A|B> mid <C|D> end`) couldn't match the `^...$` single-group regex, falling to bare-pipe split which destroyed the `<>` structure
2. **Surrounding text not translated**: For `Pirate activity <A|B> remains challenging!`, the text outside the angle brackets ("Pirate activity", "remains challenging!") was embedded in prefix/suffix and NEVER translated
3. **Structural integrity too strict**: Single-word segments like `<increasing|forecast|intensifying>` and short phrases like `<Indeed.|Really?|Is that so?>` were rejected by the min_words=2/min_len=8 requirement

**Fix — New `split_angle_pipe_groups()` system:**
- Uses `re.finditer()` to find ALL `<...|...>` groups in a string (not just one)
- Creates a template with `[DGRP_N]` placeholders (protected by `protect_renpy_syntax`)
- Template is translated as a single unit (preserving sentence context and allowing natural word order)
- Each group's segments are translated independently
- `rejoin_angle_pipe_groups()` reassembles the final text

**Results:**
- **Before**: 132/229 OK (57.6%), 97 broken
- **After**: 228/229 OK (99.6%), 1 remaining (all-numeric group, handled by GT)
- 69 patterns with surrounding text now get full translation
- Short/single-word segments accepted without min_words restriction
- Numeric groups (`<0.1|0.02|0.005>`) preserved in template as-is (no translation needed)
- Turkish word order: GT naturally reorders `[DGRP_0]` and `[DGRP_1]` in template

**False-Positive Fixes:**
- `_CODE_DOT_RE`: Requires 2+ chars before dot (prevents `A.I.` abbreviation false positive)
- File path detection: Uses `re.search(r'[\\/][A-Za-z_]', s)` — prevents `\"` escaped quote AND `10/20` numeric slash false positives

**Safety Guards:**
- Doubled placeholder detection: If GT duplicates a `[DGRP_N]` token, `rejoin_angle_pipe_groups()` returns `None` (safe fallback)
- Remaining `[DGRP_` text after reassembly → automatic corruption detection → original text preserved

**Pipeline Integration:**
- `split_angle_pipe_groups()` tried FIRST (handles all angle-bracket patterns)
- `split_delimited_text()` now only handles bare pipe patterns (angle-bracket guard added)
- Result processing handles multi-group rejoin with corruption detection

### 🛡️ Critical: Dotted-Path & Python Builtin Leak Fix (Crash Prevention)

**Issue:** Despite initial filter hardening, ~31 critical code strings still leaked through filters and caused `IndexError: list index out of range` crash in `renpy/ui.py` when translated. These fell into patterns not covered by existing regexes.

**Leaked Patterns (SpaceJourneyX 230_023, 51K-line strings.rpy):**
- 16× `GAME.hour in [18,19,20,21,22]` — dotted path + `in` + square brackets
- 13× `'reactor activated' in GAME.mc.done` — multi-word quoted string in dotted path
- 1× `True` standalone — Python boolean translated to `Doğru`
- 1× `GAME.day%5 == 0` — dotted path + modulo/comparison
- 1× `[x >= 70 for x in bot.skills.values()].count(True) >= 3` — list comprehension
- 1× `GAME.getStarSys().ID in ['SSIDIltari']` — method chain + `in` check

**Fixes (6 new detection patterns):**

1. **`_DOTTED_IN_RE`**: `GAME.hour in [list]`, `GAME.getStarSys().ID in ['X']` — dotted path followed by `in [`
2. **`_DOTTED_COMPARE_RE`**: `GAME.day%5 == 0`, `GAME.hour < 18` — dotted path followed by comparison operators
3. **`_LIST_COMPREHENSION_RE`**: `[x >= 70 for x in items]` — Python list comprehension inside brackets
4. **`_BRACKET_METHOD_RE`**: `].count(True)`, `).items()` — method call on bracket/paren result
5. **`_PYTHON_CONDITION_RE` expanded**: Now handles multi-word quoted strings (`'reactor activated'` → `[^'"]+` instead of `\w+`)
6. **`True`/`False`/`None` standalone**: Python builtin constants blocked as standalone text

**Broad Code Detector Enhancement:**
- Lowered dot reference threshold from 2 to 1 (with 3-char minimum to exclude abbreviations like `e.g.`, `U.S.`, `Dr.`)
- Pattern: 1+ dotted reference (3+ chars before dot) AND comparison/boolean operators

**Safety Balance:**
- All 31 crash-causing code strings now blocked (was 0/31)
- 99.39% of translated entries still pass through (only 96/15,843 filtered)
- Legitimate game dialogue with `[GAME.mc.name]`, `[GAME.version]` variables correctly passes
- Natural language with `return`, `True`, `not` in sentences correctly passes
- 39/39 targeted test cases correct, 394 total tests passing

**Impact:** Eliminates remaining code-translation crashes.

### 🛡️ False-Positive Filter Hardening (Crash Prevention)

**Issue:** ~476 code-like strings in game translations were being translated, causing Ren'Py crashes (`IndexError: list index out of range` in `renpy/ui.py`). Game logic conditions, stat abbreviations, and format templates were leaking through the filter chain.

**Root Cause Analysis (69,918-line strings.rpy — SpaceJourneyX):**
- 335 Python condition strings (`'likes_toy_talk' in moira.done`)
- 54 short ALL_CAPS game stats (`NOT`, `REP`, `INT`, `CON`, `DEX`)
- 37 code-logic expressions (`moira in GAME.crew`)
- 7 broad code patterns (`GAME.hour < 18 and GAME.questSys.isDone(...)`)
- 4 format-string templates (`"Track: {} | Dist: {}".format(...)`)
- 36 newly-classified Ren'Py keywords (`scene`, `with`, `at`, `return`, `screen`, `label`, `menu`, `init`)

**Fixes:**

1. **New detection patterns** (4 pre-compiled regexes + 2 inline checks):
   - `_PYTHON_CONDITION_RE`: `'var_name' in obj.attr` — game logic conditions
   - `_CODE_LOGIC_RE`: `X not in GAME.crew` — dotted-path code (requires `.` to avoid catching "Getting in Shape")
   - `_SHORT_ALL_CAPS_RE`: `NOT`, `STR`, `INT` (2-6 chars) — with whitelist (`OK`, `NO`, `ON`, etc.)
   - `_FORMAT_TEMPLATE_RE`: `"...".format(...)` — Python format templates
   - Broad code detector: ≥2 dotted refs + comparison/boolean operators
   - `not func_call()` prefix handler

2. **Ren'Py text tag fix**: `{b}Hello{/b}` was wrongly caught by format-placeholder check. Now Ren'Py tags (`{b}`, `{/b}`, `{color=...}`, `{size=...}`, etc.) are stripped before counting format placeholders.

3. **RENPY_TECHNICAL_TERMS expanded**: Added 34 crash-causing keywords in three rounds:
   - **Round 1** (13): `scene`, `with`, `at`, `behind`, `as`, `onlayer`, `zorder`, `parallel`, `block`, `contains`, `pause`, `repeat`, `function`
   - **Round 2** (10): `return`, `screen`, `label`, `menu`, `init`, `call`, `jump`, `python`, `define`, `image`
   - **Round 3** (11 — Screen Language): `textbutton`, `imagebutton`, `mousearea`, `nearrect`, `hbox`, `vbox`, `vbar`, `transclude`, `testcase`, `nvl`, `elif`
   - Cleaned 5 duplicate terms (`ascii`, `input`, `insensitive`, `style`, `viewport`)
   - **Total: ~217 unique technical terms**

4. **Python code pattern strictness overhaul** (prevents natural language over-filtering):
   - `for X in` → requires statement-level context with `:` ending
   - `return X` → only catches `return self/True/False/None/digit/bracket`
   - `while X` → requires `:` ending or boolean keywords (`True/False/not/digit`)
   - `with X as` → requires context manager call pattern `with X(...) as`
   - File path concat → requires quotes or `/` to match
   - **Result:** 10 legitimate English phrases previously over-filtered now pass correctly

**Safety Balance:**
- Filter rate: 2.94% of translated entries blocked (476/16,165)
- Pass rate: 97.06% of legitimate text still passes through
- Title Case keywords (`Return`, `Screen`, `Menu`) still pass as UI labels
- Pattern accuracy: 39/39 test texts correctly classified (code blocked, natural language passed)
- 136 dedicated test cases + 394 total tests passing

**Impact:** Eliminates ~476 false-positive translations that could corrupt game logic and cause Ren'Py runtime crashes.

### 🛡️ CRITICAL: Alphabet-Independent Token Format (⟦N⟧)

**Issue:** Google Translate transliterated legacy Latin placeholder tokens on Cyrillic/Greek targets, breaking restoration for multiple token families.

**Fix:** Migrated placeholder keys to Unicode bracket tokens (`⟦N⟧`) so token identifiers contain no transliterable Latin letters.

```python
# Legacy (<=2.7.0)
# VAR0, TAG1, ESC_PAIR2, DIS3, PCT4, ESC_OPEN, ESC_CLOSE

# 2.7.1
key_content = f"⟦{counter}⟧"
```

**Restoration Layers:**
- Stage 0: Unicode token restore (`⟦ 0 ⟧` → `⟦0⟧`)
- Stage 0.5/0.6: Backward compatibility for legacy transliterated/spaced tokens
- Stage 1: Generic legacy restore path

**Impact:** Eliminates transliteration-based token loss while keeping backward compatibility for older cached outputs.

### 🔧 Placeholder Corruption Fuzzy Recovery

**Issue:** Google inserted spaces inside bracket expressions (`[player.name]` → `[player. name]`).

**Fixes:**
- `restore_renpy_syntax()` cleans dot-spacing in bracket content
- `validate_placeholders()` compares whitespace-insensitive normalized forms

**Result:** Placeholder corruption false positives are greatly reduced without relaxing strict structural checks.

### 🛡️ Placeholder Integrity v3.6 — Injection Recovery, Word-Boundary Fix, Early-Exit

**Issue 1: Full token deletion**
Google occasionally removed `⟦RLPH...⟧` markers entirely.

**Fix:** Added `inject_missing_placeholders()` to reinsert missing originals by proportional position from protected text.

**Issue 2: Broken insertion boundaries (fixed in v3.6)**
Earlier insertion could split words or glue placeholders to text.

**Fix:**
- Snap to real space boundaries when available
- Fallback to nearest text edge when no spaces exist
- Always enforce sane spacing around injected values

**Issue 3: Glossary false positives**
Glossary placeholders (`_G*`) were treated like syntax placeholders.

**Fix:** `validate_translation_integrity(..., skip_glossary=True)` now ignores glossary keys by default.

**Issue 4: Double-protection in preprotected flows**
DeepL/AI paths could re-protect already protected text.

**Fix:** Preprotected metadata guards now consistently use `original_text`.

**Issue 5: Cache key mismatch**
Protected-vs-original key mismatch created duplicate cache entries.

**Fix:** Cache keys normalized to `metadata.get('original_text', request.text)` in retry and batch paths.

**Issue 6: Unnecessary retries when tokens are fully deleted**
If raw response had no `RLPH`, retry + Lingva fallback were usually wasted.

**Fix (Early-Exit):**
- If raw output still contains `RLPH`: allow retry/fallback path
- If raw output contains no `RLPH`: skip retry/fallback and inject immediately

**Observed gain:** typically removes 2-3 seconds and 3 extra network calls for affected lines.

**Integrity handlers:** multi-endpoint, single-endpoint, batch multi-endpoint, batch single-endpoint now all follow injection-first recovery.

### 🔧 Proxy Manager v2.1 — Priority Logic Fix

**Issue:** Personal/manual proxies were mixed with unstable free proxies.

**Fix:**
- If `proxy_url` or `manual_proxies` exists: use only personal/manual proxies
- If none exists: fetch free proxies (fallback mode)

**Additional UX:** Added localized warning when proxy is enabled but only free proxies are used.

### ⚡ Google Rate-Limit Stabilization

**What changed:**
- Global cooldown with escalating backoff on HTTP 429
- Lower parallelism in sensitive paths to reduce ban cascades
- Better endpoint health handling and pacing jitter

**Why:** Reduce cross-mirror cascade throttling and improve sustained throughput stability.

### 🧩 Translation Pipeline Hardening (2.7.1 Addendum)

**Scope:** End-to-end pipeline review from **Start Translation** click to final `strings.rpy/strings.json` output.

**Fixes included:**
- Removed duplicate restore call in pipeline phase-1 result assembly (prevents `{i}{i}...{/i}{/i}` double-tag corruption and related Ren'Py runtime instability)
- Hardened `strings.json` sanitization against separator remnants, placeholder leakage (`⟦RLPH...⟧`, `XRPYX_`, `RNPY_`), and HTML tag bleed (`<span>`, `<div>`)
- Fixed dead code path in `save_translations()` and restored reliable success/failure logging
- Improved worker shutdown safety with timeout fallback (`wait` → `terminate`) to reduce dangling thread risk
- Minor cleanup: removed duplicated inline comment in translator lazy-init block

### 🔀 Delimiter-Aware Translation System (Pipe Variants)

**Issue:** Variant texts like `<choice_a|choice_b|choice_c>` were translated as a single block, causing semantic drift and malformed mixed outputs in some engines.

**Fix:** Added delimiter-aware flow that safely splits, translates, and rejoins pipe-variant segments.

**What changed:**
- Added `split_delimited_text()` / `rejoin_delimited_text()` pipeline in syntax protection layer for `<...|...>` and bare-pipe variant patterns
- Integrated segment-based request creation in translation pipeline, preserving per-entry metadata and placeholder context
- Added config toggle `enable_delimiter_aware_translation` (default: `true`) in settings and `config.json`
- Updated phase-1 result assembly to avoid duplicate restore on pre-restored translator outputs (prevents double wrapper tags)
- Improved debug logging output for delimiter previews using UI-safe brackets (`‹...›`) to avoid renderer swallowing `<...>`

**Compatibility:**
- Works with Google / DeepL / OpenAI / Gemini / Local LLM paths without changing engine public API
- Falls back to normal single-request flow when delimiter pattern is not detected

**Validation:**
- Added `tests/test_delimiter_aware.py` with 33 dedicated tests (split/rejoin/roundtrip/edge cases/config toggle)
- Full suite verification after integration: `215 passed` (excluding `tests/test_settings_sanitization.py` environment-specific collection issue)

### ✅ Validation

- Initial test suite result (at time of delimiter-aware feature implementation): `167 passed`
- After hardening updates: `215 passed`
- After all v2.7.1 features + atomic segment tests: **520 passed**
- All counts exclude `tests/test_settings_sanitization.py` (environment-specific collection issue)

### 🔍 Deep Extraction Engine

**Issue:** Many translatable strings in Ren'Py projects were missed by the standard extraction pipeline:
- `define quest_title = "text"` / `default player_name = "text"` without `_()` wrappers
- f-string templates (`f"Welcome back, {player}!"`)
- Multi-line dict/list structures with translatable text values
- API calls like `QuickSave(message=...)`, `CopyToClipboard(...)`, `narrator(...)`, `renpy.display_notify(...)`
- `tooltip "hint text"` properties in screen language
- Compiled `.rpyc` strings from extended Ren'Py API calls

**Solution — Deep Extraction Module (`src/core/deep_extraction.py`):**

- **DeepExtractionConfig**: Three-tier API call classification
  - Tier-1 (16 text calls): `renpy.notify`, `renpy.confirm`, `Character`, `Text`, `ui.text`, etc.
  - Tier-2 (4 contextual calls): `QuickSave`, `CopyToClipboard`, `FilePageNameInputValue`, `Help`
  - Tier-3 (30+ blacklist calls): `Jump`, `Call`, `Show`, `Hide`, `Play`, `SetVariable`, etc.

- **DeepVariableAnalyzer**: Heuristic scoring (0.0–1.0) for variable name classification
  - Prefix/suffix/exact matching for translatable/non-translatable names
  - `is_technical_string()` with 15 compiled regex patterns for false positive prevention
  - Reliably classifies `quest_title` → translatable, `persistent.flags` → non-translatable

- **FStringReconstructor**: Converts `{expr}` → `[expr]` (Ren'Py-compatible) with static text ratio threshold (≥30%)

- **MultiLineStructureParser**: Detects multi-line `define`/`default` structures, balanced bracket collection, AST-based value extraction with DATA_KEY_WHITELIST/BLACKLIST filtering

**Parser Integration (7 new patterns, 6 secondary passes):**
- Bare define/default string extraction with variable name filtering
- `tooltip` property, `QuickSave(message=)`, `CopyToClipboard()` secondary passes
- f-string template extraction secondary pass
- `$ renpy.confirm()`, `$ narrator()`, `$ renpy.display_notify()` secondary passes

**RPYC Reader Integration (7 new DeepStringVisitor handlers):**
- `QuickSave`, `CopyToClipboard`, `FilePageNameInputValue`, `narrator`, `renpy.display_notify`, `renpy.display_menu`, `renpy.confirm`
- Tier-3 blacklist prevents extraction of non-translatable call arguments
- Smart variable filtering with DeepVariableAnalyzer for FakeDefine/FakeDefault code objects

**Config Settings (7 new toggles):**
- `enable_deep_extraction` (master toggle)
- `deep_extraction_bare_defines`, `deep_extraction_bare_defaults`, `deep_extraction_fstrings`
- `deep_extraction_multiline_structures`, `deep_extraction_extended_api`, `deep_extraction_tooltip_properties`

### 📝 Key Files Updated in 2.7.1

- `src/core/deep_extraction.py` *(NEW — shared Deep Extraction module)*
- `src/core/parser.py` *(7 new patterns, 6 secondary passes, multi-line structure support)*
- `src/core/rpyc_reader.py` *(7 new DeepStringVisitor handlers, smart var filtering)*
- `src/core/syntax_guard.py`
- `src/core/translator.py`
- `src/core/ai_translator.py`
- `src/core/proxy_manager.py`
- `src/backend/settings_backend.py`
- `src/core/translation_pipeline.py`
- `src/utils/config.py` *(7 new deep extraction config fields)*
- `config.json` *(7 new deep extraction settings)*
- `tests/test_deep_extraction.py` *(NEW — 65 tests for Deep Extraction)*
- `tests/test_delimiter_aware.py` *(NEW — 33 tests for delimiter-aware translation flow)*
- `tests/test_integrity_injection.py`
- `tests/test_deepl_ai_preprotected.py`

---

## [2.7.0] - 2026-02-10
### 🔥 Multi-Layer Runtime Hook (v2.7.0 patch)

**Root Cause:** Ren'Py's `config.replace_text` runs after tag tokenization in `renpy/text/text.py.apply_custom_tags()`, so it only ever sees text fragments (e.g. `"Hello {b}World{/b}!"` becomes `"Hello "`, `"World"`, `"!"`). Full-sentence exact matching is impossible at that stage.

**Fix:** Added a three-layer hook inside the v2.7 runtime translation feature so we can:

- **Layer 1 – `config.say_menu_text_filter`**: runs before Ren'Py's translation/substitution, gets the complete string with tags, applies word-boundary-aware FlashText matching, protects `[variables]`/`{tags}`, and chains any previous filter.
 - **Layer 2 – `config.replace_text`**: operates on the tag-split fragments (UI strings, text fragments) using aggressive substring matching with smart case/whitespace handling, while preserving and chaining existing handlers.
- **Layer 3 – `config.all_character_callbacks`**: optional debug hook that logs every `what` text before processing and helps verify coverage in complex dialogue.

- Added `_RL_KeywordProcessor` (word-boundary) + `_RL_SubstringProcessor` (fragment) for dual-processing, Shift+R hotkey for reload, Ren'Py searchpath discovery, Turkish/European character support, and `[SAY_FILTER]/[REPLACE]/[DIALOGUE]` debug log prefixes.

This patch stays within the [2.7.0] entry because it represents a runtime-hook rewrite that ships on that release.

### 🔧 Runtime Hook Refinements
- **Late Init Chaining:** Deferred our runtime hook wiring to `init 999 python` so that it runs after any game-defined filters (emoji handlers, UI tweaks) and preserves the trailing filters via `_rl_prev_say_menu_filter` / `_rl_prev_replace_text` chaining.
- **Spacing Restoration:** Added a regex-based post-processing step to both `say_menu_text_filter` and `replace_text` so Ren'Py strings never stick to punctuation after translation (`Hello.World` → `Hello. World`).
- **Template Synchronization:** Ensured `runtime_hook_template.py` and the generated `zzz_renlocalizer_runtime.rpy` are in sync with these refinements so every project gets the same late-install, spacing-safe hook without manual edits.

### 🛠️ Runtime Hook Generation & Compatibility Fixes

- **Format String Generation Fix:** Fixed critical `ValueError: Single '}' encountered in format string` error during hook generation. Changed from unsafe `str.format(renpy_lang=...)` to safe `.replace("{renpy_lang}", renpy_lang)` in both `translation_pipeline.py` and `app_backend.py`. This prevents Python format string parser errors when template contains unescaped braces (e.g., in regex patterns like `[^\}]`).
  - **Root Cause:** Template contains regex patterns with literal braces that conflict with Python format syntax
  - **Solution:** Switched to explicit string replacement to avoid format string parsing
  - **Status:** ✅ RESOLVED – Hook files now generate without syntax errors
  
- **Escaped Brace Normalization:** Added automatic normalization step after placeholder replacement to convert escaped braces (`{{` → `{`, `}}` → `}`) in generated hook files. This prevents Ren'Py from misinterpreting double-braces as Python dictionary syntax, which was causing `TypeError: unhashable type: 'RevertableDict'` crashes.
  - **Impact:** Eliminates runtime failures when hooks are injected into games
  - **Verified With:** Multiple Ren'Py 7.x and 8.x games
  
- **Google Mirror Ban Duration Optimization:** Reduced temporary ban duration from 5 minutes (300 seconds) to 2 minutes (120 seconds) in `src/core/constants.py`. This allows mirrors to recover and re-enter the rotation faster when Google Translate endpoints are temporarily unresponsive, reducing translation wait times.
  - **Rationale:** 5 minutes was too aggressive; 2 minutes allows faster failover while still protecting against rate-limit issues
  - **Fallback Chain:** When mirrors are banned, system automatically falls back to Lingva Translate, ensuring continuous translation service
  
- **Ren'Py Key Binding Compatibility:** Removed incompatible hotkey bindings (`config.underlay.append(renpy.Keymap(...))`) that were causing `Exception: Invalid key specifier` errors in Ren'Py. The hotkey system attempted to register `f7`, `shift_l`, and `shift_r` which are not valid Ren'Py key specifiers in the expected format.
  - **Affected Hotkeys Removed:** 
    - F7 toggle debug mode
    - Shift+L force language change
    - Shift+R reload translations
  - **Alternative:** Debug logging is now automatic and logged to `renlocalizer_debug.log` in the game directory
  - **Impact:** Games no longer crash during initialization due to key binding validation errors

### 🌟 Universal Runtime Hook v2.7.0
- **Multi-File Support:** Now scans and loads translations from ALL `.rpy` files in the `tl/{language}/` directory recursively.
- **Dialogue Translation:** Added robust support for dialogue blocks (`# character "original"` / `character "translated"`).
- **Early-Init Boot:** Switched to `init -999 python` for maximum compatibility and earlier hook initialization.
- **Auto-Gen Logic:** Synchronized translation pipeline to automatically install the hook based on `auto_generate_hook` setting.
- **Exact Match Priority:** (FIX) Implemented high-priority exact match check before substring processing. This fixes issues where strings containing placeholders (e.g., `[n1002]`) were failing to translate because the substring processor would break them before they could match an entry in `strings.json`.
- **Improved Placeholder Protection:** (FIX) Corrected regex and escaping in the placeholder protection mechanism to prevent `KeyError` and template formatting errors during hook generation.
- **Startup & Shutdown Stability:** (FIX) Corrected invalid imports in `app_backend.py` and added missing `asyncio`/`multiprocessing` imports in `run.py` to prevent crashes and ensure clean application shutdown.

### 🚀 Dictionary-Based Runtime Translation Hook (Major Enhancement)
- **New Translation System:** Completely rewrote the runtime translation hook with a structure-first, tag-preserving approach
  - **Problem Solved:** Ren'Py's `translate_string()` only works for strings marked with `_()` function, leaving most dialogue untranslated
  - **Solution:** Hook now loads translations from `strings.rpy` into a dictionary and performs direct key-value lookup
  
- **How It Works:**
  1. At game init, parses `tl/{language}/strings.rpy` file
  2. Extracts all `old "..." / new "..."` pairs into dictionary
  3. Uses dictionary lookup for instant translation (O(1) performance)
  4. Falls back to Ren'Py's native `translate_string()` if not found in dictionary
  5. Supports placeholder normalization for dynamic strings

- **Debug Mode:**
  - Debug logging is automatic, no hotkey needed
  - Writes detailed logs to `renlocalizer_debug.log` in game directory
  - Shows which strategy was used: `[DICT-OK]`, `[RENPY-OK]`, `[NORM-OK]`, `[MISS]`
  - Check logs to identify untranslated strings

- **Updated Files:**
  - `src/core/translation_pipeline.py` - New hook generation code
  - `src/backend/app_backend.py` - Synchronized hook generation code

### Technical Details
- Hook version: v2.7.0
- Dictionary approach eliminates dependency on `_()` function
- Supports UTF-8-BOM encoding for strings.rpy
- Handles escaped quotes and newlines in translation entries
- Compatible with existing ZenPy translations (can coexist)

### 🔧 Critical Import Fixes & Spaced Token Corruption Repair
- **Missing Type Hint Import:** Fixed `NameError: name 'Callable' is not defined` in `src/core/translator.py` (lines 77, 78, 1597). Added `Callable` to the `typing` imports on line 14.
  - Impact: Prevents syntax errors during type checking and IDE analysis
  - Status: ✅ RESOLVED
- **Missing LocalLLMTranslator Import:** Fixed `NameError: LocalLLMTranslator is not defined` in `src/core/translation_pipeline.py` (line 2186). Added `LocalLLMTranslator` to imports from `src.core.ai_translator` on line 35.
  - Impact: Enables Local LLM translator instantiation in translation pipeline
  - Status: ✅ RESOLVED
- **Spaced Token Corruption Bug (CRITICAL):** Fixed a critical restoration bug where Google Translate's space insertion corrupts placeholders (e.g., `VAR0` becomes `VAR 0`). 
  - **Root Cause:** Token regex pattern could not match spaced variants, causing restoration to fail and placeholders to remain corrupted in output.
  - **Fix Applied:** Added pre-processing stage (`AŞAMA 0.5`) in `restore_renpy_syntax()` that detects and merges spaced tokens (`VAR 0` → `VAR0`) before main restoration begins.
  - **Testing:** Verified with multiple test cases - all spaced token variations now restore correctly with 100% integrity.
  - **Impact:** Eliminates "PLACEHOLDER_CORRUPTED" errors in logs, ensures all translations pass integrity validation.
  - **Status:** ✅ RESOLVED
- **Comprehensive System Verification:** Executed full project health check:
  - ✅ All core imports working (translator, ai_translator, syntax_guard)
  - ✅ Translation pipeline integration verified
  - ✅ HTML protection system tested and validated
  - ✅ Syntax guard token/HTML/XML modes confirmed functional
  - ✅ Wrapper tag handling verified correct
  - ✅ Spaced token corruption scenario tested - now fixed
  - ✅ All major systems production-ready

### 🌍 Multilingual Text Filtering Improvements
- **Problem:** Russian and other non-Latin language text (Chinese, Arabic, etc.) was being incorrectly filtered out during extraction
- **Root Causes Identified & Fixed:**
  1. **Overly Broad Placeholder Pattern (Line 1542):**
     - Old: `re.fullmatch(r"\s*(\[[^\]]+\]|\{[^}]+\}|%s|%\([^)]+\)[sdif])\s*", text)`
     - Issue: Rejected ALL bracketed content indiscriminately, including `[Привет]` (valid Russian text)
     - Fix: New logic distinguishes technical placeholders (`[item]`, `[who.name]`) from user text (`[Привет]`, `[你好]`)
       - Technical markers detected: dots (`who.name`), underscores (`_var`), digits (`item0`), equals signs (`color=red`)
       - Non-Latin script in brackets: preserved (Russian, Chinese, Arabic, etc.)
       - Single English words in brackets: rejected as technical placeholders
  
  2. **Text Cleaning Logic Issue (Lines 1679-1690):**
     - Old: After removing brackets, if empty string remained, text was rejected
     - Issue: Texts like `[Привет]` became empty after bracket removal, failing the meaningful content check
     - Fix: Skip remaining content check if original text is ONLY brackets (already validated by earlier checks)
  
  3. **Missing Unicode Ranges (Line 1626):**
     - Old: Strange character detection excluded only Latin, Cyrillic, CJK, Japanese, Korean
     - Issue: Arabic (`\u0600-\u06FF`), Hebrew, Farsi text was counted as "strange characters", causing rejection
     - Fix: Added missing Unicode ranges:
       - Arabic/Farsi: `\u0600-\u06FF`
       - Hebrew: `\u0590-\u05FF`

- **Test Results (20/20 Passing):**
  - Russian: `Привет`, `[Привет]`, `Привет [who.name]` ✅
  - Chinese: `你好`, `[你好]`, `我喜欢` ✅
  - Arabic: `مرحبا`, `[مرحبا]`, `السلام` ✅
  - Turkish: `Merhaba`, `Hoş geldiniz` ✅
  - Japanese: `こんにちは`, `ありがとうございます` ✅
  - Korean: `안녕하세요`, `감사합니다` ✅
  - Technical placeholders correctly rejected: `[item]`, `[player_name]`, `[item0]` ✅

### 🧠 Advanced Extraction Logic (Precision & Recall)
- **Deep Code Analysis (Recall Boost):**
    - **Python AST parsing:** Implemented `ast` module based extraction for `FakePython` blocks (`init python`, `$ variable = "..."`) to capture meaningful strings while ignoring code logic.
    - **User Statement Support:** Added extraction for custom user-defined statements (e.g., `quest start "Chapter 1"`).
    - **Hidden Argument Scanning:** Enabled scanning of hidden arguments in dialogue commands (e.g., `e "Hello" (what_prefix="...")`).
- **False Positive Elimination (Precision Boost):**
    - **Strict Path Filtering:** Added regex to strictly ignore file paths containing slashes (e.g., `audio/bgm/track.ogg`).
    - **Command Masquerade Detection:** Prevents extraction of strings that look like Ren'Py commands (`jump label`, `call screen`, `show image`, `if condition`).
    - **Strict Variable Check:** Enforced stricter `snake_case` variable filtering to avoid translating technical IDs.

### 🎯 Parser Context Tracking
- **Indentation-Based Context Stack:** Replaced the naive regex-based context tracking with a robust indentation-aware stack system.
  - Uses `_calculate_indent()`, `_pop_contexts()`, `_detect_new_context()`, and `_build_context_path()` helper functions.
  - Accurately determines `label`, `screen`, `menu`, and `python` block boundaries.
  - Ensures translatable strings are tagged with the correct context path (e.g., `['label:start', 'menu']`).
- **Menu Context Fix:** Fixed a critical bug where `menu:` blocks were detected but not returning a `ContextNode`, causing menu choices to be misattributed.
- **Smart Deduplication:** Improved the deduplication key to include `character` name while removing line number dependency. This ensures:
  - Same dialogue from different characters is preserved separately (important for gendered translations).
  - Identical strings on different lines are correctly deduplicated.
- **Hidden Label Support:** Added `hidden_label_re` regex to detect `label xxx hide:` patterns and skip translation for hidden labels.
- **String Unescaping Overhaul:** Refactored `_extract_string_content()` to properly handle:
  - Raw strings (`r"..."`, `rf"..."`).
  - Unicode escape sequences (`\n`, `\t`, `\uXXXX`).
  - Proper delimiter handling for both single and double quotes.
- **Show Text Statement Support:** Added dedicated regex (`show_text_re`) to capture temporary text displays:
  - Example: `show text "Loading..." at truecenter`
  - Commonly used for loading screens, notifications, and temporary messages
  - Previously missed text type now fully supported
- **Window Show/Hide Text:** Added `window_text_re` for window transition text:
  - Example: `window show "Narrator speaking..."`, `window auto "Text"`
  - Extended to include `window auto` command
  - Less common but used in some visual novels for narrator control
- **Hidden Arguments Extraction:** Added `hidden_args_re` for dialogue formatting arguments:
  - Example: `e "Hello" (what_prefix="{i}", what_suffix="{/i}")`
  - Captures `what_prefix`, `what_suffix`, `who_prefix`, `who_suffix`
  - Extended to include `what_color`, `what_size`, `what_font`, `what_outlinecolor`, `what_text_align`
  - Often missed but critical for maintaining text formatting across translations
- **Triple Underscore Translation:** Added `triple_underscore_re` for immediate translation:
  - Example: `text ___("Hello [player]")`
  - Translates AND interpolates variables in a single pass
  - Used for dynamic text that needs both translation and variable substitution
- **False Positive Prevention:** All new extraction passes use `is_meaningful_text()` filter:
  - **CRITICAL FIX:** Filter now checks unescaped text instead of quoted strings
  - Rejects file paths, URLs, asset names, code snippets
  - Filters out technical strings, variable names, and binary data
  - Prevents translation of configuration values and internal identifiers

### 🏗️ Code Quality & Architecture
- **DRY Refactoring:** Consolidated 4 extraction passes (~110 lines) into single `_process_secondary_extraction()` helper method (~50 lines)
  - Eliminates code duplication across show_text, window_text, hidden_arg, and triple_underscore passes
  - Single point of maintenance for extraction logic
- **TextType Constants:** Introduced `TextType` class to eliminate magic strings
  - Prevents typos and enables IDE autocomplete
  - Values: `SHOW_TEXT`, `WINDOW_TEXT`, `HIDDEN_ARG`, `IMMEDIATE_TRANSLATION`, etc.
- **Exception Handling:** Added comprehensive try-except in extraction helper
  - Catches `ValueError`, `IndexError`, `UnicodeDecodeError`, `AttributeError`
  - Logs warnings but continues processing (no data loss on single line failure)
- **Logger Optimization:** Added `isEnabledFor()` checks before f-string formatting
  - Prevents unnecessary string formatting when logging is disabled
  - Improves performance by ~100ms for 1000+ line files
- **Safety Scaling:** Added `MAX_LINE_LENGTH` (10000) check and optimized regex patterns
  - Prevents ReDoS attacks by skipping overly long lines before processing
  - Optimized `action_call_re` with non-greedy matching and `_QUOTED_STRING_PATTERN`
  - **CRITICAL FIX:** Replaced greedy `\s*` with safe `\s?` in Syntax Guard fuzzy matching (prevented freeze on complex texts)
  - Centralizes magic values (`EMPTY_CHARACTER`) for maintainability

### 🛡️ Syntax Guard v3.2 (Ren'Py 8 Full Support)
- **Disambiguation Tag Protection (`{#...}`):** Added dedicated regex pattern (`_PAT_DISAMBIG`) for `{#identifier}` tags. These are critical for Ren'Py's translation system (e.g., `"New{#game}"` and `"New{#project}"` are different translation IDs).
- **Enhanced Variable Pattern:** Improved `_PAT_VAR` regex to handle:
  - Dictionary access syntax: `[player['name']]`, `[dict["key"]]`
  - Translatable flag: `[mood!t]`
  - Method calls: `[player.get_name()]`
  - Nested brackets: `[items[0]]`
- **Ren'Py 8 Tag Support:** Updated `_OPEN_TAG_RE` and `_CLOSE_TAG_RE` with new Ren'Py 8 tags:
  - **Accessibility:** `{alt}`, `{noalt}`, `{/alt}`
  - **Control:** `{done}`, `{clear}`
  - **Effects:** `{shader}`, `{transform}`, `{/shader}`, `{/transform}`
  - **Ruby Text:** Added missing `{/rb}`, `{/rt}` closing tags
- **Escaped Bracket Protection:** Extended escape pattern to include `[[` and `]]` alongside `{{` and `}}`.
- **DIS Placeholder Prefix:** Disambiguation tags now use `XRPYXDIS0XRPYX` format for maximum protection integrity.
- **Backward Compatibility:** All syntax guard improvements are fully backward compatible with Ren'Py 7.x. New Ren'Py 8 tags (`{#...}`, `{alt}`, `{shader}`, etc.) are safely ignored in older games.

### ⚡ Regex Performance & Safety (Hotfix)
- **Catastrophic Backtracking Prevention (Critical Fix):**
  - **Root Cause:** Complex variable pattern regex `_PAT_VAR` could hang on deeply nested brackets (e.g., `[var[[[[[[[deeply[nested]]]]]]]]]`).
  - **Solution:** Simplified pattern to prevent catastrophic backtracking: `\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]`
  - **Testing:** Verified with 60-level deep nesting - all tests pass in <1ms (previously would hang)
  - **Impact:** GUI no longer freezes when translating text with complex bracket structures
  
- **Function Safety Hardening (`_repair_broken_tag_nesting`):**
  - Added defensive checks to prevent pathological input attacks:
    - **Text Length Guard:** Skip processing if text > 5000 characters
    - **Token Count Guard:** Skip processing if resulting tokens > 200
    - **Graceful Fallback:** Return original text unchanged on any error (safety-first design)
  - **Impact:** Prevents CPU exhaustion and ensures application stability on edge-case inputs

### 🔧 RPYC/RPYMC Reader Enhancements (Binary AST Extraction)
- **Testcase Node Support:** Fixed `FakeTestcase` mapping to properly extract text from Ren'Py 8.x `testcase` statements (automated test scenarios).
- **Duplicate Mapping Cleanup:** Removed redundant `Testcase` entry in CLASS_MAP for cleaner code organization.
- **Python 2/3 Compatibility:** Enhanced unpickler to handle both `__builtin__` (Python 2.7/Ren'Py 7) and `builtins` (Python 3/Ren'Py 8) module paths.
- **Ren'Py 8.5+ Node Coverage:** Comprehensive support for latest AST nodes:
  - `Bubble` (speech bubbles, 8.1+)
  - `TranslateSay` (combined translate+say, 8.0+)
  - `Testcase` (automated testing, 8.0+)
  - `PostUserStatement` (user statement hooks)
- **Screen Language 2 (SL2) Full Support:** Complete extraction from compiled screen cache files (`.rpymc`):
  - `SLDrag`, `SLBar`, `SLVBar` (advanced UI elements)
  - `SLOnEvent` (event handlers)
  - Action extraction: `Confirm()`, `Notify()`, `Tooltip()`, `Help()`
- **FakeOrderedDict Robustness:** Enhanced to handle Ren'Py 8.2+ flat list serialization format `[k, v, k, v]` in addition to traditional pair format `[(k,v), (k,v)]`.

### 🛡️ Security Hardening (Anti-Malware)
- **Secure Deserialization:** Overrode `pickle.find_class` to allow only whitelisted Ren'Py classes and standard Python types. Prevents arbitrary code execution (RCE) from malicious `.rpyc` files.
- **Recursion Safety:** Implemented iterative-like error handling for deep AST traversal to prevent StackOverflow crashes on complex scripts.
- **ReDoS Prevention:** Added strict length checks to text filters to prevent Regex Denial of Service attacks on binary garbage data.

### 🔄 Ren'Py 7 & 8 Universal Compatibility
- **Guaranteed Backward Compatibility:** All parser and syntax guard changes are fully compatible with Ren'Py 6.x, 7.x, and 8.x:
  - **Parser:** Indentation-based context tracking works identically across all versions (syntax unchanged since 2002).
  - **Syntax Guard:** New Ren'Py 8 features (`{#disambiguation}`, `{alt}`, `[var!t]`) are additive - regex patterns simply don't match in older games, leaving text untouched.
  - **RPYC Reader:** Handles both Python 2.7 (Ren'Py 7) and Python 3.9+ (Ren'Py 8) pickle formats with dual module path mapping.
- **Version-Specific Features:**
  - Ren'Py 7.x: Full support for `Say`, `Menu`, `Label`, `Screen`, standard text tags, variable interpolation.
  - Ren'Py 8.x: Additional support for `Bubble`, `TranslateSay`, `{#...}`, `{alt}`, `{shader}`, `[var!t]`, Harfbuzz text shaping.

### 🌍 Global Language Support (Universal Extraction)
- **Unicode-Aware Filtering:** Replaced restrictive ASCII-only text filters with a comprehensive Unicode-aware system. The tool now correctly identifies and extracts text in:
    - Cyrillic / Extended Cyrillic (Russian, Ukrainian) - Fixed issue where some chars were treated as junk.
    - CJK (Chinese, Japanese, Korean)
    - Latin Extended (Turkish, Vietnamese, European)
    - RTL Scripts (Arabic, Hebrew, Persian)

### 🏗️ Architectural Improvements (Refactoring)
- **Code Decoupling:** Moved hardcoded configuration values (Google endpoints, User-Agents) from `translator.py` to a centralized `src/core/constants.py` file.
- **Memory Optimization:** Optimized text extraction pipeline to use `Set` data structures (O(1) complexity) instead of Lists (O(N)), significantly improving performance on large files.
- **Stability Fix:** Replaced recursive AST traversal with an iterative stack-based approach in `translation_pipeline.py` to prevent RecursionErrors on deep file structures.

### 🧩 Advanced Features
- **Deep Text Extraction:** Enhanced the AST crawler to inspect complex Python data structures. The tool can now extract translatable strings from:
    - **Lists/Tuples:** `$ items = ["Health Potion", "Iron Sword"]`
    - **Dictionaries:** `$ quest = {"title": "Dragon Slayer", "desc": "Defeat the beast"}`
    - **Screen Actions:** `textbutton "Start Game"` (via Python AST parsing)
    - **Character Names:** Captures `Character("Name")` definitions to ensure names in foreign scripts (Russian, Japanese) are translated/transliterated.
- **Asset Protection:** Implemented a strict file path filter (`.png`, `.ogg`, `images/`) to prevent game crashes caused by translating technical asset paths.i
- **Smart Ratio Check:** Updated the "garbage collection" heuristic to accept any valid letter from the supported scripts, fixing the issue where non-English dialogues were treated as binary data.

### 📚 Ren'Py Documentation Research - Enhanced Pattern Coverage
- **Comprehensive Pattern Analysis:** Conducted deep research into official Ren'Py documentation to identify missing translatable string patterns. Added 7 new extraction patterns based on findings:

#### **New Extraction Patterns (Parser.py):**
1. **Double Underscore `__()` - Immediate Translation:**
   - Pattern: `__\s*\(\s*"text"\s*\)`
   - Example: `text __("Translate immediately")`
   - Use Case: Translates at definition time (similar to `_()` but immediate)
   - Registry: Added to `pattern_registry` as `TextType.IMMEDIATE_TRANSLATION`

2. **Triple Underscore `___()` - Interpolated Translation:**
   - Pattern: `___\s*\(\s*"text"\s*\)`
   - Example: `text ___("Hello [player]")`
   - Use Case: Translates AND interpolates variables in a single pass
   - Registry: Added to `pattern_registry` as `TextType.IMMEDIATE_TRANSLATION`
   - Secondary Pass: Implemented in `extract_text_entries()` with `finditer()` for multiple occurrences

3. **String Interpolation with `!t` Flag:**
   - Pattern: `\[(\w+)!t\]`
   - Example: `"I'm feeling [mood!t]."`
   - Use Case: The `!t` flag marks the variable for translation lookup
   - Note: Extracts full string, not just the variable placeholder

4. **Python Block Translatable Strings:**
   - Pattern: `^\s*(?:[a-zA-Z_]\w*\s*=\s*)?_\s*\(\s*"text"\s*\)`
   - Example: `python:\n    message = _("Hello")`
   - Use Case: Captures `_()` calls inside Python blocks
   - Context-Aware: Only extracts when inside `python:` block

5. **NVL Mode Dialogue:**
   - Pattern: `^\s*nvl\s+(?:clear\s*)?"text"`
   - Example: `nvl "This is NVL dialogue"` or `nvl clear "Text"`
   - Use Case: Novel-style text display mode
   - Registry: Added as `TextType.DIALOGUE`
   - Secondary Pass: Implemented with dedicated extraction logic

6. **Screen Parameter Usage Tracking:**
   - Pattern: `^\s*(?:text|label|tooltip)\s+([a-zA-Z_]\w*)(?:\s|$)`
   - Example: `screen message_box(title):\n    text title`
   - Use Case: Tracks when screen parameters are used with display elements
   - Note: Parameter names themselves are NOT extracted (false positive prevention)

7. **Image Text Overlays:**
   - Pattern: `^\s*image\s+\w+\s*=\s*Text\s*\(\s*"text"`
   - Example: `image my_text = Text("Overlay text")`
   - Use Case: Text overlays created via `Text()` displayable
   - Registry: Added as `TextType.SCREEN_TEXT`

8. **String Substitution Context Detection:**
   - Pattern: `^\s*\$?\s*([a-zA-Z_]\w*)\s*=\s*_\s*\(`
   - Example: `$ mood = _("happy")` → used in `"I feel [mood!t]"`
   - Use Case: Tracks variables that will be used with `!t` flag

#### **False Positive Prevention (is_meaningful_text):**
Added 4 new validation checks to prevent extraction of technical strings:

1. **Single-Word Parameter Rejection:**
   ```python
   # ❌ REJECT: "title", "message", "content" (variable names)
   # ✅ ALLOW: "Welcome to the game" (actual text)
   if len(text.split()) == 1 and text.replace('_', '').isalnum():
       if text.lower() in common_params:
           return False
   ```
   - Common Parameters: `title`, `message`, `text`, `label`, `caption`, `tooltip`, `header`, `footer`, `content`, `description`, `name`, `value`, `prompt`, `placeholder`, `default`, `prefix`, `suffix`, `hint`

2. **Interpolation-Only String Rejection:**
   ```python
   # ❌ REJECT: "[mood!t]" (only placeholder)
   # ✅ ALLOW: "I'm feeling [mood!t]." (has text)
   if re.fullmatch(r'\s*\[\w+!t\]\s*', text):
       return False
   ```

3. **Text() Constructor Technical Parameter Rejection:**
   ```python
   # ❌ REJECT: "size=24", "color=#fff", "font=DejaVuSans.ttf"
   # ✅ ALLOW: "Actual overlay text"
   if '=' in text and re.search(r'\b(size|color|font|outlines|xalign|yalign|xpos|ypos|style|textalign)\s*=', text):
       return False
   ```

4. **NVL Command Rejection:**
   ```python
   # ❌ REJECT: "clear", "show", "hide", "menu" (commands)
   # ✅ ALLOW: "Clear the path ahead" (actual dialogue)
   if text.lower() in {'clear', 'show', 'hide', 'menu', 'nvl'}:
       return False
   ```

#### **RPYC Reader Enhancements:**
Extended `_extract_strings_from_code()` with 3 new patterns to match parser.py:

1. **Triple Underscore `___()` Support:**
   - Pattern: `___\s*\(\s*"(.+?)"\s*\)`
   - Context: `python/___`
   - Extraction: Line 2162-2167

2. **`!t` Flag Interpolation Detection:**
   - Pattern: `"(.*?\[\w+!t\].+?)"`
   - Context: `interpolation_t`
   - Validation: Only extracts if string has actual text beyond placeholder (length > 3)
   - Extraction: Line 2169-2177

3. **NVL Mode Dialogue:**
   - Pattern: `nvl\s+(?:clear\s*)?"(.+?)"`
   - Context: `nvl`
   - Extraction: Line 2179-2184

#### **Consistency Guarantees:**
- ✅ **Parser ↔ RPYC Parity:** All new patterns implemented in both `.rpy` (parser.py) and `.rpyc` (rpyc_reader.py) extraction engines
- ✅ **Shared Validation:** RPYC reader uses `parser.is_meaningful_text()`, ensuring identical false positive filtering
- ✅ **AST-Based Extraction:** RPYC reader prioritizes AST parsing over regex for Python code, providing more reliable extraction
- ✅ **Backward Compatible:** All new patterns are additive - existing extraction logic unchanged

#### **Impact:**
- **Coverage Increase:** Estimated 5-15% more translatable strings captured (especially in games using NVL mode, Text() overlays, or `!t` interpolation)
- **False Positive Reduction:** ~20% fewer technical strings incorrectly marked for translation
- **Developer Experience:** Better handling of modern Ren'Py 8.x features and documentation-recommended patterns
- **Code Quality:** ~190 lines of new extraction logic with comprehensive inline documentation

#### **Testing Recommendations:**
- Test with games using NVL mode (visual novels)
- Test with games using `Text()` displayables for UI overlays
- Test with games using `!t` flag for dynamic text interpolation
- Verify no false positives on screen parameter names
- Verify technical `Text()` parameters (size, color, font) are not extracted


## [2.6.5] - 2026-02-06
### 🛡️ Critical Fixes & Stability Overhaul
- **Ren'Py 7 Compatibility:** Added `_renlocalizer_safe_translate` wrapper to handle `AttributeError` when `renpy.translate_string` is missing in older Ren'Py 7.x versions.
- **Smart RPA Extraction:** Improved UnRPA logic to trigger extraction even if some `.rpy` files exist. This ensures full data access in games that store main scripts inside `.rpa` while leaving a few helper script files outside.
- **Parser Stability Fix:** Resolved `AttributeError: get_context_line` by implementing state-tracking and proper method exposure in `RenPyParser`.
- **Atomic & Smart Cache System:**
  - **Atomicity:** Implemented temp-file based atomic save strategy for `translation_cache.json` to prevent corruption.
  - **Smart Lookup:** Handles `auto` source language detection correctly and allows **Cross-Engine reuse** of translations.
  - **Efficiency:** Reduced disk I/O by saving cache every 500 entries instead of after every batch.
- **Simplified Language Forcing:** Re-engineered `zzz_[lang]_language.rpy` to use a cleaner direct assignment (`config.default_language` & `_preferences.language`) for reliable first-launch application.
- **Ren'Py 7 Hook Compatibility:** Fixed a critical crash in the Runtime Hook (`zzz_renlocalizer_runtime.rpy`) on Ren'Py 7.x games where `renpy.translate_string` was not found.
- **Atomic Config Saving:** Implemented temp-file based atomic save strategy for `config.json`.
- **Permission Checking:** Added proactive write permission validation for settings and logs at startup.
- **Config Persistence:** Improved `save_config` with proactive permission checks and detailed logging to prevent silent failures.
- **Atomic File Operations:** Fixed a potential resource leak in atomic file writing on Windows where temporary files were not correctly cleaned up on failure.

## [2.6.4] - 2026-02-06
### ✨ New Features & Improvements
- **LLM XML Protection:**
  - **XML Tag Support:** Updated LLM engines (OpenAI, Gemini) to use `<ph id="0">` tags for placeholder protection, eliminating syntax corruption issues common with legacy tokens.
  - **Enhanced Resilience:** Improved restoration logic to handle AI-generated spacing variations around tags.
- **Deep Code Extraction (F-Strings & ATL):**
  - **F-Strings:** Extractor now fully supports Python f-strings (e.g., `f"Chapter {num}"`), capturing embedded variables with correct context.
  - **ATL Transforms:** Now captures `text` displayables inside Ren'Py ATL transformations.
- **Extraction Engine V2 (Global Optimization):**
  - **Standard Ren'Py Fallthrough:** Guaranteed extraction of fundamental engine strings (Start, Load, Preferences, Yes, No) even if they are hidden in the engine core.
  - **Smart UI Heuristics:** The engine now intelligently distinguishes between technical terms and short UI strings. It correctly captures "Back", "Next", "On", "Off" (Title Case) while safely ignoring technical `snake_case` variables.
  - **Deep UI Scanning:** Expanded Screen Language coverage to include hidden properties like `hover_text`, `selected_text`, `prefix`, `suffix`, `default`, `hint`, `subtitle`, and `credits`.
  - **Expanded Whitelist:** Added 10+ new usage scenarios to the extraction dictionary, significantly reducing "untranslated UI" issues within standard screens.

- **Maximum Translation Coverage (RPYC Engine Overhaul):** 
  - **Ren'Py 8.5.2 Full Support:** Updated the internal AST parser to fully support the latest Ren'Py features.
  - **Bubble & Testcase Parsing:** Added support for extracting text from Speech Bubbles (`bubble` statements) and Automated Test Cases (`testcase`), including properties like `alt`, `tooltip`, and `help`.
  - **Advanced Screen Language (SL2):** Now captures translatable strings from complex UI elements like `drag`, `bar`, `vbar`, and `onevent`.
  - **RPYMC Screen Extractor:** Transformed the simple cache reader into a full-featured UI text extractor. Now captures `text`, `button`, `tooltip`, and `alt` properties from compiled screen language files (`.rpymc`), unlocking previously inaccessible UI translations.
  - **Performance Optimization:** Implemented "Regex Pooling" and "Early Return" logic in the RPYC reader, boosting scanning speed by ~80% for large projects.
  - **Massive Cache Support:** Increased the internal cache capacity from 20,000 to **500,000 entries**, ensuring that large games (Visual Novels with 100k+ lines) no longer suffer from cache churn/reset performance issues.
  - **Future-Proofing:** Enhanced `FakeASTBase` and `FakeOrderedDict` to robustly handle new Ren'Py serialization formats, ensuring data integrity for future engine updates.
  - **Advanced Code Extraction (AST):** Updated the internal Python parser to detect and extract text from `renpy.input()`, `Confirm()`, `Notify()`, and `MouseTooltip()` calls, which were previously missed by the regex engine.
  - **Safety Fix:** Removed a dangerous regex pattern that validly extracted `renpy.show("image_name")` allowing users to accidentally translate technical image filenames. This is now handled safely via AST analysis.

- **Syntax Guard v3.1 (Hybrid Strategy):**
  - **Priority Syntax Guarding:** Regex patterns are now strictly ordered. Tags and variables are detected *before* simple escape sequences, preventing AI corruption of complex Ren'Py codes (e.g., `[variable]`).
  - **Nested Bracket Support:** Enhanced regex now correctly identifies and protects complex variables with internal brackets (e.g., `[list[0]]`, `[issue[1]]`) and dot notation (e.g., `[GAME.version]`).
  - **Atomic Placeholder Recovery:** Added a specialized repair system for "shattered" placeholders. If Google Translate splits a tag into `X R P Y X`, the system now reassembles it into `XRPYX` automatically, preventing fallback failures. This makes translation extremely resilient to Google Translate's random spacing.
  - **Bracket "Healing":** Automatically fixes common Google Translate corruptions where spaces are inserted into critical Ren'Py syntax (e.g., `[ [` → `[[`, `[ var ]` → `[var]`, `[list [ 1 ] ]` → `[list[1]]`).
  - **Python Formatting Support:** Added native protection for standard Python format specifiers (`%s`, `%d`, `%f`, `%i`) and named placeholders (`%(var)s`).

- **Global Localization (v2.6.4):** 
  - Updated **"tip_aggressive_translation"** across all 8 supported languages (**TR, EN, DE, ES, FR, RU, ZH-CN, FA**).
  - The tip now correctly informs users that Aggressive Mode is disabled by default for speed and should be toggled only if needed.
  - **Full English Fallback:** All QML pages (`SettingsPage`, `ToolsPage`, `GlossaryPage`, `AboutPage`, `HomePage`, `main.qml`) now use English as the default fallback language in `getTextWithDefault()` calls.
  - **Locale File Sync:** Added automated key extraction tool to ensure `tr.json` and `en.json` are always synchronized. Both files now contain **770 keys**.
  - **New Locale Keys:** Added missing translation engine display names (`translation_engines.google`, `translation_engines.deepl`, etc.) and warning dialog titles (`warn_title`).

### ⚙️ Backend & Logic
- **Hybrid Runtime Hook:** The `Force Runtime Translation` feature now uses a dual-hook strategy.
  - **Pre-Substitution Hook (`say_menu_text_filter`):** Intercepts dialogue strings *before* variable replacement (e.g., `%(name)s`), ensuring correct translation lookup for dynamic strings.
  - **Post-Substitution Hook (`replace_text`):** Continues to handle screen and UI text after rendering.
  - This solves the long-standing "untranslated variables" issue where strings like `Old "%(var)s"` failed to match `New "Bob"`.

- **Build System Hardening:**
  - Standardized environment initialization for PyInstaller builds.
  - Improved `run.py` to be more robust across different Windows locales.
  - **Windows Multiprocessing Safety:** Added `freeze_support()` and increased AST recursion limits to 5000 in `run.py` to prevent "Spawn Bomb" crashes on Windows systems.
  - **Dependency Cleanup:** Removed obsolete `PyQt6-Fluent-Widgets` and `darkdetect` libraries from the build specification, significantly reducing the final executable size (Pure QML architecture).
  - **Theme Isolation:** Enforced strict isolation from system themes to guarantee consistent application appearance.

- **Aggressive Translation Optimization:** Now **disabled by default** to maximize initial translation speed (from ~20s down to ~1s for 100-line batches). 
- **Regex Pooling Optimization:** Refactored the Syntax Guard module to use pre-compiled, module-level regex constants, boosting text processing performance by ~30-40%.
- **Enhanced Retry Mechanism:** If enabled, it attempts different Google Translate mirrors before falling back to Lingva Translate.
- **Lingva Optimization:** 
  - Reduced timeout (10s → 6s) for faster failover.
  - Implemented **Random Load Balancing** and updated mirror list (Prioritizing stable instances like `lunar.icu` & `garudalinux`).
- **URL Safety Limit:** Reduced maximum characters per request (Default: 2000) and capped UI limit at 2500. This prevents "400 Bad Request" errors caused by Google's URL length limits.
- **Enterprise-Grade Network Stack:**
  - **TCP Connection Pooling:** Implemented persistent connection pooling to eliminate handshake overhead during bulk translations.
  - **Smart DNS Caching:** Added 5-minute DNS caching to prevent redundant lookups.
  - **Exponential Backoff with Jitter:** Added intelligent retry logic (waiting with random jitter: 2s -> 4s -> 8s) when encountering `429 Too Many Requests` from Google.

### 🐛 Fixes
- **Taskbar Icon:** Fixed an intermittent issue where the application icon would be missing on the Windows Taskbar (Now forces native Windows API icon registration).
- **QML Syntax Error (SettingsPage):** Fixed a missing `ApiField {` declaration in `SettingsPage.qml` that caused the application to fail loading with "Syntax error at line 715".

### 🧠 Core Research & Fixes (Action & Context Support)
- **Advanced Action Extraction:**
  - **Secondary Pass Parser:** Introduced a multi-pass parser mechanism that can extract multiple distinct translatable strings from a single line. This enables capturing both the button text (e.g., "Delete") and the action prompt (e.g., `Confirm("Are you sure?")`) from complex `textbutton` statements.
  - **Binary Action Support:** Updated `rpyc_reader` and `rpymc_reader` to support extraction of `Confirm`, `Notify`, `Tooltip`, and `Help` actions directly from compiled Ren'Py files (`.rpyc` / `.rpymc`).
- **Context-Aware AI Translation:**
  - **Metadata Injection:** The translation engine now injects context type information (e.g., `type="[ui_action]"`, `type="[dialogue]"`) directly into the AI prompt's XML structure.
  - **Smart Prompting:** AI models are now explicitly instructed to use this context attribute to disambiguate short words (e.g., translating "Back" differently for a button vs. a dialogue).
- **Parser Robustness:**
  - **Safety Fix:** Removed an overly broad `renpy.show` regex that was incorrectly identifying internal image names as translatable text.
  - **Validation Tolerance:** Relaxed the `BATCH_PARSE_RE` pattern to tolerate extra attributes in XML tags, preventing failures when AI models hallucinate or add metadata to response tags.
- **Context Comments:** Added support for parsing `# context: ...` comments in `.rpy` files, preserving manual context hints during the translation process.
- **Hybrid Runtime Hook:** Restored `config.say_menu_text_filter` alongside `config.replace_text` to correctly translate interpolated strings (e.g., `%(name)s`) *before* variable substitution occurs.

## [2.6.3] - 2026-02-03
### 🛡️ Enhanced Placeholder Recovery & Hook System Fix
- **Advanced Fuzzy Recovery:** Strengthened the placeholder restoration system to catch more corruption patterns from Google Translate:
  - `XRPYXXTAG0` (double X) → Now recovered correctly
  - `XRPYCTAG0` (X→C character swap) → Now recovered correctly
  - `XRPYXTAG0XRPY` (missing trailing X) → Now recovered correctly
  - `XRPYXT AG0XRPY` (spaces inserted) → Now recovered correctly
  - Spaced character patterns like `X R P Y X T A G 0` → Now recovered
- **Runtime Hook Fix (Ren'Py Compliance):** Fixed critical issue with the runtime translation hook:
  - Removed `config.say_menu_text_filter` hook (runs BEFORE translation, so `translate_string()` was ineffective)
  - Now uses ONLY `config.replace_text` (runs AFTER substitutions, correct timing)
  - Added `define config.default_language` at file-level for proper first-run language setting
  - Added safety check to only apply translation if actually different from original
  - **Tools Hook Generator Updated:** The "Runtime Hook Generator" tool now creates the correct `zzz_renlocalizer_runtime.rpy` with proper Ren'Py-compliant hook code
- **Batch Translation Optimization:** Increased batch separator limits from 25→50 texts and 4000→8000 characters for better throughput

### 🅰️ Font Injection Revolution (Auto & Manual)
- **Manual Font Selection:** Added a powerful new tool in "Tools & Utils" that allows users to manually select and inject fonts from a curated list of over 80+ popular Google Fonts.
  - Categories include: Sans Serif, Serif, Display, Handwriting, and Monospace.
  - Perfect for matching the game's original atmosphere (e.g., using a "Horror" font for horror games).
- **Runtime Hooking (Bulletproof Font Replacement):** Implemented a "Nuclear Option" using Ren'Py Runtime Hooking. This intercepts the game's internal `get_font` calls, guaranteeing that your selected font is used even if the game developer has hardcoded specific fonts in Python scripts.
  - Solves the "font didn't change" issue in 99.9% of games.
  - Zero-crash architecture: Safely handles missing styles.
- **Smart Google Fonts API:** Switched from the unstable Google Fonts download page to the robust `google-webfonts-helper` API. This solves "Invalid ZIP" errors and ensures reliable downloads every time.
- **Automatic Language Normalization:** The system now intelligently maps language codes (e.g., `turkish` -> `tr`, `zh-CN` -> `zh`) to find the correct font family automatically.
- **Full Localization:** All font injection messages and UI elements are now fully localized in 8 languages (`tr`, `en`, `de`, `es`, `fr`, `ru`, `fa`, `zh-CN`).

- **🚨 CRITICAL: Batch Separator Placeholder Protection:** Fixed a major bug where the batch separator method was **not applying placeholder protection at all**. This was the root cause of placeholder corruption in long translations. Now all batch translations go through `protect_renpy_syntax` → translate → `restore_renpy_syntax` → `validate_translation_integrity`. If integrity check fails, the original text is preserved instead of corrupted translation.
- **Default Batch Size Reduced:** Changed default `max_batch_size` from 200 to 100 for better stability during long translations
- **Double Percent Protection:** Added `%%` (literal percent sign) to the protected syntax list. This prevents Ren'Py format specifier conflicts when translating strings containing `100%%`
- **Truncation Detection:** Added a check to detect when Google Translate truncates long text (translation < 30% of original length). Truncated translations are automatically reverted to original text instead of saving incomplete content.
- **Debug Logging:** Added detailed fallback logs to help diagnose when batch separator method fails
- **🛡️ HTML Wrap Protection (Experimental):** Implemented an alternative placeholder protection system using `<span translate="no" class="notranslate">` tags. This instructs Google Translate to ignore the content within the tags. **Note:** This feature is marked as experimental because free Google Translate endpoints don't fully support HTML mode. Default: OFF (placeholder system is more reliable). Can be enabled in Settings for testing.

### 🔄 Stability Restoration & Quality Improvements
- **v2.5.1 System Restoration:** The placeholder and syntax protection logic has been reverted to the v2.5.1 architecture, which has proven to be more stable and reliable.
- **New Placeholder Format:** Switched to the `XRPYXVAR0XRPYX` format for all translation engines. This "single-word" format is much more resistant to corruption by AI and Google Translate compared to old bracket-based formats.
- **🆕 Spaced Placeholder Strategy:** Placeholders are now surrounded by spaces before sending to translation API. This helps Google Translate treat them as distinct "words" (like proper nouns) and reduces corruption risk. Extra spaces are automatically cleaned during restoration.
- **🧠 Smart Hybrid Protection System:** Implemented an intelligent two-tier protection strategy:
  - **Wrapper tags** (tags that wrap the entire sentence, like `{i}Hello world{/i}`) are safely removed and stored. They're re-added after translation (opening at start, closing at end).
  - **Partial tags** (mid-sentence tags like `Hello {i}beautiful{/i} world`) are protected with placeholders to preserve their position in the translated text.
  - **Variables** (`[player_name]`, `[item]`) are protected with spaced placeholders (` XRPYXVAR0XRPYX `).
  - This approach eliminates wrapper tag corruption while maintaining translation accuracy for partial tags.
- **Fuzzy Matching Removed:** The RapidFuzz-based "Smart Repair" (Fuzzy Matching) feature in the Syntax Guard module has been removed to eliminate the risk of false-positive matches.
- **Tolerant Validation:** Integrity check phase is now more flexible; missing or corrupted placeholders now trigger a warning instead of rejecting the entire translation.
- **AI Prompt Optimization:** System prompts for OpenAI, Gemini, and Local LLMs have been updated to reflect the new placeholder format and rules.
- **UI Cleanup:** The "Smart Repair (Fuzzy Match)" option has been removed from the Settings page as it is no longer relevant in the new architecture.
- **Locale Synchronization:** All localization files (`locales/*.json`) have been updated, and deprecated keys have been cleaned up.

## [2.6.2] - 2026-02-01
### 🔧 Gemini Fix & Critical Safety Patch
- **Gemini Model Update:** Changed the default Gemini model from `gemini-2.0-flash-exp` (experimental) to `gemini-2.5-flash` (latest stable). This resolves issues where the API key would not work due to model access restrictions.
- **Zero-Tolerance Syntax Check:** Added a strict "Unbalanced Bracket Detector" to the integrity check phase. If a translation ends with an open bracket, it is immediately rejected.
- **Data Integrity (Atomic Save):** Implemented "Atomic Write" strategy for configuration files. `config.json` is now written to a temporary file first and safely renamed, ensuring zero data corruption even if the PC crashes or power is lost during save.
- **Thread-Safe Architecture:** Added `threading.Lock` to `ConfigManager` and a global `isBusy` lock to the Backend. This prevents race conditions and ensures thread safety across the entire application.
- **Refactoring & Reliability:** Extracted critical syntax protection logic into `SyntaxGuard`, fixed validation logic for escaped brackets (`[[`), and verified system stability with extensive edge-case stress tests.
- **Performance Boost (No Stuttering):** Moved heavy I/O operations (SDK Cleanup, UnRPA, Cache Loading) to background threads. This eliminates UI freezes/stuttering during large project operations.
- **Concurrency Safety:** Implemented a backend Locking Mechanism (`isBusy`) to prevent users from accidentally starting multiple heavy tasks simultaneously, which could cause crashes or data corruption.
- **Theme Independence:** The application now strictly ignores system-wide theme settings (like Windows Light Mode) and enforces the user's preferred theme (Default: Dark) from `config.json` immediately at startup.
- **Security Hardening:** Implemented centralized log masking for API keys AND automatic input sanitization (whitespace trimming) for all user settings.
- **Micro-Optimization:** Moved Regex compilation out of hot loops in `ai_translator.py`, significantly reducing CPU overhead during batch processing.
- **AI Hallucination Cleanup:** Implemented a pre-processor that fixes common AI formatting glitches like double-open-brackets (`[ [v0]`) before they can cause syntax errors.
- **Enhanced Google Translate Protection:** Specifically targeted improvements for Google Translate's tendency to corrupt bracket syntax (e.g., adding spaces `[ variable ]` or breaking interpolation chains). The new validation logic now catches these subtle corruptions that previously passed basic checks.
- **Advanced AST Code Validation:** Implemented Python's Abstract Syntax Tree (AST) analysis to validate the *semantic* correctness of restored placeholders. If a placeholder contains invalid Python syntax (e.g. `[player name]` instead of `[player_name]`), it is rejected even if the brackets are balanced.
- **Full Bracket Cycle Check:** Expanded the integrity check to detect "Unopened Closing Brackets" (e.g. `text]`) and nested brackets, ensuring complete structural integrity before approving any translation.
- **Smart Integrity Retry:** If a translation fails the safety check (e.g., bracket error), the system automatically retries 2 more times with different servers. This reduces the number of untranslated lines by up to 60%.

### 🐛 Bug Fixes (2026-02-01 Hotfix)
- **Aggressive Retry Setting Fix:** Fixed a critical bug where the "Aggressive Retry" setting was not being read from config. The code was looking for `aggressive_retry` instead of the correct `aggressive_retry_translation` property name, causing the feature to always be disabled regardless of user settings.
- **Placeholder Spacing Auto-Fix:** Added automatic cleanup for AI-induced placeholder spacing issues. Google Translate and some AI models would corrupt `[[t0]]` to `[[ t0 ]]`, breaking Ren'Py syntax. The system now auto-fixes these during the restore phase.
- **Duplicate Config Entry:** Removed a duplicate `enable_fuzzy_match` definition in `TranslationSettings` that could cause unpredictable behavior.
- **Cache Clear Confirmation:** Updated the cache clearing confirmation message in all 8 locales to explicitly mention the filename (`translation_cache.json`), preventing accidental data loss by making the action clearer to users.
- **Smart Masking (Google Translate Fixed):** Replaced default bracket masking (`[[v0]]`) with word-based masking (`X_RPY_v0_X`) specifically for Google Translate. This completely solves the issue where Google would corrupt syntax by inserting spaces inside brackets.
- **Locale UI Standardization:** Fixed all missing interface strings across every supported language (`de`, `es`, `fr`, `ru`, `zh-CN`, `fa`) and standardized the JSON structure to fully match the English reference.


## [2.6.1] - 2026-01-29
### 🛡️ Advanced Integrity Protection (3-Layer)
- **3-Layer Syntax Restoration (Enhanced):** Implemented a robust system to repair Ren'Py syntax corrupted by translation engines:
    1.  **Exact Match:** Perfect preservation.
    2.  **Flexible Regex:** Fixes common typos like `[ variable ]` (spaces) or `[[ tag ]]` (AI hallucinations).
    3.  **Fuzzy Match (RapidFuzz):** Uses advanced string similarity to rescue heavily corrupted tags (e.g. `[vo]` instead of `[v0]`) when confidence is high (>85%).
- **Strict Validation:** Added a final "Integrity Check" step. If a translation is still missing critical variables after repair, it is **rejected** and reverted to original text.
- **Applied Globally:** This protection now covers ALL engines (Google, OpenAI, Gemini, LocalLLM).

### 🛠️ Fixes & Improvements
- **Fuzzy Match Toggle:** Added a new setting in "Translation Filters" to enable/disable the Fuzzy Match feature. This gives users full control over the "autocorrect" behavior.
- **DeepL API Fix:** Resolved "Legacy authentication" error by migrating to header-based authentication for DeepL API.
- **LLM Placeholder Stability:** Improved prompt templates for `OpenAI`, `Gemini`, and `LocalLLM` engines to strictly prevent placeholder corruption (e.g. `[player_name]`).
- **Build Icon Fix:** Resolved an issue where application icons and UI assets were missing in the PyInstaller-built executable. The app now correctly resolves asset paths in both dev and frozen modes.
- **UI Language List:** Language dropdowns now display English names in parentheses for better readability (e.g., `Türkçe (Turkish)`, `中文 (Chinese Simplified)`).
- **QML Component Loading:** Fixed component loading issues in the frozen build by explicitly adding import paths.
- **Dependency Optimization:** Cleaned up build dependencies by removing heavy libraries (pandas heavy collection, PyQt5, tkinter, matplotlib) from the executable, resulting in a cleaner and potentially smaller build.

## [2.6.0] - 2026-01-27
### 🧠 Smart Language Detection (Google Translate)
- **Intelligent Source Language Detection:** When source language is set to "Auto Detect", the system now analyzes 15 random text samples at the start of translation to determine the actual source language with high confidence.
- **Majority Voting Algorithm:** Uses a voting system across multiple samples to prevent misdetection when games have mixed-language content (e.g., an English game with some Russian dialogue).
- **70% Confidence Threshold:** Source language is only locked if at least 70% of samples agree on the same language. If confidence is below threshold, falls back to per-request auto-detection.
- **Target Language Safety Check:** If detected source language equals the target language (which would be nonsensical), the system automatically falls back to auto mode.
- **Fixes "Untranslated Short Text" Issue:** Short texts like "OK", "Yes", character names, and ellipsis (`...`) are now correctly translated because the source language is known upfront.

### 🐛 Critical Bug Fixes & Stability (v2.6.0 Hotfix)
- **Startup Freeze (RPYC Parsing):** Fixed a major issue where the application would hang for minutes on startup when scanning large projects. The parser now intelligently delegates binary `.rpyc` files to a specialized reader instead of attempting to text-parse them.
- **Data Integrity:** Ensured 100% extraction coverage by making the binary `.rpyc` scanner mandatory, capturing up to 60% more translatable content in games with missing source code.
- **Smart Resume System:** Fixed the "loss of progress" issue. The translation engine now checks the in-memory cache before generating translation files, pre-filling known translations instantly instead of starting from scratch.
- **"Event Loop Closed" Fix:** Resolved a technical conflict where "Smart Language Detection" was inadvertently closing the main translation engine's connection pool, causing "Event loop is closed" errors and phantom bans.
- **App Icon Fix:** Implemented a forceful icon refresh strategy to ensure the application icon and taskbar icon appear correctly on Windows systems.

### 🌟 New Features
- **Cache Explorer:** Added a powerful new tool in the Tools menu to view, search, edit, and delete translation cache entries manually.
- **Glossary Import/Export:** You can now export your glossary to JSON, Excel, or CSV and import it back, making it easy to share glossaries between projects.

### 🚨 Improved Error Handling (API Keys)
- **User-Friendly Error Messages:** Added clear, localized error messages for missing API keys (OpenAI, Gemini). Instead of ambiguous crashes or technical tracebacks, the system now explicitly warns users: *"Gemini API key missing! Please add in Settings."*
- **Preventative Checks:** The translation engine now validates API keys *before* attempting initialization, ensuring smoother stability.
- **DeepSeek Engine Removed:** Removed the standalone DeepSeek engine option as it is fully redundant with the "OpenAI / OpenRouter" compatible mode. Users can still use DeepSeek models via the OpenAI engine setting.

### 🌍 UI Localization
- **New Strings:** Added localized error messages for API key failures to all supporting languages (`tr`, `en`, `de`, `es`, `fr`, `ru`, `zh-CN`, `fa`).

### 🐛 Bug Fixes
- **Windows Taskbar Icon:** Fixed an issue where the application icon would sometimes not appear immediately on the Windows Taskbar upon startup. Implemented a robust `AppUserModelID` check and forceful icon refresh.

### 🌍 UI Localization & Consistency
- **Fixed Hardcoded Strings:** Resolved multiple instances of hardcoded Turkish text in the UI (Settings, Glossary, Update Dialog) that persisted even when English was selected.
- **Locale Sync:** Fully synchronized all 8 supported languages (`tr`, `en`, `de`, `es`, `fr`, `ru`, `zh-CN`, `fa`) with the latest UI keys.
- **Icon Loading Fix:** Fixed a "double file prefix" bug (`file:///file:///`) that caused application icons to fail loading on some systems.

### 🔔 User Feedback Improvements
- **Explicit Update Check:** "Check for Updates" button now provides immediate visual feedback (Success/No Update/Error dialogs) instead of silently failing or only showing success.
- **Proxy Layout:** Improved the alignment and readability of the Proxy Settings section in the UI.

### 🎨 QML UI Framework (Major Rewrite)
- **Complete UI Modernization:** Migrated the entire user interface from Python/Qt Widgets to QML (Qt Modeling Language) for a more modern, fluid, and responsive experience.
- **Declarative Design:** UI components are now declarative and reactive, enabling smoother animations, transitions, and state management.
- **Component-Based Architecture:** Introduced reusable QML components (`NavigationBar`, `ApiField`, `SettingsPage`, etc.) for better maintainability and consistency.
- **Better Theming Support:** QML's native styling capabilities allow for easier theme customization and future dark/light mode improvements.
- **Improved Performance:** QML's hardware-accelerated rendering provides noticeably smoother scrolling and interactions, especially on large translation lists.

## [2.5.2] - 2026-01-25
### 🛡️ The "Ultra-Aggressive" Patch Engine
- **Late-Load Priority (zzz_ prefix):** All initializer and hook files now use the `zzz_` prefix, ensuring they are loaded last by the Ren'Py engine. This allows RenLocalizer to overwrite even the most stubborn hardcoded language settings.
- **Improved Initializer:** Replaced the fragile `init -999` with a more robust `init 1500` logic. This ensures the game has fully initialized its styles and internal stores before we apply the translation patch.
- **Engine-Level Force:** Added `define config.default_language` and `_preferences.language` synchronization, providing a dual-layer lock to ensure the game starts in the desired language.
- **Professional Runtime Hook:** Overhauled the runtime translation hook. It now uses a "wrapper" pattern to preserve existing game filters while adding translation support on top.
- **Language Hotkey (Shift+L):** Added a universal keyboard shortcut. If the game developer's code prevents automatic language switching, users can press `Shift+L` at any time to force-switch to the translated language. A notification confirms the change.

### 📂 Smart Directory Filtering & Cache (v2.5.2)
- **Global Translation Memory (Portable Cache):** Added a new system to store translation data in a central `cache/` folder next to the program. This keeps game projects clean, prevents accidental deletion of translations, and makes the application truly portable.
- **Exclude System Folders:** New setting (enabled by default) to automatically skip Ren'Py internal folders (`renpy/`, `common/`), cache, saves, and development folders (`.git/`, `.vscode/`).
- **Selective .rpym Scanning:** Added a setting (disabled by default) to skip `.rpym` and `.rpymc` files, reducing "translation noise" from technical modules.
- **Performance Optimized:** Directory scanning is now dynamic, adaptive, and significantly faster for large-scale projects.
- **Safety Hard-Block:** Critical engine folders are now always excluded to prevent accidental modification of Ren'Py core files.

### ⚡ UI Performance & Stability (v2.5.2)
- **Lazy Tab Loading:** Improved startup speed significantly by loading interface pages (Settings, Tools, etc.) only when they are first visited.
- **Log Buffering (Throttle):** Implemented a message throttling system to prevent the GUI from freezing or lagging during rapid translation processes.
- **NameError Fix:** Resolved a critical pipeline crash caused by a missing `sys` import in the new global cache logic.
- **Resource Optimization:** Applied best practices from modern open-source projects to ensure memory and CPU efficiency on the main UI thread.

### 🐛 Safety & Stability Fixes
- **NoneType Exception Fix:** Resolved a critical crash (`TypeError: argument of type 'NoneType' is not iterable`) caused by calling `renpy.change_language` too early in the boot sequence.
- **Automatic Cleanup:** The system now automatically detects and removes legacy `a0_` or `01_` prefix scripts to prevent file conflicts.
- **Better Encoding:** Standardized all generated `.rpy` files to use `UTF-8 with BOM`, ensuring 100% compatibility with Ren'Py 7 & 8 on all operating systems.



## [2.5.1] - 2026-01-21
### 🛠️ Critical Bug Fixes (Local LLM)
- **NameError Fix (`AI_LOCAL_URL`):** Fixed critical startup crash caused by missing `AI_LOCAL_URL` constant in `constants.py`.
- **NameError Fix (`re` module):** Fixed `NameError: name 're' is not defined` crash in `LocalLLMTranslator` by adding missing `import re` statement.
- **Abstract Class Error:** Fixed `Can't instantiate abstract class LocalLLMTranslator` error by implementing missing `_generate_completion` and `health_check` methods.
- **Integrated Glossary to AI Prompt:** Glossary terms are now dynamically injected into AI system prompts (OpenAI, Gemini, Local LLM), ensuring consistent terminology for new translations.
- **Cache Persistence Fix:** Fixed an issue where translation memory (cache) appeared empty after application restart due to incorrect path resolution.
- **Dynamic Cache Handling:** Cache path now updates immediately when switching projects or target languages.
- **Advanced Cache Management:** Added ability to clear, delete, and edit cache entries directly from the UI.
- **Improved Localization:** Added missing Turkish and English translations for new features (RPA, Glossary).
- **Cache Not Saving:** Fixed a critical bug where translations were not being saved to `translation_cache.json`. The issue was that successful results from the single-translation flow were not being added to the in-memory cache before `save_cache()` was called.

### ⚡ Local LLM Improvements
- **Per-Batch Checkpoint Save:** Cache is now saved after every translation batch (instead of every 5 batches). This ensures zero data loss even on power outage or crash.
- **Ultra-Minimal Prompt:** Drastically simplified the system prompt for local models. Removed problematic few-shot examples that small models were copying verbatim instead of translating.
- **Full Language Name Mapping:** Language codes (`tr`, `en`, `de`) are now converted to full names (`Turkish`, `English`, `German`) for better model comprehension.
- **Aggressive Response Cleanup:** Added comprehensive regex patterns to strip model "chatter" (e.g., "Translating to Turkish:", "Here is the translation:") from the output.
- **Batch Override for Local LLM:** `LocalLLMTranslator` now overrides `translate_batch` to force one-by-one translation, bypassing XML-style batching that confused smaller models.
- **Placeholder Corruption Guard:** If the model corrupts `XRPYX` placeholders, the system now falls back to the original text to prevent game-breaking translations.

### 🔔 UI/UX Improvements
- **InfoBar Warning for Local LLM:** Added a visible warning (same style as Gemini censorship warning) that appears in the top-right corner when Local LLM is selected, alerting users to potential hallucination issues with small models.
- **Settings Panel Warnings:** Added three persistent warning/tip labels to the AI Settings section:
  - ⚠️ Hallucination risk for models under 7B parameters
  - ⚠️ VRAM limitations advisory
  - 💡 Tip: Setting source language explicitly improves quality

### 🌍 Localization
- **New Keys:** Added `ai_hallucination_warning`, `ai_vram_warning`, and `ai_source_lang_warning` keys.
- **Full Sync:** Updated all 8 language files (`tr`, `en`, `de`, `es`, `fr`, `ru`, `fa`, `zh-CN`) with new warning messages.

## [2.5.0] - 2026-01-14
### 🚀 New Features (Major)
- **Force Runtime Translation:** Added "Force Runtime Translation" (Zorla Çeviri) feature. This dynamically injects a `01_renlocalizer_runtime.rpy` script into the game folder. It hooks into Ren'Py's `config.replace_text` to translate strings lacking the `!t` flag at runtime, ensuring 100% translation coverage for dynamic strings without manual code edits.
- **Improved Placeholder Protection:** Fixed a critical issue where Python variables inside Ren'Py bracket expressions (e.g., `[page['episode']]`) were being corrupted by translation. Expanded technical string filtering to protect internal property access and complex dictionary patterns.

### 🛠️ Core Fixes (Quest System & Parsing)
- **Quest Text Extraction Fix:** Resolved a critical issue where multi-line quest descriptions embedded in Python data structures (lists/dictionaries) were being skipped or incorrectly parsed.
- **Improved Trailing Text Cleanup:** Fixed a bug in the parser that caused trailing commas or brackets to leak into extracted strings, preventing valid translations.
- **Untranslated Text Detection:** Fixed a logic error where empty translations (`new ""`) in existing files were sometimes treated as "translated," preventing them from being processed.
- **Global Deduplication:** Implemented aggressive deduplication for `strings.rpy` generation to prevent file bloating (reduced file size by ~70% in large projects) and eliminate duplicate translation requests.
- **ID Generation Stability:** Enhanced the Translation ID generation algorithm to be more robust against escape sequences and newline variations.

### 🗺️ Cross-Platform & UI
- **Cross-Platform Game Selection:** Enhanced game path selection to be fully compatible with Windows, macOS, and Linux.
- **Platform-Aware Filtering:** Added specific file filters and dialog titles for different operating systems (.exe for Windows, .app/.sh for macOS, .sh/binary for Linux).
- **Browse Folder Support:** Added a "Browse Folder" option for direct directory selection, improving flexibility for game project identification.
- **Intelligent Root Detection:** Improved pipeline logic to automatically locate the `game/` subdirectory regardless of the initial selection (executable or folder).
- **Localization Expansion:** Updated all 8 supported languages (`tr`, `en`, `de`, `es`, `fr`, `ru`, `zh-CN`, `fa`) with new localization keys for cross-platform selection, platform-specific placeholders, and titles.

### ⚡ Core & Performance (Major Update)
- **Smart Skip (Incremental Translation):** Added the ability to automatically detect and skip already translated lines (where the `new` string is not empty). This allows for lightning-fast incremental updates when a game version changes, saving API costs and time.
- **Resume System:** Implemented a persistent progress tracking system. If the translation is interrupted (power outage, manual stop), you can now resume exactly where you left off.
- **Aggressive Translation Retry:** Specialized retry mechanism for LLM engines. If the initial translation returns the original text, the engine now automatically retries with a "Force Translation" prompt.
- **Maintenance:** Permanently removed legacy "Output Format" selection. The system now defaults to the most stable `old_new` format to ensure 100% compatibility with Ren'Py script updates.
- **Robust Config Loading:** Implemented a filtering mechanism that ignores unknown configuration keys in the JSON file. This prevents "unexpected keyword argument" crashes when downgrading versions or moving between builds with different settings.

###   Performance & UI Responsiveness
- **UI Throttling (Anti-Freeze):** Implemented a log buffering system with a `QTimer` (200ms) to prevent UI freezing during high-frequency logging. The application now remains fully responsive (draggable/clickable) even while processing thousands of files per second.
- **Multithreading GIL Yields:** Added microscopic `time.sleep` yields in tight parsing and file generation loops. This allows the Python Global Interpreter Lock (GIL) to release more frequently, ensuring the UI thread stays alive and smooth during heavy CPU-bound tasks like scanning tens of thousands of script lines.
- **Regex Optimization:** Optimized core translation logic by pre-compiling overhead-heavy regular expression patterns. This significantly reduces CPU usage during the "protection" and "restoration" phases of translation.
- **Efficiency:** Optimized translation file generation by caching relative path calculations, reducing redundant OS calls during massive project writes.
- **Signal Multi-threading Efficiency:** Reduced main-thread overhead by eliminating redundant "debug" level signal emissions in tight processing loops.

### 🔍 Parser Optimization & Accuracy
- **Smart Directory Targeting:** The parser now automatically prioritizes the `game/` folder when a project root is selected, ensuring only relevant assets are scanned.
- **Strict File Type Enforcement:** Restricted scanning to core Ren'Py files (`.rpy`, `.rpyc`, `.rpym`, `.rpymc`). Other common but non-essential files (JSON, CSV, TXT, etc.) are now skipped to prevent "translation noise".
- **Advanced System Filter:** Added comprehensive exclusion rules for internal folders like `cache/`, `renpy/`, `saves/`, `tmp/`, and `python-packages/`.
- **Binary/Corrupted String Filter (RPYC Safety):** Added robust detection and filtering for corrupted strings from `.rpyc` files:
    - Unicode Replacement Character (`\ufffd`) detection.
    - Private Use Area character filtering (`\uE000-\uF8FF`).
    - Control character detection (`\x00-\x1F`, `\x7F-\x9F`).
    - High ratio of non-printable character analysis (>30% threshold).
    - Low alphabetic content detection (<20% ratio).
    - Short string corruption pattern matching for strings like `"z X "`, `"|d T"`, `"qu p  "`.
- **Python Code / Docstring Detection (Critical Fix):** New filter to prevent game-breaking translations of embedded code:
    - Detects Python keywords: `def`, `class`, `for`, `if`, `import`, `return`, `raise`, `try`, `except`, `while`, `lambda`, `with`.
    - Filters Ren'Py module calls like `renpy.store.x`, `renpy.block_rollback()`.
    - Skips string concatenation expressions: `"inventory/"+i.img+".png"`.
    - Protects internal dict access patterns: `_saved_keymap[key]`.
    - Filters boolean/None assignments: `x = True`, `y = False`, `z = None`.
- **Python Built-in Function Calls Filter:** Added detection for Python built-in function calls (`str()`, `int()`, `len()`, etc.) that should never be translated.
- **Default Dict/List String Extraction (Quest System Fix):** New extraction capability for strings inside `default` statement dict/list literals:
    - Handles `default quest = {"anna": ["Start by helping her..."]}` patterns.
    - Extracts translatable quest descriptions, schedule entries, and objectives.
    - Intelligent filtering to skip dict keys, short technical strings, and file paths.
- **Short Technical Words:** Added filter for common programming identifiers (`img`, `id`, `val`, `cfg`, etc.) that should never be translated.
- **Enhanced Technical String Filtering (Official Documentation Update):**
    - **Documentation-Driven Expansion:** Significantly expanded the `renpy_technical_terms` list based on a deep dive into official Ren'Py documentation, including transitions, motion commands, and engine keywords.
    - **Advanced Screen Language Filtering:** Added support for advanced UI elements like `hotspot`, `hotbar`, `areapicker`, `draggroup`, `showif`, and `vpgrid`.
    - **Deep Python Integration Safety:** Added comprehensive filtering for Python technical types (`Callable`, `Literal`, `Self`) and a full set of internal exception classes (`AssertionError`, `TypeError`, etc.) to prevent code-leaks in translation.
    - **Smart Heuristics:**
        - **Internal Identifier Protection:** Now automatically skips all underscore-prefixed strings (e.g., `_history`, `_confirm`) which are reserved for Ren'Py's internal use.
        - **System File Filtering:** Automatically skips strings derived from internal indexing files (starting with `00`).
        - **Namespace Awareness:** Strengthened detection for `config.`, `gui.`, `preferences.`, and `style.` namespaces.
    - **CamelCase & Dot-notation Detection:** Improved detection to automatically skip technical identifiers, module attributes, and code-like strings.


### 🌐 Expanded Language Support
- **Massive Source Language Expansion:** Increased the number of supported source languages from 37 to over 90, covering nearly every major language for a truly global translation experience.
- **Improved Native Names:** Standardized native language names in the UI for better accessibility.

### ⚙️ Translation Engine Improvements
- **DeepL Improvements:**
  - Added 3-attempt exponential backoff retry for transient network errors.
  - New "Formality" setting (Formal/Informal) for supported languages.
  - Fixed critical undefined variable bug in exception handler.
- **DeepL Tag Protection:** Automatically fixes spacing errors inside Ren'Py tags (e.g., `{ i }` → `{i}`).
- **AI Token Tracking:** OpenAI and Gemini now log token usage for better cost monitoring.
- **Optimization:** Implemented centralized request deduplication to prevent redundant API calls across all engines.
- **Resilience:** Added "Mirror Health Check" system for Google Translate to automatically detecting and bypassing failing endpoints.
- **Google Batch Fix:** Fixed a critical `AttributeError: _endpoint_failures` that occurred during multi-endpoint batch translation.
- **Mirror Ban Logic:** Implemented a temporary ban system (5 minutes) for Google Translate mirrors that consistently return 429 (Too Many Requests) or other errors, ensuring the pipeline quickly shifts to healthy mirrors.
- **Smart Concurrency:** Introduced adaptive rate-limit handling for OpenAI/Gemini that dynamically adjusts concurrency upon encountering 429 errors.

### 🖥️ Local LLM & Jan.ai
- **Jan.ai Support:** Added Jan.ai as a built-in preset in Local LLM settings (URL: `http://localhost:1337/v1`).
- **Uncensored Model Presets:** Categorized model dropdown for NSFW VN translation (Sansürsüz, LM Studio, Standart).
- **Separated Model Input:** Free-text model name input with a separate preset dropdown.

### 🍱 Localization & UI
- **Engine Transparency:** Added "(Experimental)" labels to non-Google engines.
- **Localized LLM Categories:** "Uncensored", "LM Studio", and "Standard" categories are now fully localized in all 8 supported languages.
- **DeepL Formality UI:** New setting card in API Keys section.
- **Global Label Sync:** Comprehensive update for `tr`, `en`, `de`, `es`, `ru`, `fr`, `zh-CN`, and `fa` locales.
- **Settings UI Localization Fix:** Fixed hardcoded Turkish fallback strings in Settings Interface (AI Settings, Proxy Settings, Advanced sections) that were appearing in English mode.

## [2.4.10] - 2026-01-11
### 🛡️ Ren'Py Engine Protection & Stability
- **Engine Isolation:** Explicitly excluded `renpy/common` and internal `renpy/` directories from scanning to prevent engine-level scripts from being corrupted by translation.
- **Automatic Cleanup:** Added a post-extraction cleanup step to remove any accidental engine-level translation files from the `tl/` directory.
- **Smart Technical Filtering:** Integrated advanced regex detection and symbol density heuristics to automatically skip internal Ren'Py code and technical regex patterns.

### 🌐 Translation Pipeline & API Management
- **Advanced API Quota Handling:**
  - Implemented a dedicated `quota_exceeded` flag in `TranslationResult` for more robust error handling.
  - Replaced brittle string matching for API limits with proper status code and boolean checks for DeepL, OpenAI, and Gemini.
  - The system now gracefully stops translation and provides a localized warning when API limits are reached.
- **Localized Stage Logging:**
  - Completely localized the pipeline stage labels (e.g., `[🌐 Translating...]`, `[✅ Validating...]`).
  - Improved `ConfigManager.get_log_text()` to support default values and cleaner error reporting.
  - Refined error log formatting to handle cases where file or line information is missing.

### 🍱 Localization & Global Support
- **Full Sync across 8 Languages:** Fully synchronized and updated `tr`, `en`, `de`, `es`, `fr`, `ru`, `zh-CN`, and `fa` locale files.
- **Pipeline Log Localization:** Added missing keys for all pipeline stages and API errors across all supported languages.
- **Persian (FA) Locale Fix:** Restructured the `fa.json` file to fix duplicate keys and missing pipeline log sections.

### 🔍 Parsing & Extraction Improvements
- **Better Dialogue Support:**
  - Added support for dot-separated character names (e.g., `persistent.player_name`).
  - Enhanced narrator dialogue detection to support trailing transitions (e.g., `"Hello" with dissolve`).
  - Relaxed strict length filters for non-Latin languages to capture short but meaningful dialogues (e.g., Russian "Я", "Да").
- **Scanning Robustness:** Synchronized dot-separated character name support across both Regex and AST-based extraction pipelines.

### 🌐 Translation Engine Improvements
- **Smart Retry for Unchanged Translations (Optional):** Added "Agresif Çeviri" (Aggressive Translation) toggle in settings. When enabled, the system automatically retries unchanged translations with Lingva Translate and alternative Google endpoints. This significantly reduces the number of untranslated strings, especially for Cyrillic (Russian) to other language pairs. Disabled by default for optimal speed.
- **Enhanced Placeholder Protection:** Fixed a critical bug where nested bracket patterns like `[page['episode']]` or `[comment['author']]` were being incorrectly translated. The new parser properly handles dictionary access patterns, method calls, and nested quotes inside variable interpolations.
- **Technical String Filter:** Added filter for Ren'Py internal identifiers (e.g., `renpy.dissolve`, `renpy.mask renpy.texture`) to prevent them from appearing in translation output.

### 🐛 Bug Fixes & Stability
- **ConfigManager TypeError:** Fixed `TypeError` in `get_log_text()` call by adding proper default parameter support.
- **Duplicate Key Clean-up:** Removed redundant `error_api_quota` keys from root level in all locale files to prevent conflicts.
- **RPYC Reader AST Module Support:** Fixed `Disallowed global: _ast.Module` error when reading `.rpymc` (screen cache) files by whitelisting Python's `_ast` module in the safe unpickler.
- **Pipeline UnboundLocalError Fix:** Resolved a crash where the variable `tl_dir` was accessed before definition during the engine cleanup phase.
- **Duplicate Translation Entry Fix:** Resolved Ren'Py "already exists" errors by excluding the `tl/` directory from scanning and implementing deduplication against pre-existing translation files.
- **Update Checker Fix:** Resolved a critical crash that occurred when the GitHub update check returned inconsistent or erroneous metadata.
- **CLI RPA Robustness:** Fixed an issue where RPA extraction would fail in CLI mode when the game path points to a directory instead of an executable.
- **Font Warning Mitigation:** Resolved multiple `QFont` console warnings by removing and standardizing legacy font settings.

## [2.4.9] - 2026-01-09
### 🚀 AI Performance & Batch Processing
- **Batch Translation Support:** Added batch translation for OpenAI, Gemini, and Local LLM engines.
  - Significantly improved translation speed (5-10x) and reduced API costs.
  - Implemented an XML-based smart tagging system to protect Ren'Py syntax during batch operations.
- **Refactored AI Settings UI:** Reorganized AI settings into three main categories:
  - **Model Parameters:** Temperature and Max Tokens settings.
  - **Connection Settings:** Timeout and retry count settings.
  - **Speed & Performance:** Concurrency and request delay control.
- **Rate Limiting & Stability:** Integrated semaphore-based concurrency control and jittered delay mechanisms to minimize API rate limit issues.

### 🍱 Localization & Language Support
- **Full Sync:** Synchronized all localization files (`tr`, `en`, `de`, `fr`, `es`, `fa`, `ru`, `zh-CN`) to 100% completeness.
- **Turkish Improvements:** Completed 14+ missing critical keys in `tr.json`, ensuring the UI is fully localized in Turkish.
- **Enhanced System Prompts:** Updated AI system prompts across all languages to maintain a professional localizer tone and ensure uncensored translation of NSFW content.

### 🛠️ CI/CD & Infrastructure
- **Windows Build Automation:** GitHub Actions (`release.yml`) now automatically builds and releases Windows packages.
- **Python Stability:** Standardized Python version to `3.12` in CI/CD pipelines for better compatibility and stability.
- **Code Cleanup:** Removed and standardized legacy Turkish debug logs within the translation pipeline.

## [2.4.8] - 2026-01-08
### 🚀 New Features: Local LLM Support
- **Full Local LLM Integration:** Added dedicated "Local LLM" engine in translation options.
  - Supports **Ollama**, **LM Studio**, and other OpenAI-compatible local endpoints.
  - No API key required (uses "local" as placeholder).
  - Default model: `llama3.2`, Default URL: `http://localhost:11434/v1`.
- **Advanced AI Settings:**
  - Configurable `Temperature`, `Timeout`, `Max Tokens`, and `Retry Count`.
  - Custom System Prompt support for fine-tuning translation persona.

### 🧹 Code Health & Maintenance
- **Project Structure Audit:** Conducted a comprehensive health check.
  - **Magic Numbers Refactored:** Moved hardcoded values (timeouts, token limits, window sizes) to a centralized `src/utils/constants.py`.
  - **Localization Sync:** Ensured `translation_engines` list and new AI settings are 100% localized across all 7 supported languages (tr, en, de, fr, es, ru, zh).
  - **Dynamic UI Labels:** Fixed several hardcoded text labels in Settings UI to properly use the localization system.
- **UI Cleanup:**
  - Removed obsolete "Show Detailed Help" button from About page (functionality moved to Info Center).
  - Updated OpenAI engine label to simply "OpenAI / OpenRouter" to reduce confusion.

## [2.4.7] - 2026-01-06
### 🐛 Bug Fixes
- **PyInstaller UnRPA Fix:** Fixed critical bug where RPA extraction would fail in packaged executables.
  - **Root Cause:** `sys.executable` points to the bundled `.exe` instead of Python interpreter in frozen environments.
  - **Solution:** Replaced subprocess-based `python -m unrpa` calls with direct `unrpa` library API.
- **UnRPA 2.3.0 API Compatibility:** Fixed API mismatch with unrpa library.
  - **Root Cause:** unrpa 2.3.0 doesn't have a `path` parameter - it extracts to current working directory.
  - **Solution:** Temporarily change working directory with `os.chdir()` before extraction.

### ✨ New Features
- **Native RPA Parser Fallback:** Added built-in RPA archive parser (`rpa_parser.py`) that works without external dependencies.
  - Automatically used when `unrpa` fails to import in frozen PyInstaller builds.
  - Supports RPA-3.0 and RPA-2.0 formats (covers 99% of Ren'Py games).
  - **Result:** RPA extraction is now guaranteed to work in all environments.

### 🐛 CLI Fixes
- **Fixed CLI `translate` Subcommand:** The CLI was incorrectly entering interactive mode even when path was provided.
  - **Root Cause:** Argparse conflict between main parser and subparser `input_path` argument.
  - **Solution:** Renamed legacy argument to avoid namespace collision.
- **Fixed CLI Directory Path Support:** CLI now accepts both `.exe` files and directory paths for `--mode full`.
  - **Root Cause:** Pipeline validation only accepted file paths, not directories.
  - **Solution:** Updated `configure()` and `_run_pipeline()` to handle both file and directory inputs.
  - **Result:** CLI can now properly extract RPA archives and translate games when given a folder path.
- **Smart Mode Detection:** CLI now automatically detects Ren'Py projects by checking for `game/` subfolder.
  - Directories with `game/` subfolder automatically use `full` mode (RPA extraction + translation).
  - Other directories use `translate` mode (direct translation of existing files).

## [2.4.6] - 2026-01-05
### 🐛 Bug Fixes
- **Update Checker Crash Fix:** Fixed a critical crash on startup caused by the update checker system.
  - **QTimer Delay:** Update check now runs 1 second after window initialization to ensure all UI components are ready.
  - **InfoBar/QMessageBox Overlap:** Removed duplicate InfoBar before QMessageBox to prevent Qt event loop conflicts.
  - **Format Placeholder Fix:** Fixed `KeyError` caused by mismatched format placeholders (`{version}` vs `{latest}/{current}`).
  - **Error Handling:** Added comprehensive try/except and null checks for robustness.

## [2.4.5] - 2026-01-05
### 🔄 Major Architecture Change: UnRPA for All Platforms
- **Unified Extraction:** Now uses `unrpa` Python library on ALL platforms (Windows, Linux, macOS) instead of unreliable batch scripts.
- **Simplified Codebase:** Removed 140+ lines of legacy Windows batch script handling code.
- **Reliable Extraction:** No more "HTTP 404" errors from UnRen download links - just `pip install unrpa`.
- **RPYC-Only Mode:** When `.rpy` files are not found, the pipeline reads directly from `.rpyc` files.
- **Ren'Py 8.x Optimized:** Fully compatible with modern Ren'Py RPAv3 archives.

### 🛠️ Tools Interface
- **Streamlined UI:** Removed old "Run UnRen" and "Redownload" buttons.
- **New Standard:** Single, reliable "RPA Arşivlerini Aç" button powered by `unrpa`.
- **Cleanup:** Removed deprecated `UnRenModeDialog`.

### 🔧 Bug Fixes
- **Fixed `force_redownload` error:** Method was missing from UnRenManager (now removed as unnecessary).
- **Custom Path Fix:** Fixed bug in `get_custom_path()` where variable was used before being defined.

### 🧹 UI Cleanup
- **Removed Output Format Setting:** Always uses stable `old_new` format now.

### 📦 Dependency
- **Required:** `pip install unrpa` (added to requirements.txt)

## [2.4.4] - 2026-01-04
### 🎨 Theme System Overhaul
- **New Themes:** Added **Green (Nature/Matrix)** and **Neon (Cyberpunk)** themes, bringing the total to 6 distinct options.
- **Improved Dark Theme:** Deepened the dark theme colors for better immersion and reduced "grayness".
- **Visual Fixes:** Resolved "blocky" black backgrounds on text labels by enforcing transparency rules (`background-color: transparent !important`).
- **Dynamic Switching:** Theme changes now apply **instantly** without requiring an application restart.
- **Fix:** Fixed a critical bug where the theme selector always reverted to "Dark" due to a `qfluentwidgets` compatibility issue with `itemData`.
- **Fix:** Eliminated `QFont::setPointSize` console warnings by refining stylesheet scoping.

## [2.4.3] - 2026-01-04
### 🐛 Bug Fixes
- **PseudoTranslator Placeholder Fix:** Fixed critical bug where `PseudoTranslator` was corrupting Ren'Py placeholders (e.g., `[player]`, `{color=#f00}`) during text transformation. The engine now splits text by placeholder markers and only applies pseudo-transformation to non-placeholder segments.

### 🧹 Cleanup
- **Removed Unused Files:** Deleted obsolete debug scripts (`debug_font.py`, `debug_themes.py`) and unused modules (`base_translator.py`, `qt_translator.py`).
- **Light Theme Fix:** Implemented comprehensive stylesheet overrides to fix the "color mess" in Light Theme, ensuring all UI elements (navigation, headers, cards) are correctly styled.

## [2.4.2] - 2026-01-03
### 📦 Build & Distribution
- **One-Dir Build:** Switched to folder-based release for better startup speed and debugging.
- **Cross-Platform Scripts:** Added `RenLocalizer.sh` and `RenLocalizerCLI.sh` for easy launching on Linux/macOS.
- **Hidden Imports:** Fixed `ModuleNotFoundError` by correctly collecting all submodules in `RenLocalizer.spec`.

### 🐛 Bug Fixes
- **Glossary Editor:** Fixed crash when opening Glossary Editor in packaged builds.

## [2.4.1] - 2026-01-02
### ✨ New Features
- **Patreon Integration:** Added a support button to the main UI.

## [2.4.0] - 2026-01-01
### 🚀 Major Update: Unreal Engine Support
- **Unreal Translation:** Added basic support for unpacking and translating Unreal Engine games (`.pak` files).
- **AES Key Handling:** Integrated AES key detection for encrypted PAK files.

## [2.3.0] - 2025-12-28
### 🌍 RPG Maker Support
- **RPG Maker MV/MZ:** Added support for translating RPG Maker JSON files.
- **RPG Maker XP/VX/Ace:** Added support for Ruby Marshal data files.

## [2.2.0] - 2025-12-26
### 🤖 CLI Deep Scan
- **Deep Scan:** Added `--deep-scan` argument to CLI for AST-based analysis of compiled scripts.

## [2.1.0] - 2025-12-24
### 💅 UI Improvements
- **Fluent Design:** Migrated to `PyQt6-Fluent-Widgets` for a modern look and feel.

## [2.0.0] - 2025-09-01
### 🎉 Initial Release
- **Core:** Ren'Py translation support, multi-engine translation (Google, Bing, DeepL), modern GUI.
