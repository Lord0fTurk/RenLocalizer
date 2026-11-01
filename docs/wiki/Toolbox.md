# 🛠️ Built-in Utilities & Tools

RenLocalizer integrates several automated tools directly into the translation engine to handle encrypted archives, compiled binary scripts, custom terminology, and script integrity.

---

## 📦 1. Automated RPA Archive Extractor

Ren'Py games often pack game scripts, screens, and assets into compressed `.rpa` archives (e.g. `archive.rpa`, `scripts.rpa`).

- **Automatic Extraction:** When you load a game, RenLocalizer checks if `.rpa` archives need extraction and automatically unpacks them into the `game/` folder.
- **Powered by UnRPA:** Fast, reliable archive decompression without requiring external third-party extractors.

---

## 🔍 2. RPYC Binary Reader & Decompiler

Many commercial and Patreon visual novels only ship with compiled `.rpyc` files, omitting the raw human-readable `.rpy` scripts.

- **Direct AST Traversal:** RenLocalizer includes a 2,455-line dedicated `.rpyc` binary reader capable of parsing Ren'Py AST nodes (Screen Language, Python code blocks, dialogue nodes) directly.
- **Smart Fallback:** Unrpyc decompiler automatically reconstructs readable `.rpy` translation sources on the fly.
- **Deep Extraction:** Traverses complex nested dictionaries, lists, and tuples to discover hidden UI strings.

---

## 📚 3. Custom Glossary Management (`glossary.json`)

To prevent character names, locations, fictional lore, or proper nouns from being translated into literal dictionary words, use the **Glossary**:

### File Location:
A `glossary.json` file is located in your RenLocalizer directory:

```json
{
  "Ethan": "Ethan",
  "Elena": "Elena",
  "Redwood City": "Redwood City",
  "Blackwood Corp": "Blackwood Corp",
  "Stamina": "Kondisyon"
}
```

### How it Works:
- **Left (Source Term):** Exact case-sensitive or case-insensitive term to match.
- **Right (Target Replacement):** Desired translation (or leave it identical to keep it untranslated).
- The pipeline applies glossary substitutions with word-boundary awareness, preventing partial replacements inside longer words.

---

## 🔤 4. Automatic Font & RTL Text Shaping

- **RTL Language Detection:** When translating into Right-to-Left languages like **Arabic (`ar`)**, **Persian/Farsi (`fa`)**, or **Hebrew (`he`)**, the runtime hook automatically activates BiDi text reordering and Persian/Arabic character shaping.
- **Unicode Support:** Preserves special characters and non-Latin scripts (Cyrillic, Greek, CJK, Turkish diacritics) seamlessly.

---

## ⌨️ 5. Headless CLI Engine (`run_cli.py`)

For automated batch builds, CI/CD pipelines, or server environments:

```bash
# Automated translation without GUI
python run_cli.py "D:\Games\MyVN.exe" -e deepseek -t tr --deep-scan

# Interactive rich console menu
python run_cli.py --interactive
```
