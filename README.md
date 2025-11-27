> ⚠️ **Warning (English)**: This project has been assisted by AI. It may contain mistakes, incomplete implementations and is still under active development. It is NOT a final release.

# RenLocalizer

**RenLocalizer** is a modern desktop application designed to automatically translate Ren'Py visual novel (.rpy) files with high accuracy and performance. Features multiple translation engines, smart text filtering, and a professional user interface.

## ✨ Key Features

### 🎯 Smart Translation
- **Multiple engines**: Google Translate (web), DeepL API, Deep-Translator (multi-engine) support
- **RenPy-aware parsing**: Correctly handles menu choices, dialogues, UI elements
- **Conditional menu support**: Handles `"choice" if condition:` syntax
- **Technical filtering**: Automatically excludes color codes, font files, performance metrics
- **Character preservation**: Maintains `[character_name]` variables and placeholders
-- **Offline translation**: Offline engines may be available via third-party packages (optional)

### 🚀 High Performance  
- **Concurrent processing**: Configurable thread count (1-256)
- **Batch translation**: Process multiple texts together (1-2000)
- **Proxy rotation**: Automatic proxy management and validation
- **Config-driven behaviour**: Proxy update interval, failure limits and startup tests are now fully controlled from the `Proxy` tab in Settings.
- **Smart fallback**: Falls back to direct requests if proxies fail
- **Rate limiting**: Adaptive delays to prevent blocking

### 🎨 Modern Interface
- **Professional themes**: Dark and Solarized themes
- **Minimal main screen**: Only folder selection, basic translation settings and progress bar
- **Separate settings dialog**: Advanced performance / proxy / logging options in the `Settings` menu
- **Bilingual UI**: English and Turkish interface support
- **Auto-save**: Timestamped output with proper RenPy structure

### 🔧 RenPy Integration
- **Correct format output**: Individual `translate strings` blocks as required by RenPy
- **Language initialization**: Automatic language setup files
- **Cache management**: Built-in RenPy cache clearing
- **Directory structure**: Proper `game/tl/[language]/` organization

## 📦 Installation

### Prerequisites
- Python 3.8 or higher
- Git (optional, you can also download as ZIP)
- pip (Python package manager)
- For Windows users: Visual Studio Build Tools with C++ support (for some dependencies)

### Steps

1. **Clone the repository:**
```bash
git clone https://github.com/YOUR_USERNAME/RenLocalizer.git
cd RenLocalizer
```

2. **Create virtual environment (recommended):**
```bash
python -m venv venv

# On Windows:
venv\Scripts\activate

# On Linux/macOS:
source venv/bin/activate
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

4. **Run the application:**
```bash
python run.py
```

Or on Windows, you can double-click `run.bat`

## 🚀 Quick Start
1. Launch the app (`python run.py`)
2. Select the folder containing `.rpy` files
3. Select source & target language (e.g. EN → TR)
4. Configure engine & batch settings
5. Start translation – watch live progress
6. Translations auto-save (or you can save manually)

## ⚙️ Settings
- Concurrent threads (1–256)
- Batch size (1–2000)
- Request delay (0–5 s)
- Max retries
- Enable / disable proxy
- Proxy failure limit, update interval and custom proxy list (one per line)

## 🌍 Engine Status Table
| Engine | Status | Languages | Note |
|--------|--------|-----------|------|
| Google | ✅ Active | 100+ | Web client + proxy fallback |
| DeepL | ✅ Active | 30+ | API key required only if you use it |
| OPUS-MT | ❌ Removed | - | Offline OPUS-MT removed due to native dependency issues |
| Deep-Translator | ✅ Active | 100+ | Multi-engine wrapper (Google, Bing, Yandex, etc.) |
| Bing / Microsoft | ⏳ Planned | - | Not yet added |
| Yandex | ⏳ Planned | - | Not yet added |
| LibreTranslator | ⏳ Planned | - | Future self-host option |

### Offline Engines
Offline engines may support a variable set of language pairs depending on installed packages.

## 🧠 Parsing Logic
- Excludes code blocks, label definitions, python blocks
- Only real dialogue & user-visible strings extracted
- File paths, variables, `%s`, `{name}` etc. preserved

## 📁 Project Structure
```
src/
	core/ (translation, parser, proxy)
	gui/  (interface & themes)
	utils/ (config)
run.py (launcher)
README.md / README.tr.md
LICENSE
```

## 🔐 API Keys
Currently only DeepL key meaningful; others activate when engines arrive.

## 📦 Building Executable
See `BUILD.md` for detailed instructions on creating standalone executables.

## 🧪 Test & Contribute
Pull Requests welcome. Suggested improvements:
- New engine integration
- Performance optimization
- Additional language support
- UI improvements

## ❓ Troubleshooting
| Problem | Solution |
|---------|----------|
| Module not found 'src' | Set `PYTHONPATH` or run from root |
| Slow translation | Increase threads & batch, lower delay |
| Rate limit | Enable proxy or change engine |
| Broken tag | Ensure placeholder protection enabled |

## 📄 License
This project is licensed under **GPL-3.0-or-later**. See `LICENSE`.

## 💬 Contact
Open an issue or contribute. Community contributions welcome.

---
**RenLocalizer v2.0.3** – Professional translation accelerator for Ren'Py projects.
