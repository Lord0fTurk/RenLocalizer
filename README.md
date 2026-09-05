# RenLocalizer 🎮✨

<p align="center">
  <strong>Translate any Ren'Py Visual Novel in just a few clicks — without breaking code, formatting, or save files!</strong>
</p>

<p align="center">
  <a href="https://github.com/Lord0fTurk/RenLocalizer/releases"><img alt="Latest Release" src="https://img.shields.io/badge/Release-v2.8.14-blue?style=for-the-badge&logo=github"></a>
  <a href="https://www.patreon.com/cw/LordOfTurk"><img alt="Support on Patreon" src="https://img.shields.io/badge/Support-Patreon-ff424d?style=for-the-badge&logo=patreon"></a>
</p>

<p align="center">
  <img alt="Platform" src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-2d6cdf?style=flat-square&logo=windows">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776ab?style=flat-square&logo=python&logoColor=white">
  <img alt="GUI" src="https://img.shields.io/badge/GUI-PyQt6%20%2B%20QML-41cd52?style=flat-square&logo=qt&logoColor=white">
  <img alt="RenPy" src="https://img.shields.io/badge/Ren'Py-7%20%26%208%20Compatible-ff69b4?style=flat-square">
  <img alt="License" src="https://img.shields.io/badge/License-GPL--3.0-111827?style=flat-square">
</p>

<p align="center">
  <a href="#-quick-start-3-simple-steps">Quick Start</a> •
  <a href="#-supported-translation-engines">Engines</a> •
  <a href="#-translation-modes">Translation Modes</a> •
  <a href="#-why-renlocalizer">Why RenLocalizer?</a> •
  <a href="CHANGELOG.md">Changelog</a> •
  <a href="https://github.com/Lord0fTurk/RenLocalizer/wiki">Wiki Guide</a>
</p>

---

## ⚡ Quick Start (3 Simple Steps!)

You don't need any programming skills or complex setup to translate your favorite visual novel.

```
  1. Select Game ────────► 2. Pick Language & Engine ────────► 3. Click Translate & Play!
 (Drop folder / .exe)          (Google, DeepSeek, Local LLM...)          (Launch game & enjoy!)
```

1. **Download & Open:** Grab the latest portable version from [**GitHub Releases**](https://github.com/Lord0fTurk/RenLocalizer/releases) and extract it anywhere.
2. **Select Game:** Click **"Browse"** (or **"EXE"**) and choose your game's executable or game folder.
3. **Pick Language & Translate:** Choose your target language, pick an engine (e.g. **Google Translate** for free & instant, or **Local LLM** for offline AI), and hit **Translate (▶)**!

> 💡 **macOS Users:** The app is portable. If macOS Gatekeeper says the app is damaged or cannot be opened, open Terminal and run once:
> ```bash
> xattr -cr /Applications/RenLocalizer.app
> ```

---

## 🤖 Supported Translation Engines

Pick the engine that best fits your needs — from 100% free cloud translation to private, offline AI models:

| Engine | Setup Required | Cost | Best For |
| :--- | :---: | :---: | :--- |
| 🌍 **Google Translate** | **Zero Setup** | **100% Free** | Instant translation, no API keys, built-in 13 mirror rotation. |
| 🧠 **OpenAI (GPT-4o / Mini)** | API Key | Paid API | High-accuracy literary translations and nuanced dialogue. |
| ⚡ **DeepSeek (V3 / R1)** | API Key | Very Low Cost | Outstanding translation quality with OpenAI-compatible API. |
| 💎 **Google Gemini** | API Key | Free Tier / Paid | High-speed, context-rich translations with large context windows. |
| 🏠 **Local LLM (Ollama / LM Studio)** | Local App | **100% Free** | Fully offline, private, uncensored translation (e.g. Llama 3, Qwen 2.5). |
| 🐳 **LibreTranslate** | Self-hosted | Free | Self-hosted local Docker translation service. |

---

## 🛡️ Why RenLocalizer?

Translating Ren'Py visual novels with standard translation tools usually crashes the game. Here is why RenLocalizer is different:

* 🔒 **SyntaxGuard:** Ren'Py codes like `{b}`, `{color=...}`, and variables like `[player_name]` are strictly isolated before translation and safely restored afterwards.
* 🚫 **No Duplicate Key Crashes:** Automatically tracks existing translations and native IDs, preventing Ren'Py 7.5+ / 8.x duplicate string fatal errors.
* 📦 **Deep Binary Scan (.rpyc & .rpa):** Extracts hidden strings directly from compiled `.rpyc` files and unpacks `.rpa` archives automatically.
* 🚀 **Smart Runtime Hook:** Injects a lightweight `init -999 python:` hook for dynamic on-the-fly string translation and instant language switching in-game.

---

## 💻 For Power Users & Developers

<details>
<summary><strong>⌨️ CLI (Command-Line Interface) Mode</strong></summary>

RenLocalizer includes a full-featured headless CLI mode powered by `rich`:

```bash
# Quick translation with Google (default)
python run_cli.py "C:\Games\MyVisualNovel\game.exe"

# Translate with DeepSeek to Russian
python run_cli.py "C:\Games\MyVisualNovel\game.exe" -e deepseek -t ru

# Translate with Local LLM (Ollama) with deep scan enabled
python run_cli.py "C:\Games\MyVisualNovel\game.exe" -e local_llm -t de --deep-scan

# Interactive terminal menu mode
python run_cli.py --interactive
```
</details>

<details>
<summary><strong>🛠️ Running from Source Code</strong></summary>

Requires Python 3.10+:

```bash
# 1. Clone the repository
git clone https://github.com/Lord0fTurk/RenLocalizer.git
cd RenLocalizer

# 2. Create and activate a virtual environment
python -m venv .venv

# Windows:
.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Launch the application
python run.py
```
</details>

<details>
<summary><strong>🔬 Technical Specifications & Protection Pipeline</strong></summary>

- **Placeholder Protection Modes:**
  - *Google (Token Mode):* Unicode mathematical brackets `⟦RLPH{hex}_{N}⟧` (treated as invariant punctuation by Google Translate).
  - *AI/LLM (XML & Token Modes):* `<ph id="N">...</ph>` and `__PH_N__` wrappers preventing subword tokenizer fragmentation.
  - *6-Stage Restoration:* Unicode brackets ➔ bracket-stripped ➔ transliteration repair ➔ generic recovery ➔ wrapper pair ➔ tag repair.
- **Integrity Validation:** If an AI model hallucinate or leaks tags, the string is flagged as corrupted and safely reverted to original text to prevent game crashes.
- **Runtime Hook:** `zzz_renlocalizer_runtime.rpy` features an $O(1)$ dictionary lookup, MRU cache (500 entries), and screen harvesting.
</details>

---

## 🤝 Contributing & Community

Contributions, bug reports, and feature requests are very welcome!

- 🐛 **Report a Bug:** Open an issue on [GitHub Issues](https://github.com/Lord0fTurk/RenLocalizer/issues)
- 📖 **Documentation:** Visit the [Wiki Guide](https://github.com/Lord0fTurk/RenLocalizer/wiki)
- 💖 **Support Development:** Join us on [Patreon](https://www.patreon.com/cw/LordOfTurk)
- 📜 **License:** Released under the [GNU General Public License v3.0](LICENSE)
