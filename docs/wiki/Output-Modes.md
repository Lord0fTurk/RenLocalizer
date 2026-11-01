# 📦 Output Modes: Native TLID vs Standard Runtime Hook

RenLocalizer can generate your game translations in two distinct formats. Depending on your game's complexity and script structure, choosing the right output mode ensures maximum performance and zero crashes.

---

## 🎯 Quick Comparison

| Feature | ⚡ Native TLID Mode (Default — Recommended) | ✨ Standard Mode (Runtime Hook) |
|:---|:---|:---|
| **Best For** | 🏆 95% of visual novels, maximum performance | Complex dynamic UI screens, interactive sandboxes |
| **How it Works** | Pure native Ren'Py `translate <lang>` & `strings:` blocks | Injects `zzz_renlocalizer_runtime.rpy` + `strings.json` |
| **Execution Speed** | 🚀 **Pure C-level speed** (zero overhead) | Fast O(1) in-memory lookup with MRU caching |
| **Runtime Scripts** | ❌ None (no Python hook runs during gameplay) | Yes (~1,365 lines runtime hook v4.2.0) |
| **Dynamic Interpolation** | Handled natively by Ren'Py | Pre- & post-interpolation matching |
| **Compatibility** | Ren'Py 6.99 to 8.x+ | Ren'Py 7.x to 8.x+ (Python 2 & 3 safe) |

---

## ⚡ Mode 1: Native TLID (Recommended — Default)

In **Native TLID Mode**, RenLocalizer writes dialogue lines directly into official Ren'Py translation blocks matching the original statement hashes:

```renpy
# tl/turkish/script.rpy
translate turkish start_52f47bbf:
    # e "Hello, world!"
    e "Merhaba, dünya!"
```

UI elements, choice menus, and screen texts are automatically extracted and generated as standard `translate strings:` blocks:

```renpy
# tl/turkish/common.rpy
translate turkish strings:
    old "Start Game"
    new "Oyuna Başla"
```

### ✅ Advantages:
- **Zero Performance Impact:** No custom Python scripts run during gameplay; uses Ren'Py's optimized internal lookup.
- **Save File Compatibility:** Completely safe for existing save states and rollbacks.
- **Clean Structure:** 100% compliant with standard Ren'Py SDK distribution standards.

---

## ✨ Mode 2: Standard Mode (Strings.json + Runtime Hook v4.2.0)

In **Standard Mode**, RenLocalizer bundles translations into a high-performance `strings.json` dictionary and injects a smart runtime interceptor (`zzz_renlocalizer_runtime.rpy`):

```
┌──────────────┐      ┌─────────────────────────────┐      ┌──────────────────┐
│ Game Screen  │ ───► │ Runtime Hook (v4.2.0)       │ ───► │ Translated Text  │
│ displays     │      │ - Exact O(1) lookup         │      │ seamlessly       │
│ text         │      │ - Case-insensitive fallback │      │ rendered         │
└──────────────┘      └─────────────────────────────┘      └──────────────────┘
```

### ✅ When to Use:
- When playing sandbox games or complex RPGs with heavily scripted, dynamic Python UI strings (e.g. inventory counters, quest markers, dynamic stats).
- When some screen buttons or system overlays remain untranslated under Native TLID mode.
- Features automatic **Screen Harvesting** (scans active Ren'Py screens during gameplay) and **automatic RTL text shaping** for Arabic, Persian, and Hebrew.

---

## 🛡️ Anti-Crash Protection (Ren'Py 7.5+ & 8.x)

Modern Ren'Py engines crash if the same `old "..."` string is defined more than once within `translate strings:` blocks.

**How RenLocalizer guarantees zero crashes:**
1. RenLocalizer automatically tracks all existing `tl/` files and pre-existing string entries.
2. Identical UI strings across multiple `.rpy` files are merged into a single unique translation repository.
3. Duplicate placeholder keys are automatically skipped, completely eliminating the infamous:
   > *"The string '...' has been translated more than once in the same language."* error.

---

## 🔄 How to Switch Modes

You can switch output modes at any time on the main dashboard:
1. Under **Output Settings**, toggle between **Native TLID** and **Standard**.
2. Click **Start Translation (▶)**.
3. Your translation memory preserves previously translated lines, instantly regenerating the files in your chosen format!

---

## ⚠️ Known Limitation


```python
default quests = {
    "main_1": {"name": "Main Story", "objective": "Visit the coffeeshop"}
}
```

Ren'Py's native `translate strings:` system cannot match Python f-string interpolated text. If you notice untranslated screen text or menu labels, switch to **Standard mode** — its runtime hook handles these edge cases better.

> 🔄 **Switch anytime:** Settings → Output Mode → Standard → re-translate.
