# 🏠 Welcome to the RenLocalizer Wiki

> **Translate any Ren'Py visual novel into your language — fast, free, and zero hassle.**  
> No coding required. No game crashes. Works with all Ren'Py 7 & 8 titles.

---

## ✨ What is RenLocalizer?

**RenLocalizer** is a streamlined, single-page desktop application engineered to translate Ren'Py visual novels (`.rpy`, `.rpyc`, and `tl/` translation archives). 

Unlike standard translators that break formatting and crash games, RenLocalizer isolates game code, variables like `[player]`, formatting tags like `{b}`, and Ren'Py syntax markers before translation, and seamlessly restores them afterwards.

---

## 🌟 Key Highlights (v2.8.15)

| | Feature | Highlights |
|:---:|:---|:---|
| 🌍 | **Multi-Engine Support** | Google Translate (13 mirrors, 100% free), OpenAI, DeepSeek, Google Gemini, Local LLM, and LibreTranslate |
| 🎯 | **Tencent Hy-MT2 Profile** | Specialized translation profile featuring official instruction templates and model-card sampling recipe |
| 🎭 | **3 AI Batching Modes** | 🎭 **Scene Mode** (context-aware dialogue), 📦 **JSON Mode** (structured data), 📄 **XML Mode** (legacy grouping) |
| 🛡️ | **SyntaxGuard Protection** | 3 protection modes + 6-stage fallback recovery to guarantee crash-free game execution |
| 📦 | **Dual Output Pipeline** | **Native TLID** (pure native Ren'Py blocks, default) or **Standard Mode** (dynamic runtime hook) |
| 🔍 | **Deep Extraction** | Automatically decompiles compiled `.rpyc` files and unpacks `.rpa` archives |
| 🎨 | **9 Languages & 6 Themes** | UI available in EN, TR, DE, ES, FR, RU, FA, ZH-CN, JA + Material Design themes |
| 🖥️ | **Cross-Platform** | Portable Windows, Linux AppImage, and macOS ARM64 DMG |

---

## 📖 Wiki Navigation

| Page | What You'll Find |
|:---|:---|
| [[Installation]] | 📥 Download, portable setup, and OS-specific guides |
| [[Quick-Start]] | ⚡ First translation in 3 simple steps |
| [[Settings-and-Engines]] | ⚙️ Engines, Tencent Hy-MT2 profile, batch modes, and AI tuning |
| [[Output-Modes]] | 📦 Native TLID vs Standard Runtime Hook — which to choose |
| [[Toolbox]] | 🛠️ RPA unpacking, RPYC binary reading, and glossary term preservation |
| [[FAQ]] | ❓ Common questions, troubleshooting, and pro tips |

---

## 🚀 Translate in 3 Simple Steps

```
  1. Select Game ────────► 2. Pick Language & Engine ────────► 3. Click Translate & Play!
 (Drop folder / .exe)          (Google, DeepSeek, Local LLM...)          (Launch game & enjoy!)
```

1. **Pick Your Game:** Click **"Browse"** or **"EXE"** to select your visual novel.
2. **Choose Language & Engine:** Select your target language and preferred engine (e.g. **Google Translate** for instant zero-setup, or **Local LLM** for private offline AI).
3. **Start Translating:** Click **"Translate" (▶)**. Once complete, launch the game and switch languages in the game settings!

> 💡 **Safety Guarantee:** RenLocalizer **never alters your original game files**. Everything is written cleanly to a `tl/<language>/` folder. If you ever want to uninstall a translation, simply delete that folder.
