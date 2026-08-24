# RenLocalizer: Visual Novel Localization Made Simple

<p align="center">
  <strong>Minimalist, Zero-Dependency Translation and Localization Toolkit for Ren'Py Games.</strong>
</p>

<p align="center">
  RenLocalizer is a streamlined, single-page desktop application designed to translate Ren'Py games (.rpy, .rpyc, and tl/ directories) without breaking game code, formatting, or variables. 
</p>

<p align="center">
  <a href="https://github.com/Lord0fTurk/RenLocalizer/releases">Releases</a> |
  <a href="https://github.com/Lord0fTurk/RenLocalizer/wiki/LITE-RELEASE-GUIDE">Wiki Guide</a> |
  <a href="CHANGELOG.md">Changelog</a> |
  <a href="https://www.patreon.com/cw/LordOfTurk">Patreon</a>
</p>

<p align="center">
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-2d6cdf">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-3776ab">
  <img alt="GUI" src="https://img.shields.io/badge/gui-PyQt6%20%2B%20QML-41cd52">
  <img alt="Build" src="https://img.shields.io/badge/build-Portable%20%2F%20CLI-ff6b6b">
  <img alt="Version" src="https://img.shields.io/badge/version-2.8.12-111827">
  <img alt="License" src="https://img.shields.io/badge/license-GPL--3.0-blue">
</p>

---

## Why RenLocalizer?

Visual Novel translations often fail because translation tools don't understand code. They accidentally translate variable names, corrupt formatting tags (`{i}`/`{b}`), or trigger duplicate translation key crashes. 

**RenLocalizer solves this with zero hassle:**

- **🔌 Zero Dependencies (Plug-and-Play):** All major machine translation and LLM submodules (including Google Translate, OpenAI, DeepSeek, and Local LLM support) are pre-bundled inside the application. No need to install Python or configure virtual environments.
- **🎯 Minimalist UI:** Stripped of complex tabs and overwhelming settings. The single-page Material dashboard focuses strictly on: **Select Project -> Configure Engine -> Translate.**
- **🛡️ Decoupled NMT & LLM Protection:** Google Translate is fed with custom Unicode brackets (`⟦N⟧`) which it preserves best, while LLMs (OpenAI/Local LLMs) receive structured XML tags (`<ph id="N">...</ph>`) to prevent subword tokenizer splitting and keep grammar markers contextually correct.
- **🎮 Full CLI Mode:** Headless translation with Rich-powered terminal UI — perfect for automated builds (`python run_cli.py "Game.exe" -e libretranslate -t ru`).

---

## Core Features

| Feature | Description |
|---------|-------------|
| **Google Translate** | Free, 13 mirror endpoints, no API key required |
| **OpenAI / DeepSeek** | GPT models via API key |
| **Local LLM** | Ollama / LM Studio — fully offline, uncensored models supported |
| **LibreTranslate** | Self-hosted via Docker — no rate limits, no API key needed |
| **Custom Endpoint** | Any LibreTranslate-compatible API |
| **Smart TL Retranslation** | Fill empty `new ""` blocks in existing tl/ folders |
| **Compiled RPYC Reading** | Full RPYC AST reader (2742 lines, 45+ node types) |
| **Syntax Guard** | 3 protection modes (token/HTML/XML) + 6-stage recovery |
| **False Positive Filters** | 40+ pre-compiled regex patterns + 170 technical terms |
| **CLI Mode** | Rich TUI with interactive menus, gradient banner, progress bars |
| **Source Language Selector** | Explicit source language or auto-detect |
| **Runtime Hook** | O(1) dict lookup, MRU cache, 500-entry miss set |

---

## Quick Start (GUI Workflow)

1. Download the latest packaged build from the [Releases page](https://github.com/Lord0fTurk/RenLocalizer/releases).
2. Open **RenLocalizer**.
3. Click **Browse** or **EXE** to select your game directory or executable.
4. Choose your preferred **Translation Engine** and **Target Language**.
5. Click **Translate** (▶) and watch the real-time logs.
6. Launch your game and select the new language from the preferences menu!

> **macOS:** The DMG is ad-hoc signed (no Apple Developer certificate). If Gatekeeper blocks the app ("cannot be opened" / "damaged"), drag it to Applications, then run once:
>
> ```bash
> xattr -cr /Applications/RenLocalizer.app
> ```
>
> Builds are ARM64 (Apple Silicon). Intel Macs are not supported by the prebuilt DMG — use "Running from Source" below.

---

## CLI Usage

```bash
# Translate with Google (default)
python run_cli.py "C:\Games\MyVN.exe"

# Translate with LibreTranslate to Russian
python run_cli.py "C:\Games\MyVN.exe" -e libretranslate -t ru

# Translate with OpenAI to English with deep scan
python run_cli.py "C:\Games\MyVN.exe" -e openai -t en --deep-scan

# Interactive menu mode
python run_cli.py --interactive
```

---

## Running from Source

If you prefer executing from source:

```bash
git clone https://github.com/Lord0fTurk/RenLocalizer.git
cd RenLocalizer
python -m venv .venv
```

**Windows:**
```bash
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

**Linux / macOS:**
```bash
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

---

## Technical Specifications

### Placeholder Protection
- **Google (Token Mode):** Unicode math brackets `⟦RLPH{hex}_{N}⟧` — Google treats them as punctuation, leaves them intact
- **AI/LLM (XML Mode):** `<ph id="N">...</ph>` tags — tokenizer-friendly, prevents subword splitting
- **ASCII Wrapper:** `__PH_N__` for LLM compatibility in token mode
- **6-Stage Recovery:** Unicode bracket → bracket-stripped → Cyrillic/Greek transliteration → generic → wrapper pair → tag repair

### GBNF Logit Schema Masking
For LLMs, the app passes strict schema constraints (`response_format` JSON schema). The API engine uses logit masking to enforce format matching, avoiding markdown code wrappers or dropped item IDs.

### XML Corruption Checks
In the event that an LLM returns a corrupted translation or leaks XML tags, the pipeline performs a structural check. If `<ph id=` or `</ph>` is found in the final restored translation, the string is flagged as corrupted and safely reverted to the original source text.

---

## Contributing & Support

Issues, bug reports, and pull requests are welcome. Feel free to open a ticket on the GitHub Issues page.

- [Wiki Guide](https://github.com/Lord0fTurk/RenLocalizer/wiki)
- [Contributing Guidelines](CONTRIBUTING.md)
- [License](LICENSE) (Licensed under the GPL-3.0 License)
- [Support on Patreon](https://www.patreon.com/cw/LordOfTurk)
