# Changelog

## [2.0.6] - 2025-11-26

### 🎨 UI Simplification & UX
- **Minimal main window:** Simplified the main screen to only show project folder selection, basic translation settings and a progress section so new users are not overwhelmed.
- **Removed results/log tabs:** The old right-hand panel with `Translation Results`, `Extracted Texts` and log tabs has been removed; extracted texts are now written to simple `.txt` reports under `logs/`.
- **Settings-only advanced options:** Advanced performance, proxy and logging options are now managed exclusively via the `Settings` dialog instead of the main window.
- **Window size cleanup:** Removed window size persistence and the related controls in Settings; the app now opens with a sane default size instead of reusing previous large/fullscreen sizes.

### 🌐 Glossary, Proxy & Localization
- **Glossary editor dialog:** Added a dedicated `Glossary` menu entry and dialog to edit `glossary.json` (term → preferred translation) with immediate in-memory update.
- **Config‑driven proxy manager:** Proxy behaviour is now fully driven by `Proxy` settings (enable/disable, failure limit, update interval and startup testing) instead of hardcoded values.
- **Custom proxy list support:** You can now define your own proxy list in the `Proxy` tab; these entries are parsed and preferred over public proxy sources.
- **Locale updates:** Updated English and Turkish locale files to match the new minimal UI and removed obsolete Quick Options/OPUS-MT related strings.

### 📚 Documentation
- **README refresh:** Updated both `README.md` and `README.tr.md` to describe the minimal main window, current theme options and the separate Settings dialog.

## [2.0.5] - 2025-09-16

### 🧹 Removal: Deep-Translator
- **Removed Deep-Translator:** The experimental `Deep-Translator` multi-engine wrapper and its UI entry have been removed due to stability and maintenance reasons. If you relied on this engine, please switch to supported engines (Google, DeepL, Yandex, LibreTranslator).

### 🧹 Removal: OPUS-MT (Argos Translate)
- **Removed OPUS-MT (Argos Translate):** All OPUS-MT / Argos Translate integration, model download UI, and related code paths have been removed due to instability and crashes observed in production. Offline model download/dialog features related to OPUS-MT were deleted, and references in UI/locales/docs were cleaned up.

## [2.0.4] - 2025-09-15

### 🛠️ RenPy Compliance & Cleanup
- **Config Cleanup:** Only `config.py` is now active; `config_new.py` and `config_old.py` have been completely removed.
- **Default Format:** The default translation output format is now `old_new`. The `simple` format remains as an optional legacy mode.
- **Format Compliance:** The `old_new` format is now fully compliant with RenPy documentation. All translations are grouped in a single `translate [lang] strings:` block, with each entry as `old "..."` and `new "..."`, and file/directory structure matches RenPy standards.
- **Language Init File:** The automatic language initializer file (e.g. `a0_pt_language.rpy`) is now minimal: only `define config.language = "[lang]"` is used for automatic language selection. All complex init/python blocks have been removed.
- **Bug Fixes:** Fixed quote and newline issues in language init file generation; output is now error-free.
- **Code & Documentation:** All relevant code sections and README/BUILD.md have been reviewed and updated for RenPy compliance and accuracy.
- **User Feedback:** Language initialization issues (e.g. for Portuguese) are resolved; automatic language selection now works for all languages.

## [2.0.3] - 2025-09-15

### 🔧 Build & Packaging Improvements

### 🛠️ GitHub Repository Preparation

### 🐛 Minor Fixes

### 📦 Distribution Ready

## [2.0.2] - 2025-09-15

### 🚀 New Translation Engine
- **Complete UI Translation**: All interface elements now support English and Turkish
- **Dynamic Language Switching**: Real-time language switching without restart
- **Translation Engine Names**: Engine dropdown now adapts to selected UI language
- **Model Download Dialog**: Full multi-language support for offline model downloads

### 🔧 Architecture Improvements
- **Batch Translation Optimization**: Pre-check model availability before processing thousands of texts
- **Signal-Based Download Workflow**: Clean separation between translation worker and GUI dialogs
- **Error Prevention**: Eliminated infinite loop errors from missing models
- **Memory Management**: Efficient model caching and loading system

### 🐛 Critical Fixes
- Fixed OPUS-MT model download infinite loop that caused application crashes
- Resolved Qt thread safety issues with dialog creation
- Improved error handling for missing translation models
- Better fallback mechanisms when models are unavailable

### 📚 Documentation & GitHub Preparation
- Updated README.md with OPUS-MT information and installation instructions
- Enhanced .gitignore for better repository management
- Cleaned up debug prints and improved code quality
- Added GitHub community files (CODE_OF_CONDUCT.md, issue templates, PR template)

## [2.0.1] - 2025-09-11

### 🎯 RenPy Integration Overhaul
- **Conditional Menu Support**: Perfect handling of `"choice" if condition:` syntax
- **Technical String Filtering**: Automatically excludes color codes (#08f), font files (.ttf), performance metrics
- **Correct Output Format**: Individual `translate strings` blocks (RenPy standard compliance)
- **Modern Language Initialization**: Compatible language setup without deprecated APIs
- **Encoding Fixes**: Proper UTF-8 handling for all international characters

### 🔧 Parser Improvements
- **Enhanced Regex Engine**: Improved extraction of conditional menu choices
- **Smart Content Detection**: Better filtering of meaningful vs technical content
- **Multi-line String Handling**: Fixed parsing issues with complex string patterns
- **Variable Preservation**: Maintains `[character_name]` and placeholder integrity

### 🐛 Critical Bug Fixes
- Fixed "Could not parse string" errors in RenPy
- Resolved multi-line string parsing issues (line 2327 type errors)
- Corrected character encoding problems (Türkçe character corruption)
- Fixed language initialization file compatibility issues
- Eliminated technical string translation (fps, renderer, etc.)

### � Quality Improvements
- **Cache Management**: Built-in RenPy cache clearing functionality
- **Error Prevention**: Proactive filtering prevents RenPy parse errors
- **Output Validation**: Ensures all generated files are RenPy-compatible
- **Real-world Testing**: Validated with actual RenPy visual novel projects

### � Distribution Ready
- **Clean Repository**: Removed all temporary test and debug files
- **Professional Documentation**: Updated README, added CONTRIBUTING.md, RELEASE_NOTES.md
- **Example Configuration**: Sample config.json.example for users
- **GitHub Ready**: Proper .gitignore, structured for open source collaboration

### 🧪 Testing & Validation
- Comprehensive testing with Secret Obsessions 0.11 (RenPy 8.3.2)
- Menu choice translation validation
- Technical string exclusion verification
- Encoding and character preservation testing

## [2.0.0] - Previous Release
- Initial stable release with core translation functionality
- Basic RenPy file parsing and translation
- Multi-engine support (Google, DeepL, Bing, Yandex)
- Professional UI with theme support
