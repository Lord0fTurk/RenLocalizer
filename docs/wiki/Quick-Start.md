# ⚡ Quick Start — Translate in 3 Simple Steps

Follow these simple steps to translate any Ren'Py visual novel in minutes.

---

## 🎯 Step 1 — Select Your Game

Click **"Browse"** or **"EXE"** in the **Game Selection** card:

| Button | Action | What to select |
|:---|:---|:---|
| **📁 Browse Folder** | Opens directory picker | The game's root folder (the folder containing `game/`) |
| **🎮 Browse EXE File** | Opens file picker | The game's `.exe` executable |

```
📂 MyVisualNovel/           ← Select this folder (or the .exe)
   ├── game/
   │   ├── script.rpy       ← RenLocalizer will extract text from here
   │   ├── screens.rpy
   │   └── ...
   └── MyVisualNovel.exe
```

> ✅ **Compatibility:** Works on all Ren'Py games (supports `.rpy`, `.rpyc`, and `.rpa` archives).  
> 🚫 **Unsupported Engines:** Does not work on Unity, RPG Maker, or Godot.

---

## 🌐 Step 2 — Pick Engine, Language & Mode

In the **Configuration** area:

1. **Translation Engine:**
   - Choose **Google Translate** for free, instant, zero-setup translation (13 rotating mirrors).
   - Or choose **OpenAI / DeepSeek / Gemini / Local LLM** for high-tier AI translation.
2. **Target Language:** Select the language you want to play in (e.g. *Turkish*, *Russian*, *Spanish*...).
3. **Translation Mode (for AI engines):**
   - 🎭 **Scene Mode (Recommended):** Context-aware theatre screenplay flow. Best for character dialogues and visual novels.
   - 📦 **JSON Mode:** Strict structured key-value data. Great for menus and UI text.
   - 📄 **XML Mode:** Resilient tag wrapping for smaller or older models.

---

## 🚀 Step 3 — Start Translation & Play!

Click the glowing **"START TRANSLATION" (▶)** button.

The real-time progress bar and log console will guide you through the 7-stage pipeline:

```
[1. VALIDATING] ➔ [2. UNRPA] ➔ [3. GENERATING] ➔ [4. PARSING] ➔ [5. TRANSLATING] ➔ [6. SAVING] ➔ [7. COMPLETED]
```

### 🎮 Once Finished:
1. Launch your game normally.
2. Open the in-game **Preferences / Settings** menu.
3. Switch the **Language** to your translated language.
4. **Enjoy your game!** 🎉

---

## ⏱️ Estimated Translation Times

| Game Size | Line Count | Google Translate | Local LLM (RTX 3050+) | Cloud API (DeepSeek/GPT) |
|:---|:---|:---|:---|:---|
| 🟢 **Short VN** | ~5,000 lines | ~1–2 minutes | ~10–15 minutes | ~3–5 minutes |
| 🟡 **Medium VN** | ~15,000 lines | ~3–6 minutes | ~30–45 minutes | ~10–15 minutes |
| 🔴 **Long VN** | ~50,000+ lines | ~15–30 minutes | ~1.5–3 hours | ~30–60 minutes |

> 💡 **Background Operation:** You can minimize RenLocalizer while it translates. It runs smoothly in the background without freezing.

---

## ❓ Need More Help? Check [[FAQ]] or [[Settings-and-Engines]].
